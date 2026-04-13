import pandas as pd
import numpy as np
from config import SETTINGS

def _pivots(s, lookback=None):
    lb = lookback or SETTINGS.PIVOT_LOOKBACK
    highs, lows = [], []
    vals = s.values
    idx = s.index
    for i in range(lb, len(vals) - lb):
        window = vals[i - lb : i + lb + 1]
        if vals[i] == np.nanmax(window):
            highs.append(idx[i])
        if vals[i] == np.nanmin(window):
            lows.append(idx[i])
    return highs[-2:] if len(highs) >= 2 else [], lows[-2:] if len(lows) >= 2 else []

def _strength(p1, p2, o1, o2):
    price_delta = abs(p2 - p1) / max(abs(p1), 1e-9)
    osc_delta = abs(o2 - o1) / max(abs(o1), 1e-9)
    raw = min(price_delta + osc_delta, 1.0)
    return round(max(0.1, raw), 3)

def detect_divergence(price, osc):
    if len(price) < 50:
        return "none", 0.0
    hi, lo = _pivots(price)
    if len(hi) == 2:
        p1, p2 = float(price.loc[hi[0]]), float(price.loc[hi[1]])
        o1, o2 = float(osc.loc[hi[0]]), float(osc.loc[hi[1]])
        if p2 > p1 and o2 < o1:
            return "bearish", _strength(p1, p2, o1, o2)
    if len(lo) == 2:
        p1, p2 = float(price.loc[lo[0]]), float(price.loc[lo[1]])
        o1, o2 = float(osc.loc[lo[0]]), float(osc.loc[lo[1]])
        if p2 < p1 and o2 > o1:
            return "bullish", _strength(p1, p2, o1, o2)
    return "none", 0.0


def detect_hidden_divergence(price, osc):
    """
    Hidden bullish: price makes higher low, oscillator makes lower low (trend continuation up).
    Hidden bearish: price makes lower high, oscillator makes higher high (trend continuation down).
    """
    if len(price) < 50:
        return "none", 0.0
    hi, lo = _pivots(price)

    # Hidden bearish: price lower high, osc higher high
    if len(hi) == 2:
        p1, p2 = float(price.loc[hi[0]]), float(price.loc[hi[1]])
        o1, o2 = float(osc.loc[hi[0]]), float(osc.loc[hi[1]])
        if p2 < p1 and o2 > o1:
            return "hidden_bearish", _strength(p1, p2, o1, o2)

    # Hidden bullish: price higher low, osc lower low
    if len(lo) == 2:
        p1, p2 = float(price.loc[lo[0]]), float(price.loc[lo[1]])
        o1, o2 = float(osc.loc[lo[0]]), float(osc.loc[lo[1]])
        if p2 > p1 and o2 < o1:
            return "hidden_bullish", _strength(p1, p2, o1, o2)

    return "none", 0.0


def detect_all_divergences(price, osc):
    """Detect both regular and hidden divergences. Returns combined dict."""
    reg_type, reg_str = detect_divergence(price, osc)
    hid_type, hid_str = detect_hidden_divergence(price, osc)
    return {
        'regular': {'type': reg_type, 'strength': reg_str},
        'hidden': {'type': hid_type, 'strength': hid_str},
    }
