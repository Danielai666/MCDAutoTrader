# candles.py
# Candle pattern detection: hammer, shooting star, engulfing, rejection wick, breakout
import pandas as pd
from config import SETTINGS


class CandlePattern:
    def __init__(self, name: str, direction: str, strength: float, bar_index: int):
        self.name = name              # e.g. 'hammer', 'bearish_engulfing'
        self.direction = direction    # 'bullish' or 'bearish'
        self.strength = strength      # 0.0 - 1.0
        self.bar_index = bar_index

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'direction': self.direction,
            'strength': round(self.strength, 3),
            'bar_index': self.bar_index,
        }


def _body(o, c):
    return abs(c - o)

def _range(h, l):
    return h - l if h > l else 0.0001

def _upper_wick(o, h, c):
    return h - max(o, c)

def _lower_wick(o, l, c):
    return min(o, c) - l

def _is_green(o, c):
    return c > o

def _is_red(o, c):
    return c < o


def _check_hammer(o, h, l, c) -> float:
    """Hammer: small body at top, long lower wick. Bullish reversal."""
    body = _body(o, c)
    rng = _range(h, l)
    lower = _lower_wick(o, l, c)
    upper = _upper_wick(o, h, c)
    if rng == 0 or body == 0:
        return 0.0
    if lower >= SETTINGS.CANDLE_WICK_RATIO * body and upper < body:
        body_pct = body / rng
        if body_pct <= SETTINGS.CANDLE_BODY_RATIO:
            return min(1.0, lower / rng)
    return 0.0


def _check_shooting_star(o, h, l, c) -> float:
    """Shooting star: small body at bottom, long upper wick. Bearish reversal."""
    body = _body(o, c)
    rng = _range(h, l)
    upper = _upper_wick(o, h, c)
    lower = _lower_wick(o, l, c)
    if rng == 0 or body == 0:
        return 0.0
    if upper >= SETTINGS.CANDLE_WICK_RATIO * body and lower < body:
        body_pct = body / rng
        if body_pct <= SETTINGS.CANDLE_BODY_RATIO:
            return min(1.0, upper / rng)
    return 0.0


def _check_bullish_engulfing(po, ph, pl, pc, o, h, l, c) -> float:
    """Current green candle body fully contains previous red candle body."""
    if not (_is_red(po, pc) and _is_green(o, c)):
        return 0.0
    if c > po and o < pc:
        prev_body = _body(po, pc)
        curr_body = _body(o, c)
        if prev_body > 0:
            return min(1.0, curr_body / prev_body * 0.5)
    return 0.0


def _check_bearish_engulfing(po, ph, pl, pc, o, h, l, c) -> float:
    """Current red candle body fully contains previous green candle body."""
    if not (_is_green(po, pc) and _is_red(o, c)):
        return 0.0
    if o > pc and c < po:
        prev_body = _body(po, pc)
        curr_body = _body(o, c)
        if prev_body > 0:
            return min(1.0, curr_body / prev_body * 0.5)
    return 0.0


def _check_rejection_wick(o, h, l, c, direction: str) -> float:
    """Long wick in the opposite direction. direction = 'bullish' or 'bearish'."""
    body = _body(o, c)
    rng = _range(h, l)
    if rng == 0 or body == 0:
        return 0.0
    lower = _lower_wick(o, l, c)
    upper = _upper_wick(o, h, c)
    if direction == 'bullish' and lower >= 2.0 * body:
        return min(1.0, lower / rng)
    if direction == 'bearish' and upper >= 2.0 * body:
        return min(1.0, upper / rng)
    return 0.0


def _check_breakout(df: pd.DataFrame, idx: int, lookback: int = 20) -> tuple:
    """
    Close above highest high or below lowest low of prior bars.
    Returns (direction, strength).
    """
    if idx < lookback + 1:
        return None, 0.0
    window = df.iloc[idx - lookback:idx]
    cur_close = float(df.iloc[idx]['close'])
    cur_vol = float(df.iloc[idx]['volume'])
    hh = float(window['high'].max())
    ll = float(window['low'].min())
    avg_vol = float(window['volume'].mean())

    vol_factor = min(2.0, cur_vol / avg_vol) if avg_vol > 0 else 1.0
    if cur_close > hh:
        return 'bullish', min(1.0, 0.5 * vol_factor)
    if cur_close < ll:
        return 'bearish', min(1.0, 0.5 * vol_factor)
    return None, 0.0


def detect_patterns(df: pd.DataFrame, lookback: int = 3) -> list:
    """Scan last `lookback` bars for patterns. Returns list of CandlePattern."""
    patterns = []
    n = len(df)
    if n < 2:
        return patterns

    start = max(1, n - lookback)
    for i in range(start, n):
        o = float(df.iloc[i]['open'])
        h = float(df.iloc[i]['high'])
        l = float(df.iloc[i]['low'])
        c = float(df.iloc[i]['close'])
        po = float(df.iloc[i - 1]['open'])
        ph = float(df.iloc[i - 1]['high'])
        pl = float(df.iloc[i - 1]['low'])
        pc = float(df.iloc[i - 1]['close'])

        # Hammer
        s = _check_hammer(o, h, l, c)
        if s > 0:
            patterns.append(CandlePattern('hammer', 'bullish', s, i))

        # Shooting star
        s = _check_shooting_star(o, h, l, c)
        if s > 0:
            patterns.append(CandlePattern('shooting_star', 'bearish', s, i))

        # Bullish engulfing
        s = _check_bullish_engulfing(po, ph, pl, pc, o, h, l, c)
        if s > 0:
            patterns.append(CandlePattern('bullish_engulfing', 'bullish', s, i))

        # Bearish engulfing
        s = _check_bearish_engulfing(po, ph, pl, pc, o, h, l, c)
        if s > 0:
            patterns.append(CandlePattern('bearish_engulfing', 'bearish', s, i))

        # Rejection wicks
        s = _check_rejection_wick(o, h, l, c, 'bullish')
        if s > 0:
            patterns.append(CandlePattern('rejection_wick_bull', 'bullish', s, i))
        s = _check_rejection_wick(o, h, l, c, 'bearish')
        if s > 0:
            patterns.append(CandlePattern('rejection_wick_bear', 'bearish', s, i))

        # Breakout
        bd, bs = _check_breakout(df, i)
        if bd and bs > 0:
            patterns.append(CandlePattern('breakout', bd, bs, i))

    # Sort by strength descending
    patterns.sort(key=lambda p: p.strength, reverse=True)
    return patterns


def summarize_patterns(patterns: list) -> dict:
    """Returns summary with counts and net score."""
    bullish = [p for p in patterns if p.direction == 'bullish']
    bearish = [p for p in patterns if p.direction == 'bearish']
    bull_score = sum(p.strength for p in bullish)
    bear_score = sum(p.strength for p in bearish)
    strongest = patterns[0].to_dict() if patterns else None
    return {
        'bullish_count': len(bullish),
        'bearish_count': len(bearish),
        'bull_score': round(bull_score, 3),
        'bear_score': round(bear_score, 3),
        'net_score': round(bull_score - bear_score, 3),
        'strongest': strongest,
        'patterns': [p.to_dict() for p in patterns[:5]],
    }
