# trade_executor.py
# Trade helpers + manual guard utilities

import time
from typing import Optional, Tuple

from config import SETTINGS
from storage import execute, fetchone, fetchall, _USE_POSTGRES

# -------------------------
# Trading primitives
# -------------------------
def open_trade(pair: str, side: str, qty: float, price: float,
               reason: str = "", mode: Optional[str] = None,
               entry_snapshot: Optional[str] = None) -> int:
    """Open a new trade. Returns the trade id."""
    now = int(time.time())
    if _USE_POSTGRES:
        row = fetchone(
            "INSERT INTO trades(pair, side, qty, entry, status, ts_open, note, lifecycle, entry_snapshot, trade_type) "
            "VALUES(?,?,?,?, 'OPEN', ?, ?, 'open', ?, 'auto') RETURNING id",
            (pair, side.upper(), float(qty), float(price), now, reason or "open_trade", entry_snapshot))
        return int(row[0]) if row else 0
    else:
        execute(
            "INSERT INTO trades(pair, side, qty, entry, status, ts_open, note, lifecycle, entry_snapshot, trade_type) "
            "VALUES(?,?,?,?, 'OPEN', ?, ?, 'open', ?, 'auto')",
            (pair, side.upper(), float(qty), float(price), now, reason or "open_trade", entry_snapshot))
        rowid = fetchone("SELECT last_insert_rowid()")[0]
        return int(rowid)


def close_all_for_pair(pair: str, reason: str = "") -> int:
    """Close all OPEN trades for the given pair."""
    rows = fetchall("SELECT id FROM trades WHERE status='OPEN' AND pair IN (?,?)",
                    (pair, pair.replace('/', '')))
    count = 0
    for (tid,) in rows:
        execute("UPDATE trades SET status='CLOSED', note=COALESCE(note,'')||? WHERE id=?",
                (f" | {reason}", tid))
        count += 1
    return count


def close_trade(trade_id: int, exit_price: float, reason: str = "", exit_snapshot: Optional[str] = None) -> float:
    """Close a single trade by ID. Returns PnL."""
    row = fetchone("SELECT side, qty, entry FROM trades WHERE id=?", (trade_id,))
    if not row:
        return 0.0
    side, qty, entry = str(row[0]), float(row[1]), float(row[2])
    pnl = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
    now = int(time.time())
    execute(
        "UPDATE trades SET exit_price=?, pnl=?, status='CLOSED', lifecycle='closed', ts_close=?, note=COALESCE(note,'')||?, exit_snapshot=? WHERE id=?",
        (exit_price, pnl, now, f" | {reason}" if reason else "", exit_snapshot, trade_id))
    return pnl


def update_trade_lifecycle(trade_id: int, lifecycle: str):
    """Update lifecycle state: pending, open, protected, trailing, closed, blocked."""
    execute("UPDATE trades SET lifecycle=? WHERE id=?", (lifecycle, trade_id))


def get_open_trades_for_pair(pair: str) -> list:
    """Get all open trades for a pair as list of dicts."""
    rows = fetchall("SELECT id, side, qty, entry, ts_open FROM trades WHERE status='OPEN' AND pair=?", (pair,))
    return [{'id': r[0], 'side': r[1], 'qty': float(r[2]), 'entry': float(r[3]), 'ts_open': r[4]} for r in rows]


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

    return execute("""
        INSERT INTO manual_guards(user_id, pair, stop_loss, take_profit, trail_pct, trail_stop, high_watermark)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(user_id, pair) DO UPDATE SET
            stop_loss=excluded.stop_loss,
            take_profit=excluded.take_profit,
            trail_pct=excluded.trail_pct,
            trail_stop=excluded.trail_stop,
            high_watermark=excluded.high_watermark
    """, (uid, pair, new_sl, new_tp, new_trail, new_stop, new_hwm))


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
