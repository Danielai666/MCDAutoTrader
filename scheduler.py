import time
import json
import logging
from typing import Dict, List
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

# Per-user execution locks (prevent concurrent execution for same user)
import asyncio
_user_locks: dict = {}

def _get_user_lock(uid: int) -> asyncio.Lock:
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]

async def _with_lock(name: str, coro):
    if name in _running_jobs:
        log.info("Job '%s' already running, skipping", name)
        return None
    _running_jobs.add(name)
    try:
        return await coro
    finally:
        _running_jobs.discard(name)


def _get_autotrade_user_ids() -> List[int]:
    """Return list of user_ids with autotrade_enabled=1."""
    rows = fetchall("SELECT user_id FROM users WHERE autotrade_enabled=1")
    return [int(r[0]) for r in rows] if rows else []


def _is_autotrade_enabled() -> bool:
    """Backward compat: True if any user has autotrade on."""
    return len(_get_autotrade_user_ids()) > 0


def _record_user_signal(uid: int, user_results: list) -> None:
    """
    Populate the control-panel header's `Last Signal` line.

    Picks the most salient result for this user's watchlist:
      1. Highest-conviction ENTER/EXIT (conf × |merged_score|)
      2. Otherwise, strongest non-HOLD merged signal by |merged_score|
    Best-effort: never raises, never blocks the cycle.
    """
    try:
        import panel as _panel
    except Exception:
        return
    if not user_results:
        return
    try:
        actionable = [r for r in user_results
                      if r.get('decision', {}).get('decision') in ('ENTER', 'EXIT')]
        if actionable:
            actionable.sort(
                key=lambda r: r['decision'].get('confidence', 0) * abs(
                    r.get('features', {}).get('merged', {}).get('merged_score', 0)),
                reverse=True,
            )
            best = actionable[0]
            dec = best['decision']
            if dec.get('decision') == 'EXIT':
                direction = 'EXIT'
            else:
                direction = dec.get('side', 'BUY')
            score = best.get('features', {}).get('merged', {}).get('merged_score', 0)
            conf = dec.get('confidence', 0)
        else:
            ranked = sorted(
                user_results,
                key=lambda r: abs(r.get('features', {}).get('merged', {}).get('merged_score', 0)),
                reverse=True,
            )
            best = ranked[0]
            merged = best.get('features', {}).get('merged', {})
            direction = merged.get('merged_direction', 'HOLD')
            score = merged.get('merged_score', 0)
            conf = best.get('decision', {}).get('confidence', 0)
        _panel.track_last_signal(uid, direction, float(score or 0.0), float(conf or 0.0))
    except Exception:
        pass


async def _compute_signals(pair: str = None) -> Dict:
    pair = pair or SETTINGS.PAIR
    sigs = {}
    for tf in SETTINGS.TIMEFRAMES:
        try:
            df = fetch_ohlcv(pair, tf, SETTINGS.CANDLE_LIMIT)
            if df is None or df.empty:
                log.warning("Empty OHLCV for %s %s, skipping timeframe", pair, tf)
                continue
            sigs[tf] = tf_signal(df, symbol=pair, timeframe=tf)
        except Exception as e:
            log.warning("Signal computation failed for %s %s: %s", pair, tf, e)
            continue
    if not sigs:
        return {'pair': pair, 'by_tf': {}, 'merged': {'merged_direction': 'HOLD', 'merged_score': 0, 'regime': 'HOLD'}, 'breakdown': {}}
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


async def _analyze_pair(app: Application, pair: str, user_id: int = None) -> dict:
    """Analyze a single pair. Returns structured result."""
    features = await _compute_signals(pair)
    dec = await decide_async(features)
    txt = _format(features, dec)

    # Update pair signal in watchlist
    try:
        from pair_manager import update_pair_signal
        merged = features.get('merged', {})
        update_pair_signal(pair, merged.get('merged_direction', 'HOLD'),
                          merged.get('merged_score', 0), user_id)
    except Exception:
        pass

    return {'pair': pair, 'features': features, 'decision': dec, 'text': txt}


