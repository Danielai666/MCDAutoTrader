import time
import json
import logging
from typing import Dict
from config import SETTINGS
from exchange import fetch_ohlcv, market_price, health_check
from strategy import tf_signal, merge_mtf, build_score_breakdown
from ai_decider import decide_async
from risk import (can_enter_enhanced, position_size, atr_stop_loss, atr_take_profit,
                  portfolio_exposure_check, confidence_scaled_position_size,
                  should_skip_weak_setup, compute_atr_trailing_stop,
                  is_atr_trail_triggered, get_equity_status, drawdown_position_scale)
from trade_executor import (open_trade, close_all_for_pair, set_manual_guard,
                             execute_autonomous_trade, execute_autonomous_exit)
from storage import execute, fetchall, fetchone, upsert_bot_state
from telegram.ext import Application

log = logging.getLogger(__name__)

# Job locking
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


def _is_autotrade_enabled() -> bool:
    """Check if any admin has autotrade_enabled=1."""
    admin_ids = SETTINGS.TELEGRAM_ADMIN_IDS
    if not admin_ids:
        return False
    for aid in admin_ids:
        row = fetchone("SELECT autotrade_enabled FROM users WHERE user_id=?", (aid,))
        if row and row[0] and int(row[0]) == 1:
            return True
    return False


async def _compute_signals(pair: str = None) -> Dict:
    pair = pair or SETTINGS.PAIR
    sigs = {}
    for tf in SETTINGS.TIMEFRAMES:
        df = fetch_ohlcv(pair, tf, SETTINGS.CANDLE_LIMIT)
        sigs[tf] = tf_signal(df, symbol=pair, timeframe=tf)
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
    return "\n".join(lines) + "\n"


async def _analyze_pair(app: Application, pair: str) -> dict:
    """Analyze a single pair. Returns structured result."""
    features = await _compute_signals(pair)
    dec = await decide_async(features)
    txt = _format(features, dec)

    # Update pair signal in watchlist
    try:
        from pair_manager import update_pair_signal
        merged = features.get('merged', {})
        update_pair_signal(pair, merged.get('merged_direction', 'HOLD'), merged.get('merged_score', 0))
    except Exception:
        pass

    return {'pair': pair, 'features': features, 'decision': dec, 'text': txt}


# -------------------------------------------------------------------
# Autonomous execution engine
# -------------------------------------------------------------------
async def _execute_autonomous_cycle(app: Application, pair_results: list) -> list:
    """Process all analyzed pairs: exits first, then ranked entries. Returns action log."""
    action_log = []

    # 1. Process EXITs first (free up capital/slots)
    for r in pair_results:
        dec = r['decision']
        if dec.get('decision') == 'EXIT' and SETTINGS.ENABLE_EXIT_AUTOMATION:
            result = execute_autonomous_exit(r['pair'], 'AI_EXIT')
            if result['closed_count'] > 0:
                msg = f"EXIT {r['pair']}: closed {result['closed_count']} (PnL: ${result['total_pnl']:.2f}, {result['mode']})"
                action_log.append(msg)
                execute('INSERT INTO signals(ts,pair,tf,direction,reason) VALUES(?,?,?,?,?)',
                        (int(time.time()), r['pair'], 'MTF', 'SELL', 'AUTO EXIT'))

    # 2. Collect and rank ENTER candidates
    enter_candidates = [r for r in pair_results if r['decision'].get('decision') == 'ENTER']
    enter_candidates.sort(
        key=lambda r: r['decision'].get('confidence', 0) * abs(r['features'].get('merged', {}).get('merged_score', 0)),
        reverse=True
    )

    # 3. Execute top candidates
    trades_opened = 0
    for r in enter_candidates:
        if trades_opened >= SETTINGS.MAX_PAIRS_PER_CYCLE:
            break

        pair_name = r['pair']
        dec = r['decision']
        features = r['features']
        side = dec.get('side', 'BUY')
        fusion = dec.get('fusion', {})

        # Extract setup_quality and risk_flags from fusion
        all_decs = fusion.get('decisions', [])
        setup_quality = max((d.get('setup_quality', 0) for d in all_decs), default=0)
        risk_flags = [f for d in all_decs for f in d.get('risk_flags', [])]

        # Setup quality filter
        skip, skip_reason = should_skip_weak_setup(setup_quality, risk_flags, dec['confidence'])
        if skip:
            action_log.append(f"SKIP {pair_name}: {skip_reason}")
            continue

        # Risk gate
        allowed, block_reason = can_enter_enhanced(pair_name, side)
        if not allowed:
            action_log.append(f"BLOCKED {pair_name}: {block_reason}")
            continue

        # Portfolio exposure check
        can_trade, current_exp, remaining_usd = portfolio_exposure_check()
        if not can_trade:
            action_log.append(f"PORTFOLIO FULL (${current_exp:.0f}), stopping entries")
            break

        # Price and ATR
        try:
            px = market_price(pair_name)
        except Exception as e:
            action_log.append(f"ERROR {pair_name}: price fetch failed: {e}")
            continue

        atr_val = features.get('by_tf', {}).get('1h', {}).get('snapshot', {}).get('atr', 0)
        if atr_val <= 0 or px <= 0:
            continue

        # Confidence-scaled position size
        qty = confidence_scaled_position_size(px, atr_val, dec['confidence'], setup_quality, remaining_usd)
        if qty <= 0:
            action_log.append(f"SKIP {pair_name}: qty=0 after scaling")
            continue

        # SL and TP
        sl = atr_stop_loss(px, atr_val, side)
        tp = atr_take_profit(px, atr_val, side)

        # Entry snapshot (includes ATR for trailing stop calculations)
        entry_snapshot = json.dumps({
            'merged': features.get('merged', {}),
            'confidence': dec['confidence'],
            'setup_quality': setup_quality,
            'risk_flags': risk_flags,
            'fusion_policy': fusion.get('policy_used', 'local'),
            'atr_at_entry': atr_val,
        })

        # EXECUTE THE TRADE
        result = execute_autonomous_trade(
            pair_name, side, qty, px, sl, tp,
            reason=f"AUTO conf={dec['confidence']:.2f} q={setup_quality:.2f}",
            entry_snapshot=entry_snapshot
        )

        if result['success']:
            trades_opened += 1
            msg = (f"TRADE {result['mode']}: {side} {qty:.6f} {pair_name} @ ${px:.2f}\n"
                   f"  SL=${sl:.2f} TP=${tp:.2f} | conf={dec['confidence']:.2f} quality={setup_quality:.2f}")
            action_log.append(msg)
            execute('INSERT INTO signals(ts,pair,tf,direction,reason) VALUES(?,?,?,?,?)',
                    (int(time.time()), pair_name, 'MTF', side, f'AUTO ENTER conf={dec["confidence"]:.2f}'))
        else:
            action_log.append(f"FAILED {pair_name}: {result.get('error', 'unknown')}")

    return action_log


