# backtest.py
# Backtesting engine: replays historical OHLCV through a simplified signal pipeline + risk gates.
# Simulates entries/exits, computes PnL, win rate, max drawdown, equity curve.
# Telegram command: /backtest <pair> [days] [timeframe]

import logging
import io
from dataclasses import dataclass, field
from typing import List, Optional
from config import SETTINGS

log = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    pair: str
    side: str
    entry_price: float
    entry_bar: int
    sl: float
    tp: float
    qty: float = 0.0
    exit_price: float = 0.0
    exit_bar: int = 0
    pnl: float = 0.0
    status: str = 'open'
    reason: str = ''


@dataclass
class BacktestResult:
    pair: str
    timeframe: str
    days: int
    total_bars: int
    total_trades: int = 0
    winning: int = 0
    losing: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown_pct: float = 0.0
    starting_capital: float = 1000.0
    ending_equity: float = 1000.0
    peak_equity: float = 1000.0
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    signals_generated: int = 0
    signals_blocked: int = 0


def run_backtest(pair: str, days: int = 30, timeframe: str = '1h',
                 capital: float = 1000.0, risk_pct: float = 0.01) -> BacktestResult:
    """
    Run a backtest on historical data.
    Fetches OHLCV, walks forward bar-by-bar, generates signals, manages SL/TP.
    """
    from exchange import fetch_ohlcv
    from indicators import macd, rsi, atr, adx, ema_pair, bollinger, stochastic

    limit = days * (24 if timeframe == '1h' else 96 if timeframe == '15m' else 6 if timeframe == '4h' else 1)
    limit = min(limit, 1000)

    try:
        df = fetch_ohlcv(pair, timeframe, limit)
    except Exception as e:
        log.error("Backtest fetch failed for %s: %s", pair, e)
        return BacktestResult(pair=pair, timeframe=timeframe, days=days, total_bars=0)

    if df is None or len(df) < 100:
        return BacktestResult(pair=pair, timeframe=timeframe, days=days,
                              total_bars=len(df) if df is not None else 0)

    n = len(df)
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values

    macd_line, macd_sig, macd_hist = macd(df['close'])
    rsi_vals = rsi(df['close'], 14)
    atr_vals = atr(df['high'], df['low'], df['close'], 14)
    adx_vals, _, _ = adx(df['high'], df['low'], df['close'], 14)
    ema9, ema21 = ema_pair(df['close'], 9, 21)
    bb_up, _, bb_lo = bollinger(df['close'], 20, 2.0)
    stoch_k, _ = stochastic(df['high'], df['low'], df['close'])

    result = BacktestResult(
        pair=pair, timeframe=timeframe, days=days, total_bars=n,
        starting_capital=capital, ending_equity=capital, peak_equity=capital)

    equity = capital
    open_trade: Optional[BacktestTrade] = None
    cooldown_until = 0
    equity_curve = [capital]

    for i in range(50, n):
        bar_close = float(closes[i])
        bar_high = float(highs[i])
        bar_low = float(lows[i])
        cur_atr = float(atr_vals.iloc[i])
        cur_adx = float(adx_vals.iloc[i])
        cur_hist = float(macd_hist.iloc[i])
        prev_hist = float(macd_hist.iloc[i - 1])
        cur_ema9 = float(ema9.iloc[i])
        cur_ema21 = float(ema21.iloc[i])
        bb_range = max(float(bb_up.iloc[i]) - float(bb_lo.iloc[i]), 0.0001)
        cur_bb_pos = (bar_close - float(bb_lo.iloc[i])) / bb_range
        cur_stoch_k = float(stoch_k.iloc[i])
        cur_rsi = float(rsi_vals.iloc[i])
        cur_macd = float(macd_line.iloc[i])
        cur_macd_sig = float(macd_sig.iloc[i])

        # Manage open trade
        if open_trade and open_trade.status == 'open':
            if open_trade.side == 'BUY':
                if bar_low <= open_trade.sl:
                    open_trade.exit_price = open_trade.sl
                    open_trade.pnl = (open_trade.sl - open_trade.entry_price) * open_trade.qty
                    open_trade.status = 'closed_sl'
                    open_trade.exit_bar = i
                elif bar_high >= open_trade.tp:
                    open_trade.exit_price = open_trade.tp
                    open_trade.pnl = (open_trade.tp - open_trade.entry_price) * open_trade.qty
                    open_trade.status = 'closed_tp'
                    open_trade.exit_bar = i
            else:
                if bar_high >= open_trade.sl:
                    open_trade.exit_price = open_trade.sl
                    open_trade.pnl = (open_trade.entry_price - open_trade.sl) * open_trade.qty
                    open_trade.status = 'closed_sl'
                    open_trade.exit_bar = i
                elif bar_low <= open_trade.tp:
                    open_trade.exit_price = open_trade.tp
                    open_trade.pnl = (open_trade.entry_price - open_trade.tp) * open_trade.qty
                    open_trade.status = 'closed_tp'
                    open_trade.exit_bar = i

            if open_trade.status != 'open':
                equity += open_trade.pnl
                result.trades.append(open_trade)
                cooldown_until = i + 3
                open_trade = None

        # Generate signal
        if open_trade is None and i > cooldown_until and cur_atr > 0:
            signal = _compute_signal(cur_adx, cur_rsi, cur_hist, prev_hist,
                                      cur_ema9, cur_ema21, cur_bb_pos, cur_stoch_k,
                                      cur_macd, cur_macd_sig)
            if signal != 'HOLD':
                result.signals_generated += 1
                if cur_adx < SETTINGS.ADX_TREND_MIN:
                    result.signals_blocked += 1
                else:
                    sl_dist = cur_atr * SETTINGS.ATR_SL_MULTIPLIER
                    risk_usd = equity * risk_pct
                    qty = risk_usd / sl_dist if sl_dist > 0 else 0
                    if qty > 0:
                        if signal == 'BUY':
                            sl = bar_close - sl_dist
                            tp = bar_close + cur_atr * SETTINGS.TP_ATR_MULTIPLIER
                        else:
                            sl = bar_close + sl_dist
                            tp = bar_close - cur_atr * SETTINGS.TP_ATR_MULTIPLIER
                        open_trade = BacktestTrade(
                            pair=pair, side=signal, entry_price=bar_close,
                            entry_bar=i, sl=sl, tp=tp, qty=qty)

        equity_curve.append(equity)
        if equity > result.peak_equity:
            result.peak_equity = equity
        dd = (result.peak_equity - equity) / result.peak_equity if result.peak_equity > 0 else 0
        if dd > result.max_drawdown_pct:
            result.max_drawdown_pct = dd

    # Close remaining trade
    if open_trade and open_trade.status == 'open':
        open_trade.exit_price = float(closes[-1])
        if open_trade.side == 'BUY':
            open_trade.pnl = (open_trade.exit_price - open_trade.entry_price) * open_trade.qty
        else:
            open_trade.pnl = (open_trade.entry_price - open_trade.exit_price) * open_trade.qty
        open_trade.status = 'closed_end'
        open_trade.exit_bar = n - 1
        equity += open_trade.pnl
        result.trades.append(open_trade)

    # Metrics
    result.ending_equity = round(equity, 2)
    result.equity_curve = equity_curve
    result.total_trades = len(result.trades)
    wins = [t for t in result.trades if t.pnl > 0]
    losses = [t for t in result.trades if t.pnl <= 0]
    result.winning = len(wins)
    result.losing = len(losses)
    result.win_rate = round(len(wins) / max(result.total_trades, 1) * 100, 1)
    result.total_pnl = round(sum(t.pnl for t in result.trades), 2)
    result.avg_win = round(sum(t.pnl for t in wins) / max(len(wins), 1), 2)
    result.avg_loss = round(sum(t.pnl for t in losses) / max(len(losses), 1), 2)
    total_win = sum(t.pnl for t in wins)
    total_loss = abs(sum(t.pnl for t in losses))
    result.profit_factor = round(total_win / max(total_loss, 0.01), 2)
    result.expectancy = round(
        (result.win_rate / 100 * result.avg_win) + ((1 - result.win_rate / 100) * result.avg_loss), 2)
    result.max_drawdown_pct = round(result.max_drawdown_pct, 4)

    return result


