# trade_executor.py
# Trade helpers + manual guard utilities + execution integrity

import time
import logging
from typing import Optional

from config import SETTINGS
from storage import (execute, fetchone, fetchall, _USE_POSTGRES,
                     insert_trade, append_trade_note,
                     upsert_manual_guard, upsert_bot_state)

log = logging.getLogger(__name__)

# -------------------------
# Trading primitives
# -------------------------
def open_trade(pair: str, side: str, qty: float, price: float,
               reason: str = "", mode: Optional[str] = None,
               entry_snapshot: Optional[str] = None) -> int:
    """Open a new trade. Returns the trade id."""
    return insert_trade(pair, side, qty, price, reason, entry_snapshot)


def close_all_for_pair(pair: str, reason: str = "") -> int:
    """Close all OPEN trades for the given pair."""
    rows = fetchall("SELECT id FROM trades WHERE status='OPEN' AND pair IN (?,?)",
                    (pair, pair.replace('/', '')))
    count = 0
    for (tid,) in rows:
        append_trade_note(tid, f" | {reason}")
        execute("UPDATE trades SET status='CLOSED' WHERE id=?", (tid,))
        count += 1
    return count


def close_trade(trade_id: int, exit_price: float, reason: str = "",
                exit_snapshot: Optional[str] = None) -> float:
    """Close a single trade by ID. Returns PnL."""
    row = fetchone("SELECT side, qty, entry FROM trades WHERE id=?", (trade_id,))
    if not row:
        log.warning("close_trade: trade %d not found", trade_id)
        return 0.0
    side, qty, entry = str(row[0]), float(row[1]), float(row[2])
    pnl = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
    now = int(time.time())

    if reason:
        append_trade_note(trade_id, f" | {reason}")

    execute(
        "UPDATE trades SET exit_price=?, pnl=?, status='CLOSED', lifecycle='closed', "
        "ts_close=?, exit_snapshot=? WHERE id=?",
        (exit_price, pnl, now, exit_snapshot, trade_id))
    return pnl


def update_trade_lifecycle(trade_id: int, lifecycle: str):
    """Update lifecycle state: pending, open, protected, trailing, closed, blocked."""
    execute("UPDATE trades SET lifecycle=? WHERE id=?", (lifecycle, trade_id))


def get_open_trades_for_pair(pair: str, user_id: int = None) -> list:
    """Get open trades for a pair, optionally filtered by user."""
    if user_id is not None:
        rows = fetchall("SELECT id, side, qty, entry, ts_open FROM trades WHERE status='OPEN' AND pair=? AND user_id=?", (pair, user_id))
    else:
        rows = fetchall("SELECT id, side, qty, entry, ts_open FROM trades WHERE status='OPEN' AND pair=?", (pair,))
    return [{'id': r[0], 'side': r[1], 'qty': float(r[2]), 'entry': float(r[3]), 'ts_open': r[4]} for r in rows]


# -------------------------
# Autonomous execution bridge — hardened for production
# -------------------------

# Execution lock to prevent duplicate simultaneous trades
_execution_lock = {}


def _check_execution_lock(pair: str, side: str) -> bool:
    """Prevent duplicate execution within a short window."""
    key = f"{pair}:{side}"
    now = time.time()
    last = _execution_lock.get(key, 0)
    if now - last < 10:  # 10-second dedup window
        log.warning("Execution dedup: %s blocked (last: %.1fs ago)", key, now - last)
        return False
    _execution_lock[key] = now
    return True


def _clear_execution_lock(pair: str, side: str):
    key = f"{pair}:{side}"
    _execution_lock.pop(key, None)