# -------------------------------------------------------------------
# Main cycle
# -------------------------------------------------------------------
async def run_cycle_once(app: Application, notify: bool = True, pair: str = None) -> str:
    """Run analysis for one or all active pairs. Execute trades if autotrade is ON."""

    # Single pair request (manual /signal) — analyze only, no autonomous execution
    if pair:
        result = await _analyze_pair(app, pair)
        txt = result['text'] + "Decision: " + result['decision'].get('decision', 'HOLD') + ".\n"
        return txt

    # Multi-pair cycle
    from pair_manager import get_active_pairs
    pairs = get_active_pairs()

    # Step 1: Analyze ALL pairs
    pair_results = []
    for p in pairs:
        try:
            r = await _analyze_pair(app, p)
            pair_results.append(r)
        except Exception as e:
            pair_results.append({'pair': p, 'text': f"Error on {p}: {e}\n",
                                 'decision': {'decision': 'HOLD', 'confidence': 0}, 'features': {}})
            log.exception("Analysis failed for %s", p)

    # Step 2: Signal summary
    signal_summary = "\n---\n".join(r['text'] for r in pair_results)

    # Step 3: Autonomous execution (only if autotrade enabled)
    action_log = []
    autotrade_on = _is_autotrade_enabled()

    if autotrade_on:
        action_log = await _execute_autonomous_cycle(app, pair_results)
        actions_txt = "\n".join(action_log) if action_log else "No actions — all HOLD."

        # Append equity/drawdown status
        try:
            eq = get_equity_status()
            dd_scale = drawdown_position_scale()
            eq_line = (f"Equity: ${eq['equity']:,.2f} | DD: {eq['drawdown_pct']:.1%} | "
                       f"Size scale: {dd_scale:.0%}")
        except Exception:
            eq_line = ""

        combined = f"{signal_summary}\n\n=== Autonomous Actions ===\n{actions_txt}"
        if eq_line:
            combined += f"\n\n{eq_line}"
    else:
        combined = f"{signal_summary}\nAutoTrade: OFF (signal report only)"

    # Step 4: Notify
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
    try:
        ex_ok, ex_msg = health_check()
        now = int(time.time())
        upsert_bot_state('health_exchange', 'OK' if ex_ok else ex_msg, now)
        upsert_bot_state('last_health_check', str(now), now)
        if not ex_ok:
            for aid in SETTINGS.TELEGRAM_ADMIN_IDS:
                try:
                    await app.bot.send_message(chat_id=aid, text=f"Health Warning: {ex_msg}")
                except Exception:
                    pass
    except Exception as e:
        log.warning("Health check failed: %s", e)


async def _daily_report_job(app: Application):
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
_jobs_scheduled = False

def schedule_jobs(app: Application):
    """Register scheduled jobs. Idempotent — safe to call multiple times."""
    global _jobs_scheduled
    if _jobs_scheduled:
        log.warning("schedule_jobs called again — skipping duplicate registration")
        return
    _jobs_scheduled = True

    jq = app.job_queue

    # Remove any existing jobs with same names (safety for restarts)
    for name in ["analysis_cycle", "health_check", "daily_report"]:
        existing = jq.get_jobs_by_name(name)
        for j in existing:
            j.schedule_removal()
            log.info("Removed stale job: %s", name)

    async def analysis_job(ctx):
        async def _run():
            try:
                await run_cycle_once(app, notify=True)
            except Exception as e:
                log.exception("Analysis cycle error: %s", e)
                for aid in SETTINGS.TELEGRAM_ADMIN_IDS:
                    try:
                        await app.bot.send_message(chat_id=aid, text=f'Scheduler error: {e}')
                    except Exception:
                        pass
        await _with_lock('analysis', _run())

    jq.run_repeating(analysis_job, interval=SETTINGS.ANALYSIS_INTERVAL_SECONDS,
                     first=10, name="analysis_cycle")

    async def health_job(ctx):
        await _with_lock('health', _health_check_job(app))

    jq.run_repeating(health_job, interval=SETTINGS.HEALTH_CHECK_INTERVAL_SECONDS,
                     first=60, name="health_check")

    async def daily_job(ctx):
        await _daily_report_job(app)

    jq.run_repeating(daily_job, interval=86400, first=3600, name="daily_report")
    log.info("Scheduler jobs registered: analysis=%ds, health=%ds, daily=86400s",
             SETTINGS.ANALYSIS_INTERVAL_SECONDS, SETTINGS.HEALTH_CHECK_INTERVAL_SECONDS)
