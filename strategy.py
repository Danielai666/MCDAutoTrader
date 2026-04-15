import pandas as pd

from config import SETTINGS
from indicators import macd, rsi, stochastic, ema_pair, vol_ma, atr, adx, bollinger
from divergence import detect_divergence, detect_hidden_divergence


def tf_signal(df: pd.DataFrame, symbol: str = '', timeframe: str = '') -> dict:
    close = df['close']; high = df['high']; low = df['low']; vol = df['volume']

    # --- compute all indicators ---
    mline, msig, mhist = macd(close)
    r = rsi(close, 14)
    k, d = stochastic(high, low, close, 14, 3)
    e9, e21 = ema_pair(close, 9, 21)
    vma = vol_ma(vol, 20)
    a = atr(high, low, close, SETTINGS.ATR_PERIOD)
    adx_line, plus_di, minus_di = adx(high, low, close, SETTINGS.ADX_PERIOD)
    bb_up, bb_mid, bb_lo = bollinger(close, SETTINGS.BB_PERIOD, SETTINGS.BB_STD)

    # --- divergences (regular + hidden) ---
    md_type, md_str = detect_divergence(close, mline)
    rd_type, rd_str = detect_divergence(close, r)

    hid_md_type, hid_md_str = ("none", 0.0)
    hid_rd_type, hid_rd_str = ("none", 0.0)
    if SETTINGS.FEATURE_HIDDEN_DIVERGENCE:
        hid_md_type, hid_md_str = detect_hidden_divergence(close, mline)
        hid_rd_type, hid_rd_str = detect_hidden_divergence(close, r)

    # --- candle patterns ---
    candle_summary = None
    if SETTINGS.FEATURE_CANDLE_PATTERNS:
        from candles import detect_patterns, summarize_patterns
        patterns = detect_patterns(df, lookback=3)
        candle_summary = summarize_patterns(patterns)

    # --- market regime (for daily TF) ---
    regime_result = None
    if SETTINGS.FEATURE_MARKET_REGIME:
        from market_regime import detect_regime
        regime_result = detect_regime(df)

    # --- divergence radar zones ---
    radar_zones = []
    try:
        from div_radar import scan_divergence_zones
        radar_zones = scan_divergence_zones(df, symbol=symbol, timeframe=timeframe)
    except Exception:
        pass

    # --- ADX trend filter ---
    cur_adx = float(adx_line.iloc[-1])
    if cur_adx < SETTINGS.ADX_TREND_MIN:
        return _build_result(
            'HOLD', 0, f'ADX {cur_adx:.1f} < {SETTINGS.ADX_TREND_MIN} (choppy)',
            close, mline, r, k, d, e9, e21, a, adx_line, bb_up, bb_lo,
            candle_summary, regime_result, radar_zones=radar_zones
        )

    # --- weighted scoring ---
    buy_score = 0.0; sell_score = 0.0; reasons = []; components = []

    # 1. Regular divergence (weight 1.5 * strength)
    if md_type == 'bullish':
        buy_score += 1.5 * md_str; reasons.append(f'MACD bull div ({md_str:.2f})')
        components.append({'name': 'macd_div', 'direction': 'bullish', 'weight': round(1.5 * md_str, 3)})
    if rd_type == 'bullish':
        buy_score += 1.5 * rd_str; reasons.append(f'RSI bull div ({rd_str:.2f})')
        components.append({'name': 'rsi_div', 'direction': 'bullish', 'weight': round(1.5 * rd_str, 3)})
    if md_type == 'bearish':
        sell_score += 1.5 * md_str; reasons.append(f'MACD bear div ({md_str:.2f})')
        components.append({'name': 'macd_div', 'direction': 'bearish', 'weight': round(1.5 * md_str, 3)})
    if rd_type == 'bearish':
        sell_score += 1.5 * rd_str; reasons.append(f'RSI bear div ({rd_str:.2f})')
        components.append({'name': 'rsi_div', 'direction': 'bearish', 'weight': round(1.5 * rd_str, 3)})

    # 2. Hidden divergence (weight 1.0 * strength) — trend continuation
    if SETTINGS.FEATURE_HIDDEN_DIVERGENCE:
        if hid_md_type == 'hidden_bullish':
            buy_score += 1.0 * hid_md_str; reasons.append(f'MACD hidden bull ({hid_md_str:.2f})')
            components.append({'name': 'hidden_macd_div', 'direction': 'bullish', 'weight': round(1.0 * hid_md_str, 3)})
        if hid_rd_type == 'hidden_bullish':
            buy_score += 1.0 * hid_rd_str; reasons.append(f'RSI hidden bull ({hid_rd_str:.2f})')
            components.append({'name': 'hidden_rsi_div', 'direction': 'bullish', 'weight': round(1.0 * hid_rd_str, 3)})
        if hid_md_type == 'hidden_bearish':
            sell_score += 1.0 * hid_md_str; reasons.append(f'MACD hidden bear ({hid_md_str:.2f})')
            components.append({'name': 'hidden_macd_div', 'direction': 'bearish', 'weight': round(1.0 * hid_md_str, 3)})
        if hid_rd_type == 'hidden_bearish':
            sell_score += 1.0 * hid_rd_str; reasons.append(f'RSI hidden bear ({hid_rd_str:.2f})')
            components.append({'name': 'hidden_rsi_div', 'direction': 'bearish', 'weight': round(1.0 * hid_rd_str, 3)})

    # 3. EMA trend (weight 1.0)
    up = e9.iloc[-1] > e21.iloc[-1]
    if up:
        buy_score += 1.0; reasons.append('EMA9>EMA21')
        components.append({'name': 'ema_trend', 'direction': 'bullish', 'weight': 1.0})
    else:
        sell_score += 1.0; reasons.append('EMA9<EMA21')
        components.append({'name': 'ema_trend', 'direction': 'bearish', 'weight': 1.0})

    # 4. Stochastic (weight 0.75)
    st_k, st_d = float(k.iloc[-1]), float(d.iloc[-1])
    if st_k > st_d and st_k < 80:
        buy_score += 0.75; reasons.append('Stoch bullish')
        components.append({'name': 'stochastic', 'direction': 'bullish', 'weight': 0.75})
    elif st_k < st_d and st_k > 20:
        sell_score += 0.75; reasons.append('Stoch bearish')
        components.append({'name': 'stochastic', 'direction': 'bearish', 'weight': 0.75})

    # 5. Volume (weight 0.5)
    vol_ok = float(vol.iloc[-1]) > float(vma.iloc[-1])
    if vol_ok:
        buy_score += 0.5; sell_score += 0.5; reasons.append('Vol > MA20')
        components.append({'name': 'volume', 'direction': 'neutral', 'weight': 0.5})

    # 6. Bollinger position (weight 0.5)
    bb_pos = _bb_pos(close.iloc[-1], bb_up.iloc[-1], bb_lo.iloc[-1])
    if bb_pos < 0.2:
        buy_score += 0.5; reasons.append(f'Near BB lower ({bb_pos:.2f})')
        components.append({'name': 'bollinger', 'direction': 'bullish', 'weight': 0.5})
    elif bb_pos > 0.8:
        sell_score += 0.5; reasons.append(f'Near BB upper ({bb_pos:.2f})')
        components.append({'name': 'bollinger', 'direction': 'bearish', 'weight': 0.5})

    # 7. MACD histogram momentum (weight 0.5)
    h_cur, h_prev = float(mhist.iloc[-1]), float(mhist.iloc[-2])
    if h_cur > h_prev and h_cur > 0:
        buy_score += 0.5; reasons.append('MACD hist rising')
        components.append({'name': 'macd_hist', 'direction': 'bullish', 'weight': 0.5})
    elif h_cur < h_prev and h_cur < 0:
        sell_score += 0.5; reasons.append('MACD hist falling')
        components.append({'name': 'macd_hist', 'direction': 'bearish', 'weight': 0.5})

    # 8. Candle confirmation (weight 0.75) — feature flag
    if SETTINGS.FEATURE_CANDLE_PATTERNS and candle_summary:
        net = candle_summary.get('net_score', 0)
        if net > 0:
            buy_score += min(0.75, net * 0.5); reasons.append(f'Candle bullish ({net:.2f})')
            components.append({'name': 'candles', 'direction': 'bullish', 'weight': round(min(0.75, net * 0.5), 3)})
        elif net < 0:
            sell_score += min(0.75, abs(net) * 0.5); reasons.append(f'Candle bearish ({net:.2f})')
            components.append({'name': 'candles', 'direction': 'bearish', 'weight': round(min(0.75, abs(net) * 0.5), 3)})

    # 9. Divergence radar zones (weight up to 2.0 for confirmed)
    if radar_zones:
        best_bull = [z for z in radar_zones if z.direction == 'bullish']
        best_bear = [z for z in radar_zones if z.direction == 'bearish']
        if best_bull:
            z = best_bull[0]
            w = z.probability * 2.0  # up to 2.0 for confirmed zones
            buy_score += w
            reasons.append(f'DivRadar bull [{z.stage}] p={z.probability:.0%}')
            components.append({'name': 'div_radar', 'direction': 'bullish', 'weight': round(w, 3), 'stage': z.stage})
        if best_bear:
            z = best_bear[0]
            w = z.probability * 2.0
            sell_score += w
            reasons.append(f'DivRadar bear [{z.stage}] p={z.probability:.0%}')
            components.append({'name': 'div_radar', 'direction': 'bearish', 'weight': round(w, 3), 'stage': z.stage})

    # 10. Ichimoku confirmation (weight 1.0) — feature flag
    ichimoku_result = None
    if SETTINGS.FEATURE_ICHIMOKU:
        try:
            from indicators import ichimoku
            tenkan, kijun, senkou_a, senkou_b, chikou = ichimoku(high, low, close)
            cur_close = float(close.iloc[-1])
            cur_tenkan = float(tenkan.iloc[-1]) if not pd.isna(tenkan.iloc[-1]) else 0
            cur_kijun = float(kijun.iloc[-1]) if not pd.isna(kijun.iloc[-1]) else 0
            cur_senkou_a = float(senkou_a.iloc[-1]) if not pd.isna(senkou_a.iloc[-1]) else 0
            cur_senkou_b = float(senkou_b.iloc[-1]) if not pd.isna(senkou_b.iloc[-1]) else 0

            cloud_top = max(cur_senkou_a, cur_senkou_b)
            cloud_bottom = min(cur_senkou_a, cur_senkou_b)
            tk_bull = cur_tenkan > cur_kijun
            above_cloud = cur_close > cloud_top
            below_cloud = cur_close < cloud_bottom

            ichimoku_result = {
                'tenkan': round(cur_tenkan, 4), 'kijun': round(cur_kijun, 4),
                'senkou_a': round(cur_senkou_a, 4), 'senkou_b': round(cur_senkou_b, 4),
                'above_cloud': above_cloud, 'below_cloud': below_cloud,
                'tk_bullish': tk_bull,
            }

            if tk_bull and above_cloud:
                buy_score += 1.0; reasons.append('Ichimoku bullish (TK cross + above cloud)')
                components.append({'name': 'ichimoku', 'direction': 'bullish', 'weight': 1.0})
            elif not tk_bull and below_cloud:
                sell_score += 1.0; reasons.append('Ichimoku bearish (TK cross + below cloud)')
                components.append({'name': 'ichimoku', 'direction': 'bearish', 'weight': 1.0})
        except Exception:
            pass

    # --- direction decision (threshold 1.5) ---
    direction = 'HOLD'
    score = buy_score - sell_score
    if buy_score >= 1.5 and buy_score > sell_score: direction = 'BUY'
    elif sell_score >= 1.5 and sell_score > buy_score: direction = 'SELL'

    # --- Strong divergence trigger (only overrides HOLD, never flips direction) ---
    # A high-strength regular divergence with candle confirmation is itself
    # a valid setup even if total score is below the 1.5 threshold.
    if direction == 'HOLD':
        DIV_TRIGGER_STR = 0.65  # clear divergence threshold
        strong_bull_div = (md_type == 'bullish' and md_str >= DIV_TRIGGER_STR) or \
                          (rd_type == 'bullish' and rd_str >= DIV_TRIGGER_STR)
        strong_bear_div = (md_type == 'bearish' and md_str >= DIV_TRIGGER_STR) or \
                          (rd_type == 'bearish' and rd_str >= DIV_TRIGGER_STR)

        candle_bull = bool(candle_summary and candle_summary.get('net_score', 0) > 0.2)
        candle_bear = bool(candle_summary and candle_summary.get('net_score', 0) < -0.2)

        if strong_bull_div and candle_bull and sell_score < 1.5:
            direction = 'BUY'
            score = max(score, 1.5)
            reasons.append('TRIGGER: strong bull divergence + candle confirm')
        elif strong_bear_div and candle_bear and buy_score < 1.5:
            direction = 'SELL'
            score = min(score, -1.5)
            reasons.append('TRIGGER: strong bear divergence + candle confirm')

    return _build_result(
        direction, score, ', '.join(reasons),
        close, mline, r, k, d, e9, e21, a, adx_line, bb_up, bb_lo,
        candle_summary, regime_result, components, radar_zones=radar_zones,
        ichimoku_result=ichimoku_result
    )