def execute_autonomous_trade(pair: str, side: str, qty: float, price: float,
                              sl_price: float, tp_price: float,
                              reason: str = "", entry_snapshot: str = None,
                              ctx=None) -> dict:
    """
    Full trade execution: DB record + exchange order + SL/TP guards.
    If ctx (UserContext) is provided, uses per-user settings and credentials.
    Hardened sequence:
      1. Dedup check
      2. Create DB record (status=PENDING)
      3. Place exchange order
      4. On success: update DB with order_id, set status=OPEN
      5. On failure: mark DB record as FAILED
      6. Set SL/TP guards
    Returns {'success': bool, 'trade_id': int, 'order_id': str, 'mode': str, 'error': str}
    """
    if SETTINGS.DRY_RUN_MODE:
        log.info("DRY RUN: %s %s %.6f %s @ %.2f (SL=%.2f TP=%.2f)",
                 side, qty, qty, pair, price, sl_price, tp_price)
        return {'success': True, 'trade_id': 0, 'order_id': 'dry-run', 'mode': 'DRY_RUN', 'error': ''}

    # 1. Dedup check
    if not _check_execution_lock(pair, side):
        return {'success': False, 'trade_id': 0, 'order_id': None,
                'mode': 'DEDUP', 'error': 'Duplicate execution blocked'}

    trade_id = 0
    order_id = None
    is_paper = ctx.paper_trading if ctx else SETTINGS.PAPER_TRADING
    mode = 'PAPER' if is_paper else 'LIVE'
    uid = ctx.user_id if ctx else None

    try:
        # 2. Create DB record with PENDING status
        now = int(time.time())
        if _USE_POSTGRES:
            row = fetchone(
                "INSERT INTO trades(pair, side, qty, entry, status, ts_open, note, lifecycle, "
                "entry_snapshot, trade_type, user_id) "
                "VALUES(?,?,?,?, 'PENDING', ?, ?, 'pending', ?, 'auto', ?) RETURNING id",
                (pair, side.upper(), float(qty), float(price), now,
                 reason or "auto_trade", entry_snapshot, uid))
            trade_id = int(row[0]) if row else 0
        else:
            from storage import _sqlite_lock, _get_sqlite_conn
            with _sqlite_lock:
                conn = _get_sqlite_conn()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO trades(pair, side, qty, entry, status, ts_open, note, lifecycle, "
                    "entry_snapshot, trade_type, user_id) "
                    "VALUES(?,?,?,?, 'PENDING', ?, ?, 'pending', ?, 'auto', ?)",
                    (pair, side.upper(), float(qty), float(price), now,
                     reason or "auto_trade", entry_snapshot, uid))
                conn.commit()
                trade_id = cur.lastrowid

        if trade_id == 0:
            log.error("Failed to create trade record for %s %s (user %s)", side, pair, uid)
            _clear_execution_lock(pair, side)
            return {'success': False, 'trade_id': 0, 'order_id': None,
                    'mode': mode, 'error': 'DB insert failed'}

        log.info("Trade %d created (PENDING): %s %s %.6f %s @ %.2f [user=%s]",
                 trade_id, mode, side, qty, pair, price, uid)

        # 3. Execute on exchange (using user's credentials if ctx provided)
        try:
            from exchange import place_market_order
            result = place_market_order(pair, side, qty, ctx=ctx)
            order_id = result.get('id', f'paper-{trade_id}')

            # 4. Success: update to OPEN with order_id
            execute("UPDATE trades SET status='OPEN', lifecycle='open', order_id=? WHERE id=?",
                    (str(order_id), trade_id))
            log.info("Trade %d OPEN: order=%s [user=%s]", trade_id, order_id, uid)

        except Exception as e:
            # 5. Failure: mark as FAILED
            log.error("Order execution failed for trade %d (%s, user %s): %s", trade_id, pair, uid, e)
            execute("UPDATE trades SET status='FAILED', lifecycle='blocked', note=? WHERE id=?",
                    (f"Order failed: {e}", trade_id))
            _clear_execution_lock(pair, side)
            return {'success': False, 'trade_id': trade_id, 'order_id': None,
                    'mode': mode, 'error': str(e)}

        # 6. Set SL/TP guards (for the trade's owning user)
        guard_uid = uid or ((SETTINGS.TELEGRAM_ADMIN_IDS or [None])[0] if SETTINGS.TELEGRAM_ADMIN_IDS else None)
        if guard_uid:
            try:
                set_manual_guard(guard_uid, pair, sl=sl_price, tp=tp_price)
            except Exception as e:
                log.warning("Failed to set guards for trade %d: %s", trade_id, e)

        return {'success': True, 'trade_id': trade_id, 'order_id': order_id,
                'mode': mode, 'error': ''}

    except Exception as e:
        log.exception("Unexpected error in execute_autonomous_trade: %s", e)
        # If trade_id was created, mark it failed
        if trade_id > 0:
            try:
                execute("UPDATE trades SET status='FAILED', lifecycle='blocked', note=? WHERE id=?",
                        (f"Unexpected error: {e}", trade_id))
            except Exception:
                pass
        _clear_execution_lock(pair, side)
        return {'success': False, 'trade_id': trade_id, 'order_id': None,
                'mode': mode, 'error': str(e)}


