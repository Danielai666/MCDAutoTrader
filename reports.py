from __future__ import annotations
import time
from typing import List, Tuple
from storage import fetchall, fetchone, execute
from config import SETTINGS


def _fmt_usd(x):
    if x is None: return "-"
    return f"${float(x):.2f}"


# -------------------------------------------------------------------
# Trade queries (user_id=None → all users for backward compat)
# -------------------------------------------------------------------
def get_open_trades(user_id: int = None, pair: str | None = None) -> List[Tuple]:
    if user_id is not None and pair:
        return fetchall(
            "SELECT id,pair,side,qty,entry,ts_open FROM trades WHERE status='OPEN' AND user_id=? AND pair=? ORDER BY id DESC", (user_id, pair))
    elif user_id is not None:
        return fetchall(
            "SELECT id,pair,side,qty,entry,ts_open FROM trades WHERE status='OPEN' AND user_id=? ORDER BY id DESC", (user_id,))
    elif pair:
        return fetchall(
            "SELECT id,pair,side,qty,entry,ts_open FROM trades WHERE status='OPEN' AND pair=? ORDER BY id DESC", (pair,))
    return fetchall("SELECT id,pair,side,qty,entry,ts_open FROM trades WHERE status='OPEN' ORDER BY id DESC")


def get_recent_closed(n: int = 5, user_id: int = None, pair: str | None = None) -> List[Tuple]:
    if user_id is not None and pair:
        return fetchall(
            "SELECT id,pair,side,qty,entry,exit_price,pnl,ts_close FROM trades WHERE status='CLOSED' AND user_id=? AND pair=? ORDER BY id DESC LIMIT ?",
            (user_id, pair, n))
    elif user_id is not None:
        return fetchall(
            "SELECT id,pair,side,qty,entry,exit_price,pnl,ts_close FROM trades WHERE status='CLOSED' AND user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, n))
    elif pair:
        return fetchall(
            "SELECT id,pair,side,qty,entry,exit_price,pnl,ts_close FROM trades WHERE status='CLOSED' AND pair=? ORDER BY id DESC LIMIT ?",
            (pair, n))
    return fetchall(
        "SELECT id,pair,side,qty,entry,exit_price,pnl,ts_close FROM trades WHERE status='CLOSED' ORDER BY id DESC LIMIT ?",
        (n,))


def daily_pnl_sum(user_id: int = None) -> float:
    start = int(time.time()) - 86400
    if user_id is not None:
        row = fetchone("SELECT COALESCE(SUM(pnl), 0.0) FROM trades WHERE status='CLOSED' AND ts_close>=? AND user_id=?", (start, user_id))
    else:
        row = fetchone("SELECT COALESCE(SUM(pnl), 0.0) FROM trades WHERE status='CLOSED' AND ts_close>=?", (start,))
    return float(row[0] if row and row[0] is not None else 0.0)


# -------------------------------------------------------------------
# Performance summary
# -------------------------------------------------------------------
def performance_summary(user_id: int = None, pair: str = None, days: int = 30) -> dict:
    start = int(time.time()) - (days * 86400)
    if user_id is not None and pair:
        rows = fetchall("SELECT pnl FROM trades WHERE status='CLOSED' AND user_id=? AND pair=? AND ts_close>=?", (user_id, pair, start))
    elif user_id is not None:
        rows = fetchall("SELECT pnl FROM trades WHERE status='CLOSED' AND user_id=? AND ts_close>=?", (user_id, start))
    elif pair:
        rows = fetchall("SELECT pnl FROM trades WHERE status='CLOSED' AND pair=? AND ts_close>=?", (pair, start))
    else:
        rows = fetchall("SELECT pnl FROM trades WHERE status='CLOSED' AND ts_close>=?", (start,))

    pnls = [float(r[0]) for r in rows if r[0] is not None]
    total = len(pnls)
    if total == 0:
        return {'total_trades': 0, 'winning': 0, 'losing': 0, 'win_rate': 0,
                'total_pnl': 0, 'avg_win': 0, 'avg_loss': 0, 'expectancy': 0,
                'profit_factor': 0, 'largest_win': 0, 'largest_loss': 0}

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / total if total > 0 else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    total_win = sum(wins)
    total_loss = abs(sum(losses))
    profit_factor = total_win / total_loss if total_loss > 0 else float('inf') if total_win > 0 else 0
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    return {
        'total_trades': total,
        'winning': len(wins),
        'losing': len(losses),
        'win_rate': round(win_rate * 100, 1),
        'total_pnl': round(sum(pnls), 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'expectancy': round(expectancy, 2),
        'profit_factor': round(profit_factor, 2),
        'largest_win': round(max(wins) if wins else 0, 2),
        'largest_loss': round(min(losses) if losses else 0, 2),
    }


# -------------------------------------------------------------------
# Formatted reports
# -------------------------------------------------------------------
def format_position_report(user_id: int = None) -> str:
    rows = get_open_trades(user_id)
    if not rows:
        return "No open positions."
    lines = ["Open Positions:"]
    for _id, pair, side, qty, entry, ts_open in rows:
        try:
            from exchange import market_price
            px = market_price(pair)
            unrealized = (px - float(entry)) * float(qty) if side == 'BUY' else (float(entry) - px) * float(qty)
            lines.append(f"#{_id} {pair} {side} {qty:g} @ {entry:g} | now {px:.2f} | uPnL: {_fmt_usd(unrealized)}")
        except Exception:
            lines.append(f"#{_id} {pair} {side} {qty:g} @ {entry:g}")
    return "\n".join(lines)


def format_pnl_report(user_id: int = None, pair: str = None, days: int = 30) -> str:
    s = performance_summary(user_id, pair, days)
    pair_txt = pair or "All pairs"
    return (
        f"Performance Report ({pair_txt}, {days}d)\n"
        f"Trades: {s['total_trades']} (W:{s['winning']} L:{s['losing']})\n"
        f"Win Rate: {s['win_rate']}%\n"
        f"Total PnL: {_fmt_usd(s['total_pnl'])}\n"
        f"Avg Win: {_fmt_usd(s['avg_win'])} | Avg Loss: {_fmt_usd(s['avg_loss'])}\n"
        f"Expectancy: {_fmt_usd(s['expectancy'])}\n"
        f"Profit Factor: {s['profit_factor']}\n"
        f"Best: {_fmt_usd(s['largest_win'])} | Worst: {_fmt_usd(s['largest_loss'])}"
    )


def daily_report(user_id: int = None, pair: str = None) -> str:
    pnl = daily_pnl_sum(user_id)
    closed = get_recent_closed(n=50, user_id=user_id, pair=pair)
    today_count = len(closed)

    equity_lines = ""
    try:
        from risk import get_equity_status
        from user_context import UserContext
        ctx = UserContext.load(user_id) if user_id else None
        eq = get_equity_status(ctx)
        equity_lines = (
            f"\nEquity: {_fmt_usd(eq['equity'])} (peak: {_fmt_usd(eq['peak_equity'])})\n"
            f"Drawdown: {eq['drawdown_pct']:.1%} ({_fmt_usd(eq['drawdown_usd'])})\n"
            f"Max Drawdown: {eq['max_drawdown_pct']:.1%}"
        )
    except Exception:
        pass

    return (
        f"Daily Summary\n"
        f"PnL Today: {_fmt_usd(pnl)}\n"
        f"Trades Closed: {today_count}\n"
        f"Open Positions: {len(get_open_trades(user_id, pair))}"
        f"{equity_lines}"
    )


def format_trade_close_report(trade_id: int) -> str:
    """Generate a close report for a single trade with PnL, R:R, duration."""
    import json
    row = fetchone(
        "SELECT pair, side, qty, entry, exit_price, pnl, ts_open, ts_close, entry_snapshot "
        "FROM trades WHERE id=?", (trade_id,))
    if not row:
        return ""
    pair, side, qty, entry, exit_price, pnl, ts_open, ts_close, snap_json = row
    qty = float(qty) if qty else 0
    entry = float(entry) if entry else 0
    exit_price = float(exit_price) if exit_price else 0
    pnl = float(pnl) if pnl else 0
    duration_mins = ((ts_close or 0) - (ts_open or 0)) / 60

    rr_txt = ""
    if snap_json:
        try:
            snap = json.loads(snap_json)
            atr = snap.get('atr_at_entry', 0)
            if atr > 0:
                from config import SETTINGS
                risk_dist = atr * SETTINGS.ATR_SL_MULTIPLIER
                reward = abs(exit_price - entry)
                rr = reward / risk_dist if risk_dist > 0 else 0
                rr_txt = f" | R:R 1:{rr:.1f}"
        except Exception:
            pass

    sign = '+' if pnl >= 0 else ''
    return (
        f"Trade Closed #{trade_id}\n"
        f"{pair} {side} {qty:g} @ {entry:g} -> {exit_price:g}\n"
        f"PnL: {sign}${pnl:.2f}{rr_txt}\n"
        f"Duration: {duration_mins:.0f}m"
    )


def blocked_trades_summary(user_id: int = None, days: int = 7) -> str:
    start = int(time.time()) - (days * 86400)
    if user_id is not None:
        rows = fetchall("SELECT pair, side, reason, ts FROM blocked_trades WHERE ts>=? AND user_id=? ORDER BY ts DESC LIMIT 10", (start, user_id))
    else:
        rows = fetchall("SELECT pair, side, reason, ts FROM blocked_trades WHERE ts>=? ORDER BY ts DESC LIMIT 10", (start,))
    if not rows:
        return f"No blocked trades in last {days} days."
    lines = [f"Blocked Trades (last {days}d):"]
    for pair, side, reason, ts in rows:
        lines.append(f"  {pair} {side}: {reason}")
    return "\n".join(lines)


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
            lines.append(f"#{_id} {pr} {side} qty={qty:g} entry={entry:g} -> exit={ex if ex else '-'} pnl={_fmt_usd(pnl)}")
    return "\n".join(lines)


# -------------------------------------------------------------------
# CSV export
# -------------------------------------------------------------------
def export_trades_csv(filepath: str, user_id: int = None, pair: str | None = None) -> str:
    if user_id is not None and pair:
        rows = fetchall(
            "SELECT id,pair,side,qty,entry,exit_price,pnl,status,ts_open,ts_close FROM trades WHERE user_id=? AND pair=? ORDER BY id",
            (user_id, pair))
    elif user_id is not None:
        rows = fetchall(
            "SELECT id,pair,side,qty,entry,exit_price,pnl,status,ts_open,ts_close FROM trades WHERE user_id=? ORDER BY id",
            (user_id,))
    elif pair:
        rows = fetchall(
            "SELECT id,pair,side,qty,entry,exit_price,pnl,status,ts_open,ts_close FROM trades WHERE pair=? ORDER BY id",
            (pair,))
    else:
        rows = fetchall("SELECT id,pair,side,qty,entry,exit_price,pnl,status,ts_open,ts_close FROM trades ORDER BY id")
    headers = ["id", "pair", "side", "qty", "entry", "exit", "pnl", "status", "ts_open", "ts_close"]
    import os, csv
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    return filepath


# -------------------------------------------------------------------
# Performance snapshot persistence
# -------------------------------------------------------------------
def save_performance_snapshot(user_id: int = None, pair: str = None, period: str = 'daily'):
    s = performance_summary(user_id, pair, days=30)
    execute(
        """INSERT INTO performance_snapshots(ts, pair, period, total_trades, winning_trades,
           losing_trades, total_pnl, avg_win, avg_loss, win_rate, expectancy, user_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (int(time.time()), pair or 'ALL', period, s['total_trades'], s['winning'],
         s['losing'], s['total_pnl'], s['avg_win'], s['avg_loss'], s['win_rate'], s['expectancy'], user_id)
    )
