# trade_executor.py
# Minimal trade helpers + manual guard utilities used by scheduler/telegram bot

import time
from typing import Optional, Tuple

from config import SETTINGS
from storage import execute, fetchone, fetchall

# -------------------------
# Trading primitives
# -------------------------
def open_trade(pair: str, side: str, qty: float, price: float,
               reason: str = "", mode: Optional[str] = None,
               entry_snapshot: Optional[str] = None) -> int:
    """
    Open a new trade. Inserts an OPEN row in `trades`.
    Returns the inserted trade id (SQLite rowid).
    """
    now = int(time.time())
    execute("""
        INSERT INTO trades(pair, side, qty, entry, status, ts_open, note, lifecycle, entry_snapshot, trade_type)
        VALUES(?,?,?,?, 'OPEN', ?, ?, 'open', ?, 'auto')
    """, (pair, side.upper(), float(qty), float(price), now, reason or "open_trade", entry_snapshot))
    rowid = fetchone("SELECT last_insert_rowid()")[0]
    return int(rowid)


def close_all_for_pair(pair: str, reason: str = "") -> int:
    """
    Closes all OPEN trades for the given pair.
    Paper-safe fallback: just marks them CLOSED (your PnL may be set elsewhere).
    """
    rows = fetchall('SELECT id FROM trades WHERE status="OPEN" AND pair IN (?,?)',
                    (pair, pair.replace('/', '')))
    count = 0
    for (tid,) in rows:
        count += execute('UPDATE trades SET status="CLOSED", note=COALESCE(note,"")||? WHERE id=?',
                         (f" | {reason}", tid))
    return count

# -------------------------
# Manual guard utilities
# -------------------------
def set_manual_guard(uid: int, pair: str, sl: Optional[float] = None,
                     tp: Optional[float] = None, trail_pct: Optional[float] = None) -> int:
    """
    Update only provided fields; preserve others. Create row if needed (UPSERT).
    Changing trail_pct resets trail_stop/high_watermark so the guard loop recomputes them.
    """
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
    """
    which ∈ {'sl','tp','trail','all'}
    Clearing 'trail' also clears trail_stop & high_watermark.
    """
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
# Hook used by scheduler
# -------------------------
def check_manual_guards() -> str:
    """
    Lightweight status helper for scheduler/UI.
    (The actual closing logic is handled by telegram_bot.auto_exit_task loop.)
    Returns a short human-readable line.
    """
    try:
        admin_ids = SETTINGS.TELEGRAM_ADMIN_IDS or []
        uid = admin_ids[0] if admin_ids else None
        if not uid:
            return "Guard action: no-admin"

        row = fetchone(
            "SELECT stop_loss, take_profit, trail_pct FROM manual_guards "
            "WHERE user_id=? AND pair IN (?,?)",
            (uid, SETTINGS.PAIR, SETTINGS.PAIR.replace('/', ''))
        )
        if not row:
            return "Guard action: no-guards"

        sl, tp, tr = row
        parts = []
        if sl is not None:
            parts.append(f"SL={sl:g}")
        if tp is not None:
            parts.append(f"TP={tp:g}")
        if tr is not None:
            parts.append(f"TRAIL={float(tr)*100:.2f}%")
        return "Guard action: " + (", ".join(parts) if parts else "configured")
    except Exception:
        return "Guard action: error"
    # --- legacy compatibility shim (safe no-op) ---
def check_manual_guards(*_args, **_kwargs):
    """Kept for backward-compatibility. Guard checks moved to auto_exit_task."""
    return None

