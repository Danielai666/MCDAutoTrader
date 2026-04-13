# risk.py
# Risk management: entry gates, position sizing, cooldowns, kill switch
# All query functions accept optional user_id for multi-tenant scoping.
import time
import json
import logging
from config import SETTINGS
from storage import fetchall, fetchone, execute, upsert_bot_state

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Basic queries (user_id=None → all users, for backward compat)
# -------------------------------------------------------------------
def realized_pnl_today(user_id: int = None) -> float:
    start = int(time.time()) - 86400
    if user_id is not None:
        rows = fetchall('SELECT COALESCE(SUM(pnl),0) FROM trades WHERE ts_close IS NOT NULL AND ts_close>=? AND user_id=?', (start, user_id))
    else:
        rows = fetchall('SELECT COALESCE(SUM(pnl),0) FROM trades WHERE ts_close IS NOT NULL AND ts_close>=?', (start,))
    return float(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else 0.0

def open_trade_count(user_id: int = None) -> int:
    if user_id is not None:
        rows = fetchall("SELECT COUNT(*) FROM trades WHERE status='OPEN' AND user_id=?", (user_id,))
    else:
        rows = fetchall("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
    return int(rows[0][0]) if rows else 0

def trade_count_today(user_id: int = None) -> int:
    start = int(time.time()) - 86400
    if user_id is not None:
        rows = fetchall('SELECT COUNT(*) FROM trades WHERE ts_open>=? AND user_id=?', (start, user_id))
    else:
        rows = fetchall('SELECT COUNT(*) FROM trades WHERE ts_open>=?', (start,))
    return int(rows[0][0]) if rows else 0

def last_trade_ts(user_id: int = None, pair: str = None) -> int:
    if user_id is not None and pair:
        row = fetchone('SELECT MAX(ts_open) FROM trades WHERE pair=? AND user_id=?', (pair, user_id))
    elif user_id is not None:
        row = fetchone('SELECT MAX(ts_open) FROM trades WHERE user_id=?', (user_id,))
    elif pair:
        row = fetchone('SELECT MAX(ts_open) FROM trades WHERE pair=?', (pair,))
    else:
        row = fetchone('SELECT MAX(ts_open) FROM trades')
    return int(row[0]) if row and row[0] else 0

def consecutive_losses(user_id: int = None, pair: str = None) -> int:
    if user_id is not None and pair:
        rows = fetchall("SELECT pnl FROM trades WHERE status='CLOSED' AND pair=? AND user_id=? ORDER BY ts_close DESC LIMIT 20", (pair, user_id))
    elif user_id is not None:
        rows = fetchall("SELECT pnl FROM trades WHERE status='CLOSED' AND user_id=? ORDER BY ts_close DESC LIMIT 20", (user_id,))
    elif pair:
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
# Accepts optional ctx (UserContext) for per-user settings.
# -------------------------------------------------------------------
def is_in_cooldown(user_id: int = None, pair: str = None) -> tuple:
    """Returns (is_cooling_down, reason)."""
    last_ts = last_trade_ts(user_id, pair)
    if last_ts == 0:
        return False, ''
    elapsed = int(time.time()) - last_ts
    if elapsed < SETTINGS.COOLDOWN_AFTER_TRADE_SECONDS:
        remaining = SETTINGS.COOLDOWN_AFTER_TRADE_SECONDS - elapsed
        return True, f'Cooldown: {remaining}s remaining'
    return False, ''

def is_consecutive_loss_paused(user_id: int = None) -> tuple:
    """Returns (is_paused, reason)."""
    losses = consecutive_losses(user_id)
    if losses >= SETTINGS.CONSECUTIVE_LOSS_COOLDOWN:
        last_ts = last_trade_ts(user_id)
        elapsed = int(time.time()) - last_ts
        if elapsed < SETTINGS.CONSECUTIVE_LOSS_PAUSE_SECONDS:
            remaining = SETTINGS.CONSECUTIVE_LOSS_PAUSE_SECONDS - elapsed
            return True, f'{losses} consecutive losses, paused {remaining}s'
    return False, ''

def is_duplicate_trade(user_id: int = None, pair: str = '', side: str = '') -> bool:
    if user_id is not None:
        rows = fetchall("SELECT COUNT(*) FROM trades WHERE status='OPEN' AND pair=? AND side=? AND user_id=?", (pair, side.upper(), user_id))
    else:
        rows = fetchall("SELECT COUNT(*) FROM trades WHERE status='OPEN' AND pair=? AND side=?", (pair, side.upper()))
    return int(rows[0][0]) > 0 if rows else False

def can_enter_enhanced(pair: str, side: str, signal_snapshot: dict = None, ctx=None) -> tuple:
    """
    Combined risk gate. Returns (allowed: bool, reason: str).
    If ctx (UserContext) is provided, uses per-user settings. Otherwise uses global SETTINGS.
    """
    uid = ctx.user_id if ctx else None
    max_open = ctx.max_open_trades if ctx else SETTINGS.MAX_OPEN_TRADES
    daily_limit = ctx.daily_loss_limit if ctx else SETTINGS.DAILY_LOSS_LIMIT_USD
    capital = ctx.capital_usd if ctx else SETTINGS.CAPITAL_USD
    max_exposure = ctx.max_portfolio_exposure if ctx else SETTINGS.MAX_PORTFOLIO_EXPOSURE

    # 1. Kill switch
    if SETTINGS.KILL_SWITCH:
        _log_blocked(pair, side, 'Kill switch active', signal_snapshot, uid)
        return False, 'Kill switch active'

    # 2. Open trades limit
    if open_trade_count(uid) >= max_open:
        _log_blocked(pair, side, f'Max open trades ({max_open})', signal_snapshot, uid)
        return False, f'Max open trades ({max_open})'

    # 2.5 Portfolio exposure limit
    can_trade, current_exp, remaining = portfolio_exposure_check(ctx)
    if not can_trade:
        max_exp = capital * max_exposure
        _log_blocked(pair, side, f'Portfolio exposure ${current_exp:.0f}/${max_exp:.0f}', signal_snapshot, uid)
        return False, f'Portfolio full (${current_exp:.0f}/${max_exp:.0f})'

    # 3. Daily loss limit
    pnl = realized_pnl_today(uid)
    if pnl <= -abs(daily_limit):
        _log_blocked(pair, side, f'Daily loss limit (${daily_limit})', signal_snapshot, uid)
        return False, f'Daily loss limit (PnL: ${pnl:.2f})'

    # 4. Daily trade count
    if trade_count_today(uid) >= SETTINGS.MAX_DAILY_TRADES:
        _log_blocked(pair, side, f'Max daily trades ({SETTINGS.MAX_DAILY_TRADES})', signal_snapshot, uid)
        return False, f'Max daily trades ({SETTINGS.MAX_DAILY_TRADES})'

    # 5. Cooldown
    cooling, cool_reason = is_in_cooldown(uid, pair)
    if cooling:
        _log_blocked(pair, side, cool_reason, signal_snapshot, uid)
        return False, cool_reason

    # 6. Consecutive loss pause
    paused, pause_reason = is_consecutive_loss_paused(uid)
    if paused:
        _log_blocked(pair, side, pause_reason, signal_snapshot, uid)
        return False, pause_reason

    # 7. Duplicate trade check
    if is_duplicate_trade(uid, pair, side):
        _log_blocked(pair, side, f'Duplicate {side} on {pair}', signal_snapshot, uid)
        return False, f'Duplicate {side} already open on {pair}'

    # 8. Correlation risk check
    corr_ok, corr_reason, corr_pairs = check_correlation_risk(pair, side, uid)
    if not corr_ok:
        _log_blocked(pair, side, corr_reason, signal_snapshot, uid)
        return False, corr_reason

    # 9. Drawdown halt check
    dd_scale = drawdown_position_scale(ctx)
    if dd_scale <= 0.0:
        status = get_equity_status(ctx)
        reason = f"Drawdown halt ({status['drawdown_pct']:.1%} >= {SETTINGS.DRAWDOWN_HALT_THRESHOLD:.0%})"
        _log_blocked(pair, side, reason, signal_snapshot, uid)
        return False, reason

    # 10. Dry run mode (allow but flag)
    if SETTINGS.DRY_RUN_MODE:
        return True, 'DRY RUN - would trade'

    return True, 'OK'

def _log_blocked(pair: str, side: str, reason: str, snapshot: dict = None, user_id: int = None):
    try:
        execute(
            'INSERT INTO blocked_trades(ts, pair, side, reason, signal_snapshot, user_id) VALUES(?,?,?,?,?,?)',
            (int(time.time()), pair, side, reason, json.dumps(snapshot) if snapshot else None, user_id)
        )
    except Exception as e:
        log.warning("Failed to log blocked trade: %s", e)

# -------------------------------------------------------------------
# Position sizing (ctx-aware)
# -------------------------------------------------------------------
def position_size(price: float, atr_value: float, ctx=None) -> float:
    if atr_value <= 0 or price <= 0:
        return 0.0
    rpt = ctx.risk_per_trade if ctx else SETTINGS.RISK_PER_TRADE
    capital = ctx.capital_usd if ctx else SETTINGS.CAPITAL_USD
    risk_usd = rpt * capital
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
    if atr_value <= 0:
        return False
    threshold = atr_value * SETTINGS.BREAK_EVEN_ATR_MULTIPLIER
    if side.upper() == "BUY":
        return current_price >= entry_price + threshold
    return current_price <= entry_price - threshold

# -------------------------------------------------------------------
# Portfolio exposure (ctx-aware)
# -------------------------------------------------------------------
def portfolio_exposure_check(ctx=None) -> tuple:
    """Returns (can_trade, current_exposure_usd, remaining_usd)."""
    uid = ctx.user_id if ctx else None
    if uid is not None:
        rows = fetchall("SELECT qty, entry FROM trades WHERE status='OPEN' AND user_id=?", (uid,))
    else:
        rows = fetchall("SELECT qty, entry FROM trades WHERE status='OPEN'")
    total_exposure = sum(float(r[0]) * float(r[1]) for r in rows if r[0] and r[1])
    capital = ctx.capital_usd if ctx else SETTINGS.CAPITAL_USD
    max_exp_pct = ctx.max_portfolio_exposure if ctx else SETTINGS.MAX_PORTFOLIO_EXPOSURE
    max_allowed = capital * max_exp_pct
    remaining = max(0, max_allowed - total_exposure)
    return remaining > 0, total_exposure, remaining

# -------------------------------------------------------------------
# Confidence-scaled position sizing (ctx-aware)
# -------------------------------------------------------------------
def confidence_scaled_position_size(price: float, atr_value: float,
                                     confidence: float, setup_quality: float,
                                     remaining_capital: float,
                                     dd_scale: float = None, ctx=None) -> float:
    """Position size scaled by confidence, quality, and drawdown."""
    if atr_value <= 0 or price <= 0:
        return 0.0
    base_qty = position_size(price, atr_value, ctx)
    conf_range = max(0.01, 1.0 - SETTINGS.AI_CONFIDENCE_MIN)
    conf_normalized = max(0, min(1, (confidence - SETTINGS.AI_CONFIDENCE_MIN) / conf_range))
    conf_factor = SETTINGS.CONFIDENCE_SCALE_MIN + conf_normalized * (SETTINGS.CONFIDENCE_SCALE_MAX - SETTINGS.CONFIDENCE_SCALE_MIN)
    quality_bonus = min(1.2, 1.0 + setup_quality * 0.2)
    if dd_scale is None:
        dd_scale = drawdown_position_scale(ctx)
    scaled_qty = base_qty * conf_factor * quality_bonus * dd_scale
    cptp = ctx.capital_per_trade_pct if ctx else SETTINGS.CAPITAL_PER_TRADE_PCT
    capital = ctx.capital_usd if ctx else SETTINGS.CAPITAL_USD
    max_by_capital = (cptp * capital) / price
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
    distance = atr_value * SETTINGS.TP_ATR_MULTIPLIER
    if side.upper() == "BUY":
        return round(entry_price + distance, 6)
    return round(entry_price - distance, 6)


# -------------------------------------------------------------------
# ATR-based trailing stop
# -------------------------------------------------------------------
def compute_atr_trailing_stop(entry_price: float, current_price: float,
                               atr_value: float, side: str,
                               current_trail_stop: float = None) -> dict:
    if not SETTINGS.TRAILING_ENABLED or atr_value <= 0:
        return {'active': False, 'trail_stop': None, 'distance_atr': 0,
                'profit_atr': 0, 'tightened': False}
    is_buy = side.upper() == "BUY"
    if is_buy:
        profit_atr = (current_price - entry_price) / atr_value
    else:
        profit_atr = (entry_price - current_price) / atr_value
    if profit_atr < SETTINGS.TRAILING_ACTIVATION_ATR:
        return {'active': False, 'trail_stop': current_trail_stop,
                'distance_atr': 0, 'profit_atr': profit_atr, 'tightened': False}
    tightened = profit_atr >= SETTINGS.TRAILING_TIGHTEN_AFTER_ATR
    if tightened:
        trail_distance = atr_value * SETTINGS.TRAILING_TIGHTEN_MULTIPLIER
    else:
        trail_distance = atr_value * SETTINGS.TRAILING_ATR_MULTIPLIER
    if is_buy:
        new_trail = current_price - trail_distance
        if current_trail_stop is not None and new_trail <= current_trail_stop:
            new_trail = current_trail_stop
    else:
        new_trail = current_price + trail_distance
        if current_trail_stop is not None and new_trail >= current_trail_stop:
            new_trail = current_trail_stop
    return {
        'active': True,
        'trail_stop': round(new_trail, 6),
        'distance_atr': trail_distance / atr_value,
        'profit_atr': round(profit_atr, 2),
        'tightened': tightened,
    }


def is_atr_trail_triggered(current_price: float, trail_stop: float, side: str) -> bool:
    if trail_stop is None:
        return False
    if side.upper() == "BUY":
        return current_price <= trail_stop
    return current_price >= trail_stop


# -------------------------------------------------------------------
# Correlation-aware risk (user_id-aware)
# -------------------------------------------------------------------
def get_correlation(pair_a: str, pair_b: str) -> float:
    if not SETTINGS.CORRELATION_CHECK_ENABLED:
        return 0.0
    try:
        from exchange import fetch_ohlcv
        import numpy as np
        df_a = fetch_ohlcv(pair_a, SETTINGS.CORRELATION_TIMEFRAME, SETTINGS.CORRELATION_LOOKBACK_BARS)
        df_b = fetch_ohlcv(pair_b, SETTINGS.CORRELATION_TIMEFRAME, SETTINGS.CORRELATION_LOOKBACK_BARS)
        if df_a is None or df_b is None or len(df_a) < 20 or len(df_b) < 20:
            return 0.0
        min_len = min(len(df_a), len(df_b))
        returns_a = df_a['close'].pct_change().dropna().tail(min_len - 1).values
        returns_b = df_b['close'].pct_change().dropna().tail(min_len - 1).values
        min_ret = min(len(returns_a), len(returns_b))
        if min_ret < 10:
            return 0.0
        corr = float(np.corrcoef(returns_a[-min_ret:], returns_b[-min_ret:])[0, 1])
        return corr if not np.isnan(corr) else 0.0
    except Exception as e:
        log.warning("Correlation check failed for %s/%s: %s", pair_a, pair_b, e)
        return 0.0


def check_correlation_risk(pair: str, side: str, user_id: int = None) -> tuple:
    if not SETTINGS.CORRELATION_CHECK_ENABLED:
        return True, 'Correlation check disabled', []
    if user_id is not None:
        rows = fetchall("SELECT DISTINCT pair FROM trades WHERE status='OPEN' AND user_id=?", (user_id,))
    else:
        rows = fetchall("SELECT DISTINCT pair FROM trades WHERE status='OPEN'")
    open_pairs = [r[0] for r in rows if r[0] != pair]
    if not open_pairs:
        return True, 'No open positions to correlate against', []
    correlated = []
    for op in open_pairs:
        corr = get_correlation(pair, op)
        if abs(corr) >= SETTINGS.CORRELATION_THRESHOLD:
            correlated.append((op, round(corr, 3)))
    if len(correlated) >= SETTINGS.MAX_CORRELATED_EXPOSURE:
        pairs_str = ', '.join(f'{p}({c:+.2f})' for p, c in correlated)
        return False, f'High correlation with {len(correlated)} open positions: {pairs_str}', correlated
    return True, 'OK', correlated


# -------------------------------------------------------------------
# Equity & drawdown tracking (ctx-aware)
# -------------------------------------------------------------------
def get_equity_status(ctx=None) -> dict:
    uid = ctx.user_id if ctx else None
    capital = ctx.capital_usd if ctx else SETTINGS.CAPITAL_USD

    if uid is not None:
        realized_row = fetchone("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='CLOSED' AND user_id=?", (uid,))
    else:
        realized_row = fetchone("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='CLOSED'")
    realized = float(realized_row[0]) if realized_row and realized_row[0] is not None else 0.0

    if uid is not None:
        open_rows = fetchall("SELECT pair, side, qty, entry FROM trades WHERE status='OPEN' AND user_id=?", (uid,))
    else:
        open_rows = fetchall("SELECT pair, side, qty, entry FROM trades WHERE status='OPEN'")
    unrealized = 0.0
    for pair, side, qty, entry in open_rows:
        try:
            from exchange import market_price
            px = market_price(pair)
            qty, entry = float(qty), float(entry)
            if side == 'BUY':
                unrealized += (px - entry) * qty
            else:
                unrealized += (entry - px) * qty
        except Exception:
            pass

    equity = capital + realized + unrealized

    # Per-user or global peak equity
    peak_key = f'peak_equity_{uid}' if uid else 'peak_equity'
    peak_row = fetchone("SELECT value FROM bot_state WHERE key=?", (peak_key,))
    peak_equity = float(peak_row[0]) if peak_row and peak_row[0] else capital

    now = int(time.time())
    if equity > peak_equity:
        peak_equity = equity
        upsert_bot_state(peak_key, str(round(peak_equity, 2)), now)

    drawdown_usd = peak_equity - equity
    drawdown_pct = drawdown_usd / peak_equity if peak_equity > 0 else 0.0

    dd_key = f'max_drawdown_pct_{uid}' if uid else 'max_drawdown_pct'
    max_dd_row = fetchone("SELECT value FROM bot_state WHERE key=?", (dd_key,))
    max_dd = float(max_dd_row[0]) if max_dd_row and max_dd_row[0] else 0.0
    if drawdown_pct > max_dd:
        max_dd = drawdown_pct
        upsert_bot_state(dd_key, str(round(max_dd, 4)), now)

    eq_key = f'current_equity_{uid}' if uid else 'current_equity'
    upsert_bot_state(eq_key, str(round(equity, 2)), now)

    return {
        'equity': round(equity, 2),
        'peak_equity': round(peak_equity, 2),
        'drawdown_usd': round(drawdown_usd, 2),
        'drawdown_pct': round(drawdown_pct, 4),
        'max_drawdown_pct': round(max_dd, 4),
        'realized_pnl': round(realized, 2),
        'unrealized_pnl': round(unrealized, 2),
    }


def drawdown_position_scale(ctx=None) -> float:
    if not SETTINGS.DRAWDOWN_TRACKING_ENABLED:
        return 1.0
    status = get_equity_status(ctx)
    dd_pct = status['drawdown_pct']
    if dd_pct >= SETTINGS.DRAWDOWN_HALT_THRESHOLD:
        return 0.0
    elif dd_pct >= SETTINGS.DRAWDOWN_SCALE_THRESHOLD:
        range_pct = SETTINGS.DRAWDOWN_HALT_THRESHOLD - SETTINGS.DRAWDOWN_SCALE_THRESHOLD
        depth = (dd_pct - SETTINGS.DRAWDOWN_SCALE_THRESHOLD) / range_pct if range_pct > 0 else 1.0
        return max(0.0, SETTINGS.DRAWDOWN_SCALE_FACTOR * (1.0 - depth))
    else:
        return 1.0
