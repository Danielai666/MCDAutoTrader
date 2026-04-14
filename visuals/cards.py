# visuals/cards.py
# Server-side rendering of visual report cards for Telegram.
# Produces PNG images using matplotlib (Agg backend).

import io
import time
import logging
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
from datetime import datetime

from visuals.gauges import (
    draw_gauge, compute_composite_score,
    _DARK_BG, _PANEL_BG, _TEXT_COLOR, _ACCENT_GREEN, _ACCENT_RED,
    _ACCENT_YELLOW, _ACCENT_BLUE, _GRID_COLOR, _score_color
)

log = logging.getLogger(__name__)

# Image cache: key -> (bytes, timestamp)
_cache = {}
_CACHE_TTL_STATUS = 60    # 60s for market overview
_CACHE_TTL_REPORT = 300   # 5 min for daily report

# Max image size for Railway CPU safety
_MAX_WIDTH = 1280
_MAX_HEIGHT = 720


def _get_cached(key: str, ttl: int) -> bytes:
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < ttl:
            return data
    return None


def _set_cached(key: str, data: bytes):
    _cache[key] = (data, time.time())


def _fig_to_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight',
                facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# -------------------------------------------------------------------
# 1) Signal Card
# -------------------------------------------------------------------
def render_signal_card(df: pd.DataFrame, pair: str, timeframe: str,
                       entry: float, sl: float, tp1: float, tp2: float = None,
                       side: str = 'BUY', risk_pct: float = 0.01,
                       confidence: float = 0.0, mode: str = 'Signal',
                       snapshot: dict = None, exchange: str = '') -> bytes:
    """
    Render a signal card with candlestick chart, indicator panels, and info box.
    Returns PNG bytes.
    """
    if snapshot is None:
        snapshot = {}

    # Limit data
    plot_df = df.tail(120).copy()
    n = len(plot_df)
    x = np.arange(n)

    fig = plt.figure(figsize=(10.67, 6), facecolor=_DARK_BG)

    # Layout: candlestick (60%), RSI (15%), MACD (15%), info strip (10% right)
    gs = fig.add_gridspec(3, 2, height_ratios=[4, 1, 1], width_ratios=[4, 1],
                          hspace=0.08, wspace=0.02,
                          left=0.06, right=0.98, top=0.93, bottom=0.05)

    # --- Candlestick panel ---
    ax_candle = fig.add_subplot(gs[0, 0])
    ax_candle.set_facecolor(_PANEL_BG)

    opens = plot_df['open'].values
    highs = plot_df['high'].values
    lows = plot_df['low'].values
    closes = plot_df['close'].values

    for i in range(n):
        color = _ACCENT_GREEN if closes[i] >= opens[i] else _ACCENT_RED
        # Body
        body_low = min(opens[i], closes[i])
        body_high = max(opens[i], closes[i])
        body_height = max(body_high - body_low, (highs[i] - lows[i]) * 0.005)
        ax_candle.bar(i, body_height, bottom=body_low, width=0.6, color=color, edgecolor=color, linewidth=0.5)
        # Wicks
        ax_candle.plot([i, i], [lows[i], body_low], color=color, linewidth=0.7)
        ax_candle.plot([i, i], [body_high, highs[i]], color=color, linewidth=0.7)

    # Entry / SL / TP lines
    is_buy = side.upper() == 'BUY'
    ax_candle.axhline(entry, color=_ACCENT_BLUE, linestyle='--', linewidth=1.2, alpha=0.9)
    ax_candle.text(n + 0.5, entry, f'Entry {entry:.2f}', fontsize=7, color=_ACCENT_BLUE, va='center')

    ax_candle.axhline(sl, color=_ACCENT_RED, linestyle='--', linewidth=1, alpha=0.8)
    ax_candle.text(n + 0.5, sl, f'SL {sl:.2f}', fontsize=7, color=_ACCENT_RED, va='center')

    ax_candle.axhline(tp1, color=_ACCENT_GREEN, linestyle='--', linewidth=1, alpha=0.8)
    ax_candle.text(n + 0.5, tp1, f'TP1 {tp1:.2f}', fontsize=7, color=_ACCENT_GREEN, va='center')

    if tp2:
        ax_candle.axhline(tp2, color=_ACCENT_GREEN, linestyle=':', linewidth=0.8, alpha=0.6)
        ax_candle.text(n + 0.5, tp2, f'TP2 {tp2:.2f}', fontsize=6, color=_ACCENT_GREEN, va='center', alpha=0.7)

    # Buy/Sell arrow
    arrow_y = entry
    arrow_color = _ACCENT_GREEN if is_buy else _ACCENT_RED
    arrow_marker = '^' if is_buy else 'v'
    ax_candle.plot(n - 3, arrow_y, marker=arrow_marker, color=arrow_color,
                   markersize=12, markeredgecolor='white', markeredgewidth=0.5, zorder=10)

    # SL/TP shading
    if is_buy:
        ax_candle.axhspan(sl, entry, alpha=0.05, color=_ACCENT_RED)
        ax_candle.axhspan(entry, tp1, alpha=0.05, color=_ACCENT_GREEN)
    else:
        ax_candle.axhspan(entry, sl, alpha=0.05, color=_ACCENT_RED)
        ax_candle.axhspan(tp1, entry, alpha=0.05, color=_ACCENT_GREEN)

    ax_candle.set_xlim(-1, n + 8)
    ax_candle.tick_params(colors=_TEXT_COLOR, labelsize=7)
    ax_candle.set_xticklabels([])
    ax_candle.yaxis.tick_right()
    ax_candle.spines['top'].set_visible(False)
    ax_candle.spines['bottom'].set_visible(False)
    ax_candle.spines['left'].set_visible(False)
    ax_candle.spines['right'].set_color(_GRID_COLOR)
    ax_candle.grid(True, alpha=0.15, color=_GRID_COLOR)

    # Title
    fig.text(0.06, 0.96, f'{pair}  {timeframe}', fontsize=14, fontweight='bold',
             color=_TEXT_COLOR, va='top')
    fig.text(0.30, 0.96, f'{side}', fontsize=13, fontweight='bold',
             color=arrow_color, va='top')

    # --- RSI panel ---
    ax_rsi = fig.add_subplot(gs[1, 0], sharex=ax_candle)
    ax_rsi.set_facecolor(_PANEL_BG)
    rsi_val = snapshot.get('rsi', 50)
    # Simple RSI line from last values
    from indicators import rsi as calc_rsi
    rsi_series = calc_rsi(plot_df['close'], 14)
    ax_rsi.plot(x, rsi_series.values, color=_ACCENT_BLUE, linewidth=1)
    ax_rsi.axhline(70, color=_ACCENT_RED, linewidth=0.5, linestyle=':', alpha=0.5)
    ax_rsi.axhline(30, color=_ACCENT_GREEN, linewidth=0.5, linestyle=':', alpha=0.5)
    ax_rsi.fill_between(x, 30, 70, alpha=0.03, color=_TEXT_COLOR)
    ax_rsi.set_ylim(10, 90)
    ax_rsi.set_ylabel('RSI', fontsize=7, color=_TEXT_COLOR, rotation=0, labelpad=15)
    ax_rsi.tick_params(colors=_TEXT_COLOR, labelsize=6)
    ax_rsi.set_xticklabels([])
    ax_rsi.yaxis.tick_right()
    ax_rsi.spines['top'].set_visible(False)
    ax_rsi.spines['bottom'].set_visible(False)
    ax_rsi.spines['left'].set_visible(False)
    ax_rsi.spines['right'].set_color(_GRID_COLOR)
    ax_rsi.grid(True, alpha=0.1, color=_GRID_COLOR)

    # --- MACD panel ---
    ax_macd = fig.add_subplot(gs[2, 0], sharex=ax_candle)
    ax_macd.set_facecolor(_PANEL_BG)
    from indicators import macd as calc_macd
    mline, msig, mhist = calc_macd(plot_df['close'])
    colors_hist = [_ACCENT_GREEN if v >= 0 else _ACCENT_RED for v in mhist.values]
    ax_macd.bar(x, mhist.values, color=colors_hist, alpha=0.6, width=0.6)
    ax_macd.plot(x, mline.values, color=_ACCENT_BLUE, linewidth=0.8)
    ax_macd.plot(x, msig.values, color=_ACCENT_YELLOW, linewidth=0.8, alpha=0.7)
    ax_macd.axhline(0, color=_GRID_COLOR, linewidth=0.5)
    ax_macd.set_ylabel('MACD', fontsize=7, color=_TEXT_COLOR, rotation=0, labelpad=15)
    ax_macd.tick_params(colors=_TEXT_COLOR, labelsize=6)
    ax_macd.yaxis.tick_right()
    ax_macd.spines['top'].set_visible(False)
    ax_macd.spines['left'].set_visible(False)
    ax_macd.spines['right'].set_color(_GRID_COLOR)
    ax_macd.spines['bottom'].set_color(_GRID_COLOR)
    ax_macd.grid(True, alpha=0.1, color=_GRID_COLOR)

    # --- Info box (right column, spans all rows) ---
    ax_info = fig.add_subplot(gs[:, 1])
    ax_info.set_facecolor(_PANEL_BG)
    ax_info.axis('off')

    # R:R calculation
    risk_dist = abs(entry - sl)
    reward_dist = abs(tp1 - entry)
    rr = reward_dist / risk_dist if risk_dist > 0 else 0

    info_lines = [
        ('Symbol', pair),
        ('TF', timeframe),
        ('Exchange', exchange or '-'),
        ('', ''),
        ('Side', side),
        ('Entry', f'{entry:.4f}'),
        ('SL', f'{sl:.4f}'),
        ('TP1', f'{tp1:.4f}'),
        ('', ''),
        ('Risk', f'{risk_pct:.1%}'),
        ('R:R', f'1:{rr:.1f}'),
        ('Conf', f'{confidence:.0%}'),
        ('', ''),
        ('Mode', mode),
    ]

    y_start = 0.95
    for i, (label, value) in enumerate(info_lines):
        y = y_start - i * 0.065
        if not label:
            continue
        color = _TEXT_COLOR
        if label == 'Side':
            color = _ACCENT_GREEN if is_buy else _ACCENT_RED
        elif label == 'Mode':
            color = _ACCENT_YELLOW if mode == 'Signal' else _ACCENT_GREEN if mode == 'Paper' else _ACCENT_RED
        ax_info.text(0.05, y, label, fontsize=7, color=_TEXT_COLOR, alpha=0.6,
                     transform=ax_info.transAxes, va='top')
        ax_info.text(0.95, y, value, fontsize=8, color=color, fontweight='bold',
                     transform=ax_info.transAxes, va='top', ha='right')

    return _fig_to_bytes(fig)


