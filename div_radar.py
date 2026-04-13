# div_radar.py
# Divergence Radar Engine: detects zones where divergence is likely forming
# before full confirmation. Classifies maturity stages and ranks opportunities.

import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass, field
from indicators import macd, rsi, atr, vol_ma, ema

log = logging.getLogger(__name__)

# Maturity stages
STAGE_POTENTIAL = 'potential_zone'
STAGE_DEVELOPING = 'developing'
STAGE_NEAR_CONFIRMED = 'near_confirmed'
STAGE_CONFIRMED = 'confirmed'


@dataclass
class DivZone:
    symbol: str = ''
    timeframe: str = ''
    direction: str = ''          # 'bullish' or 'bearish'
    stage: str = STAGE_POTENTIAL
    probability: float = 0.0     # 0.0-1.0
    strength: float = 0.0        # 0.0-1.0
    confidence: float = 0.0      # 0.0-1.0
    trigger_price: float = 0.0   # price level that would confirm
    invalidation: float = 0.0    # price level that kills the setup
    reasons: list = field(default_factory=list)
    oscillator: str = ''         # 'rsi' or 'macd'

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol, 'timeframe': self.timeframe,
            'direction': self.direction, 'stage': self.stage,
            'probability': round(self.probability, 3),
            'strength': round(self.strength, 3),
            'confidence': round(self.confidence, 3),
            'trigger': round(self.trigger_price, 4),
            'invalidation': round(self.invalidation, 4),
            'reasons': self.reasons, 'oscillator': self.oscillator,
        }

    @property
    def score(self) -> float:
        """Composite score for ranking: probability * strength * confidence."""
        return self.probability * self.strength * self.confidence


# -------------------------------------------------------------------
# Pivot detection (reused from divergence.py but with more lookback)
# -------------------------------------------------------------------
def _find_pivots(s, lookback=5, count=5):
    """Find last `count` pivot highs and lows within the series."""
    vals = s.values
    idx = s.index
    highs, lows = [], []
    for i in range(lookback, len(vals) - 1):  # note: -1 not -lookback (allow recent bars)
        window_left = vals[max(0, i - lookback):i]
        window_right = vals[i + 1:min(len(vals), i + lookback + 1)]
        if len(window_left) > 0 and vals[i] >= max(window_left):
            if len(window_right) == 0 or vals[i] >= max(window_right):
                highs.append((idx[i], float(vals[i])))
        if len(window_left) > 0 and vals[i] <= min(window_left):
            if len(window_right) == 0 or vals[i] <= min(window_right):
                lows.append((idx[i], float(vals[i])))
    return highs[-count:], lows[-count:]