def execute_autonomous_exit(pair: str, reason: str = "AI_EXIT", ctx=None) -> dict:
    """
    Close all open trades for pair, executing on exchange if live.
    If ctx (UserContext) provided, uses per-user credentials and closes only that user's trades.
    """
    from exchange import market_price, place_market_order
    is_paper = ctx.paper_trading if ctx else SETTINGS.PAPER_TRADING
    uid = ctx.user_id if ctx else None
    mode = 'PAPER' if is_paper else 'LIVE'
    errors = []
    total_pnl = 0.0
    closed = 0

    try:
        px = market_price(pair)
    except Exception as e:
        return {'success': False, 'closed_count': 0, 'total_pnl': 0,
                'mode': mode, 'errors': [f'Price fetch: {e}']}

    trades = get_open_trades_for_pair(pair, user_id=uid)
    for t in trades:
        try:
            opposite = 'sell' if t['side'] == 'BUY' else 'buy'
            if not is_paper:
                try:
                    place_market_order(pair, opposite, t['qty'], ctx=ctx)
                except Exception as e:
                    log.error("Exit order failed for trade %s: %s", t['id'], e)
                    errors.append(f"Trade #{t['id']} order failed: {e}")
                    # Still close in DB to avoid orphaned state
                    append_trade_note(t['id'], f" | EXIT_ORDER_FAILED: {e}")

            pnl = close_trade(t['id'], px, reason)
            total_pnl += pnl
            closed += 1
        except Exception as e:
            log.error("Exit failed for trade %s: %s", t['id'], e)
            errors.append(f"Trade #{t['id']}: {e}")

    # Clear guards and ATR trail state (for the owning user)
    guard_uid = uid or ((SETTINGS.TELEGRAM_ADMIN_IDS or [None])[0] if SETTINGS.TELEGRAM_ADMIN_IDS else None)
    if guard_uid:
        try:
            clear_manual_guard(guard_uid, pair, 'all')
        except Exception:
            pass

    # Clean ATR trailing state for closed trades
    for t in trades:
        try:
            execute("DELETE FROM bot_state WHERE key=?", (f"atr_trail_{t['id']}",))
        except Exception:
            pass

    return {'success': len(errors) == 0, 'closed_count': closed,
            'total_pnl': total_pnl, 'mode': mode, 'errors': errors}


# -------------------------
# Manual guard utilities
# -------------------------
def set_manual_guard(uid: int, pair: str, sl: Optional[float] = None,
                     tp: Optional[float] = None, trail_pct: Optional[float] = None) -> int:
    """Update only provided fields; preserve others. Create row if needed (UPSERT)."""
    row = fetchone(
        "SELECT stop_loss, take_profit, trail_pct, trail_stop, high_watermark "
        "FROM manual_guards WHERE user_id=? AND pair IN (?,?)",
        (uid, pair, pair.replace('/', ''))
    )
    if row:
        old_sl, old_tp, old_trail, old_stop, old_hwm = row
    else:
        old_sl = old_tp = old_trail = old_stop = old_hwm = None

    new_sl    = sl        if sl        is not None else old_sl
    new_tp    = tp        if tp        is not None else old_tp
    new_trail = trail_pct if trail_pct is not None else old_trail

    if trail_pct is not None:
        new_stop = None
        new_hwm  = None
    else:
        new_stop = old_stop
        new_hwm  = old_hwm

    upsert_manual_guard(uid, pair, new_sl, new_tp, new_trail, new_stop, new_hwm)
    return 1


def clear_manual_guard(uid: int, pair: str, which: str) -> int:
    """which in {'sl','tp','trail','all'}"""
    cols = []
    w = which.lower()
    if w in ('sl', 'all'):
        cols.append('stop_loss=NULL')
    if w in ('tp', 'all'):
        cols.append('take_profit=NULL')
    if w in ('trail', 'all'):
        cols += ['trail_pct=NULL', 'trail_stop=NULL', 'high_watermark=NULL']
    if not cols:
        return 0
    return execute(
        f"UPDATE manual_guards SET {', '.join(cols)} WHERE user_id=? AND pair IN (?,?)",
        (uid, pair, pair.replace('/', ''))
    )


# -------------------------
# Trade state recovery (for restart safety)
# -------------------------
def recover_pending_trades():
    """
    On startup, find trades stuck in PENDING status (crash during execution).
    Mark them as FAILED so they don't block future trading.
    """
    rows = fetchall("SELECT id, pair, side, ts_open FROM trades WHERE status='PENDING'")
    if not rows:
        return 0
    count = 0
    for tid, pair, side, ts_open in rows:
        age = int(time.time()) - (ts_open or 0)
        log.warning("Recovering PENDING trade %d (%s %s) — age %ds, marking FAILED",
                     tid, pair, side, age)
        execute("UPDATE trades SET status='FAILED', lifecycle='blocked', "
                "note='Recovered from PENDING on restart' WHERE id=?", (tid,))
        count += 1
    return count


def get_trade_state_summary() -> dict:
    """Get summary of current trade states for health checks."""
    summary = {}
    for status in ['OPEN', 'PENDING', 'CLOSED', 'FAILED']:
        row = fetchone("SELECT COUNT(*) FROM trades WHERE status=?", (status,))
        summary[status.lower()] = int(row[0]) if row else 0
    return summary
