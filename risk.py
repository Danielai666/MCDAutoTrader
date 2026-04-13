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

    # 8. Correlation risk check
    corr_ok, corr_reason, corr_pairs = check_correlation_risk(pair, side)
    if not corr_ok:
        _log_blocked(pair, side, corr_reason, signal_snapshot)
        return False, corr_reason

    # 9. Drawdown halt check
    dd_scale = drawdown_position_scale()
    if dd_scale <= 0.0:
        status = get_equity_status()
        reason = f"Drawdown halt ({status['drawdown_pct']:.1%} >= {SETTINGS.DRAWDOWN_HALT_THRESHOLD:.0%})"
        _log_blocked(pair, side, reason, signal_snapshot)
        return False, reason

    # 10. Dry run mode (allow but flag)
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
    # Apply drawdown scaling
    dd_scale = drawdown_position_scale()
    scaled_qty = base_qty * conf_factor * quality_bonus * dd_scale
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


# -------------------------------------------------------------------
# ATR-based trailing stop
# -------------------------------------------------------------------
def compute_atr_trailing_stop(entry_price: float, current_price: float,
                               atr_value: float, side: str,
                               current_trail_stop: float = None) -> dict:
    """
    Compute ATR-based trailing stop that tightens as profit grows.

    - Activates after price moves TRAILING_ACTIVATION_ATR * ATR in favor.
    - Initial trail distance: TRAILING_ATR_MULTIPLIER * ATR from high watermark.
    - After profit exceeds TRAILING_TIGHTEN_AFTER_ATR * ATR, trail tightens
      to TRAILING_TIGHTEN_MULTIPLIER * ATR.

    Returns: {'active': bool, 'trail_stop': float|None, 'distance_atr': float,
              'profit_atr': float, 'tightened': bool}
    """
    if not SETTINGS.TRAILING_ENABLED or atr_value <= 0:
        return {'active': False, 'trail_stop': None, 'distance_atr': 0,
                'profit_atr': 0, 'tightened': False}

    is_buy = side.upper() == "BUY"

    # Profit in ATR units
    if is_buy:
        profit_atr = (current_price - entry_price) / atr_value
    else:
        profit_atr = (entry_price - current_price) / atr_value

    # Not yet activated
    if profit_atr < SETTINGS.TRAILING_ACTIVATION_ATR:
        return {'active': False, 'trail_stop': current_trail_stop,
                'distance_atr': 0, 'profit_atr': profit_atr, 'tightened': False}

    # Choose trail distance: tighten once profit is large enough
    tightened = profit_atr >= SETTINGS.TRAILING_TIGHTEN_AFTER_ATR
    if tightened:
        trail_distance = atr_value * SETTINGS.TRAILING_TIGHTEN_MULTIPLIER
    else:
        trail_distance = atr_value * SETTINGS.TRAILING_ATR_MULTIPLIER

    # Compute new trail stop from current price (high watermark)
    if is_buy:
        new_trail = current_price - trail_distance
        # Trail can only move UP for buys
        if current_trail_stop is not None and new_trail <= current_trail_stop:
            new_trail = current_trail_stop
    else:
        new_trail = current_price + trail_distance
        # Trail can only move DOWN for sells
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
    """Check if price has breached the ATR trailing stop."""
    if trail_stop is None:
        return False
    if side.upper() == "BUY":
        return current_price <= trail_stop
    return current_price >= trail_stop


# -------------------------------------------------------------------
# Correlation-aware risk
# -------------------------------------------------------------------
def get_correlation(pair_a: str, pair_b: str) -> float:
    """Compute rolling correlation between two pairs using close prices."""
    if not SETTINGS.CORRELATION_CHECK_ENABLED:
        return 0.0
    try:
        from exchange import fetch_ohlcv
        import numpy as np
        df_a = fetch_ohlcv(pair_a, SETTINGS.CORRELATION_TIMEFRAME, SETTINGS.CORRELATION_LOOKBACK_BARS)
        df_b = fetch_ohlcv(pair_b, SETTINGS.CORRELATION_TIMEFRAME, SETTINGS.CORRELATION_LOOKBACK_BARS)
        if df_a is None or df_b is None or len(df_a) < 20 or len(df_b) < 20:
            return 0.0
        # Align by length
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