# -------------------------------------------------------------------
# Bearish divergence radar
# -------------------------------------------------------------------
def _scan_bearish(df, osc_series, osc_name, symbol, tf):
    """Detect zones where bearish divergence is forming or confirmed."""
    close = df['close']
    high = df['high']
    volume = df['volume']
    n = len(df)
    if n < 50:
        return []

    zones = []
    price_highs, _ = _find_pivots(close, lookback=5, count=4)
    osc_highs, _ = _find_pivots(osc_series, lookback=5, count=4)

    if len(price_highs) < 2:
        return []

    # Current bar context
    cur_price = float(close.iloc[-1])
    cur_high = float(high.iloc[-1])
    cur_osc = float(osc_series.iloc[-1])
    prev_price_high_idx, prev_price_high_val = price_highs[-1]
    prev2_price_high_val = price_highs[-2][1] if len(price_highs) >= 2 else prev_price_high_val

    # Volume analysis
    vma = vol_ma(volume, 20)
    cur_vol = float(volume.iloc[-1])
    avg_vol = float(vma.iloc[-1]) if not pd.isna(vma.iloc[-1]) else cur_vol

    # ATR for trigger/invalidation levels
    atr_val = float(atr(high, df['low'], close, 14).iloc[-1])

    # MACD histogram for momentum decay
    _, _, mhist = macd(close)
    hist_cur = float(mhist.iloc[-1])
    hist_prev = float(mhist.iloc[-2]) if n > 1 else hist_cur
    hist_3 = float(mhist.iloc[-3]) if n > 2 else hist_cur

    reasons = []
    prob = 0.0

    # --- Signal 1: Price near or above previous high but oscillator weaker ---
    if cur_price >= prev_price_high_val * 0.995:  # within 0.5% of prev high
        # Find osc value at prev price high
        prev_osc_at_high = float(osc_series.iloc[-1])  # approximate
        for oh_idx, oh_val in osc_highs:
            if oh_idx == prev_price_high_idx:
                prev_osc_at_high = oh_val
                break

        if cur_osc < prev_osc_at_high * 0.95:  # oscillator 5%+ weaker
            prob += 0.30
            reasons.append(f'Price near high but {osc_name} weaker')

    # --- Signal 2: MACD histogram fading (momentum decay) ---
    if hist_cur < hist_prev < hist_3 and hist_cur > 0:
        prob += 0.20
        reasons.append('MACD histogram fading (3-bar decay)')
    elif hist_cur < hist_prev and hist_cur > 0:
        prob += 0.10
        reasons.append('MACD histogram declining')

    # --- Signal 3: Weak volume on push higher ---
    if cur_price > prev_price_high_val * 0.99 and cur_vol < avg_vol * 0.8:
        prob += 0.15
        reasons.append('Weak volume on push to high')

    # --- Signal 4: RSI-specific: overbought but weakening ---
    if osc_name == 'rsi':
        if cur_osc > 65 and cur_osc < float(osc_series.iloc[-2]):
            prob += 0.15
            reasons.append(f'RSI {cur_osc:.0f} overbought but declining')

    # --- Signal 5: Price made higher high, osc made lower high (classic confirmed) ---
    if len(price_highs) >= 2 and len(osc_highs) >= 2:
        p1, p2 = price_highs[-2][1], price_highs[-1][1]
        o1_idx = osc_highs[-2][0]
        o2_idx = osc_highs[-1][0]
        o1 = float(osc_series.loc[o1_idx]) if o1_idx in osc_series.index else 0
        o2 = float(osc_series.loc[o2_idx]) if o2_idx in osc_series.index else 0
        if p2 > p1 and o2 < o1:
            prob += 0.30
            reasons.append(f'Confirmed: HH price + LH {osc_name}')

    if prob < 0.10:
        return []

    # Classify maturity
    if prob >= 0.70:
        stage = STAGE_CONFIRMED
    elif prob >= 0.50:
        stage = STAGE_NEAR_CONFIRMED
    elif prob >= 0.30:
        stage = STAGE_DEVELOPING
    else:
        stage = STAGE_POTENTIAL

    # Strength based on how divergent price vs oscillator are
    price_range = prev_price_high_val - prev2_price_high_val if prev2_price_high_val != prev_price_high_val else 1
    strength = min(1.0, prob * 1.2)

    zone = DivZone(
        symbol=symbol, timeframe=tf, direction='bearish',
        stage=stage, probability=round(min(1.0, prob), 3),
        strength=round(strength, 3),
        confidence=round(min(1.0, prob * 0.9), 3),
        trigger_price=round(prev_price_high_val - atr_val * 0.5, 4),
        invalidation=round(prev_price_high_val + atr_val * 1.5, 4),
        reasons=reasons, oscillator=osc_name,
    )
    zones.append(zone)
    return zones


