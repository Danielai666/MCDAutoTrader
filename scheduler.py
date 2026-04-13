import time
import json
from typing import Dict
from config import SETTINGS
from exchange import fetch_ohlcv, market_price
from strategy import tf_signal, merge_mtf, build_score_breakdown
from ai_decider import decide_async
from risk import can_enter, can_enter_enhanced, position_size, atr_stop_loss
from trade_executor import open_trade, close_all_for_pair, set_manual_guard
from storage import execute, fetchall
from telegram.ext import Application

async def _compute_signals(pair: str = None) -> Dict:
    pair = pair or SETTINGS.PAIR
    sigs = {}
    for tf in SETTINGS.TIMEFRAMES:
        df = fetch_ohlcv(pair, tf, SETTINGS.CANDLE_LIMIT)
        sigs[tf] = tf_signal(df)
    merged = merge_mtf(sigs)
    breakdown = build_score_breakdown(sigs, merged)
    return {'pair': pair, 'by_tf': sigs, 'merged': merged, 'breakdown': breakdown}

def _format(features: Dict, dec: Dict) -> str:
    m = features['merged']
    pair = features['pair']

    # Extract ADX/ATR from 1h snapshot
    snap_1h = features.get('by_tf', {}).get('1h', {}).get('snapshot', {})
    adx_txt = f"ADX: {snap_1h.get('adx', 0):.1f}" if snap_1h.get('adx') else ""
    atr_txt = f"ATR: {snap_1h.get('atr', 0):.4f}" if snap_1h.get('atr') else ""

    # Regime info
    regime_str = m.get('regime', '?')
    regime_detail = m.get('regime_detail')
    if regime_detail:
        regime_str = f"{regime_detail.get('regime', '?')} ({regime_detail.get('confidence', 0):.0%})"

    lines = [
        f"Pair: {pair}",
        f"Regime: {regime_str}",
        f"Merged: {m.get('merged_direction')} (score {m.get('merged_score', 0):.2f})",
        f"AI: {dec['decision']} (conf {dec['confidence']:.2f})",
    ]

    # Fusion details
    fusion = dec.get('fusion')
    if fusion and fusion.get('policy_used') != 'local_only':
        lines.append(f"Fusion: {fusion.get('consensus_notes', '')}")

    if adx_txt or atr_txt:
        lines.append(f"{adx_txt}  {atr_txt}".strip())

    # Notes
    if dec.get('notes'):
        lines.append(f"Notes: {dec['notes']}")

    return "\n".join(lines) + "\n"

async def run_cycle_once(app: Application, notify: bool = True, pair: str = None) -> str:
    features = await _compute_signals(pair)
    dec = await decide_async(features)
    txt = _format(features, dec)

    pair_name = features['pair']

    if dec['decision'] == 'ENTER':
        allowed, block_reason = can_enter_enhanced(pair_name, dec.get('side', 'BUY'))
        if allowed:
            px = market_price(pair_name)
            atr_val = features.get('by_tf', {}).get('1h', {}).get('snapshot', {}).get('atr', 0)
            qty = position_size(px, atr_val) if atr_val > 0 else 0.1
            sl = atr_stop_loss(px, atr_val) if atr_val > 0 else None

            # Build entry snapshot
            entry_snapshot = json.dumps({
                'merged': features.get('merged', {}),
                'confidence': dec['confidence'],
                'fusion_policy': dec.get('fusion', {}).get('policy_used', 'local'),
            })

            open_trade(pair_name, 'BUY', qty, px,
                       reason=f"AI ENTER conf={dec['confidence']:.2f}",
                       entry_snapshot=entry_snapshot)
            execute(
                'INSERT INTO signals(ts,pair,tf,direction,reason) VALUES(?,?,?,?,?)',
                (int(time.time()), pair_name, 'MTF', 'BUY', 'AI ENTER')
            )

            # Auto-set SL guard
            if sl is not None:
                admin_id = (SETTINGS.TELEGRAM_ADMIN_IDS or [None])[0] if SETTINGS.TELEGRAM_ADMIN_IDS else None
                if admin_id:
                    set_manual_guard(admin_id, pair_name, sl=sl)

            mode_txt = 'DRY RUN' if SETTINGS.DRY_RUN_MODE else ('PAPER' if SETTINGS.PAPER_TRADING else 'LIVE')
            txt += f"Order: BUY {qty:.6f} @ {px:.2f} (SL={sl:.2f if sl else 'none'}, {mode_txt}).\n"
        else:
            txt += f'Blocked: {block_reason}\n'
    elif dec['decision'] == 'EXIT':
        if SETTINGS.ENABLE_EXIT_AUTOMATION:
            c = close_all_for_pair(pair_name, 'AI_EXIT')
            execute(
                'INSERT INTO signals(ts,pair,tf,direction,reason) VALUES(?,?,?,?,?)',
                (int(time.time()), pair_name, 'MTF', 'SELL', 'AI EXIT')
            )
            txt += f'Auto-Exit: closed {c} trade(s).\n'
        else:
            txt += 'Exit suggested. Use /sellnow (auto-exit disabled).\n'
    else:
        txt += 'Decision: HOLD.\n'

    if notify:
        users = fetchall('SELECT user_id FROM users')
        for (uid,) in users:
            try:
                await app.bot.send_message(chat_id=uid, text=txt)
            except Exception:
                pass
    return txt

def schedule_jobs(app: Application):
    jq = app.job_queue

    async def analysis_job(ctx):
        try:
            await run_cycle_once(app, notify=True)
        except Exception as e:
            for aid in SETTINGS.TELEGRAM_ADMIN_IDS:
                try:
                    await app.bot.send_message(chat_id=aid, text=f'Scheduler error: {e}')
                except Exception:
                    pass

    jq.run_repeating(analysis_job, interval=SETTINGS.ANALYSIS_INTERVAL_SECONDS, first=5, name="analysis_cycle")
