# visuals/gauges.py
# Gauge rendering + composite market mood scoring.
# All rendering uses matplotlib with Agg backend (no display needed).

import math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch

# -------------------------------------------------------------------
# Composite score calculation (0..100)
# -------------------------------------------------------------------

def compute_composite_score(snapshot: dict, merged: dict = None) -> dict:
    """
    Compute weighted composite market mood score from signal snapshot.

    Weights:
      35% TrendScore (Ichimoku / EMA)
      30% DivergenceScore (MACD divergence strength)
      20% MomentumConfirm (RSI level + direction)
      10% CandleConfirm
       5% VolatilitySanity (ATR-based)

    Returns dict with total_score (0..100), sub-scores, bias, reasons.
    """
    reasons = []

    # --- 35% Trend Score ---
    trend_score = 50  # neutral default
    ichi = snapshot.get('ichimoku')
    if ichi:
        if ichi.get('above_cloud') and ichi.get('tk_bullish'):
            trend_score = 85
            reasons.append('Above cloud + TK bullish')
        elif ichi.get('above_cloud'):
            trend_score = 70
            reasons.append('Above cloud')
        elif ichi.get('below_cloud') and not ichi.get('tk_bullish'):
            trend_score = 15
            reasons.append('Below cloud + TK bearish')
        elif ichi.get('below_cloud'):
            trend_score = 30
            reasons.append('Below cloud')
        else:
            trend_score = 50
            reasons.append('Inside cloud (neutral)')
    else:
        # Fallback to EMA
        if snapshot.get('ema9_gt_ema21'):
            trend_score = 65
            reasons.append('EMA9 > EMA21')
        else:
            trend_score = 35
            reasons.append('EMA9 < EMA21')

    # --- 30% Divergence Score ---
    div_score = 50
    components = snapshot.get('components', []) if 'components' in snapshot else []
    # Check from merged signal if available
    if merged:
        m_dir = merged.get('merged_direction', 'HOLD')
        m_score = abs(merged.get('merged_score', 0))
        if m_dir == 'BUY':
            div_score = min(95, 50 + m_score * 30)
            if m_score > 0.5:
                reasons.append(f'Bullish divergence (score {m_score:.2f})')
        elif m_dir == 'SELL':
            div_score = max(5, 50 - m_score * 30)
            if m_score > 0.5:
                reasons.append(f'Bearish divergence (score {m_score:.2f})')

    # Check div_radar in snapshot
    radar = snapshot.get('div_radar', [])
    if radar:
        best = radar[0] if isinstance(radar, list) and len(radar) > 0 else None
        if best:
            prob = best.get('probability', 0)
            direction = best.get('direction', '')
            if direction == 'bullish' and prob > 0.3:
                div_score = min(95, div_score + prob * 20)
            elif direction == 'bearish' and prob > 0.3:
                div_score = max(5, div_score - prob * 20)

    # --- 20% Momentum (RSI) ---
    rsi_val = snapshot.get('rsi', 50)
    if rsi_val > 70:
        momentum_score = 75
        reasons.append(f'RSI overbought ({rsi_val:.0f})')
    elif rsi_val > 55:
        momentum_score = 65
    elif rsi_val < 30:
        momentum_score = 25
        reasons.append(f'RSI oversold ({rsi_val:.0f})')
    elif rsi_val < 45:
        momentum_score = 35
    else:
        momentum_score = 50

    # --- 10% Candle Confirm ---
    candle_score = 50
    candles = snapshot.get('candles')
    if candles:
        net = candles.get('net_score', 0)
        if net > 0.3:
            candle_score = 70
            reasons.append('Bullish candle pattern')
        elif net < -0.3:
            candle_score = 30
            reasons.append('Bearish candle pattern')

    # --- 5% Volatility Sanity ---
    vol_score = 50
    atr = snapshot.get('atr', 0)
    adx = snapshot.get('adx', 0)
    no_trade = False
    if adx < 15:
        vol_score = 20
        no_trade = True
        reasons.append('Very low ADX — no trade')
    elif adx > 40:
        vol_score = 80
        reasons.append(f'Strong trend ADX={adx:.0f}')
    else:
        vol_score = 50

    # --- Weighted total ---
    total = (trend_score * 0.35 +
             div_score * 0.30 +
             momentum_score * 0.20 +
             candle_score * 0.10 +
             vol_score * 0.05)
    total = max(0, min(100, total))

    # Bias label
    if total >= 65:
        bias = 'BULLISH'
    elif total <= 35:
        bias = 'BEARISH'
    else:
        bias = 'NEUTRAL'

    return {
        'total_score': round(total, 1),
        'trend_score': round(trend_score, 1),
        'divergence_score': round(div_score, 1),
        'momentum_score': round(momentum_score, 1),
        'candle_score': round(candle_score, 1),
        'volatility_score': round(vol_score, 1),
        'bias': bias,
        'no_trade': no_trade,
        'reasons': reasons[:5],
    }