# -------------------------------------------------------------------
# Bullish divergence radar
# -------------------------------------------------------------------
def _scan_bullish(df, osc_series, osc_name, symbol, tf):
    """Detect zones where bullish divergence is forming or confirmed."""
    close = df['close']
    low = df['low']
    volume = df['volume']
    high = df['high']
    n = len(df)
    if n < 50:
        return []

    zones = []
    _, price_lows = _find_pivots(close, lookback=5, count=4)
    _, osc_lows = _find_pivots(osc_series, lookback=5, count=4)

    if len(price_lows) < 2:
        return []

    cur_price = float(close.iloc[-1])
    cur_osc = float(osc_series.iloc[-1])
    prev_price_low_idx, prev_price_low_val = price_lows[-1]
    prev2_price_low_val = price_lows[-2][1] if len(price_lows) >= 2 else prev_price_low_val

    vma_s = vol_ma(volume, 20)
    cur_vol = float(volume.iloc[-1])
    avg_vol = float(vma_s.iloc[-1]) if not pd.isna(vma_s.iloc[-1]) else cur_vol

    atr_val = float(atr(high, low, close, 14).iloc[-1])

    _, _, mhist = macd(close)
    hist_cur = float(mhist.iloc[-1])
    hist_prev = float(mhist.iloc[-2]) if n > 1 else hist_cur
    hist_3 = float(mhist.iloc[-3]) if n > 2 else hist_cur

    reasons = []
    prob = 0.0

    # --- Signal 1: Price near or below previous low but oscillator stronger ---
    if cur_price <= prev_price_low_val * 1.005:
        prev_osc_at_low = cur_osc
        for ol_idx, ol_val in osc_lows:
            if ol_idx == prev_price_low_idx:
                prev_osc_at_low = ol_val
                break

        if cur_osc > prev_osc_at_low * 1.05:
            prob += 0.30
            reasons.append(f'Price near low but {osc_name} stronger')

    # --- Signal 2: MACD histogram recovering (sell pressure fading) ---
    if hist_cur > hist_prev > hist_3 and hist_cur < 0:
        prob += 0.20
        reasons.append('MACD histogram recovering (3-bar)')
    elif hist_cur > hist_prev and hist_cur < 0:
        prob += 0.10
        reasons.append('MACD histogram improving')

    # --- Signal 3: Declining volume on push lower ---
    if cur_price < prev_price_low_val * 1.01 and cur_vol < avg_vol * 0.8:
        prob += 0.15
        reasons.append('Declining volume on push to low')

    # --- Signal 4: RSI-specific: oversold but improving ---
    if osc_name == 'rsi':
        if cur_osc < 35 and cur_osc > float(osc_series.iloc[-2]):
            prob += 0.15
            reasons.append(f'RSI {cur_osc:.0f} oversold but improving')

    # --- Signal 5: Confirmed: LL price + HL osc ---
    if len(price_lows) >= 2 and len(osc_lows) >= 2:
        p1, p2 = price_lows[-2][1], price_lows[-1][1]
        o1_idx = osc_lows[-2][0]
        o2_idx = osc_lows[-1][0]
        o1 = float(osc_series.loc[o1_idx]) if o1_idx in osc_series.index else 0
        o2 = float(osc_series.loc[o2_idx]) if o2_idx in osc_series.index else 0
        if p2 < p1 and o2 > o1:
            prob += 0.30
            reasons.append(f'Confirmed: LL price + HL {osc_name}')

    if prob < 0.10:
        return []

    if prob >= 0.70:
        stage = STAGE_CONFIRMED
    elif prob >= 0.50:
        stage = STAGE_NEAR_CONFIRMED
    elif prob >= 0.30:
        stage = STAGE_DEVELOPING
    else:
        stage = STAGE_POTENTIAL

    strength = min(1.0, prob * 1.2)

    zone = DivZone(
        symbol=symbol, timeframe=tf, direction='bullish',
        stage=stage, probability=round(min(1.0, prob), 3),
        strength=round(strength, 3),
        confidence=round(min(1.0, prob * 0.9), 3),
        trigger_price=round(prev_price_low_val + atr_val * 0.5, 4),
        invalidation=round(prev_price_low_val - atr_val * 1.5, 4),
        reasons=reasons, oscillator=osc_name,
    )
    zones.append(zone)
    return zones


# -------------------------------------------------------------------
# Main radar scan
# -------------------------------------------------------------------
def scan_divergence_zones(df: pd.DataFrame, symbol: str = '', timeframe: str = '') -> list:
    """
    Scan a single OHLCV dataframe for all divergence zones.
    Returns list of DivZone sorted by composite score descending.
    """
    close = df['close']
    rsi_series = rsi(close, 14)
    macd_line, _, _ = macd(close)

    zones = []

    # Scan both oscillators for both directions
    zones.extend(_scan_bearish(df, rsi_series, 'rsi', symbol, timeframe))
    zones.extend(_scan_bearish(df, macd_line, 'macd', symbol, timeframe))
    zones.extend(_scan_bullish(df, rsi_series, 'rsi', symbol, timeframe))
    zones.extend(_scan_bullish(df, macd_line, 'macd', symbol, timeframe))

    # Deduplicate: if same direction found on both oscillators, merge and boost
    merged = _merge_zones(zones)

    # Sort by composite score
    merged.sort(key=lambda z: z.score, reverse=True)
    return merged


