from __future__ import annotations
from typing import List, Tuple
from storage import fetchall, fetchone
from config import SETTINGS

def _fmt_usd(x):
    if x is None: return "-"
    return f"{float(x):.2f}"

def get_open_trades(pair: str | None = None) -> List[Tuple]:
    if pair:
        return fetchall(
            "SELECT id,pair,side,qty,entry,ts_open FROM trades WHERE status='OPEN' AND pair=? ORDER BY id DESC",
            (pair,)
        )
    return fetchall("SELECT id,pair,side,qty,entry,ts_open FROM trades WHERE status='OPEN' ORDER BY id DESC")

def get_recent_closed(n: int = 5, pair: str | None = None) -> List[Tuple]:
    if pair:
        return fetchall(
            "SELECT id,pair,side,qty,entry,exit,pnl,ts_close FROM trades WHERE status='CLOSED' AND pair=? ORDER BY id DESC LIMIT ?",
            (pair, n)
        )
    return fetchall(
        "SELECT id,pair,side,qty,entry,exit,pnl,ts_close FROM trades WHERE status='CLOSED' ORDER BY id DESC LIMIT ?",
        (n,)
    )

def daily_pnl_sum() -> float:
    row = fetchone("""        SELECT COALESCE(SUM(pnl), 0.0) FROM trades
        WHERE status='CLOSED'
          AND date(ts_close, 'unixepoch', 'localtime') = date('now', 'localtime')
    """)
    return float(row[0] if row and row[0] is not None else 0.0)

def export_trades_csv(filepath: str, pair: str | None = None) -> str:
    if pair:
        rows = fetchall(            """            SELECT id,pair,side,qty,entry,exit,pnl,status,
                   datetime(ts_open,'unixepoch','localtime') AS opened_at,
                   COALESCE(datetime(ts_close,'unixepoch','localtime'),'') AS closed_at
            FROM trades
            WHERE pair=?
            ORDER BY id ASC
            """, (pair,))
    else:
        rows = fetchall(            """            SELECT id,pair,side,qty,entry,exit,pnl,status,
                   datetime(ts_open,'unixepoch','localtime') AS opened_at,
                   COALESCE(datetime(ts_close,'unixepoch','localtime'),'') AS closed_at
            FROM trades
            ORDER BY id ASC
            """
        )
    headers = ["id","pair","side","qty","entry","exit","pnl","status","opened_at","closed_at"]
    import os, csv
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    return filepath

def format_trades_brief(rows: List[Tuple], kind: str) -> str:
    if not rows:
        return f"No {kind} trades."
    lines = [f"{kind} trades ({len(rows)}):"]
    for r in rows[:10]:
        if len(r) == 6:
            _id, pr, side, qty, entry, ts_open = r
            lines.append(f"#{_id} {pr} {side} qty={qty:g} entry={entry:g}")
        else:
            _id, pr, side, qty, entry, ex, pnl, ts_close = r
            lines.append(f"#{_id} {pr} {side} qty={qty:g} entry={entry:g} → exit={ex if ex is not None else '-'} pnl={_fmt_usd(pnl)}")
    return "\n".join(lines)