# -------------------------------------------------------------------
# 2) Market Overview Card
# -------------------------------------------------------------------
def render_market_overview_card(pair_scores: list, snapshot: dict = None,
                                 merged: dict = None) -> bytes:
    """
    Render market overview card with main gauge + mini gauges + table.
    pair_scores: list of dicts [{pair, score, bias, timeframe}, ...]
    snapshot: latest signal snapshot for gauge computation
    Returns PNG bytes.
    """
    cache_key = 'market_overview'
    cached = _get_cached(cache_key, _CACHE_TTL_STATUS)
    if cached:
        return cached

    snapshot = snapshot or {}
    scores = compute_composite_score(snapshot, merged)

    fig = plt.figure(figsize=(10.67, 6), facecolor=_DARK_BG)
    gs = fig.add_gridspec(2, 4, hspace=0.35, wspace=0.3,
                          left=0.04, right=0.96, top=0.88, bottom=0.08)

    # Title
    fig.text(0.5, 0.95, 'Market Overview', fontsize=16, fontweight='bold',
             color=_TEXT_COLOR, ha='center', va='top')

    # --- Main gauge (top-left, spans 2 cols) ---
    ax_main = fig.add_subplot(gs[0, 0:2])
    draw_gauge(ax_main, scores['total_score'], 'Market Mood', size=1.2)

    # Bias label under gauge
    bias_color = _score_color(scores['total_score'])
    ax_main.text(0, -0.45, scores['bias'], ha='center', fontsize=11,
                 fontweight='bold', color=bias_color)

    # --- Mini gauges (top-right) ---
    ax_conf = fig.add_subplot(gs[0, 2])
    draw_gauge(ax_conf, scores['momentum_score'], 'Momentum', size=0.8)

    ax_risk = fig.add_subplot(gs[0, 3])
    # Risk gauge: invert (high volatility = high risk)
    risk_display = 100 - scores['volatility_score']
    draw_gauge(ax_risk, risk_display, 'Risk', size=0.8)

    # --- Reasons (bottom-left) ---
    ax_reasons = fig.add_subplot(gs[1, 0:2])
    ax_reasons.set_facecolor(_PANEL_BG)
    ax_reasons.axis('off')

    reasons_text = scores.get('reasons', [])
    for i, reason in enumerate(reasons_text[:5]):
        y = 0.85 - i * 0.17
        ax_reasons.text(0.05, y, f'  {reason}', fontsize=9, color=_TEXT_COLOR,
                        transform=ax_reasons.transAxes, va='top')

    if scores.get('no_trade'):
        ax_reasons.text(0.5, 0.05, 'NO TRADE — LOW VOLATILITY', ha='center',
                        fontsize=11, fontweight='bold', color=_ACCENT_RED,
                        transform=ax_reasons.transAxes)

    # Sub-score breakdown
    ax_reasons.text(0.05, 0.02, (
        f"Trend:{scores['trend_score']:.0f}  Div:{scores['divergence_score']:.0f}  "
        f"Mom:{scores['momentum_score']:.0f}  Candle:{scores['candle_score']:.0f}  "
        f"Vol:{scores['volatility_score']:.0f}"
    ), fontsize=7, color=_TEXT_COLOR, alpha=0.5, transform=ax_reasons.transAxes)

    # --- Top symbols table (bottom-right) ---
    ax_table = fig.add_subplot(gs[1, 2:4])
    ax_table.set_facecolor(_PANEL_BG)
    ax_table.axis('off')

    ax_table.text(0.5, 0.95, 'Top Symbols', fontsize=10, fontweight='bold',
                  color=_TEXT_COLOR, ha='center', transform=ax_table.transAxes, va='top')

    # Header
    headers = ['Symbol', 'Score', 'Bias', 'TF']
    for j, h in enumerate(headers):
        ax_table.text(0.05 + j * 0.25, 0.80, h, fontsize=7, color=_TEXT_COLOR,
                      alpha=0.6, transform=ax_table.transAxes, va='top', fontweight='bold')

    # Rows
    for i, ps in enumerate(pair_scores[:5]):
        y = 0.65 - i * 0.13
        score_val = ps.get('score', 0) or 0
        bias = 'BUY' if score_val > 0.3 else 'SELL' if score_val < -0.3 else 'HOLD'
        bias_c = _ACCENT_GREEN if bias == 'BUY' else _ACCENT_RED if bias == 'SELL' else _TEXT_COLOR

        ax_table.text(0.05, y, ps.get('pair', ''), fontsize=8, color=_TEXT_COLOR,
                      transform=ax_table.transAxes, va='top')
        ax_table.text(0.30, y, f'{abs(score_val):.2f}', fontsize=8, color=_TEXT_COLOR,
                      transform=ax_table.transAxes, va='top')
        ax_table.text(0.55, y, bias, fontsize=8, color=bias_c, fontweight='bold',
                      transform=ax_table.transAxes, va='top')
        ax_table.text(0.80, y, ps.get('timeframe', '1h'), fontsize=8, color=_TEXT_COLOR,
                      transform=ax_table.transAxes, va='top', alpha=0.7)

    result = _fig_to_bytes(fig)
    _set_cached(cache_key, result)
    return result