def _merge_zones(zones: list) -> list:
    """Merge overlapping zones on same symbol/tf/direction. Boost probability."""
    if len(zones) <= 1:
        return zones

    grouped = {}
    for z in zones:
        key = (z.symbol, z.timeframe, z.direction)
        if key not in grouped:
            grouped[key] = z
        else:
            existing = grouped[key]
            # Merge: take higher probability, combine reasons, boost confidence
            existing.probability = min(1.0, existing.probability + z.probability * 0.3)
            existing.strength = max(existing.strength, z.strength)
            existing.confidence = min(1.0, (existing.confidence + z.confidence) / 2 + 0.1)
            existing.reasons = list(set(existing.reasons + z.reasons))
            existing.oscillator = f"{existing.oscillator}+{z.oscillator}"
            # Upgrade stage if merged zone is stronger
            if z.stage == STAGE_CONFIRMED:
                existing.stage = STAGE_CONFIRMED
            elif z.stage == STAGE_NEAR_CONFIRMED and existing.stage in (STAGE_POTENTIAL, STAGE_DEVELOPING):
                existing.stage = STAGE_NEAR_CONFIRMED

    return list(grouped.values())


# -------------------------------------------------------------------
# Multi-pair, multi-timeframe radar
# -------------------------------------------------------------------
def full_radar_scan(pairs: list, timeframes: list, fetch_fn) -> list:
    """
    Scan multiple pairs across multiple timeframes.
    fetch_fn(pair, tf, limit) should return OHLCV DataFrame.
    Returns all DivZones sorted by score descending.
    """
    all_zones = []
    for pair in pairs:
        for tf in timeframes:
            try:
                df = fetch_fn(pair, tf, 300)
                zones = scan_divergence_zones(df, symbol=pair, timeframe=tf)
                all_zones.extend(zones)
            except Exception as e:
                log.warning("Radar scan failed for %s/%s: %s", pair, tf, e)
    all_zones.sort(key=lambda z: z.score, reverse=True)
    return all_zones


# -------------------------------------------------------------------
# Formatting for Telegram
# -------------------------------------------------------------------
def format_radar_report(zones: list, max_zones: int = 10) -> str:
    """Format divergence zones for Telegram output."""
    if not zones:
        return "No divergence zones detected."

    lines = [f"Divergence Radar ({len(zones)} zones):"]
    for i, z in enumerate(zones[:max_zones], 1):
        stage_icon = {'potential_zone': '~', 'developing': '>', 'near_confirmed': '>>', 'confirmed': '!!!'}
        icon = stage_icon.get(z.stage, '?')
        lines.append(
            f"\n{i}. {z.symbol} {z.timeframe} — {z.direction.upper()} [{icon} {z.stage}]"
            f"\n   Prob: {z.probability:.0%} | Str: {z.strength:.0%} | Conf: {z.confidence:.0%}"
            f"\n   Trigger: {z.trigger_price:.2f} | Invalid: {z.invalidation:.2f}"
            f"\n   {', '.join(z.reasons[:3])}"
        )
    return "\n".join(lines)


def format_radar_brief(zones: list, tf_filter: str = None) -> str:
    """Short format for a specific timeframe."""
    if tf_filter:
        zones = [z for z in zones if z.timeframe == tf_filter]
    if not zones:
        return f"No divergence zones{' for ' + tf_filter if tf_filter else ''}."
    lines = [f"Div Zones{' (' + tf_filter + ')' if tf_filter else ''}: {len(zones)}"]
    for z in zones[:8]:
        lines.append(f"  {z.symbol} {z.timeframe} {z.direction} [{z.stage}] prob={z.probability:.0%}")
    return "\n".join(lines)
