# market_regime.py
# Detects market regime: trending_up, trending_down, ranging, volatile
import pandas as pd
from config import SETTINGS
from indicators import ema, atr, adx


class RegimeResult:
    def __init__(self, regime: str, confidence: float, details: dict):
        self.regime = regime
        self.confidence = confidence
        self.details = details

    def to_dict(self) -> dict:
        return {
            'regime': self.regime,
            'confidence': round(self.confidence, 3),
            'details': self.details,
        }


def detect_regime(df: pd.DataFrame) -> RegimeResult:
    """
    Analyze OHLCV to determine market regime.
    Uses EMA crossover, ADX for trend strength, ATR percentile for volatility.

    Returns one of: 'trending_up', 'trending_down', 'ranging', 'volatile'
    """
    close = df['close']
    high = df['high']
    low = df['low']

    # EMA direction
    ema_fast = ema(close, SETTINGS.REGIME_EMA_FAST)
    ema_slow = ema(close, SETTINGS.REGIME_EMA_SLOW)
    ema_bullish = float(ema_fast.iloc[-1]) > float(ema_slow.iloc[-1])
    ema_gap_pct = abs(float(ema_fast.iloc[-1]) - float(ema_slow.iloc[-1])) / float(ema_slow.iloc[-1]) * 100

    # ADX trend strength
    adx_line, plus_di, minus_di = adx(high, low, close, SETTINGS.ADX_PERIOD)
    cur_adx = float(adx_line.iloc[-1])
    is_trending = cur_adx >= SETTINGS.REGIME_ADX_THRESHOLD

    # ATR volatility percentile
    atr_values = atr(high, low, close, SETTINGS.ATR_PERIOD)
    lookback = SETTINGS.REGIME_VOLATILITY_LOOKBACK
    if len(atr_values) >= lookback:
        recent_atr = float(atr_values.iloc[-1])
        atr_window = atr_values.iloc[-lookback:]
        atr_pct = (atr_window < recent_atr).sum() / len(atr_window)
    else:
        atr_pct = 0.5

    high_volatility = atr_pct > 0.75

    # Regime classification
    if is_trending and ema_bullish:
        regime = 'trending_up'
        confidence = min(1.0, 0.5 + cur_adx / 100 + ema_gap_pct / 10)
    elif is_trending and not ema_bullish:
        regime = 'trending_down'
        confidence = min(1.0, 0.5 + cur_adx / 100 + ema_gap_pct / 10)
    elif not is_trending and high_volatility:
        regime = 'volatile'
        confidence = min(1.0, 0.4 + atr_pct / 2)
    else:
        regime = 'ranging'
        confidence = min(1.0, 0.5 + (1 - cur_adx / SETTINGS.REGIME_ADX_THRESHOLD) * 0.3)

    details = {
        'ema_fast': round(float(ema_fast.iloc[-1]), 4),
        'ema_slow': round(float(ema_slow.iloc[-1]), 4),
        'ema_bullish': ema_bullish,
        'ema_gap_pct': round(ema_gap_pct, 3),
        'adx': round(cur_adx, 2),
        'atr_percentile': round(atr_pct, 3),
        'is_trending': is_trending,
        'high_volatility': high_volatility,
    }

    return RegimeResult(regime, round(confidence, 3), details)