def _compute_signal(adx_val, rsi_val, hist, prev_hist, ema9, ema21,
                     bb_pos, stoch_k, macd_val, macd_sig) -> str:
    """Simplified signal for backtest (mirrors strategy.py scoring logic)."""
    buy = 0.0
    sell = 0.0

    if ema9 > ema21: buy += 1.0
    else: sell += 1.0

    if hist > prev_hist and hist > 0: buy += 0.5
    elif hist < prev_hist and hist < 0: sell += 0.5

    if macd_val > macd_sig and prev_hist < 0 and hist > 0: buy += 1.5
    elif macd_val < macd_sig and prev_hist > 0 and hist < 0: sell += 1.5

    if rsi_val < 35: buy += 0.5
    elif rsi_val > 65: sell += 0.5

    if bb_pos < 0.2: buy += 0.5
    elif bb_pos > 0.8: sell += 0.5

    if stoch_k < 25: buy += 0.5
    elif stoch_k > 75: sell += 0.5

    if buy >= 2.5 and buy > sell: return 'BUY'
    elif sell >= 2.5 and sell > buy: return 'SELL'
    return 'HOLD'


def format_backtest_result(r: BacktestResult) -> str:
    sign = '+' if r.total_pnl >= 0 else ''
    return (
        f"Backtest: {r.pair} {r.timeframe} ({r.days}d)\n"
        f"Bars: {r.total_bars} | Signals: {r.signals_generated} (blocked: {r.signals_blocked})\n"
        f"Trades: {r.total_trades} (W:{r.winning} L:{r.losing})\n"
        f"Win Rate: {r.win_rate}% | PF: {r.profit_factor}\n"
        f"PnL: {sign}${r.total_pnl:.2f} | Max DD: {r.max_drawdown_pct:.1%}\n"
        f"Equity: ${r.starting_capital:,.0f} -> ${r.ending_equity:,.2f}"
    )