def _bb_pos(price, upper, lower):
    span = float(upper) - float(lower)
    if span <= 0: return 0.5
    return max(0.0, min(1.0, (float(price) - float(lower)) / span))


def _build_result(direction, score, reasons, close, mline, r, k, d, e9, e21, a, adx_line, bb_up, bb_lo,
                  candle_summary=None, regime_result=None, components=None, radar_zones=None,
                  ichimoku_result=None):
    snapshot = {
        'macd': float(mline.iloc[-1]), 'rsi': float(r.iloc[-1]),
        'stoch_k': float(k.iloc[-1]), 'stoch_d': float(d.iloc[-1]),
        'ema9_gt_ema21': bool(e9.iloc[-1] > e21.iloc[-1]),
        'adx': float(adx_line.iloc[-1]), 'atr': float(a.iloc[-1]),
        'bb_position': _bb_pos(close.iloc[-1], bb_up.iloc[-1], bb_lo.iloc[-1]),
    }
    if candle_summary:
        snapshot['candles'] = candle_summary
    if regime_result:
        snapshot['regime'] = regime_result.to_dict()
    if radar_zones:
        snapshot['div_radar'] = [z.to_dict() for z in radar_zones[:5]]
    if ichimoku_result:
        snapshot['ichimoku'] = ichimoku_result

    result = {
        'direction': direction, 'score': score,
        'reasons': reasons, 'snapshot': snapshot,
    }
    if components:
        result['components'] = components
    return result


