# risk.py
# Risk management: entry gates, position sizing, cooldowns, kill switch
import time
import json
import logging
from config import SETTINGS
from storage import fetchall, fetchone, execute

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Basic queries
# -------------------------------------------------------------------
def realized_pnl_today() -> float:
    start = int(time.time()) - 86400
    rows = fetchall('SELECT COALESCE(SUM(pnl),0) FROM trades WHERE ts_close IS NOT NULL AND ts_close>=?', (start,))
    return float(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else 0.0

def open_trade_count() -> int:
    rows = fetchall("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
    return int(rows[0][0]) if rows else 0

def trade_count_today() -> int:
    start = int(time.time()) - 86400
    rows = fetchall('SELECT COUNT(*) FROM trades WHERE ts_open>=?', (start,))
    return int(rows[0][0]) if rows else 0

def last_trade_ts(pair: str = None) -> int:
    if pair:
        row = fetchone('SELECT MAX(ts_open) FROM trades WHERE pair=?', (pair,))
    else:
        row = fetchone('SELECT MAX(ts_open) FROM trades')
    return int(row[0]) if row and row[0] else 0

def consecutive_losses(pair: str = None) -> int:
    if pair:
        rows = fetchall("SELECT pnl FROM trades WHERE status='CLOSED' AND pair=? ORDER BY ts_close DESC LIMIT 20", (pair,))
    else:
        rows = fetchall("SELECT pnl FROM trades WHERE status='CLOSED' ORDER BY ts_close DESC LIMIT 20")
    count = 0
    for (pnl,) in rows:
        if pnl is not None and float(pnl) < 0:
            count += 1
        else:
            break
    return count

# -------------------------------------------------------------------
# Original gate (kept for backward compatibility)
# -------------------------------------------------------------------
def can_enter(max_open_trades: int, daily_loss_limit: float) -> bool:
    if open_trade_count() >= max_open_trades: return False
    if realized_pnl_today() <= -abs(daily_loss_limit): return False
    return True

# -------------------------------------------------------------------
# Enhanced gate with cooldowns, kill switch, etc.
# -------------------------------------------------------------------
def is_in_cooldown(pair: str = None) -> tuple:
    """Returns (is_cooling_down, reason)."""
    last_ts = last_trade_ts(pair)
    if last_ts == 0:
        return False, ''
    elapsed = int(time.time()) - last_ts
    if elapsed < SETTINGS.COOLDOWN_AFTER_TRADE_SECONDS:
        remaining = SETTINGS.COOLDOWN_AFTER_TRADE_SECONDS - elapsed
        return True, f'Cooldown: {remaining}s remaining'
    return False, ''

def is_consecutive_loss_paused() -> tuple:
    """Returns (is_paused, reason)."""
    losses = consecutive_losses()
    if losses >= SETTINGS.CONSECUTIVE_LOSS_COOLDOWN:
        last_ts = last_trade_ts()
        elapsed = int(time.time()) - last_ts
        if elapsed < SETTINGS.CONSECUTIVE_LOSS_PAUSE_SECONDS:
            remaining = SETTINGS.CONSECUTIVE_LOSS_PAUSE_SECONDS - elapsed
            return True, f'{losses} consecutive losses, paused {remaining}s'
    return False, ''

def is_duplicate_trade(pair: str, side: str) -> bool:
    rows = fetchall("SELECT COUNT(*) FROM trades WHERE status='OPEN' AND pair=? AND side=?", (pair, side.upper()))
    return int(rows[0][0]) > 0 if rows else False

def can_enter_enhanced(pair: str, side: str, signal_snapshot: dict = None) -> tuple:
    """
    Combined risk gate. Returns (allowed: bool, reason: str).
    Blocked trades are logged to blocked_trades table.
    """
    # 1. Kill switch
    if SETTINGS.KILL_SWITCH:
        _log_blocked(pair, side, 'Kill switch active', signal_snapshot)
        return False, 'Kill switch active'

    # 2. Open trades limit
    if open_trade_count() >= SETTINGS.MAX_OPEN_TRADES:
        _log_blocked(pair, side, f'Max open trades ({SETTINGS.MAX_OPEN_TRADES})', signal_snapshot)
        return False, f'Max open trades ({SETTINGS.MAX_OPEN_TRADES})'

    # 2.5 Portfolio exposure limit
    can_trade, current_exp, remaining = portfolio_exposure_check()
    if not can_trade:
        max_exp = SETTINGS.CAPITAL_USD * SETTINGS.MAX_PORTFOLIO_EXPOSURE
        _log_blocked(pair, side, f'Portfolio exposure ${current_exp:.0f}/${max_exp:.0f}', signal_snapshot)
        return False, f'Portfolio full (${current_exp:.0f}/${max_exp:.0f})'

    # 3. Daily loss limit
    pnl = realized_pnl_today()
    if pnl <= -abs(SETTINGS.DAILY_LOSS_LIMIT_USD):
        _log_blocked(pair, side, f'Daily loss limit (${SETTINGS.DAILY_LOSS_LIMIT_USD})', signal_snapshot)
        return False, f'Daily loss limit (PnL: ${pnl:.2f})'

    # 4. Daily trade count
    if trade_count_today() >= SETTINGS.MAX_DAILY_TRADES:
        _log_blocked(pair, side, f'Max daily trades ({SETTINGS.MAX_DAILY_TRADES})', signal_snapshot)
        return False, f'Max daily trades ({SETTINGS.MAX_DAILY_TRADES})'

    # 5. Cooldown
    cooling, cool_reason = is_in_cooldown(pair)
    if cooling:
        _log_blocked(pair, side, cool_reason, signal_snapshot)
        return False, cool_reason

    # 6. Consecutive loss pause
    paused, pause_reason = is_consecutive_loss_paused()
    if paused:
        _log_blocked(pair, side, pause_reason, signal_snapshot)
        return False, pause_reason

    # 7. Duplicate trade check
    if is_duplicate_trade(pair, side):
        _log_blocked(pair, side, f'Duplicate {side} on {pair}', signal_snapshot)
        return False, f'Duplicate {side} already open on {pair}'

    # 8. Dry run mode (allow but flag)
    if SETTINGS.DRY_RUN_MODE:
        return True, 'DRY RUN - would trade'

    return True, 'OK'

def _log_blocked(pair: str, side: str, reason: str, snapshot: dict = None):
    try:
        execute(
            'INSERT INTO blocked_trades(ts, pair, side, reason, signal_snapshot) VALUES(?,?,?,?,?)',
            (int(time.time()), pair, side, reason, json.dumps(snapshot) if snapshot else None)
        )
    except Exception as e:
        log.warning("Failed to log blocked trade: %s", e)

# -------------------------------------------------------------------
# Position sizing
# -------------------------------------------------------------------
def position_size(price: float, atr_value: float) -> float:
    if atr_value <= 0 or price <= 0:
        return 0.0
    risk_usd = SETTINGS.RISK_PER_TRADE * SETTINGS.CAPITAL_USD
    sl_distance = atr_value * SETTINGS.ATR_SL_MULTIPLIER
    qty = risk_usd / sl_distance
    return round(qty, 6)

def atr_stop_loss(entry_price: float, atr_value: float, side: str = "BUY") -> float:
    distance = atr_value * SETTINGS.ATR_SL_MULTIPLIER
    if side.upper() == "BUY":
        return round(entry_price - distance, 6)
    return round(entry_price + distance, 6)

# -------------------------------------------------------------------
# Break-even logic
# -------------------------------------------------------------------
def should_move_to_break_even(entry_price: float, current_price: float, atr_value: float, side: str = "BUY") -> bool:
    """True if price moved BREAK_EVEN_ATR_MULTIPLIER * ATR in favor."""
    if atr_value <= 0:
        return False
    threshold = atr_value * SETTINGS.BREAK_EVEN_ATR_MULTIPLIER
    if side.upper() == "BUY":
        return current_price >= entry_price + threshold
    return current_price <= entry_price - threshold

# -------------------------------------------------------------------
# Portfolio exposure
# -------------------------------------------------------------------
def portfolio_exposure_check() -> tuple:
    """Returns (can_trade, current_exposure_usd, remaining_usd)."""
    rows = fetchall("SELECT qty, entry FROM trades WHERE status='OPEN'")
    total_exposure = sum(float(r[0]) * float(r[1]) for r in rows if r[0] and r[1])
    max_allowed = SETTINGS.CAPITAL_USD * SETTINGS.MAX_PORTFOLIO_EXPOSURE
    remaining = max(0, max_allowed - total_exposure)
    return remaining > 0, total_exposure, remaining

# -------------------------------------------------------------------
# Confidence-scaled position sizing
# -------------------------------------------------------------------
def confidence_scaled_position_size(price: float, atr_value: float,
                                     confidence: float, setup_quality: float,
                                     remaining_capital: float) -> float:
    """Position size scaled by confidence and quality, capped by capital limits."""
    if atr_value <= 0 or price <= 0:
        return 0.0
    base_qty = position_size(price, atr_value)
    conf_range = max(0.01, 1.0 - SETTINGS.AI_CONFIDENCE_MIN)
    conf_normalized = max(0, min(1, (confidence - SETTINGS.AI_CONFIDENCE_MIN) / conf_range))
    conf_factor = SETTINGS.CONFIDENCE_SCALE_MIN + conf_normalized * (SETTINGS.CONFIDENCE_SCALE_MAX - SETTINGS.CONFIDENCE_SCALE_MIN)
    quality_bonus = min(1.2, 1.0 + setup_quality * 0.2)
    scaled_qty = base_qty * conf_factor * quality_bonus
    max_by_capital = (SETTINGS.CAPITAL_PER_TRADE_PCT * SETTINGS.CAPITAL_USD) / price
    max_by_remaining = remaining_capital / price
    return round(max(0.0, min(scaled_qty, max_by_capital, max_by_remaining)), 6)

# -------------------------------------------------------------------
# Setup quality filter
# -------------------------------------------------------------------
def should_skip_weak_setup(setup_quality: float, risk_flags: list, confidence: float) -> tuple:
    """Returns (should_skip, reason)."""
    if setup_quality < SETTINGS.MIN_SETUP_QUALITY:
        return True, f'Quality {setup_quality:.2f} < {SETTINGS.MIN_SETUP_QUALITY}'
    if len(risk_flags) > SETTINGS.MAX_RISK_FLAGS:
        return True, f'{len(risk_flags)} risk flags > max {SETTINGS.MAX_RISK_FLAGS}'
    if confidence < SETTINGS.AI_CONFIDENCE_MIN:
        return True, f'Confidence {confidence:.2f} < {SETTINGS.AI_CONFIDENCE_MIN}'
    return False, 'OK'

# -------------------------------------------------------------------
# Take-profit
# -------------------------------------------------------------------
def atr_take_profit(entry_price: float, atr_value: float, side: str = "BUY") -> float:
    """TP at TP_ATR_MULTIPLIER * ATR from entry."""
    distance = atr_value * SETTINGS.TP_ATR_MULTIPLIER
    if side.upper() == "BUY":
        return round(entry_price + distance, 6)
    return round(entry_price - distance, 6)
