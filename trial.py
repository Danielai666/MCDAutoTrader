# trial.py
# Trial Mode — a UX/tracking layer on top of existing paper trading.
#
# It does NOT modify the trading engine, risk engine, execution layer,
# or database schema meaningfully. It only:
#   - Records when a user starts a structured trial (start_ts, capital,
#     target_days) in 5 additive columns on the users table.
#   - Computes aggregate metrics by filtering the existing trades table
#     on user_id + ts_open >= trial_start_ts.
#   - Renders English or Farsi status / report / summary strings via i18n.
#
# Paper trading engine is used as-is. When /trial start is issued, we:
#   - set trade_mode = 'PAPER'
#   - set autotrade_enabled = 1
#   - set capital_usd = <trial capital>
#   - stamp trial_active / trial_start_ts / trial_capital / trial_target_days
#
# /trial go_live flips trade_mode to 'LIVE' (subject to LIVE_TRADE_ALLOWED_IDS)
# and kicks reconcile — purely UI plumbing over existing commands.

import logging
import time
from dataclasses import dataclass
from typing import Optional

from config import SETTINGS
from storage import execute, fetchone, fetchall
from i18n import t as _t

log = logging.getLogger(__name__)


def is_enabled() -> bool:
    return bool(getattr(SETTINGS, "FEATURE_TRIAL_MODE", True))


# -------------------------------------------------------------------
# Trial state (reads the 5 additive columns on users)
# -------------------------------------------------------------------
@dataclass
class TrialState:
    active: bool = False
    start_ts: int = 0
    capital: float = 0.0
    target_days: int = 14

    @property
    def days_elapsed(self) -> float:
        if self.start_ts <= 0:
            return 0.0
        return max(0.0, (time.time() - self.start_ts) / 86400.0)

    @property
    def day_index(self) -> int:
        return max(1, min(self.target_days, int(self.days_elapsed) + 1))


def get_trial(uid: int) -> TrialState:
    try:
        row = fetchone(
            "SELECT trial_active, trial_start_ts, trial_capital, trial_target_days "
            "FROM users WHERE user_id=?",
            (uid,),
        )
    except Exception as e:
        log.debug("trial.get_trial query failed: %s", e)
        return TrialState()
    if not row:
        return TrialState()
    return TrialState(
        active=bool(row[0]) if row[0] is not None else False,
        start_ts=int(row[1]) if row[1] else 0,
        capital=float(row[2]) if row[2] else 0.0,
        target_days=int(row[3]) if row[3] else 14,
    )


def start_trial(uid: int, capital: float, target_days: int = 14) -> bool:
    if capital <= 0:
        return False
    try:
        ts = int(time.time())
        execute(
            "UPDATE users SET trial_active=1, trial_start_ts=?, trial_capital=?, "
            "trial_target_days=?, capital_usd=?, trade_mode='PAPER', autotrade_enabled=1 "
            "WHERE user_id=?",
            (ts, float(capital), int(target_days), float(capital), uid),
        )
        return True
    except Exception as e:
        log.error("trial.start_trial failed for uid=%s: %s", uid, e)
        return False


def stop_trial(uid: int) -> bool:
    try:
        execute("UPDATE users SET trial_active=0 WHERE user_id=?", (uid,))
        return True
    except Exception as e:
        log.error("trial.stop_trial failed for uid=%s: %s", uid, e)
        return False


# -------------------------------------------------------------------
# Metrics — aggregate from the existing trades table
# -------------------------------------------------------------------
@dataclass
class TrialMetrics:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    open_positions: int = 0
    realized_pnl: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    equity: float = 0.0
    roi_pct: float = 0.0

    @property
    def win_rate(self) -> float:
        closed = self.wins + self.losses
        return (self.wins / closed * 100.0) if closed else 0.0