def merge_mtf(signals: dict) -> dict:
    w = {'30m': 1.0, '1h': 1.5, '4h': 2.0}
    regime = signals.get('1d', {}).get('direction', 'HOLD')

    # Use market regime if available
    regime_detail = None
    daily_snap = signals.get('1d', {}).get('snapshot', {})
    if daily_snap.get('regime'):
        regime_detail = daily_snap['regime']
        r = regime_detail.get('regime', '')
        if r == 'trending_up': regime = 'BUY'
        elif r == 'trending_down': regime = 'SELL'
        else: regime = 'HOLD'

    wsum = 0; s = 0
    for tf, sig in signals.items():
        if tf == '1d': continue
        v = 1 if sig.get('direction') == 'BUY' else -1 if sig.get('direction') == 'SELL' else 0
        s += v * w.get(tf, 1.0); wsum += w.get(tf, 1.0)
    m = s / wsum if wsum else 0.0
    md = 'HOLD'
    if m > 0.4: md = 'BUY'
    if m < -0.4: md = 'SELL'
    if regime == 'SELL' and md == 'BUY': md = 'HOLD'
    if regime == 'BUY' and md == 'SELL': md = 'HOLD'

    result = {'merged_direction': md, 'merged_score': m, 'regime': regime}
    if regime_detail:
        result['regime_detail'] = regime_detail
    return result


def build_score_breakdown(signals: dict, merged: dict) -> dict:
    """Structured explainable breakdown for Telegram and AI input."""
    by_tf = {}
    for tf, sig in signals.items():
        by_tf[tf] = {
            'direction': sig.get('direction'),
            'score': sig.get('score'),
            'reasons': sig.get('reasons'),
            'components': sig.get('components', []),
        }

    return {
        'by_timeframe': by_tf,
        'regime': merged.get('regime'),
        'regime_detail': merged.get('regime_detail'),
        'merged': {
            'direction': merged.get('merged_direction'),
            'score': merged.get('merged_score'),
        },
    }