def check_correlation_risk(pair: str, side: str) -> tuple:
    """
    Check if entering this pair would create excessive correlated exposure.
    Returns (allowed: bool, reason: str, correlated_pairs: list).
    """
    if not SETTINGS.CORRELATION_CHECK_ENABLED:
        return True, 'Correlation check disabled', []

    # Get all distinct pairs with open trades
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
# Equity & drawdown tracking
# -------------------------------------------------------------------
def get_equity_status() -> dict:
    """
    Calculate current equity, peak equity, drawdown.
    Returns: {equity, peak_equity, drawdown_pct, drawdown_usd, max_drawdown_pct}
    """
    # Current equity = starting capital + all realized PnL + unrealized PnL
    realized_row = fetchone("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='CLOSED'")
    realized = float(realized_row[0]) if realized_row and realized_row[0] is not None else 0.0

    # Unrealized PnL from open trades
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

    equity = SETTINGS.CAPITAL_USD + realized + unrealized

    # Get peak equity from bot_state
    peak_row = fetchone("SELECT value FROM bot_state WHERE key='peak_equity'")
    peak_equity = float(peak_row[0]) if peak_row and peak_row[0] else SETTINGS.CAPITAL_USD

    # Update peak if new high
    if equity > peak_equity:
        peak_equity = equity
        execute(
            "INSERT INTO bot_state(key, value, updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            ('peak_equity', str(round(peak_equity, 2)), int(time.time()))
        )

    # Current drawdown
    drawdown_usd = peak_equity - equity
    drawdown_pct = drawdown_usd / peak_equity if peak_equity > 0 else 0.0

    # Max drawdown (historical)
    max_dd_row = fetchone("SELECT value FROM bot_state WHERE key='max_drawdown_pct'")
    max_dd = float(max_dd_row[0]) if max_dd_row and max_dd_row[0] else 0.0
    if drawdown_pct > max_dd:
        max_dd = drawdown_pct
        execute(
            "INSERT INTO bot_state(key, value, updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            ('max_drawdown_pct', str(round(max_dd, 4)), int(time.time()))
        )

    # Save equity snapshot
    execute(
        "INSERT INTO bot_state(key, value, updated_ts) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
        ('current_equity', str(round(equity, 2)), int(time.time()))
    )

    return {
        'equity': round(equity, 2),
        'peak_equity': round(peak_equity, 2),
        'drawdown_usd': round(drawdown_usd, 2),
        'drawdown_pct': round(drawdown_pct, 4),
        'max_drawdown_pct': round(max_dd, 4),
        'realized_pnl': round(realized, 2),
        'unrealized_pnl': round(unrealized, 2),
    }


def drawdown_position_scale() -> float:
    """
    Returns a scaling factor (0.0 - 1.0) for position sizing based on drawdown.
    - No drawdown: 1.0 (full size)
    - Drawdown > DRAWDOWN_SCALE_THRESHOLD: reduced by DRAWDOWN_SCALE_FACTOR
    - Drawdown > DRAWDOWN_HALT_THRESHOLD: 0.0 (halt trading)
    """
    if not SETTINGS.DRAWDOWN_TRACKING_ENABLED:
        return 1.0

    status = get_equity_status()
    dd_pct = status['drawdown_pct']

    if dd_pct >= SETTINGS.DRAWDOWN_HALT_THRESHOLD:
        return 0.0
    elif dd_pct >= SETTINGS.DRAWDOWN_SCALE_THRESHOLD:
        # Linear scale between threshold and halt
        range_pct = SETTINGS.DRAWDOWN_HALT_THRESHOLD - SETTINGS.DRAWDOWN_SCALE_THRESHOLD
        depth = (dd_pct - SETTINGS.DRAWDOWN_SCALE_THRESHOLD) / range_pct if range_pct > 0 else 1.0
        return max(0.0, SETTINGS.DRAWDOWN_SCALE_FACTOR * (1.0 - depth) + 0.0 * depth)
    else:
        return 1.0
