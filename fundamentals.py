# fundamentals.py
# Fundamental analysis gate: news/event risk scoring.
# Acts as a FILTER on technical signals, not a signal generator.
# Blocks or reduces position size when event risk is high.

import time
import logging
import json
from config import SETTINGS

log = logging.getLogger(__name__)

# Global cache for event risk (shared across users, refreshed every 15 min)
_event_risk_cache = {
    'score': 50,       # 0..100 (0=safe, 100=extreme risk)
    'reasons': ['No news feed configured'],
    'level': 'NEUTRAL',
    'ts': 0,
    'symbols': {},     # per-symbol overrides
}
_CACHE_TTL = 900  # 15 minutes

# Thresholds
EVENT_RISK_HIGH = 75    # Block new trades
EVENT_RISK_MEDIUM = 50  # Reduce position size


def get_news_event_risk(symbols: list = None) -> dict:
    """
    Get current event risk score.
    Returns: {score: 0..100, level: LOW/NEUTRAL/MEDIUM/HIGH/EXTREME,
              reasons: [str], no_trade: bool, size_factor: float}

    If no news source is configured, returns neutral (50) with graceful degradation.
    """
    global _event_risk_cache

    now = time.time()
    if now - _event_risk_cache['ts'] < _CACHE_TTL:
        return _format_risk_result(_event_risk_cache)

    # Try to fetch news/events from configured sources
    score = 50
    reasons = []

    # Source 1: Check if any high-impact events are configured in bot_state
    try:
        from storage import fetchone
        event_row = fetchone("SELECT value FROM bot_state WHERE key='event_risk_override'")
        if event_row and event_row[0]:
            try:
                override = json.loads(event_row[0])
                score = int(override.get('score', 50))
                reasons = override.get('reasons', [])
                log.info("Event risk from manual override: %d", score)
            except Exception:
                pass
    except Exception:
        pass

    # Source 2: Check for known high-risk time windows
    # (major economic events, FOMC, CPI, NFP release windows)
    try:
        time_risk, time_reasons = _check_time_based_risk()
        if time_risk > 0:
            score = max(score, time_risk)
            reasons.extend(time_reasons)
    except Exception:
        pass

    # Source 3: Volatility spike detection (sudden ATR expansion = possible news event)
    if symbols:
        try:
            vol_risk, vol_reasons = _check_volatility_spike(symbols)
            if vol_risk > 0:
                score = max(score, vol_risk)
                reasons.extend(vol_reasons)
        except Exception:
            pass

    if not reasons:
        reasons = ['No significant events detected']

    # Determine level
    if score >= 90:
        level = 'EXTREME'
    elif score >= EVENT_RISK_HIGH:
        level = 'HIGH'
    elif score >= EVENT_RISK_MEDIUM:
        level = 'MEDIUM'
    elif score >= 25:
        level = 'LOW'
    else:
        level = 'NEUTRAL'

    _event_risk_cache = {
        'score': score,
        'reasons': reasons[:3],
        'level': level,
        'ts': now,
        'symbols': {},
    }

    return _format_risk_result(_event_risk_cache)


def _format_risk_result(cache: dict) -> dict:
    """Format the cached risk data into the standard result dict."""
    score = cache['score']
    no_trade = score >= EVENT_RISK_HIGH

    # Position size factor
    if score >= EVENT_RISK_HIGH:
        size_factor = 0.0  # Block
    elif score >= EVENT_RISK_MEDIUM:
        # Linear reduction from 1.0 at 50 to 0.0 at 75
        size_factor = max(0.0, 1.0 - (score - EVENT_RISK_MEDIUM) / (EVENT_RISK_HIGH - EVENT_RISK_MEDIUM))
    else:
        size_factor = 1.0

    return {
        'score': score,
        'level': cache['level'],
        'reasons': cache['reasons'],
        'no_trade': no_trade,
        'size_factor': round(size_factor, 2),
    }


def _check_time_based_risk() -> tuple:
    """
    Check for known high-risk time windows (UTC).
    Returns (risk_score, reasons).
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.weekday()  # 0=Monday

    reasons = []
    risk = 0

    # Weekend: crypto markets are thinner
    if weekday >= 5:
        risk = max(risk, 30)
        reasons.append('Weekend — reduced liquidity')

    # Daily rollover window (00:00-01:00 UTC)
    if hour == 0:
        risk = max(risk, 40)
        reasons.append('Daily rollover window')

    # US market open volatility (13:30-15:00 UTC)
    if 13 <= hour <= 14 and weekday < 5:
        risk = max(risk, 35)
        reasons.append('US market open — potential volatility')

    # First Friday of month (NFP release, typically 13:30 UTC)
    if weekday == 4 and now.day <= 7 and 13 <= hour <= 14:
        risk = max(risk, 70)
        reasons.append('NFP release window (first Friday)')

    return risk, reasons


def _check_volatility_spike(symbols: list) -> tuple:
    """
    Detect sudden ATR expansion as proxy for news events.
    If current ATR is 2x+ the 20-period average, flag as elevated risk.
    """
    from exchange import fetch_ohlcv
    from indicators import atr

    risk = 0
    reasons = []

    for symbol in symbols[:3]:  # Check top 3 symbols only (CPU budget)
        try:
            df = fetch_ohlcv(symbol, '1h', 30)
            if df is None or len(df) < 25:
                continue
            atr_series = atr(df['high'], df['low'], df['close'], 14)
            current_atr = float(atr_series.iloc[-1])
            avg_atr = float(atr_series.iloc[-20:].mean())

            if avg_atr > 0:
                atr_ratio = current_atr / avg_atr
                if atr_ratio >= 2.5:
                    risk = max(risk, 80)
                    reasons.append(f'{symbol}: ATR spike {atr_ratio:.1f}x (possible news event)')
                elif atr_ratio >= 1.8:
                    risk = max(risk, 55)
                    reasons.append(f'{symbol}: elevated volatility {atr_ratio:.1f}x')
        except Exception:
            continue

    return risk, reasons


# -------------------------------------------------------------------
# Integration helpers
# -------------------------------------------------------------------
def apply_event_risk_to_position_size(qty: float, event_risk: dict = None) -> float:
    """Apply event risk factor to position size. Returns adjusted qty."""
    if event_risk is None:
        event_risk = get_news_event_risk()
    return round(qty * event_risk['size_factor'], 6)


def should_block_for_event_risk(event_risk: dict = None) -> tuple:
    """Returns (blocked: bool, reason: str)."""
    if event_risk is None:
        event_risk = get_news_event_risk()
    if event_risk['no_trade']:
        return True, f"High event risk ({event_risk['level']}): {', '.join(event_risk['reasons'][:2])}"
    return False, ''


# -------------------------------------------------------------------
# Admin: manual event risk override via /seteventrisk command
# -------------------------------------------------------------------
def set_event_risk_override(score: int, reasons: list):
    """Manually override event risk (admin tool). Persists to bot_state."""
    from storage import upsert_bot_state
    data = json.dumps({'score': score, 'reasons': reasons})
    upsert_bot_state('event_risk_override', data, int(time.time()))
    # Invalidate cache
    global _event_risk_cache
    _event_risk_cache['ts'] = 0


def clear_event_risk_override():
    """Clear manual override."""
    from storage import execute
    execute("DELETE FROM bot_state WHERE key='event_risk_override'")
    global _event_risk_cache
    _event_risk_cache['ts'] = 0