# -------------------------------------------------------------------
# Per-user autonomous execution engine
# -------------------------------------------------------------------
async def _execute_autonomous_cycle_for_user(app: Application, ctx, pair_results: list) -> list:
    """Execute trades for a single user based on shared market analysis."""
    action_log = []
    uid = ctx.user_id
    cycle_ts = int(time.time())

    # Control-panel header hook — runs before mode gates so every user
    # whose cycle fires gets `Last Signal` populated, regardless of ai_mode.
    _record_user_signal(uid, pair_results)

    # Mode gating
    if getattr(ctx, 'panic_stopped', False):
        return [f"PANIC STOP active for user {uid}, skipping."]

    mode = getattr(ctx, 'mode', 'signal_only')
    ai_mode = getattr(ctx, 'ai_mode', 'signal_only')

    if mode == 'signal_only':
        return [f"Signal-only mode, no execution."]

    if ai_mode == 'manual_confirm':
        # Queue signals for user confirmation instead of auto-executing
        for r in pair_results:
            dec = r['decision']
            if dec.get('decision') in ('ENTER', 'EXIT'):
                pair_name = r['pair']
                side = dec.get('side', 'BUY')
                conf = dec.get('confidence', 0)
                action_log.append(f"PENDING CONFIRM: {side} {pair_name} (conf={conf:.0%})")
                try:
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"Execute {side} {pair_name}", callback_data=f"confirm_trade_{pair_name}_{side}"),
                         InlineKeyboardButton("Skip", callback_data="confirm_skip")]
                    ])
                    await app.bot.send_message(
                        chat_id=uid,
                        text=f"Trade candidate: {side} {pair_name}\nConfidence: {conf:.0%}\nScore: {r['features'].get('merged', {}).get('merged_score', 0):.2f}",
                        reply_markup=kb)
                except Exception:
                    pass
        return action_log

    # ai_mode == 'ai_full': proceed with autonomous execution

    # Cache equity/drawdown once per user per cycle
    try:
        _cached_equity = get_equity_status(ctx)
        _cached_dd_scale = drawdown_position_scale(ctx)
    except Exception:
        _cached_equity = None
        _cached_dd_scale = 1.0

    # 1. Process EXITs first (free up capital/slots)
    for r in pair_results:
        dec = r['decision']
        if dec.get('decision') == 'EXIT' and SETTINGS.ENABLE_EXIT_AUTOMATION:
            result = execute_autonomous_exit(r['pair'], f'AI_EXIT_u{uid}', ctx=ctx)
            if result['closed_count'] > 0:
                msg = f"EXIT {r['pair']}: closed {result['closed_count']} (PnL: ${result['total_pnl']:.2f}, {result['mode']})"
                action_log.append(msg)
                execute('INSERT INTO signals(ts,pair,tf,direction,reason,user_id) VALUES(?,?,?,?,?,?)',
                        (int(time.time()), r['pair'], 'MTF', 'SELL', 'AUTO EXIT', uid))

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

        # Risk gate (per-user via ctx)
        allowed, block_reason = can_enter_enhanced(pair_name, side, ctx=ctx)
        if not allowed:
            action_log.append(f"BLOCKED {pair_name}: {block_reason}")
            continue

        # Portfolio exposure check (per-user via ctx)
        can_trade, current_exp, remaining_usd = portfolio_exposure_check(ctx)
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

        # Confidence-scaled position size (per-user via ctx + cached dd_scale)
        qty = confidence_scaled_position_size(px, atr_val, dec['confidence'], setup_quality,
                                              remaining_usd, dd_scale=_cached_dd_scale, ctx=ctx)
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

        # EXECUTE THE TRADE (per-user via ctx, with operation_id for idempotency)
        op_id = f"{uid}:{pair_name}:{side}:{cycle_ts}"
        result = execute_autonomous_trade(
            pair_name, side, qty, px, sl, tp,
            reason=f"AUTO conf={dec['confidence']:.2f} q={setup_quality:.2f}",
            entry_snapshot=entry_snapshot,
            ctx=ctx,
            operation_id=op_id
        )

        if result['success']:
            trades_opened += 1
            msg = (f"TRADE {result['mode']}: {side} {qty:.6f} {pair_name} @ ${px:.2f}\n"
                   f"  SL=${sl:.2f} TP=${tp:.2f} | conf={dec['confidence']:.2f} quality={setup_quality:.2f}")
            action_log.append(msg)
            execute('INSERT INTO signals(ts,pair,tf,direction,reason,user_id) VALUES(?,?,?,?,?,?)',
                    (int(time.time()), pair_name, 'MTF', side, f'AUTO ENTER conf={dec["confidence"]:.2f}', uid))
        else:
            action_log.append(f"FAILED {pair_name}: {result.get('error', 'unknown')}")

    return action_log