def compute_metrics(uid: int, trial: TrialState) -> TrialMetrics:
    m = TrialMetrics()
    if not trial.active or trial.start_ts <= 0:
        return m

    # Closed trades within the trial window
    try:
        closed = fetchall(
            "SELECT pnl FROM trades "
            "WHERE user_id=? AND status='CLOSED' AND ts_open >= ?",
            (uid, trial.start_ts),
        )
    except Exception as e:
        log.debug("trial.compute_metrics closed query failed: %s", e)
        closed = []

    wins = losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    realized = 0.0

    # Chronological cumulative PnL for drawdown
    try:
        chrono = fetchall(
            "SELECT pnl FROM trades "
            "WHERE user_id=? AND status='CLOSED' AND ts_open >= ? "
            "ORDER BY ts_close ASC",
            (uid, trial.start_ts),
        )
    except Exception:
        chrono = closed

    peak = 0.0
    running = 0.0
    max_dd = 0.0
    for r in chrono:
        pnl = float(r[0] or 0.0)
        running += pnl
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    for r in closed:
        pnl = float(r[0] or 0.0)
        realized += pnl
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            losses += 1
            gross_loss += -pnl

    try:
        open_row = fetchone(
            "SELECT COUNT(*) FROM trades WHERE user_id=? AND status='OPEN' "
            "AND ts_open >= ?",
            (uid, trial.start_ts),
        )
        m.open_positions = int(open_row[0]) if open_row and open_row[0] else 0
    except Exception:
        m.open_positions = 0

    m.trades = len(closed) + m.open_positions
    m.wins = wins
    m.losses = losses
    m.realized_pnl = round(realized, 2)
    m.max_drawdown = round(max_dd, 2)
    if gross_loss > 0:
        m.profit_factor = round(gross_profit / gross_loss, 2)
    elif gross_profit > 0:
        m.profit_factor = float("inf")
    else:
        m.profit_factor = 0.0
    m.equity = round(trial.capital + realized, 2)
    if trial.capital > 0:
        m.roi_pct = round((realized / trial.capital) * 100.0, 2)
    return m


# -------------------------------------------------------------------
# Rendering helpers (bilingual)
# -------------------------------------------------------------------
def _progress_bar(elapsed_days: float, target_days: int, width: int = 10) -> str:
    if target_days <= 0:
        return "░" * width
    pct = max(0.0, min(1.0, elapsed_days / target_days))
    filled = int(round(pct * width))
    return ("█" * filled) + ("░" * (width - filled))


def _age_human(seconds: float, uid: int) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def panel_block(uid: int) -> str:
    """Short block to inject into the control panel when a trial is active."""
    if not is_enabled():
        return ""
    trial = get_trial(uid)
    if not trial.active:
        return ""
    bar = _progress_bar(trial.days_elapsed, trial.target_days)
    day_now = min(trial.target_days, int(trial.days_elapsed) + 1)
    day_word = _t(uid, "trial_days")
    progress_label = _t(uid, "trial_progress")
    capital_label = _t(uid, "trial_capital")
    return (
        f"{progress_label}: `{bar}` {day_now}/{trial.target_days} {day_word}\n"
        f"{capital_label}: `${trial.capital:,.2f}`"
    )


def render_status(uid: int) -> str:
    if not is_enabled():
        return _t(uid, "trial_not_active")
    trial = get_trial(uid)
    if not trial.active:
        return _t(uid, "trial_not_active")
    m = compute_metrics(uid, trial)
    running = _age_human(time.time() - trial.start_ts, uid)
    day_now = min(trial.target_days, int(trial.days_elapsed) + 1)
    lines = [
        f"*{_t(uid, 'trial_status')}*",
        f"{_t(uid, 'trial_running_time')}: `{running}`  ({day_now}/{trial.target_days} {_t(uid, 'trial_days')})",
        f"{_t(uid, 'trial_capital')}: `${trial.capital:,.2f}`",
        f"{_t(uid, 'trial_current_equity')}: `${m.equity:,.2f}`",
        f"{_t(uid, 'trial_pnl')}: `${m.realized_pnl:,.2f}`  ({_t(uid, 'trial_roi')}: {m.roi_pct:+.2f}%)",
        f"{_t(uid, 'trial_progress')}: `{_progress_bar(trial.days_elapsed, trial.target_days)}`",
    ]
    return "\n".join(lines)