# -------------------------------------------------------------------
# Gauge drawing
# -------------------------------------------------------------------

# Color scheme
_DARK_BG = '#1a1a2e'
_PANEL_BG = '#16213e'
_TEXT_COLOR = '#e0e0e0'
_ACCENT_GREEN = '#00d26a'
_ACCENT_RED = '#f92672'
_ACCENT_YELLOW = '#ffd93d'
_ACCENT_BLUE = '#4fc3f7'
_GRID_COLOR = '#2a2a4a'


def _score_color(score: float) -> str:
    """Return color based on score 0..100."""
    if score >= 65:
        return _ACCENT_GREEN
    elif score <= 35:
        return _ACCENT_RED
    return _ACCENT_YELLOW


def draw_gauge(ax, score: float, label: str, size: float = 1.0):
    """Draw a semicircular speedometer gauge on the given axes."""
    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-0.4, 1.3)
    ax.set_aspect('equal')
    ax.axis('off')

    # Background arc segments (red → yellow → green)
    angles_deg = np.linspace(180, 0, 100)
    for i in range(len(angles_deg) - 1):
        pct = i / len(angles_deg)
        if pct < 0.35:
            c = _ACCENT_RED
        elif pct < 0.65:
            c = _ACCENT_YELLOW
        else:
            c = _ACCENT_GREEN
        a1 = math.radians(angles_deg[i])
        a2 = math.radians(angles_deg[i + 1])
        xs = [0, math.cos(a1), math.cos(a2)]
        ys = [0, math.sin(a1), math.sin(a2)]
        ax.fill(xs, ys, color=c, alpha=0.15)

    # Outer arc
    theta = np.linspace(math.pi, 0, 200)
    ax.plot(np.cos(theta), np.sin(theta), color=_GRID_COLOR, lw=2)

    # Needle
    needle_angle = math.pi - (score / 100.0) * math.pi
    nx = 0.85 * math.cos(needle_angle)
    ny = 0.85 * math.sin(needle_angle)
    needle_color = _score_color(score)
    ax.annotate('', xy=(nx, ny), xytext=(0, 0),
                arrowprops=dict(arrowstyle='->', color=needle_color, lw=2.5))
    ax.plot(0, 0, 'o', color=needle_color, markersize=6, zorder=5)

    # Score text
    ax.text(0, -0.15, f'{score:.0f}', ha='center', va='center',
            fontsize=int(18 * size), fontweight='bold', color=needle_color)
    ax.text(0, -0.32, label, ha='center', va='center',
            fontsize=int(9 * size), color=_TEXT_COLOR, alpha=0.8)

    # Min/max labels
    ax.text(-1.05, -0.05, '0', ha='center', fontsize=7, color=_TEXT_COLOR, alpha=0.5)
    ax.text(1.05, -0.05, '100', ha='center', fontsize=7, color=_TEXT_COLOR, alpha=0.5)