def render_backtest_card(r: BacktestResult) -> bytes:
    """Render backtest result as a PNG card."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    _BG = '#1a1a2e'
    _PNL = '#16213e'
    _TXT = '#e0e0e0'
    _GRN = '#00d26a'
    _RED = '#f92672'
    _BLU = '#4fc3f7'
    _YEL = '#ffd93d'
    _GRD = '#2a2a4a'

    fig = plt.figure(figsize=(10.67, 6), facecolor=_BG)
    gs = fig.add_gridspec(2, 3, hspace=0.35, wspace=0.3,
                          left=0.06, right=0.96, top=0.88, bottom=0.08)

    fig.text(0.5, 0.95, f'Backtest: {r.pair} {r.timeframe} ({r.days}d)',
             fontsize=14, fontweight='bold', color=_TXT, ha='center')

    ax_eq = fig.add_subplot(gs[0, 0:2])
    ax_eq.set_facecolor(_PNL)
    if r.equity_curve:
        x = range(len(r.equity_curve))
        start = r.equity_curve[0]
        ax_eq.fill_between(x, start, r.equity_curve,
                           where=[v >= start for v in r.equity_curve], alpha=0.15, color=_GRN)
        ax_eq.fill_between(x, start, r.equity_curve,
                           where=[v < start for v in r.equity_curve], alpha=0.15, color=_RED)
        ax_eq.plot(x, r.equity_curve, color=_BLU, linewidth=1.2)
        ax_eq.axhline(start, color=_GRD, linewidth=0.5, linestyle=':')
    ax_eq.set_title('Equity Curve', fontsize=10, color=_TXT, pad=8)
    ax_eq.tick_params(colors=_TXT, labelsize=7)
    for s in ax_eq.spines.values(): s.set_color(_GRD)
    ax_eq.grid(True, alpha=0.1, color=_GRD)

    ax_pie = fig.add_subplot(gs[0, 2])
    ax_pie.set_facecolor(_BG)
    if r.total_trades > 0:
        ax_pie.pie([max(r.winning, 0.1), max(r.losing, 0.1)], colors=[_GRN, _RED],
                   startangle=90, wedgeprops=dict(width=0.4, edgecolor=_BG))
        ax_pie.text(0, 0, f'{r.win_rate:.0f}%', ha='center', va='center',
                    fontsize=14, fontweight='bold', color=_TXT)
    ax_pie.set_title('Win Rate', fontsize=10, color=_TXT, pad=8)

    ax_m = fig.add_subplot(gs[1, :])
    ax_m.set_facecolor(_PNL)
    ax_m.axis('off')
    pc = _GRN if r.total_pnl >= 0 else _RED
    metrics = [
        ('PnL', f'${r.total_pnl:+,.2f}', pc), ('Win Rate', f'{r.win_rate}%', _TXT),
        ('PF', f'{r.profit_factor}', _TXT), ('Max DD', f'{r.max_drawdown_pct:.1%}', _YEL),
        ('Trades', f'{r.total_trades}', _TXT), ('Avg Win', f'${r.avg_win:+.2f}', _GRN),
        ('Avg Loss', f'${r.avg_loss:.2f}', _RED), ('Expectancy', f'${r.expectancy:+.2f}', pc),
    ]
    for i, (lb, val, c) in enumerate(metrics):
        col, row = i % 4, i // 4
        xp, yp = 0.05 + col * 0.25, 0.75 - row * 0.45
        ax_m.text(xp, yp, lb, fontsize=8, color=_TXT, alpha=0.6, transform=ax_m.transAxes, va='top')
        ax_m.text(xp, yp - 0.15, val, fontsize=13, fontweight='bold', color=c, transform=ax_m.transAxes, va='top')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor=_BG, edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return buf.read()