def render_report(uid: int, limit: int = 10) -> str:
    if not is_enabled():
        return _t(uid, "trial_not_active")
    trial = get_trial(uid)
    if not trial.active:
        return _t(uid, "trial_not_active")

    # Recent closed
    try:
        recent = fetchall(
            "SELECT ts_close, pair, side, pnl FROM trades "
            "WHERE user_id=? AND status='CLOSED' AND ts_open >= ? "
            "ORDER BY ts_close DESC LIMIT ?",
            (uid, trial.start_ts, limit),
        )
    except Exception:
        recent = []
    try:
        open_rows = fetchall(
            "SELECT pair, side, qty, entry FROM trades "
            "WHERE user_id=? AND status='OPEN' AND ts_open >= ?",
            (uid, trial.start_ts),
        )
    except Exception:
        open_rows = []

    lines = [f"*{_t(uid, 'trial_report')}*"]
    lines.append(f"_{_t(uid, 'trial_recent_trades')}_:")
    if not recent:
        lines.append(_t(uid, "trial_no_trades"))
    else:
        for r in recent:
            ts_close, pair, side, pnl = r
            tag = "✅" if (pnl or 0) > 0 else "❌" if (pnl or 0) < 0 else "➖"
            lines.append(f"{tag} `{pair}` {side}  `${float(pnl or 0):+.2f}`")

    lines.append("")
    lines.append(f"_{_t(uid, 'trial_open_positions')}_:")
    if not open_rows:
        lines.append(_t(uid, "trial_no_open"))
    else:
        for r in open_rows:
            pair, side, qty, entry = r
            lines.append(f"• `{pair}` {side}  qty=`{float(qty or 0):.4f}`  @ `${float(entry or 0):,.2f}`")

    return "\n".join(lines)


def render_summary(uid: int) -> str:
    if not is_enabled():
        return _t(uid, "trial_not_active")
    trial = get_trial(uid)
    if not trial.active:
        return _t(uid, "trial_not_active")

    m = compute_metrics(uid, trial)
    running = _age_human(time.time() - trial.start_ts, uid)
    day_now = min(trial.target_days, int(trial.days_elapsed) + 1)

    lines = [
        f"*{_t(uid, 'trial_summary')}*",
        f"{_t(uid, 'trial_running_time')}: `{running}`  ({day_now}/{trial.target_days} {_t(uid, 'trial_days')})",
        f"{_t(uid, 'trial_capital')}: `${trial.capital:,.2f}`",
        f"{_t(uid, 'trial_current_equity')}: `${m.equity:,.2f}`",
        f"{_t(uid, 'trial_total_pnl')}: `${m.realized_pnl:,.2f}`  ({_t(uid, 'trial_roi')}: {m.roi_pct:+.2f}%)",
        f"{_t(uid, 'trial_trades_count')}: `{m.trades}`  ({m.wins}W / {m.losses}L)",
        f"{_t(uid, 'trial_win_rate')}: `{m.win_rate:.1f}%`",
        f"{_t(uid, 'trial_max_drawdown')}: `${m.max_drawdown:,.2f}`",
        f"{_t(uid, 'trial_profit_factor')}: `{m.profit_factor:.2f}`" if m.profit_factor != float("inf") else f"{_t(uid, 'trial_profit_factor')}: `∞`",
        f"{_t(uid, 'trial_progress')}: `{_progress_bar(trial.days_elapsed, trial.target_days)}`",
    ]

    # Verdict (not financial advice — heuristic guidance)
    if m.trades >= 5:
        if m.roi_pct > 2.0 and m.win_rate >= 50.0 and m.profit_factor >= 1.3:
            verdict_key = "trial_summary_verdict_good"
        elif m.roi_pct < 0.0 or m.profit_factor < 1.0:
            verdict_key = "trial_summary_verdict_bad"
        else:
            verdict_key = "trial_summary_verdict_mixed"
        lines.append("")
        lines.append(f"_{_t(uid, verdict_key)}_")

    return "\n".join(lines)


# -------------------------------------------------------------------
# Go Live (plumbing — reuses existing live gate)
# -------------------------------------------------------------------
def can_go_live(uid: int) -> bool:
    allowed = getattr(SETTINGS, "LIVE_TRADE_ALLOWED_IDS", ()) or ()
    return uid in allowed


def convert_to_live(uid: int) -> bool:
    if not can_go_live(uid):
        return False
    try:
        execute("UPDATE users SET trade_mode='LIVE', trial_active=0 WHERE user_id=?", (uid,))
        return True
    except Exception as e:
        log.error("trial.convert_to_live failed for uid=%s: %s", uid, e)
        return False