# -------------------------------------------------------------------
# 3) Daily Report Card
# -------------------------------------------------------------------
def render_daily_report_card(equity_history: list = None,
                              perf: dict = None, equity_status: dict = None) -> bytes:
    """
    Render daily report card with equity curve, win/loss pie, and metrics.
    equity_history: list of (date_str, equity_value) for the curve
    perf: performance_summary() dict
    equity_status: get_equity_status() dict
    Returns PNG bytes.
    """
    cache_key = 'daily_report'
    cached = _get_cached(cache_key, _CACHE_TTL_REPORT)
    if cached:
        return cached

    perf = perf or {}
    equity_status = equity_status or {}

    fig = plt.figure(figsize=(10.67, 6), facecolor=_DARK_BG)
    gs = fig.add_gridspec(2, 3, hspace=0.35, wspace=0.3,
                          left=0.06, right=0.96, top=0.88, bottom=0.08)

    fig.text(0.5, 0.95, 'Daily Performance Report', fontsize=16, fontweight='bold',
             color=_TEXT_COLOR, ha='center', va='top')

    # --- Equity curve (top, spans 2 cols) ---
    ax_eq = fig.add_subplot(gs[0, 0:2])
    ax_eq.set_facecolor(_PANEL_BG)

    if equity_history and len(equity_history) > 1:
        dates = [h[0] for h in equity_history]
        values = [h[1] for h in equity_history]
        x_eq = range(len(values))

        # Color the line based on whether above or below starting value
        start_val = values[0]
        ax_eq.fill_between(x_eq, start_val, values, where=[v >= start_val for v in values],
                           alpha=0.15, color=_ACCENT_GREEN)
        ax_eq.fill_between(x_eq, start_val, values, where=[v < start_val for v in values],
                           alpha=0.15, color=_ACCENT_RED)
        ax_eq.plot(x_eq, values, color=_ACCENT_BLUE, linewidth=1.5)
        ax_eq.axhline(start_val, color=_GRID_COLOR, linewidth=0.5, linestyle=':')
    else:
        # No history — show current equity as single point
        eq_val = equity_status.get('equity', 1000)
        ax_eq.text(0.5, 0.5, f'${eq_val:,.2f}', fontsize=20, fontweight='bold',
                   color=_ACCENT_BLUE, ha='center', va='center', transform=ax_eq.transAxes)

    ax_eq.set_title('Equity Curve', fontsize=10, color=_TEXT_COLOR, pad=8)
    ax_eq.tick_params(colors=_TEXT_COLOR, labelsize=7)
    ax_eq.spines['top'].set_visible(False)
    ax_eq.spines['right'].set_visible(False)
    ax_eq.spines['left'].set_color(_GRID_COLOR)
    ax_eq.spines['bottom'].set_color(_GRID_COLOR)
    ax_eq.grid(True, alpha=0.1, color=_GRID_COLOR)

    # --- Win/Loss pie (top-right) ---
    ax_pie = fig.add_subplot(gs[0, 2])
    ax_pie.set_facecolor(_DARK_BG)

    wins = perf.get('winning', 0)
    losses = perf.get('losing', 0)
    total_trades = perf.get('total_trades', 0)

    if total_trades > 0:
        sizes = [wins, losses]
        colors_pie = [_ACCENT_GREEN, _ACCENT_RED]
        labels = [f'Win {wins}', f'Loss {losses}']
        wedges, texts = ax_pie.pie(sizes, colors=colors_pie, startangle=90,
                                    wedgeprops=dict(width=0.4, edgecolor=_DARK_BG))
        ax_pie.text(0, 0, f'{perf.get("win_rate", 0):.0f}%', ha='center', va='center',
                    fontsize=14, fontweight='bold', color=_TEXT_COLOR)
        ax_pie.text(0, -0.15, 'Win Rate', ha='center', va='center',
                    fontsize=7, color=_TEXT_COLOR, alpha=0.6)
    else:
        ax_pie.text(0.5, 0.5, 'No trades', ha='center', va='center',
                    fontsize=10, color=_TEXT_COLOR, alpha=0.5, transform=ax_pie.transAxes)
    ax_pie.set_title('Win/Loss', fontsize=10, color=_TEXT_COLOR, pad=8)

    # --- Key metrics (bottom, spans all 3 cols) ---
    ax_metrics = fig.add_subplot(gs[1, :])
    ax_metrics.set_facecolor(_PANEL_BG)
    ax_metrics.axis('off')

    total_pnl = perf.get('total_pnl', 0)
    pnl_color = _ACCENT_GREEN if total_pnl >= 0 else _ACCENT_RED

    metrics = [
        ('Total PnL', f'${total_pnl:+,.2f}', pnl_color),
        ('Win Rate', f'{perf.get("win_rate", 0):.1f}%', _TEXT_COLOR),
        ('Avg R:R', f'{perf.get("profit_factor", 0):.2f}', _TEXT_COLOR),
        ('Max DD', f'{equity_status.get("max_drawdown_pct", 0):.1%}', _ACCENT_YELLOW),
        ('Trades', f'{total_trades}', _TEXT_COLOR),
        ('Equity', f'${equity_status.get("equity", 0):,.2f}', _ACCENT_BLUE),
        ('Peak', f'${equity_status.get("peak_equity", 0):,.2f}', _TEXT_COLOR),
        ('Expectancy', f'${perf.get("expectancy", 0):+.2f}', pnl_color),
    ]

    for i, (label, value, color) in enumerate(metrics):
        col = i % 4
        row = i // 4
        x_pos = 0.05 + col * 0.25
        y_pos = 0.75 - row * 0.45

        ax_metrics.text(x_pos, y_pos, label, fontsize=8, color=_TEXT_COLOR, alpha=0.6,
                        transform=ax_metrics.transAxes, va='top')
        ax_metrics.text(x_pos, y_pos - 0.15, value, fontsize=13, fontweight='bold',
                        color=color, transform=ax_metrics.transAxes, va='top')

    result = _fig_to_bytes(fig)
    _set_cached(cache_key, result)
    return result
