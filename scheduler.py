import time
import json
import logging
from typing import Dict
from config import SETTINGS
from exchange import fetch_ohlcv, market_price, health_check
from strategy import tf_signal, merge_mtf, build_score_breakdown
from ai_decider import decide_async
from risk import can_enter_enhanced, position_size, atr_stop_loss
from trade_executor import open_trade, close_all_for_pair, set_manual_guard
from storage import execute, fetchall, fetchone
from telegram.ext import Application

log = logging.getLogger(__name__)

# Job locking to prevent overlapping runs
_running_jobs = set()

async def _with_lock(name: str, coro):
    if name in _running_jobs:
        log.info("Job '%s' already running, skipping", name)
        return None
    _running_jobs.add(name)
    try:
        return await coro
    finally:
        _running_jobs.discard(name)


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
    snap_1h = features.get('by_tf', {}).get('1h', {}).get('snapshot', {})
    adx_txt = f"ADX: {snap_1h.get('adx', 0):.1f}" if snap_1h.get('adx') else ""
    atr_txt = f"ATR: {snap_1h.get('atr', 0):.4f}" if snap_1h.get('atr') else ""

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
    fusion = dec.get('fusion')
    if fusion and fusion.get('policy_used') != 'local_only':
        lines.append(f"Fusion: {fusion.get('consensus_notes', '')}")
    if adx_txt or atr_txt:
        lines.append(f"{adx_txt}  {atr_txt}".strip())
    if dec.get('notes'):
        lines.append(f"Notes: {dec['notes']}")
    return "\n".join(lines) + "\n"


async def _run_for_pair(app: Application, pair: str, notify: bool) -> str:
    """Run analysis + trade logic for a single pair."""
    features = await _compute_signals(pair)
    dec = await decide_async(features)
    txt = _format(features, dec)
    pair_name = features['pair']

    # Update pair signal in watchlist
    try:
        from pair_manager import update_pair_signal
        merged = features.get('merged', {})
        update_pair_signal(pair_name, merged.get('merged_direction', 'HOLD'), merged.get('merged_score', 0))
    except Exception:
        pass

    if dec['decision'] == 'ENTER':
        allowed, block_reason = can_enter_enhanced(pair_name, dec.get('side', 'BUY'))
        if allowed:
            px = market_price(pair_name)
            atr_val = features.get('by_tf', {}).get('1h', {}).get('snapshot', {}).get('atr', 0)
            qty = position_size(px, atr_val) if atr_val > 0 else 0.1
            sl = atr_stop_loss(px, atr_val) if atr_val > 0 else None

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
            txt += 'Exit suggested. Use /sellnow.\n'
    else:
        txt += 'Decision: HOLD.\n'

    return txt


async def run_cycle_once(app: Application, notify: bool = True, pair: str = None) -> str:
    """Run analysis for one or all active pairs."""
    if pair:
        pairs = [pair]
    else:
        from pair_manager import get_active_pairs
        pairs = get_active_pairs()

    results = []
    for p in pairs:
        try:
            txt = await _run_for_pair(app, p, notify)
            results.append(txt)
        except Exception as e:
            results.append(f"Error on {p}: {e}\n")
            log.exception("Analysis failed for %s", p)

    combined = "\n---\n".join(results) if len(results) > 1 else (results[0] if results else "No pairs to analyze.")

    if notify:
        users = fetchall('SELECT user_id FROM users')
        for (uid,) in users:
            try:
                await app.bot.send_message(chat_id=uid, text=combined)
            except Exception:
                pass
    return combined


# -------------------------------------------------------------------
# Health check job
# -------------------------------------------------------------------
async def _health_check_job(app: Application):
    """Periodic health check: exchange + DB."""
    try:
        ex_ok, ex_msg = health_check()
        # Store in bot_state
        execute(
            "INSERT INTO bot_state(key, value, updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            ('health_exchange', 'OK' if ex_ok else ex_msg, int(time.time()))
        )
        execute(
            "INSERT INTO bot_state(key, value, updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            ('last_health_check', str(int(time.time())), int(time.time()))
        )
        if not ex_ok:
            for aid in SETTINGS.TELEGRAM_ADMIN_IDS:
                try:
                    await app.bot.send_message(chat_id=aid, text=f"Health Warning: {ex_msg}")
                except Exception:
                    pass
    except Exception as e:
        log.warning("Health check failed: %s", e)


# -------------------------------------------------------------------
# Daily report job
# -------------------------------------------------------------------
async def _daily_report_job(app: Application):
    """Send daily performance summary to admins."""
    try:
        from reports import daily_report
        report = daily_report()
        for aid in SETTINGS.TELEGRAM_ADMIN_IDS:
            try:
                await app.bot.send_message(chat_id=aid, text=f"Daily Report\n{report}")
            except Exception:
                pass
    except Exception as e:
        log.warning("Daily report failed: %s", e)


# -------------------------------------------------------------------
# Schedule all jobs
# -------------------------------------------------------------------
def schedule_jobs(app: Application):
    jq = app.job_queue

    # Main analysis cycle
    async def analysis_job(ctx):
        async def _run():
            try:
                await run_cycle_once(app, notify=True)
            except Exception as e:
                for aid in SETTINGS.TELEGRAM_ADMIN_IDS:
                    try:
                        await app.bot.send_message(chat_id=aid, text=f'Scheduler error: {e}')
                    except Exception:
                        pass
        await _with_lock('analysis', _run())

    jq.run_repeating(analysis_job, interval=SETTINGS.ANALYSIS_INTERVAL_SECONDS, first=5, name="analysis_cycle")

    # Health check
    async def health_job(ctx):
        await _with_lock('health', _health_check_job(app))

    jq.run_repeating(health_job, interval=SETTINGS.HEALTH_CHECK_INTERVAL_SECONDS, first=60, name="health_check")

    # Daily report (every 24h, first run after 1h)
    async def daily_job(ctx):
        await _daily_report_job(app)

    jq.run_repeating(daily_job, interval=86400, first=3600, name="daily_report")