# -------------------------------------------------------------------
# Main cycle — two-phase: shared analysis + per-user execution
# -------------------------------------------------------------------
async def run_cycle_once(app: Application, notify: bool = True,
                         pair: str = None, user_id: int = None) -> str:
    """Run analysis. If user_id given, scope to that user. Otherwise multi-user cycle."""

    # Single pair request (manual /signal) — analyze only, no execution
    if pair:
        result = await _analyze_pair(app, pair, user_id)
        txt = result['text'] + "Decision: " + result['decision'].get('decision', 'HOLD') + ".\n"
        return txt

    # === PHASE 1: Shared market analysis ===
    # Get union of all users' active pairs (market data is shared)
    from pair_manager import get_active_pairs, get_all_active_pairs_union
    all_pairs = get_all_active_pairs_union()

    # Analyze each pair once (shared across users)
    market_data = {}
    for p in all_pairs:
        try:
            r = await _analyze_pair(app, p)
            market_data[p] = r
        except Exception as e:
            market_data[p] = {'pair': p, 'text': f"Error on {p}: {e}\n",
                              'decision': {'decision': 'HOLD', 'confidence': 0}, 'features': {}}
            log.exception("Analysis failed for %s", p)

    # Signal summary (shared)
    signal_summary = "\n---\n".join(r['text'] for r in market_data.values())

    # === PHASE 2: Per-user execution ===
    autotrade_uids = _get_autotrade_user_ids()
    combined_parts = [signal_summary]

    if autotrade_uids:
        from user_context import UserContext

        for uid in autotrade_uids:
            # Per-user lock prevents concurrent execution for same user
            lock = _get_user_lock(uid)
            if lock.locked():
                log.info("User %d execution still running, skipping this cycle", uid)
                continue

            try:
                async with lock:
                    ctx = UserContext.load(uid)
                    user_pairs = get_active_pairs(uid)
                    user_results = [market_data[p] for p in user_pairs if p in market_data]

                    if not user_results:
                        continue

                    action_log = await _execute_autonomous_cycle_for_user(app, ctx, user_results)
                    actions_txt = "\n".join(action_log) if action_log else "No actions."

                    # Per-user equity status
                    try:
                        eq = get_equity_status(ctx)
                        dd_scale = drawdown_position_scale(ctx)
                        eq_line = (f"Equity: ${eq['equity']:,.2f} | DD: {eq['drawdown_pct']:.1%} | "
                                   f"Size scale: {dd_scale:.0%}")
                    except Exception:
                        eq_line = ""

                    user_section = f"\n=== User {uid} Actions ===\n{actions_txt}"
                    if eq_line:
                        user_section += f"\n{eq_line}"
                    combined_parts.append(user_section)

                    # Notify this user specifically
                    if notify:
                        user_msg = f"{signal_summary}\n{user_section}"
                        try:
                            await app.bot.send_message(chat_id=uid, text=user_msg)
                        except Exception:
                            pass

            except Exception as e:
                log.exception("Autonomous cycle failed for user %d: %s", uid, e)
    else:
        combined_parts.append("\nAutoTrade: OFF (signal report only)")

    combined = "\n".join(combined_parts)

    # Notify users without autotrade (signal report only)
    if notify:
        non_auto_users = fetchall("SELECT user_id FROM users WHERE autotrade_enabled=0 OR autotrade_enabled IS NULL")
        for (uid,) in (non_auto_users or []):
            if uid not in autotrade_uids:
                # Populate this user's panel Last Signal from their watchlist slice.
                try:
                    user_pairs = get_active_pairs(uid)
                    user_results = [market_data[p] for p in user_pairs if p in market_data]
                    if user_results:
                        _record_user_signal(uid, user_results)
                except Exception:
                    pass
                try:
                    await app.bot.send_message(chat_id=uid, text=f"{signal_summary}\nAutoTrade: OFF")
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
    """Send per-user daily reports at each user's local 20:00."""
    try:
        from reports import daily_report, performance_summary
        from risk import get_equity_status
        from storage import get_user_settings
        from datetime import datetime

        try:
            import pytz
        except ImportError:
            pytz = None

        users = fetchall("SELECT user_id FROM users")
        now_utc = datetime.utcnow()

        for (uid,) in (users or []):
            try:
                # Check user timezone — only send if it's their report hour (20:00 local)
                tz_name = 'UTC'
                settings = get_user_settings(uid)
                if settings and settings.get('timezone'):
                    tz_name = settings['timezone']

                if pytz:
                    user_tz = pytz.timezone(tz_name)
                    user_now = datetime.now(pytz.utc).astimezone(user_tz)
                    if user_now.hour != 20:
                        continue
                # If pytz not available, send to everyone (fallback)

                # Try to send visual report card
                try:
                    perf = performance_summary(user_id=uid, days=30)
                    eq = get_equity_status()
                    total_pnl = perf.get('total_pnl', 0)
                    sign = '+' if total_pnl >= 0 else ''

                    summary = (
                        f"PnL: {sign}${total_pnl:.2f} | Win: {perf.get('win_rate', 0):.0f}%\n"
                        f"Trades: {perf.get('total_trades', 0)} | Equity: ${eq.get('equity', 0):,.2f}\n"
                        f"Max DD: {eq.get('max_drawdown_pct', 0):.1%}"
                    )

                    from visuals.cards import render_daily_report_card
                    png = render_daily_report_card(perf=perf, equity_status=eq)
                    import io
                    await app.bot.send_photo(chat_id=uid, photo=io.BytesIO(png), caption=f"Daily Report\n{summary}")
                except Exception:
                    # Fallback to text
                    report = daily_report(user_id=uid)
                    await app.bot.send_message(chat_id=uid, text=f"Daily Report\n{report}")
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
                import health_telemetry as ht
                _t0 = time.time()
                await run_cycle_once(app, notify=True)
                ht.record_cycle(int((time.time() - _t0) * 1000))
                ht.flush_to_db()
            except Exception as e:
                log.exception("Analysis cycle error: %s", e)
                try:
                    import health_telemetry as ht
                    ht.increment('scheduler_errors')
                except Exception:
                    pass
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

    jq.run_repeating(daily_job, interval=3600, first=3600, name="daily_report")  # hourly check, sends at user's local 20:00
    log.info("Scheduler jobs registered: analysis=%ds, health=%ds, daily=86400s",
             SETTINGS.ANALYSIS_INTERVAL_SECONDS, SETTINGS.HEALTH_CHECK_INTERVAL_SECONDS)
