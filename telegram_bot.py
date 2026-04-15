# telegram_bot.py
import logging, time, os
from typing import Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import SETTINGS
from storage import execute, fetchone, fetchall, upsert_bot_state, upsert_user
from trade_executor import close_all_for_pair, set_manual_guard, clear_manual_guard
from scheduler import schedule_jobs

log = logging.getLogger(__name__)

# ---------------------------
# Globals
# ---------------------------
PAIR_TXT = SETTINGS.PAIR
PAIR_DB  = PAIR_TXT.replace('/', '')


def _drawdown_bar(dd_pct: float) -> str:
    """Visual drawdown indicator."""
    if dd_pct < 0.05:
        return "[OK]"
    elif dd_pct < SETTINGS.DRAWDOWN_SCALE_THRESHOLD:
        return "[LOW]"
    elif dd_pct < SETTINGS.DRAWDOWN_HALT_THRESHOLD:
        return "[SCALING DOWN]"
    else:
        return "[HALTED]"

LAST_NOTIFY = {}
NOTIFY_COOLDOWN = 300

# ---------------------------
# Rate limiter
# ---------------------------
_rate_limits: dict = {}  # uid -> list of timestamps

def _check_rate_limit(uid: int, limit: int = 10, window: int = 60) -> bool:
    """Returns True if allowed, False if rate limited."""
    now = time.time()
    times = _rate_limits.setdefault(uid, [])
    times[:] = [t for t in times if now - t < window]
    if len(times) >= limit:
        return False
    times.append(now)
    return True

def rate_limited(func):
    """Decorator: applies per-user rate limiting to command handlers."""
    async def wrapper(update: Update, context):
        uid = update.effective_user.id
        if not _check_rate_limit(uid):
            await update.message.reply_text("Rate limit exceeded. Try again shortly.")
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper

# ---------------------------
# Connect exchange state machine
# ---------------------------
from dataclasses import dataclass, field as dc_field
from enum import Enum

class ConnectState(Enum):
    IDLE = "idle"
    SELECT_EXCHANGE = "select_exchange"
    ENTER_KEY = "enter_key"
    ENTER_SECRET = "enter_secret"
    VALIDATING = "validating"

@dataclass
class ConnectSession:
    state: ConnectState = ConnectState.IDLE
    exchange_id: str = ''
    api_key: str = ''
    api_secret: str = ''
    started_ts: float = 0.0
    msgs_to_delete: list = dc_field(default_factory=list)

_connect_sessions: dict = {}  # uid -> ConnectSession
_CONNECT_TTL = 300  # 5 minutes

SUPPORTED_EXCHANGES = [
    'kraken', 'binance', 'bybit', 'coinbasepro', 'kucoin',
    'okx', 'bitfinex', 'gate', 'mexc', 'htx',
]

def _get_connect_session(uid: int) -> ConnectSession:
    s = _connect_sessions.get(uid)
    if s and (time.time() - s.started_ts) > _CONNECT_TTL:
        _connect_sessions.pop(uid, None)
        return None
    return s

def _connect_exchange_keyboard():
    rows = []
    for i in range(0, len(SUPPORTED_EXCHANGES), 2):
        row = [InlineKeyboardButton(ex.upper(), callback_data=f"conn_ex_{ex}")
               for ex in SUPPORTED_EXCHANGES[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("Cancel", callback_data="conn_cancel")])
    return InlineKeyboardMarkup(rows)

# ---------------------------
# Inline Keyboard Menus
# ---------------------------
def main_menu_keyboard():
    # When the control panel is enabled we delegate to panel.build_panel_keyboard
    # which re-lays out the same callback_data into a modern grid. This keeps
    # every existing dispatch case in button_callback working unchanged.
    try:
        import panel as _panel
        if _panel.is_enabled():
            return _panel.build_panel_keyboard()
    except Exception:
        pass
    return _legacy_main_menu_keyboard()


def _legacy_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Signal", callback_data="cmd_signal"),
         InlineKeyboardButton("💰 Price", callback_data="cmd_price")],
        [InlineKeyboardButton("📈 Status", callback_data="cmd_status"),
         InlineKeyboardButton("🔥 Heatmap", callback_data="cmd_heatmap")],
        [InlineKeyboardButton("📍 Positions", callback_data="cmd_positions_card"),
         InlineKeyboardButton("⚠️ Risk Board", callback_data="cmd_risk_board")],
        [InlineKeyboardButton("🛡️ Guards", callback_data="cmd_guards"),
         InlineKeyboardButton("🔍 Check Guards", callback_data="cmd_checkguards")],
        [InlineKeyboardButton("🤖 AutoTrade ➤", callback_data="menu_autotrade"),
         InlineKeyboardButton("📋 Mode ➤", callback_data="menu_mode")],
        [InlineKeyboardButton("🎯 Risk ➤", callback_data="menu_risk"),
         InlineKeyboardButton("🛑 Sell Now", callback_data="cmd_sellnow")],
        [InlineKeyboardButton("📐 SL / TP / Trail ➤", callback_data="menu_guards_set")],
        [InlineKeyboardButton("❌ Cancel Guards ➤", callback_data="menu_cancel")],
        [InlineKeyboardButton("📊 Backtest", callback_data="cmd_backtest"),
         InlineKeyboardButton("🎨 Visuals", callback_data="cmd_visuals")],
        [InlineKeyboardButton("🧠 AI Card", callback_data="cmd_ai_card"),
         InlineKeyboardButton("⚙️ My Account", callback_data="cmd_myaccount")],
        [InlineKeyboardButton("📸 Analyze", callback_data="cmd_analyze_screens"),
         InlineKeyboardButton("🔗 Connect", callback_data="cmd_connect")],
        [InlineKeyboardButton("💚 Health", callback_data="cmd_health_stats"),
         InlineKeyboardButton("🚀 Go Live", callback_data="cmd_golive")],
        [InlineKeyboardButton("🆘 PANIC STOP", callback_data="cmd_panic_stop")],
        [InlineKeyboardButton("📊 Report ➤", callback_data="menu_reporting"),
         InlineKeyboardButton("🌐 Pairs ➤", callback_data="menu_pairs")],
        [InlineKeyboardButton("🔌 Disconnect", callback_data="cmd_disconnect"),
         InlineKeyboardButton("🔧 Admin ➤", callback_data="menu_admin")],
    ])

def reporting_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Positions", callback_data="cmd_positions"),
         InlineKeyboardButton("📈 PnL Report", callback_data="cmd_pnl")],
        [InlineKeyboardButton("📋 Recent Trades", callback_data="cmd_trades"),
         InlineKeyboardButton("🚫 Blocked", callback_data="cmd_blocked")],
        [InlineKeyboardButton("📊 Full Report", callback_data="cmd_report")],
        [InlineKeyboardButton("⬅️ Back", callback_data="cmd_menu")],
    ])

def pairs_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 List Pairs", callback_data="cmd_pairs"),
         InlineKeyboardButton("🏆 Ranking", callback_data="cmd_ranking")],
        [InlineKeyboardButton("➕ Add Pair", callback_data="prompt_addpair"),
         InlineKeyboardButton("➖ Remove Pair", callback_data="prompt_rmpair")],
        [InlineKeyboardButton("⬅️ Back", callback_data="cmd_menu")],
    ])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏥 Health", callback_data="cmd_health"),
         InlineKeyboardButton("🧠 AI Status", callback_data="cmd_ai")],
        [InlineKeyboardButton("🔴 Kill Switch", callback_data="cmd_killswitch")],
        [InlineKeyboardButton("🔍 Reconcile", callback_data="cmd_reconcile"),
         InlineKeyboardButton("🚀 Live Ready?", callback_data="cmd_liveready")],
        [InlineKeyboardButton("⬅️ Back", callback_data="cmd_menu")],
    ])

def autotrade_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ AutoTrade ON", callback_data="cmd_autotrade_on"),
         InlineKeyboardButton("⛔ AutoTrade OFF", callback_data="cmd_autotrade_off")],
        [InlineKeyboardButton("⬅️ Back", callback_data="cmd_menu")],
    ])

def mode_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Paper Mode", callback_data="cmd_mode_paper"),
         InlineKeyboardButton("🔴 Live Mode", callback_data="cmd_mode_live")],
        [InlineKeyboardButton("⬅️ Back", callback_data="cmd_menu")],
    ])

def risk_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("$25", callback_data="cmd_risk_25"),
         InlineKeyboardButton("$50", callback_data="cmd_risk_50"),
         InlineKeyboardButton("$100", callback_data="cmd_risk_100")],
        [InlineKeyboardButton("$200", callback_data="cmd_risk_200"),
         InlineKeyboardButton("$500", callback_data="cmd_risk_500")],
        [InlineKeyboardButton("⬅️ Back", callback_data="cmd_menu")],
    ])

def guards_set_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Set SL", callback_data="prompt_sl"),
         InlineKeyboardButton("🎯 Set TP", callback_data="prompt_tp")],
        [InlineKeyboardButton("📐 Set Trail %", callback_data="prompt_trail")],
        [InlineKeyboardButton("⬅️ Back", callback_data="cmd_menu")],
    ])

def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Cancel SL", callback_data="cmd_cancel_sl"),
         InlineKeyboardButton("Cancel TP", callback_data="cmd_cancel_tp")],
        [InlineKeyboardButton("Cancel Trail", callback_data="cmd_cancel_trail"),
         InlineKeyboardButton("Cancel ALL", callback_data="cmd_cancel_all")],
        [InlineKeyboardButton("⬅️ Back", callback_data="cmd_menu")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Menu", callback_data="cmd_menu")],
    ])

# ---------------------------
# Helpers & permissions
# ---------------------------
def admin_only(uid: int) -> bool:
    try:
        return uid in (SETTINGS.TELEGRAM_ADMIN_IDS or [])
    except Exception:
        return False

def _get_admin_id() -> Optional[int]:
    try:
        ids = SETTINGS.TELEGRAM_ADMIN_IDS or []
        return ids[0] if ids else None
    except Exception:
        return None

# ---------------------------
# Auto-Exit logic (built-in)
# ---------------------------
def _fetch_last_price(pair: str = None) -> Optional[float]:
    pair = pair or SETTINGS.PAIR
    try:
        from exchange import market_price
        return market_price(pair)
    except Exception as e:
        log.warning("auto-exit: fetch price failed for %s: %s", pair, e)
    return None

def _load_guard(uid: int, pair: str):
    row = fetchone(
        "SELECT stop_loss, take_profit, trail_pct, trail_stop, high_watermark "
        "FROM manual_guards WHERE user_id=? AND pair=?",
        (uid, pair),
    )
    if not row:
        return None
    sl, tp, trail_pct, trail_stop, high_wm = row
    return {"sl": sl, "tp": tp, "trail_pct": trail_pct, "trail_stop": trail_stop, "high_wm": high_wm}

def _save_trailing(uid: int, pair: str, trail_stop: Optional[float], high_wm: Optional[float]):
    execute(
        "UPDATE manual_guards SET trail_stop=?, high_watermark=? WHERE user_id=? AND pair=?",
        (trail_stop, high_wm, uid, pair),
    )

def _paper_close_all(pair: str, px: float, user_id: int = None) -> Tuple[int, float]:
    now = int(time.time())
    if user_id is not None:
        rows = fetchall("SELECT id, side, qty, entry FROM trades WHERE status='OPEN' AND pair=? AND user_id=?", (pair, user_id))
    else:
        rows = fetchall("SELECT id, side, qty, entry FROM trades WHERE status='OPEN' AND pair=?", (pair,))
    total_pnl = 0.0
    closed = 0
    for tid, side, qty, entry in rows:
        qty = float(qty); entry = float(entry)
        pnl = (px - entry) * qty if side == "BUY" else (entry - px) * qty
        execute(
            "UPDATE trades SET exit_price=?, pnl=?, status='CLOSED', ts_close=? WHERE id=?",
            (px, pnl, now, tid),
        )
        total_pnl += pnl
        closed += 1
    return closed, total_pnl

def _check_atr_trailing_stops(pair: str, price: float, user_id: int = None) -> Optional[str]:
    """
    Check ATR-based trailing stops for open trades on this pair (optionally per-user).
    Updates trail stops in DB and returns exit reason if triggered.
    """
    from risk import compute_atr_trailing_stop, is_atr_trail_triggered
    import json as _json

    if not SETTINGS.TRAILING_ENABLED:
        return None

    if user_id is not None:
        rows = fetchall(
            "SELECT id, side, entry, entry_snapshot FROM trades WHERE status='OPEN' AND pair=? AND user_id=?",
            (pair, user_id))
    else:
        rows = fetchall(
            "SELECT id, side, entry, entry_snapshot FROM trades WHERE status='OPEN' AND pair=?",
            (pair,))
    for tid, side, entry, snapshot_str in rows:
        entry = float(entry)
        # Get ATR from entry snapshot
        atr_val = 0.0
        if snapshot_str:
            try:
                snap = _json.loads(snapshot_str)
                atr_val = float(snap.get('atr_at_entry', 0))
            except Exception:
                pass
        if atr_val <= 0:
            continue

        # Get current trail stop from bot_state
        trail_key = f'atr_trail_{tid}'
        trail_row = fetchone("SELECT value FROM bot_state WHERE key=?", (trail_key,))
        current_trail = float(trail_row[0]) if trail_row and trail_row[0] else None

        # Compute new trailing stop
        result = compute_atr_trailing_stop(entry, price, atr_val, side, current_trail)

        if result['active'] and result['trail_stop'] is not None:
            # Persist updated trail stop
            upsert_bot_state(trail_key, str(result['trail_stop']), int(time.time()))

            # Check if triggered
            if is_atr_trail_triggered(price, result['trail_stop'], side):
                tighten_txt = " [tightened]" if result['tightened'] else ""
                return (f"ATR trail stop hit{tighten_txt}: "
                        f"stop={result['trail_stop']:g} px={price:g} "
                        f"(profit {result['profit_atr']:.1f}x ATR)")

            # Update trade lifecycle to 'trailing' if active
            try:
                from trade_executor import update_trade_lifecycle
                update_trade_lifecycle(tid, 'trailing')
            except Exception:
                pass

    return None


async def auto_exit_task(application) -> None:
    """Check guards for ALL users with open trades. Per-user isolation."""
    # Get all users who have open trades
    user_rows = fetchall("SELECT DISTINCT user_id FROM trades WHERE status='OPEN' AND user_id IS NOT NULL")
    if not user_rows:
        return

    for (uid,) in user_rows:
        # Get this user's open trade pairs
        pair_rows = fetchall("SELECT DISTINCT pair FROM trades WHERE status='OPEN' AND user_id=?", (uid,))
        for (pair,) in (pair_rows or []):
            try:
                await _check_pair_guards(application, uid, pair)
            except Exception as e:
                log.warning("auto-exit check failed for user %s pair %s: %s", uid, pair, e)


async def _check_pair_guards(application, admin_id: int, pair: str) -> None:
    """Check all guard types for a single pair."""
    price = _fetch_last_price(pair)
    if not price or price <= 0:
        return

    # --- Check manual guards (SL/TP/trail%) ---
    reason = None
    guard = _load_guard(admin_id, pair)
    if guard:
        sl = guard.get("sl")
        tp = guard.get("tp")

        # Determine trade direction for correct SL/TP comparison
        open_trades = fetchall("SELECT side FROM trades WHERE status='OPEN' AND pair=?", (pair,))
        is_long = any(r[0] == 'BUY' for r in open_trades) if open_trades else True

        if isinstance(sl, (int, float)):
            if is_long and price <= float(sl):
                reason = f"SL hit @ {float(sl):g} (px={price:g})"
            elif not is_long and price >= float(sl):
                reason = f"SL hit @ {float(sl):g} (px={price:g})"

        if not reason and isinstance(tp, (int, float)):
            if is_long and price >= float(tp):
                reason = f"TP hit @ {float(tp):g} (px={price:g})"
            elif not is_long and price <= float(tp):
                reason = f"TP hit @ {float(tp):g} (px={price:g})"

        trail_pct = guard.get("trail_pct")
        if not reason and isinstance(trail_pct, (int, float)) and float(trail_pct) > 0:
            high_wm = guard.get("high_wm")
            trail_stop = guard.get("trail_stop")
            updated = False
            if (high_wm is None) or (price > float(high_wm)):
                high_wm = float(price)
                trail_stop = float(high_wm) * (1.0 - float(trail_pct))
                _save_trailing(admin_id, pair, trail_stop, high_wm)
                updated = True
            if trail_stop is not None and price <= float(trail_stop):
                reason = f"TRAIL stop hit @ {float(trail_stop):g} (px={price:g})"
            elif updated:
                log.info("auto-exit: %s trail updated high=%.6f stop=%.6f", pair, high_wm, trail_stop or -1)

    # --- Check ATR-based trailing stops for this user's open trades ---
    if not reason:
        reason = _check_atr_trailing_stops(pair, price, user_id=admin_id)

    if not reason:
        return

    # Dedup notification
    key = (admin_id, pair, reason)
    now_ts = int(time.time())
    last_ts = LAST_NOTIFY.get(key, 0)
    if now_ts - last_ts < NOTIFY_COOLDOWN:
        return
    LAST_NOTIFY[key] = now_ts

    # Execute close (scoped to user)
    closed = 0
    total_pnl = None
    try:
        # Use user's trade mode if available
        from user_context import UserContext
        try:
            ctx = UserContext.load(admin_id)
            is_paper = ctx.paper_trading
        except Exception:
            is_paper = SETTINGS.PAPER_TRADING

        closed_ids = []
        if is_paper:
            closed, total_pnl = _paper_close_all(pair, price, user_id=admin_id)
        else:
            user_trades = fetchall("SELECT id FROM trades WHERE status='OPEN' AND pair=? AND user_id=?", (pair, admin_id))
            for (tid,) in (user_trades or []):
                from trade_executor import close_trade
                pnl = close_trade(tid, price, f"auto_exit: {reason}")
                total_pnl = (total_pnl or 0) + pnl
                closed += 1
                closed_ids.append(tid)
    except Exception as e:
        log.exception("auto-exit: closing failed for user %s pair %s: %s", admin_id, pair, e)

    # Notify
    try:
        lines = [
            "Auto-Exit Triggered",
            f"Pair: {pair}",
            f"Reason: {reason}",
            f"Price: {price:g}",
            f"Closed trades: {closed}",
        ]
        if total_pnl is not None:
            lines.append(f"PnL (paper): {total_pnl:.2f}")
        await application.bot.send_message(chat_id=admin_id, text="\n".join(lines))

        # Send per-trade close reports
        if closed_ids:
            from reports import format_trade_close_report
            for tid in closed_ids:
                try:
                    report = format_trade_close_report(tid)
                    if report:
                        await application.bot.send_message(chat_id=admin_id, text=report)
                except Exception:
                    pass
    except Exception as e:
        log.warning("auto-exit: notify failed for %s: %s", pair, e)

# ---------------------------
# Commands (also used by callbacks)
# ---------------------------
async def _do_signal(app, chat_id, message_id=None, uid=None):
    from scheduler import run_cycle_once, _compute_signals
    if message_id:
        try:
            await app.bot.edit_message_text("Running analysis...", chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    res = await run_cycle_once(app, notify=False, user_id=uid)

    # Try to render signal card
    try:
        pair = SETTINGS.PAIR
        features = await _compute_signals(pair)
        merged = features.get('merged', {})
        snap = features.get('by_tf', {}).get('1h', {}).get('snapshot', {})
        from exchange import fetch_ohlcv
        df = fetch_ohlcv(pair, '1h', 120)

        from risk import atr_stop_loss, atr_take_profit
        atr_val = snap.get('atr', 0)
        price = float(df['close'].iloc[-1]) if len(df) > 0 else 0
        side = merged.get('merged_direction', 'HOLD')

        if side in ('BUY', 'SELL') and atr_val > 0:
            sl = atr_stop_loss(price, atr_val, side)
            tp1 = atr_take_profit(price, atr_val, side)
            from ai_decider import decide_async
            dec = await decide_async(features)
            conf = dec.get('confidence', 0)

            from visuals.cards import render_signal_card
            png = render_signal_card(
                df, pair, '1h', entry=price, sl=sl, tp1=tp1,
                side=side, risk_pct=SETTINGS.RISK_PER_TRADE,
                confidence=conf, mode='Paper' if SETTINGS.PAPER_TRADING else 'Live',
                snapshot=snap, exchange=SETTINGS.EXCHANGE,
            )
            summary = (
                f"{pair} {side} @ {price:.2f}\n"
                f"SL: {sl:.2f} | TP: {tp1:.2f}\n"
                f"Confidence: {conf:.0%} | Score: {merged.get('merged_score', 0):.2f}\n"
                f"Decision: {dec.get('decision', 'HOLD')}"
            )
            import io
            await app.bot.send_photo(chat_id=chat_id, photo=io.BytesIO(png),
                                     caption=summary, reply_markup=back_keyboard())
            return
    except Exception as e:
        log.warning("Signal card render failed, falling back to text: %s", e)

    # Fallback to text
    if message_id:
        try:
            await app.bot.edit_message_text(res, chat_id=chat_id, message_id=message_id, reply_markup=back_keyboard())
        except Exception:
            await app.bot.send_message(chat_id=chat_id, text=res, reply_markup=back_keyboard())
    else:
        await app.bot.send_message(chat_id=chat_id, text=res, reply_markup=back_keyboard())

async def _do_price(app, chat_id):
    try:
        import ccxt
        ex = ccxt.kraken()
        t = ex.fetch_ticker(SETTINGS.PAIR)
        p = t.get("last") or t.get("close")
        await app.bot.send_message(chat_id=chat_id, text=f"💰 {SETTINGS.PAIR}: ${float(p):,.2f}", reply_markup=back_keyboard())
    except Exception as e:
        await app.bot.send_message(chat_id=chat_id, text=f"Price fetch failed: {e}", reply_markup=back_keyboard())

async def _do_status(app, chat_id, uid):
    row = fetchone(
        "SELECT tier, autotrade_enabled, trade_mode, daily_loss_limit, max_open_trades "
        "FROM users WHERE user_id=?", (uid,),
    )
    if not row:
        await app.bot.send_message(chat_id=chat_id, text="Not registered. Use /start.", reply_markup=back_keyboard())
        return
    tier, auto, mode_val, dll, mot = row
    from risk import (portfolio_exposure_check, open_trade_count, trade_count_today,
                      realized_pnl_today, get_equity_status)
    from pair_manager import get_active_pairs, get_pair_ranking

    eq = get_equity_status()
    pnl_today = realized_pnl_today(uid)

    # Short text summary (3-6 lines)
    summary = (
        f"Equity: ${eq['equity']:,.2f} | DD: {eq['drawdown_pct']:.1%}\n"
        f"Open: {open_trade_count(uid)}/{mot} | Today PnL: ${pnl_today:+,.2f}\n"
        f"Mode: {'LIVE' if mode_val == 'LIVE' else 'PAPER'} | "
        f"Auto: {'ON' if auto else 'OFF'}\n"
        f"Pairs: {len(get_active_pairs(uid))} active"
    )

    # Try to render Market Overview Card
    try:
        pair_scores = get_pair_ranking(uid)

        # Get snapshot from primary pair for gauge computation
        snapshot = {}
        merged = {}
        try:
            from scheduler import _compute_signals
            features = await _compute_signals(SETTINGS.PAIR)
            snap_1h = features.get('by_tf', {}).get('1h', {}).get('snapshot', {})
            snapshot = snap_1h
            merged = features.get('merged', {})
        except Exception:
            pass

        # Get event risk for gauge
        try:
            from fundamentals import get_news_event_risk
            event_risk = get_news_event_risk()
        except Exception:
            event_risk = None

        from visuals.cards import render_market_overview_card
        png = render_market_overview_card(pair_scores, snapshot, merged, event_risk=event_risk)

        import io
        await app.bot.send_photo(chat_id=chat_id, photo=io.BytesIO(png),
                                 caption=summary, reply_markup=back_keyboard())
        return
    except Exception as e:
        log.warning("Market overview card render failed: %s", e)

    # Fallback to text-only
    await app.bot.send_message(chat_id=chat_id, text=summary, reply_markup=back_keyboard())

async def _do_settings(app, chat_id):
    tfs = ", ".join(SETTINGS.TIMEFRAMES) if isinstance(SETTINGS.TIMEFRAMES, (list, tuple)) else str(SETTINGS.TIMEFRAMES)
    lines = [
        "⚙️ Settings",
        f"Pair: {SETTINGS.PAIR}",
        f"Timeframes: {tfs}",
        f"Paper: {'✅' if SETTINGS.PAPER_TRADING else '❌'}",
        f"ADX Min: {SETTINGS.ADX_TREND_MIN}",
        f"ATR SL Multiplier: {SETTINGS.ATR_SL_MULTIPLIER}",
        f"Confidence Min: {SETTINGS.AI_CONFIDENCE_MIN}",
        f"Score Min: {SETTINGS.SIGNAL_SCORE_MIN}",
    ]
    await app.bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup=back_keyboard())

async def _do_guards(app, chat_id, uid):
    row = fetchone(
        'SELECT stop_loss, take_profit, trail_pct, trail_stop, high_watermark '
        'FROM manual_guards WHERE user_id=? AND pair=?',
        (uid, SETTINGS.PAIR)
    )
    if not row:
        await app.bot.send_message(chat_id=chat_id, text="🛡️ No guards set.", reply_markup=back_keyboard())
        return
    sl, tp, trail_pct, trail_stop, hwm = row
    lines = [
        f"🛡️ Guards — {SETTINGS.PAIR}",
        f"SL: {sl if sl is not None else '—'}",
        f"TP: {tp if tp is not None else '—'}",
        f"Trail %: {trail_pct if trail_pct is not None else '—'}",
        f"Trail Stop: {trail_stop if trail_stop is not None else '—'}",
        f"HWM: {hwm if hwm is not None else '—'}",
    ]
    await app.bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup=back_keyboard())

# ---------------------------
# Callback Query Handler
# ---------------------------
# Store pending input state per user: {uid: {"type": "sl"|"tp"|"trail", "chat_id": int}}
PENDING_INPUT = {}

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = query.from_user.id
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    app = context.application

    # --- Live dashboard: native Telegram toast on button press ---
    # query.answer(text=...) shows a brief non-blocking notification at the
    # top of the screen. Feels responsive, no panel flicker. ~64 char limit.
    try:
        import panel as _panel
        _label = _panel.label_for(data) if _panel.is_enabled() else ""
        if _label:
            await query.answer(text=f"⏳ {_label}...")
        else:
            await query.answer()
        # Mark busy so the header renders 🟡 System: Busy during processing
        if _panel.is_enabled():
            _panel.set_state(uid, "busy")
    except Exception:
        try:
            await query.answer()
        except Exception:
            pass

    # Rate limit
    if not _check_rate_limit(uid):
        await query.edit_message_text("Rate limit exceeded. Try again in a moment.")
        try:
            import panel as _panel
            if _panel.is_enabled():
                _panel.set_state(uid, "healthy")
        except Exception:
            pass
        return

    # --- Main Menu ---
    if data == "cmd_menu":
        try:
            import panel as _panel
            if _panel.is_enabled():
                await query.edit_message_text(
                    _panel.build_panel_text(uid),
                    reply_markup=_panel.build_panel_keyboard(),
                    parse_mode="Markdown",
                )
                _panel.track_panel(uid, chat_id, query.message.message_id)
            else:
                await query.edit_message_text("📋 Main Menu", reply_markup=main_menu_keyboard())
        except Exception:
            await query.edit_message_text("📋 Main Menu", reply_markup=main_menu_keyboard())

    # --- Signal ---
    elif data == "cmd_signal":
        await _do_signal(app, chat_id, msg_id, uid=uid)

    # --- Price ---
    elif data == "cmd_price":
        await query.edit_message_text("⏳ Fetching price...")
        await _do_price(app, chat_id)

    # --- Status ---
    elif data == "cmd_status":
        await _do_status(app, chat_id, uid)

    # --- Settings ---
    elif data == "cmd_settings":
        await _do_settings(app, chat_id)

    # --- Guards ---
    elif data == "cmd_guards":
        await _do_guards(app, chat_id, uid)

    # --- Check Guards ---
    elif data == "cmd_checkguards":
        from scheduler import run_cycle_once
        await query.edit_message_text("⏳ Checking guards...")
        try:
            res = await run_cycle_once(app, notify=True)
        except TypeError:
            res = await run_cycle_once(app)
        await app.bot.send_message(chat_id=chat_id, text=res, reply_markup=back_keyboard())

    # --- AutoTrade submenu ---
    elif data == "menu_autotrade":
        await query.edit_message_text("🤖 AutoTrade", reply_markup=autotrade_keyboard())

    elif data == "cmd_autotrade_on":
        if admin_only(uid):
            execute("UPDATE users SET autotrade_enabled=1 WHERE user_id=?", (uid,))
            await query.edit_message_text("✅ AutoTrade enabled.", reply_markup=back_keyboard())
        else:
            await query.edit_message_text("⛔ Not allowed.", reply_markup=back_keyboard())

    elif data == "cmd_autotrade_off":
        if admin_only(uid):
            execute("UPDATE users SET autotrade_enabled=0 WHERE user_id=?", (uid,))
            await query.edit_message_text("⛔ AutoTrade disabled.", reply_markup=back_keyboard())
        else:
            await query.edit_message_text("⛔ Not allowed.", reply_markup=back_keyboard())

    # --- Mode submenu ---
    elif data == "menu_mode":
        await query.edit_message_text("📋 Trading Mode", reply_markup=mode_keyboard())

    elif data == "cmd_mode_paper":
        if admin_only(uid):
            execute("UPDATE users SET trade_mode='PAPER' WHERE user_id=?", (uid,))
            await query.edit_message_text("📝 Mode set to PAPER.", reply_markup=back_keyboard())
        else:
            await query.edit_message_text("⛔ Not allowed.", reply_markup=back_keyboard())

    elif data == "cmd_mode_live":
        if admin_only(uid):
            if uid not in (SETTINGS.LIVE_TRADE_ALLOWED_IDS or []):
                await query.edit_message_text("⛔ Live mode requires approval.", reply_markup=back_keyboard())
            else:
                execute("UPDATE users SET trade_mode='LIVE' WHERE user_id=?", (uid,))
                await query.edit_message_text("🔴 Mode set to LIVE.", reply_markup=back_keyboard())
        else:
            await query.edit_message_text("⛔ Not allowed.", reply_markup=back_keyboard())

    # --- Risk submenu ---
    elif data == "menu_risk":
        await query.edit_message_text("🎯 Set Daily Loss Limit", reply_markup=risk_keyboard())

    elif data.startswith("cmd_risk_"):
        val = float(data.replace("cmd_risk_", ""))
        execute("UPDATE users SET daily_loss_limit=? WHERE user_id=?", (val, uid))
        await query.edit_message_text(f"✅ Daily loss limit set to ${val:.0f}", reply_markup=back_keyboard())

    # --- Sell Now ---
    elif data == "cmd_sellnow":
        if admin_only(uid):
            closed = close_all_for_pair(SETTINGS.PAIR, "manual_sellnow") or 0
            await query.edit_message_text(f"🛑 Closed {closed} open trade(s).", reply_markup=back_keyboard())
        else:
            await query.edit_message_text("⛔ Not allowed.", reply_markup=back_keyboard())

    # --- Guards Set submenu ---
    elif data == "menu_guards_set":
        await query.edit_message_text("📐 Set SL / TP / Trail\nTap one, then type the value:", reply_markup=guards_set_keyboard())

    elif data == "prompt_sl":
        PENDING_INPUT[uid] = {"type": "sl", "chat_id": chat_id}
        await query.edit_message_text("🛑 Type the Stop-Loss price:\n(e.g. 580.50)", reply_markup=back_keyboard())

    elif data == "prompt_tp":
        PENDING_INPUT[uid] = {"type": "tp", "chat_id": chat_id}
        await query.edit_message_text("🎯 Type the Take-Profit price:\n(e.g. 620.00)", reply_markup=back_keyboard())

    elif data == "prompt_trail":
        PENDING_INPUT[uid] = {"type": "trail", "chat_id": chat_id}
        await query.edit_message_text("📐 Type the trailing %:\n(e.g. 0.05 for 5%)", reply_markup=back_keyboard())

    # --- Cancel Guards submenu ---
    elif data == "menu_cancel":
        await query.edit_message_text("❌ Cancel Guards", reply_markup=cancel_keyboard())

    elif data == "cmd_cancel_sl":
        clear_manual_guard(uid, SETTINGS.PAIR, "sl")
        await query.edit_message_text("✅ SL cancelled.", reply_markup=back_keyboard())

    elif data == "cmd_cancel_tp":
        clear_manual_guard(uid, SETTINGS.PAIR, "tp")
        await query.edit_message_text("✅ TP cancelled.", reply_markup=back_keyboard())

    elif data == "cmd_cancel_trail":
        clear_manual_guard(uid, SETTINGS.PAIR, "trail")
        await query.edit_message_text("✅ Trailing cancelled.", reply_markup=back_keyboard())

    elif data == "cmd_cancel_all":
        clear_manual_guard(uid, SETTINGS.PAIR, "all")
        await query.edit_message_text("✅ All guards cancelled.", reply_markup=back_keyboard())

    # --- Reporting submenu ---
    elif data == "menu_reporting":
        await query.edit_message_text("📊 Reports", reply_markup=reporting_keyboard())

    elif data == "cmd_positions":
        from reports import format_position_report
        txt = format_position_report(user_id=uid)
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_pnl":
        from reports import format_pnl_report
        txt = format_pnl_report(user_id=uid, days=30)
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_trades":
        from reports import get_recent_closed, format_trades_brief
        rows = get_recent_closed(n=10, user_id=uid)
        txt = format_trades_brief(rows, "Recent closed")
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_blocked":
        from reports import blocked_trades_summary
        txt = blocked_trades_summary(user_id=uid, days=7)
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_report":
        from reports import format_pnl_report, daily_report, performance_summary
        from risk import get_equity_status

        perf = performance_summary(user_id=uid, days=30)
        eq = get_equity_status()
        total_pnl = perf.get('total_pnl', 0)
        pnl_sign = '+' if total_pnl >= 0 else ''

        summary = (
            f"PnL: {pnl_sign}${total_pnl:.2f} | Win Rate: {perf.get('win_rate', 0):.0f}%\n"
            f"Trades: {perf.get('total_trades', 0)} (W:{perf.get('winning', 0)} L:{perf.get('losing', 0)})\n"
            f"Equity: ${eq.get('equity', 0):,.2f} | Max DD: {eq.get('max_drawdown_pct', 0):.1%}\n"
            f"Expectancy: ${perf.get('expectancy', 0):+.2f}"
        )

        # Try to render Daily Report Card
        try:
            from visuals.cards import render_daily_report_card
            png = render_daily_report_card(perf=perf, equity_status=eq)
            import io
            await app.bot.send_photo(chat_id=chat_id, photo=io.BytesIO(png),
                                     caption=summary, reply_markup=back_keyboard())
        except Exception as e:
            log.warning("Report card render failed: %s", e)
            txt = format_pnl_report(user_id=uid, days=30) + "\n\n" + daily_report(user_id=uid)
            await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    # --- Pairs submenu ---
    elif data == "menu_pairs":
        await query.edit_message_text("🌐 Pair Management", reply_markup=pairs_keyboard())

    elif data == "cmd_pairs":
        from pair_manager import list_all_pairs
        pairs = list_all_pairs(user_id=uid)
        if not pairs:
            txt = "No pairs in watchlist."
        else:
            lines = ["Watchlist:"]
            for p in pairs:
                status = "✅" if p['active'] else "⛔"
                sig = f"{p['direction']} ({p['score']:.2f})" if p['direction'] else "—"
                lines.append(f"{status} {p['pair']} | {sig}")
            txt = "\n".join(lines)
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_ranking":
        from pair_manager import get_pair_ranking
        ranking = get_pair_ranking(user_id=uid)
        if not ranking:
            txt = "No active pairs."
        else:
            lines = ["Pair Ranking (by signal strength):"]
            for i, p in enumerate(ranking, 1):
                lines.append(f"{i}. {p['pair']} — {p['direction'] or 'HOLD'} ({p['score'] or 0:.2f})")
            txt = "\n".join(lines)
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "prompt_addpair":
        PENDING_INPUT[uid] = {"type": "addpair", "chat_id": chat_id}
        await query.edit_message_text("➕ Type the pair to add:\n(e.g. BTC/USDT or ETH/USDC)", reply_markup=back_keyboard())

    elif data == "prompt_rmpair":
        PENDING_INPUT[uid] = {"type": "rmpair", "chat_id": chat_id}
        await query.edit_message_text("➖ Type the pair to remove:\n(e.g. BTC/USDT)", reply_markup=back_keyboard())

    # --- Admin submenu ---
    elif data == "menu_admin":
        await query.edit_message_text("🔧 Admin", reply_markup=admin_keyboard())

    elif data == "cmd_health":
        from validators import run_all_checks
        txt = run_all_checks(SETTINGS)
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_ai":
        row = fetchone("SELECT action, side, confidence, source, fusion_policy, ts FROM ai_decisions ORDER BY id DESC LIMIT 1")
        if row:
            txt = (f"🧠 Last AI Decision\n"
                   f"Action: {row[0]} {row[1] or ''}\n"
                   f"Confidence: {row[2]:.3f}\n"
                   f"Source: {row[3]}\n"
                   f"Policy: {row[4]}")
        else:
            txt = "No AI decisions yet."
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_killswitch":
        if admin_only(uid):
            import config
            config.SETTINGS.KILL_SWITCH = not config.SETTINGS.KILL_SWITCH
            state = "🔴 ON (trading stopped)" if config.SETTINGS.KILL_SWITCH else "🟢 OFF (trading active)"
            await query.edit_message_text(f"Kill Switch: {state}", reply_markup=back_keyboard())
        else:
            await query.edit_message_text("⛔ Not allowed.", reply_markup=back_keyboard())

    elif data == "cmd_reconcile":
        if admin_only(uid):
            await query.edit_message_text("Running reconciliation...")
            from reconcile import reconcile_positions, format_reconcile_report
            report = reconcile_positions()
            txt = format_reconcile_report(report)
            await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())
        else:
            await query.edit_message_text("⛔ Not allowed.", reply_markup=back_keyboard())

    elif data == "cmd_liveready":
        if admin_only(uid):
            await query.edit_message_text("Running live-readiness check...")
            from reconcile import check_live_readiness, format_readiness_report
            result = check_live_readiness()
            txt = format_readiness_report(result)
            await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())
        else:
            await query.edit_message_text("⛔ Not allowed.", reply_markup=back_keyboard())

    # --- New visual card commands ---
    elif data == "cmd_heatmap":
        await query.edit_message_text("Building heatmap...")
        try:
            from pair_manager import get_active_pairs
            from scheduler import _compute_signals
            from visuals.cards import render_heatmap_card
            pairs = get_active_pairs(uid)[:10] or [SETTINGS.PAIR]
            tfs = ['15m', '1h', '4h', '1d']
            data_rows = []
            for p in pairs:
                try:
                    scores = {}
                    for tf in tfs:
                        f = await _compute_signals(p)
                        m = f.get('merged', {})
                        scores[tf] = m.get('merged_score', 0)
                    data_rows.append({'pair': p, 'scores': scores})
                except Exception:
                    pass
            png = render_heatmap_card(data_rows, tfs)
            import io as _io
            await app.bot.send_photo(chat_id=chat_id, photo=_io.BytesIO(png),
                                     caption="Watchlist Heatmap", reply_markup=back_keyboard())
        except Exception as e:
            await app.bot.send_message(chat_id=chat_id, text=f"Heatmap error: {e}", reply_markup=back_keyboard())

    elif data == "cmd_positions_card":
        try:
            from storage import fetchall
            from exchange import market_price
            from visuals.cards import render_position_card
            rows = fetchall("SELECT pair, side, qty, entry FROM trades WHERE status='OPEN' AND user_id=?", (uid,))
            positions = []
            for pair, side, qty, entry in (rows or []):
                try: px = market_price(pair)
                except: px = float(entry)
                pnl = (px - float(entry)) * float(qty) if side == 'BUY' else (float(entry) - px) * float(qty)
                positions.append({
                    'pair': pair, 'side': side, 'qty': float(qty),
                    'entry': float(entry), 'current_price': px, 'pnl': pnl,
                })
            png = render_position_card(positions)
            import io as _io
            summary = f"Open: {len(positions)} positions" if positions else "No open positions"
            await app.bot.send_photo(chat_id=chat_id, photo=_io.BytesIO(png),
                                     caption=summary, reply_markup=back_keyboard())
        except Exception as e:
            await app.bot.send_message(chat_id=chat_id, text=f"Positions error: {e}", reply_markup=back_keyboard())

    elif data == "cmd_risk_board":
        try:
            from risk import portfolio_exposure_check, realized_pnl_today, get_equity_status
            from fundamentals import get_news_event_risk
            from user_context import UserContext
            ctx = UserContext.load(uid)
            _, exp, _ = portfolio_exposure_check(ctx)
            max_exp = ctx.capital_usd * ctx.max_portfolio_exposure
            eq = get_equity_status(ctx)
            er = get_news_event_risk()
            risk_data = {
                'exposure_pct': exp / max_exp if max_exp > 0 else 0,
                'daily_loss_pct': abs(realized_pnl_today(uid)) / ctx.daily_loss_limit if ctx.daily_loss_limit else 0,
                'drawdown_pct': eq.get('drawdown_pct', 0),
                'correlation_risk': 50,
                'event_risk_score': er.get('score', 50),
                'blocked_reasons': [],
            }
            from visuals.cards import render_risk_dashboard_card
            png = render_risk_dashboard_card(risk_data)
            import io as _io
            summary = f"Exposure: ${exp:.0f} | DD: {eq.get('drawdown_pct', 0):.1%} | Event: {er.get('level', '?')}"
            await app.bot.send_photo(chat_id=chat_id, photo=_io.BytesIO(png),
                                     caption=summary, reply_markup=back_keyboard())
        except Exception as e:
            await app.bot.send_message(chat_id=chat_id, text=f"Risk board error: {e}", reply_markup=back_keyboard())

    elif data == "cmd_ai_card":
        try:
            from storage import fetchall
            from visuals.cards import render_ai_decision_card
            rows = fetchall(
                "SELECT pair, action, side, confidence, source, fusion_policy, ts "
                "FROM ai_decisions WHERE user_id=? ORDER BY id DESC LIMIT 8", (uid,)) or []
            decisions = [{
                'pair': r[0], 'action': r[1], 'side': r[2] or '',
                'confidence': float(r[3]) if r[3] else 0,
                'source': r[4] or '', 'policy': r[5] or '', 'ts': r[6]
            } for r in rows]
            png = render_ai_decision_card(decisions)
            import io as _io
            await app.bot.send_photo(chat_id=chat_id, photo=_io.BytesIO(png),
                                     caption=f"Last {len(decisions)} AI decisions", reply_markup=back_keyboard())
        except Exception as e:
            await app.bot.send_message(chat_id=chat_id, text=f"AI card error: {e}", reply_markup=back_keyboard())

    elif data == "cmd_myaccount":
        try:
            from user_context import UserContext
            from crypto_utils import mask_secret
            ctx = UserContext.load(uid)
            lines = [
                "My Account",
                f"User ID: {ctx.user_id}",
                f"Tier: {ctx.tier}",
                f"Capital: ${ctx.capital_usd:,.2f}",
                f"Risk/Trade: {ctx.risk_per_trade:.1%}",
                f"Max Open: {ctx.max_open_trades}",
                f"Mode: {ctx.trade_mode} | Paper: {'Yes' if ctx.paper_trading else 'No'}",
                f"AutoTrade: {'ON' if ctx.autotrade_enabled else 'OFF'}",
                f"Exchange: {ctx.exchange_name}",
                f"API Key: {mask_secret(ctx.exchange_key) if ctx.exchange_key else 'Not set'}",
            ]
            await app.bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup=back_keyboard())
        except Exception as e:
            await app.bot.send_message(chat_id=chat_id, text=f"Account error: {e}", reply_markup=back_keyboard())

    elif data == "cmd_health_stats":
        if admin_only(uid):
            from health_telemetry import format_health_stats
            await app.bot.send_message(chat_id=chat_id, text=format_health_stats(), reply_markup=back_keyboard())
        else:
            await query.edit_message_text("⛔ Admin only", reply_markup=back_keyboard())

    elif data == "cmd_golive":
        await query.edit_message_text("Use /golive command to run the wizard", reply_markup=back_keyboard())

    elif data == "cmd_panic_stop":
        await query.edit_message_text("Use /panic_stop command to confirm and execute", reply_markup=back_keyboard())

    elif data == "cmd_backtest":
        await query.edit_message_text("Use: /backtest <pair> [days] [timeframe]\nExample: /backtest BTC/USD 30 1h",
                                      reply_markup=back_keyboard())

    elif data == "cmd_visuals":
        await query.edit_message_text("Use /visuals command to open visual settings",
                                      reply_markup=back_keyboard())

    elif data == "cmd_analyze_screens":
        if not SETTINGS.FEATURE_SCREENSHOTS:
            await query.edit_message_text(
                "Screenshot analysis is disabled.\n\n"
                "To enable: set FEATURE_SCREENSHOTS=true in Railway and add "
                "CLAUDE_API_KEY or OPENAI_API_KEY, then redeploy.",
                reply_markup=back_keyboard())
            return
        # Check AI key availability
        if not (SETTINGS.CLAUDE_API_KEY or SETTINGS.OPENAI_API_KEY):
            await query.edit_message_text(
                "Screenshot analysis needs an AI vision key.\n"
                "Set CLAUDE_API_KEY or OPENAI_API_KEY in Railway and redeploy.",
                reply_markup=back_keyboard())
            return
        from screenshot_analyzer import start_session
        start_session(uid, chat_id)
        await query.edit_message_text(
            f"Screenshot session started.\n\n"
            f"Send up to {SETTINGS.SCREENSHOT_MAX_IMAGES} chart images, then type /done to analyze.\n"
            f"Session expires in 10 minutes.",
            reply_markup=back_keyboard())

    # --- Manual confirm trade execution ---
    elif data.startswith("confirm_trade_"):
        # Format: confirm_trade_{PAIR}_{SIDE}
        parts = data.replace("confirm_trade_", "").rsplit("_", 1)
        if len(parts) == 2:
            c_pair, c_side = parts[0], parts[1]
            await query.edit_message_text(f"Executing {c_side} {c_pair}...")
            try:
                from user_context import UserContext
                from scheduler import _compute_signals
                from risk import atr_stop_loss, atr_take_profit, can_enter_enhanced, confidence_scaled_position_size, portfolio_exposure_check
                from exchange import market_price
                from trade_executor import execute_autonomous_trade

                ctx = UserContext.load(uid)
                features = await _compute_signals(c_pair)
                snap = features.get('by_tf', {}).get('1h', {}).get('snapshot', {})
                atr_val = snap.get('atr', 0)
                px = market_price(c_pair)

                if atr_val > 0 and px > 0:
                    sl = atr_stop_loss(px, atr_val, c_side)
                    tp = atr_take_profit(px, atr_val, c_side)
                    allowed, reason = can_enter_enhanced(c_pair, c_side, ctx=ctx)
                    if allowed:
                        _, _, remaining = portfolio_exposure_check(ctx)
                        qty = confidence_scaled_position_size(px, atr_val, 0.7, 0.5, remaining, ctx=ctx)
                        if qty > 0:
                            result = execute_autonomous_trade(c_pair, c_side, qty, px, sl, tp,
                                                              reason="MANUAL_CONFIRM", ctx=ctx)
                            if result['success']:
                                await app.bot.send_message(chat_id=chat_id,
                                    text=f"Executed: {c_side} {qty:.6f} {c_pair} @ ${px:.2f}\nSL: ${sl:.2f} | TP: ${tp:.2f}",
                                    reply_markup=back_keyboard())
                            else:
                                await app.bot.send_message(chat_id=chat_id,
                                    text=f"Execution failed: {result.get('error', 'unknown')}", reply_markup=back_keyboard())
                        else:
                            await app.bot.send_message(chat_id=chat_id, text="Position size = 0, skipped.", reply_markup=back_keyboard())
                    else:
                        await app.bot.send_message(chat_id=chat_id, text=f"Blocked: {reason}", reply_markup=back_keyboard())
                else:
                    await app.bot.send_message(chat_id=chat_id, text="Cannot execute: missing price/ATR data.", reply_markup=back_keyboard())
            except Exception as e:
                await app.bot.send_message(chat_id=chat_id, text=f"Error: {e}", reply_markup=back_keyboard())

    elif data == "confirm_skip":
        await query.edit_message_text("Trade skipped.", reply_markup=back_keyboard())

    # --- Visual settings toggles ---
    elif data.startswith("vtoggle_"):
        field = data.replace("vtoggle_", "")
        from storage import get_user_settings, upsert_user_settings
        settings = get_user_settings(uid) or {}
        current = bool(settings.get(field, 1))
        upsert_user_settings(uid, **{field: 0 if current else 1})
        new_val = "ON" if not current else "OFF"
        await query.edit_message_text(f"{field}: {new_val}", reply_markup=back_keyboard())

    elif data.startswith("vcycle_"):
        field = data.replace("vcycle_", "")
        from storage import get_user_settings, upsert_user_settings
        settings = get_user_settings(uid) or {}
        if field == 'visuals_style':
            options = ['dark', 'classic', 'high_contrast']
            current = settings.get('visuals_style', 'dark')
            idx = (options.index(current) + 1) % len(options) if current in options else 0
            upsert_user_settings(uid, visuals_style=options[idx])
            await query.edit_message_text(f"Style: {options[idx]}", reply_markup=back_keyboard())
        elif field == 'visuals_density':
            options = ['compact', 'detailed']
            current = settings.get('visuals_density', 'detailed')
            idx = (options.index(current) + 1) % len(options) if current in options else 0
            upsert_user_settings(uid, visuals_density=options[idx])
            await query.edit_message_text(f"Density: {options[idx]}", reply_markup=back_keyboard())

    # --- Connect Exchange flow ---
    elif data == "cmd_connect":
        session = ConnectSession(state=ConnectState.SELECT_EXCHANGE, started_ts=time.time())
        _connect_sessions[uid] = session
        await query.edit_message_text("Select your exchange:", reply_markup=_connect_exchange_keyboard())

    elif data.startswith("conn_ex_"):
        ex_id = data.replace("conn_ex_", "")
        session = _get_connect_session(uid)
        if not session:
            session = ConnectSession(started_ts=time.time())
            _connect_sessions[uid] = session
        session.state = ConnectState.ENTER_KEY
        session.exchange_id = ex_id
        PENDING_INPUT[uid] = {"type": "connect_key", "chat_id": chat_id}
        await query.edit_message_text(f"Exchange: {ex_id.upper()}\n\nSend your API Key now.\n(Message will be deleted)")

    elif data == "conn_cancel":
        _connect_sessions.pop(uid, None)
        PENDING_INPUT.pop(uid, None)
        await query.edit_message_text("Connect cancelled.", reply_markup=back_keyboard())

    elif data == "cmd_disconnect":
        from storage import get_credential, delete_credential
        cred = get_credential(uid, 'ccxt')
        if cred:
            delete_credential(uid, 'ccxt', cred['exchange_id'])
            await query.edit_message_text(f"Disconnected from {cred['exchange_id'].upper()}.", reply_markup=back_keyboard())
        else:
            await query.edit_message_text("No exchange connected.", reply_markup=back_keyboard())

    # --- Live dashboard finalization: clear Busy, record Last Action ---
    # Runs after every successful dispatch (flat if/elif chain — no early
    # returns after the rate-limit check). If an action raised, PTB's handler
    # error plumbing surfaces it and auto_refresh_all's BUSY_TIMEOUT clears
    # any stuck busy state within 30s.
    try:
        import panel as _panel
        if _panel.is_enabled():
            _panel.set_state(uid, "healthy")
            _panel.set_last_action(uid, _panel.label_for(data))
    except Exception:
        pass

# ---------------------------
# Text handler for pending input (SL/TP/Trail values)
# ---------------------------
async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    # --- Persistent bottom ReplyKeyboard shortcuts ---
    # These taps arrive as plain text messages. Route them before checking
    # PENDING_INPUT so the shortcut works even mid-flow.
    raw = (update.message.text or "").strip()
    low = raw.lower()
    if low in ("menu", "/menu"):
        await menu_cmd(update, context)
        return
    if low in ("status", "/status"):
        await status(update, context)
        try:
            import panel as _panel
            if _panel.is_enabled():
                await _panel.refresh_panel(context.application.bot, update.effective_chat.id, uid)
        except Exception:
            pass
        return
    if low in ("panic stop", "panic", "/panic_stop"):
        await panic_stop_cmd(update, context)
        return

    if uid not in PENDING_INPUT:
        return  # not waiting for input, ignore

    pending = PENDING_INPUT.pop(uid)
    txt = update.message.text.strip()
    ptype = pending["type"]

    # --- Connect exchange flow: key and secret input ---
    if ptype == "connect_key":
        # Delete the message containing the API key immediately
        try:
            await update.message.delete()
        except Exception:
            pass
        session = _get_connect_session(uid)
        if not session:
            await update.effective_chat.send_message("Session expired. Start over with Connect Exchange.", reply_markup=back_keyboard())
            return
        session.api_key = txt
        session.state = ConnectState.ENTER_SECRET
        PENDING_INPUT[uid] = {"type": "connect_secret", "chat_id": pending["chat_id"]}
        await update.effective_chat.send_message("API Key received (deleted).\n\nNow send your API Secret.\n(Message will be deleted)")
        return

    if ptype == "connect_secret":
        # Delete the message containing the secret immediately
        try:
            await update.message.delete()
        except Exception:
            pass
        session = _get_connect_session(uid)
        if not session or not session.api_key:
            await update.effective_chat.send_message("Session expired. Start over.", reply_markup=back_keyboard())
            return
        session.api_secret = txt
        session.state = ConnectState.VALIDATING

        await update.effective_chat.send_message(f"Validating credentials on {session.exchange_id.upper()}...")

        # Validate credentials
        try:
            from ccxt_provider import CCXTProvider
            provider = CCXTProvider(session.exchange_id, session.api_key, session.api_secret)
            ok, msg = provider.validate_credentials()

            if ok:
                # Encrypt and save
                from crypto_utils import encrypt_exchange_keys, is_encryption_configured
                if is_encryption_configured():
                    enc = encrypt_exchange_keys(session.api_key, session.api_secret)
                    from storage import save_credential
                    save_credential(uid, 'ccxt', session.exchange_id,
                                    enc['api_key_enc'], enc['api_secret_enc'],
                                    enc.get('data_key_enc', ''), enc.get('encryption_version', 2))
                    await update.effective_chat.send_message(
                        f"Connected to {session.exchange_id.upper()}.\n"
                        f"Credentials encrypted and saved.\n"
                        f"Use /myaccount to verify.",
                        reply_markup=back_keyboard())
                else:
                    # Fallback: save with V1 encryption
                    from crypto_utils import encrypt_credential
                    from storage import save_credential
                    key_enc = encrypt_credential(session.api_key)
                    secret_enc = encrypt_credential(session.api_secret)
                    save_credential(uid, 'ccxt', session.exchange_id,
                                    key_enc, secret_enc, '', 1)
                    await update.effective_chat.send_message(
                        f"Connected to {session.exchange_id.upper()} (V1 encryption).",
                        reply_markup=back_keyboard())
            else:
                await update.effective_chat.send_message(
                    f"Validation failed: {msg}\nPlease try again.",
                    reply_markup=back_keyboard())
        except Exception as e:
            log.error("Connect exchange failed for user %d: %s", uid, e)
            await update.effective_chat.send_message(
                f"Connection error: {e}", reply_markup=back_keyboard())
        finally:
            # Clear session data (secrets in memory)
            session.api_key = ''
            session.api_secret = ''
            _connect_sessions.pop(uid, None)
        return

    # Non-numeric inputs
    if ptype in ("addpair", "rmpair"):
        if ptype == "addpair":
            from pair_manager import add_pair
            ok, msg = add_pair(uid, txt.upper())
            await update.message.reply_text(f"{'✅' if ok else '❌'} {msg}", reply_markup=back_keyboard())
        elif ptype == "rmpair":
            from pair_manager import remove_pair
            remove_pair(txt.upper(), user_id=uid)
            await update.message.reply_text(f"✅ {txt.upper()} removed", reply_markup=back_keyboard())
        return

    # Numeric inputs
    try:
        val = float(txt)
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Try again from menu.", reply_markup=back_keyboard())
        return
    if ptype == "sl":
        set_manual_guard(uid, SETTINGS.PAIR, sl=val, tp=None, trail_pct=None)
        await update.message.reply_text(f"✅ Stop-Loss set at {val}", reply_markup=back_keyboard())
    elif ptype == "tp":
        set_manual_guard(uid, SETTINGS.PAIR, sl=None, tp=val, trail_pct=None)
        await update.message.reply_text(f"✅ Take-Profit set at {val}", reply_markup=back_keyboard())
    elif ptype == "trail":
        set_manual_guard(uid, SETTINGS.PAIR, sl=None, tp=None, trail_pct=val)
        await update.message.reply_text(f"✅ Trailing set at {val*100:.2f}%", reply_markup=back_keyboard())

# ---------------------------
# Original command handlers (still work if typed)
# ---------------------------
async def guards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _do_guards(context.application, update.effective_chat.id, update.effective_user.id)

async def checkguards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from scheduler import run_cycle_once
    msg = await update.message.reply_text('Checking guards & analysis now...')
    try:
        res = await run_cycle_once(context.application, notify=True)
    except TypeError:
        res = await run_cycle_once(context.application)
    await msg.edit_text(res, reply_markup=back_keyboard())

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _do_price(context.application, update.effective_chat.id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    upsert_user(uid, uname, int(time.time()))
    try:
        import panel as _panel
        if _panel.is_enabled():
            # 1. Send the persistent bottom ReplyKeyboard (Menu / Status / Panic Stop).
            await update.message.reply_text(
                "👋 Welcome to MCDAutoTrader!",
                reply_markup=_panel.bottom_reply_keyboard(),
            )
            # 2. Send the inline control panel and track its message_id.
            msg = await update.message.reply_text(
                _panel.build_panel_text(uid),
                reply_markup=_panel.build_panel_keyboard(),
                parse_mode="Markdown",
            )
            _panel.track_panel(uid, update.effective_chat.id, msg.message_id)
            return
    except Exception as e:
        log.debug("panel start path failed, falling back: %s", e)
    await update.message.reply_text(
        "👋 Welcome to MCDAutoTrader!\n\n"
        "Tap the menu below to get started:",
        reply_markup=main_menu_keyboard()
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        import panel as _panel
        if _panel.is_enabled():
            msg = await update.message.reply_text(
                _panel.build_panel_text(uid),
                reply_markup=_panel.build_panel_keyboard(),
                parse_mode="Markdown",
            )
            _panel.track_panel(uid, update.effective_chat.id, msg.message_id)
            return
    except Exception as e:
        log.debug("panel menu_cmd failed, falling back: %s", e)
    await update.message.reply_text("📋 Main Menu", reply_markup=main_menu_keyboard())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "📋 Tap /menu for the button menu\n\n"
        "━━ CORE ━━\n"
        "/status  /signal  /price  /settings\n\n"
        "━━ TRADING ━━\n"
        "/autotrade on|off  /mode paper|live\n"
        "/risk daily <usd>  /sellnow  /killswitch\n"
        "/panic_stop  /golive\n\n"
        "━━ GUARDS ━━\n"
        "/sl <price>  /tp <price>  /trail <%>\n"
        "/cancel sl|tp|trail|all\n"
        "/guards  /checkguards\n\n"
        "━━ PAIRS ━━\n"
        "/pairs  /addpair <PAIR>  /rmpair <PAIR>\n"
        "/ranking\n\n"
        "━━ REPORTS ━━\n"
        "/positions  /trades  /pnl  /report\n"
        "/blocked  /backtest <pair> [days] [tf]\n\n"
        "━━ AI / ANALYSIS ━━\n"
        "/ai  /divzones  /divradar\n"
        "/analyze_screens  /done\n\n"
        "━━ ADMIN ━━\n"
        "/health  /health_stats\n"
        "/liveready  /reconcile [fix]\n"
        "/capital <usd>  /maxexposure <0.0-1.0>\n\n"
        "━━ MULTI-USER ━━\n"
        "/setkeys <key> <secret>\n"
        "/myaccount  /visuals"
    )
    await update.message.reply_text(txt, reply_markup=main_menu_keyboard())

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _do_status(context.application, update.effective_chat.id, update.effective_user.id)

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _do_settings(context.application, update.effective_chat.id)

async def autotrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not admin_only(uid):
        await update.message.reply_text("Not allowed.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /autotrade on|off")
        return
    val = 1 if context.args[0].lower() == "on" else 0
    execute("UPDATE users SET autotrade_enabled=? WHERE user_id=?", (val, uid))
    await update.message.reply_text(f"Auto-Trade {'enabled' if val else 'disabled'}.", reply_markup=back_keyboard())

async def mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not admin_only(uid):
        await update.message.reply_text("Not allowed.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /mode paper|live")
        return
    m = context.args[0].upper()
    if m not in ("PAPER", "LIVE"):
        await update.message.reply_text("Mode must be paper or live.")
        return
    if m == "LIVE" and uid not in (SETTINGS.LIVE_TRADE_ALLOWED_IDS or []):
        await update.message.reply_text("Live mode requires approval.")
        return
    execute("UPDATE users SET trade_mode=? WHERE user_id=?", (m, uid))
    await update.message.reply_text(f"Mode set to {m}.", reply_markup=back_keyboard())

async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args or (len(context.args) < 2) or (context.args[0].lower() != "daily"):
        await update.message.reply_text("Usage: /risk daily <usd>")
        return
    try:
        val = float(context.args[1])
    except Exception:
        await update.message.reply_text("Invalid number.")
        return
    execute("UPDATE users SET daily_loss_limit=? WHERE user_id=?", (val, uid))
    await update.message.reply_text(f"Daily loss limit set to {val} USD.", reply_markup=back_keyboard())

async def sellnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not admin_only(uid):
        await update.message.reply_text("Not allowed.")
        return
    closed = close_all_for_pair(SETTINGS.PAIR, "manual_sellnow") or 0
    await update.message.reply_text(f"Closed {closed} open trade(s).", reply_markup=back_keyboard())

async def set_sl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /sl <price>")
        return
    try:
        p = float(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid number.")
        return
    set_manual_guard(uid, SETTINGS.PAIR, sl=p, tp=None, trail_pct=None)
    await update.message.reply_text(f"Stop-loss set at {p}.", reply_markup=back_keyboard())

async def set_tp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /tp <price>")
        return
    try:
        p = float(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid number.")
        return
    set_manual_guard(uid, SETTINGS.PAIR, sl=None, tp=p, trail_pct=None)
    await update.message.reply_text(f"Take-profit set at {p}.", reply_markup=back_keyboard())

async def set_trail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /trail <percent e.g. 0.05>")
        return
    try:
        pct = float(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid number.")
        return
    set_manual_guard(uid, SETTINGS.PAIR, sl=None, tp=None, trail_pct=pct)
    await update.message.reply_text(f"Trailing set at {pct*100:.2f}%.", reply_markup=back_keyboard())

async def cancel_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /cancel sl|tp|trail|all")
        return
    w = context.args[0].lower()
    if w not in ("sl", "tp", "trail", "all"):
        await update.message.reply_text("Choose one of: sl|tp|trail|all")
        return
    clear_manual_guard(uid, SETTINGS.PAIR, w)
    await update.message.reply_text(f"Cleared: {w}.", reply_markup=back_keyboard())

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Running analysis...")
    await _do_signal(context.application, update.effective_chat.id, msg.message_id)

# --- New Phase 6-7 commands ---
async def positions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from reports import format_position_report
    await update.message.reply_text(format_position_report(), reply_markup=back_keyboard())

async def trades_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from reports import get_recent_closed, format_trades_brief
    n = int(context.args[0]) if context.args else 5
    rows = get_recent_closed(n=n)
    await update.message.reply_text(format_trades_brief(rows, "Recent closed"), reply_markup=back_keyboard())

async def pnl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from reports import format_pnl_report
    days = int(context.args[0]) if context.args else 30
    await update.message.reply_text(format_pnl_report(days=days), reply_markup=back_keyboard())

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from reports import format_pnl_report, daily_report
    txt = format_pnl_report(days=30) + "\n\n" + daily_report()
    await update.message.reply_text(txt, reply_markup=back_keyboard())

async def pairs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from pair_manager import list_all_pairs
    pairs = list_all_pairs()
    if not pairs:
        await update.message.reply_text("No pairs.", reply_markup=back_keyboard())
        return
    lines = ["Watchlist:"]
    for p in pairs:
        s = "✅" if p['active'] else "⛔"
        sig = f"{p['direction']} ({p['score']:.2f})" if p['direction'] else "—"
        lines.append(f"{s} {p['pair']} | {sig}")
    await update.message.reply_text("\n".join(lines), reply_markup=back_keyboard())

async def addpair_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addpair BTC/USDT")
        return
    from pair_manager import add_pair
    ok, msg = add_pair(context.args[0])
    await update.message.reply_text(f"{'✅' if ok else '❌'} {msg}", reply_markup=back_keyboard())

async def rmpair_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /rmpair BTC/USDT")
        return
    from pair_manager import remove_pair
    remove_pair(context.args[0])
    await update.message.reply_text(f"✅ {context.args[0].upper()} removed", reply_markup=back_keyboard())

async def ranking_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from pair_manager import get_pair_ranking
    ranking = get_pair_ranking()
    if not ranking:
        await update.message.reply_text("No active pairs.", reply_markup=back_keyboard())
        return
    lines = ["Pair Ranking:"]
    for i, p in enumerate(ranking, 1):
        lines.append(f"{i}. {p['pair']} — {p['direction'] or 'HOLD'} ({p['score'] or 0:.2f})")
    await update.message.reply_text("\n".join(lines), reply_markup=back_keyboard())

async def capital_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not admin_only(uid):
        await update.message.reply_text("Not allowed.")
        return
    if not context.args:
        await update.message.reply_text(f"Capital: ${SETTINGS.CAPITAL_USD:,.2f}\nUsage: /capital <amount>", reply_markup=back_keyboard())
        return
    try:
        val = float(context.args[0])
        if val <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return
    import config
    config.SETTINGS.CAPITAL_USD = val
    upsert_bot_state('capital_usd', str(val), int(time.time()))
    await update.message.reply_text(f"Capital set to ${val:,.2f}", reply_markup=back_keyboard())

async def maxexposure_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not admin_only(uid):
        await update.message.reply_text("Not allowed.")
        return
    if not context.args:
        pct = SETTINGS.MAX_PORTFOLIO_EXPOSURE
        await update.message.reply_text(f"Max exposure: {pct*100:.0f}%\nUsage: /maxexposure <0.0-1.0>", reply_markup=back_keyboard())
        return
    try:
        val = float(context.args[0])
        if not 0 < val <= 1.0: raise ValueError
    except ValueError:
        await update.message.reply_text("Must be 0 < value <= 1.0")
        return
    import config
    config.SETTINGS.MAX_PORTFOLIO_EXPOSURE = val
    upsert_bot_state('max_portfolio_exposure', str(val), int(time.time()))
    await update.message.reply_text(f"Max exposure: {val*100:.0f}% (${SETTINGS.CAPITAL_USD * val:,.2f})", reply_markup=back_keyboard())

async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from validators import run_all_checks
    await update.message.reply_text(run_all_checks(SETTINGS), reply_markup=back_keyboard())

async def divzones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show divergence radar zones. Usage: /divzones [timeframe]"""
    from div_radar import full_radar_scan, format_radar_report, format_radar_brief
    from exchange import fetch_ohlcv
    from pair_manager import get_active_pairs
    msg = await update.message.reply_text("Scanning divergence zones...")
    tf_filter = context.args[0] if context.args else None
    pairs = get_active_pairs()
    tfs = [tf_filter] if tf_filter else list(SETTINGS.TIMEFRAMES)
    zones = full_radar_scan(pairs, tfs, fetch_ohlcv)
    if tf_filter:
        txt = format_radar_brief(zones, tf_filter)
    else:
        txt = format_radar_report(zones)
    await msg.edit_text(txt, reply_markup=back_keyboard())

async def divradar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Full divergence radar scan across all pairs and timeframes."""
    from div_radar import full_radar_scan, format_radar_report
    from exchange import fetch_ohlcv
    from pair_manager import get_active_pairs
    msg = await update.message.reply_text("Running full divergence radar...")
    pairs = get_active_pairs()
    zones = full_radar_scan(pairs, list(SETTINGS.TIMEFRAMES), fetch_ohlcv)
    txt = format_radar_report(zones, max_zones=15)
    await msg.edit_text(txt, reply_markup=back_keyboard())

async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = fetchone("SELECT action, side, confidence, source, fusion_policy, ts FROM ai_decisions ORDER BY id DESC LIMIT 1")
    if row:
        txt = (f"🧠 Last AI Decision\nAction: {row[0]} {row[1] or ''}\n"
               f"Confidence: {row[2]:.3f}\nSource: {row[3]}\nPolicy: {row[4]}")
    else:
        txt = "No AI decisions yet."
    await update.message.reply_text(txt, reply_markup=back_keyboard())

async def killswitch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not admin_only(uid):
        await update.message.reply_text("Not allowed.")
        return
    import config
    config.SETTINGS.KILL_SWITCH = not config.SETTINGS.KILL_SWITCH
    state = "🔴 ON (trading stopped)" if config.SETTINGS.KILL_SWITCH else "🟢 OFF (trading active)"
    await update.message.reply_text(f"Kill Switch: {state}", reply_markup=back_keyboard())

async def blocked_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from reports import blocked_trades_summary
    days = int(context.args[0]) if context.args else 7
    await update.message.reply_text(blocked_trades_summary(days), reply_markup=back_keyboard())


async def setkeys_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set exchange API keys. Usage: /setkeys <api_key> <api_secret>
    Keys are encrypted at rest. The message containing keys is deleted for safety."""
    uid = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /setkeys <api_key> <api_secret>\n"
            "Keys will be encrypted and your message deleted.",
            reply_markup=back_keyboard())
        return

    api_key = context.args[0]
    api_secret = context.args[1]

    # Delete the message containing plaintext keys immediately
    try:
        await update.message.delete()
    except Exception:
        pass

    try:
        from crypto_utils import encrypt_credential, is_encryption_configured
        if not is_encryption_configured():
            await update.effective_chat.send_message(
                "Encryption not configured. Set CREDENTIAL_ENCRYPTION_KEY env var.",
                reply_markup=back_keyboard())
            return

        key_enc = encrypt_credential(api_key)
        secret_enc = encrypt_credential(api_secret)
        execute("UPDATE users SET exchange_key_enc=?, exchange_secret_enc=? WHERE user_id=?",
                (key_enc, secret_enc, uid))
        await update.effective_chat.send_message(
            "Exchange API keys set and encrypted.\n"
            "Your message with plaintext keys has been deleted.",
            reply_markup=back_keyboard())
    except Exception as e:
        await update.effective_chat.send_message(f"Failed to set keys: {e}", reply_markup=back_keyboard())


async def myaccount_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's account settings."""
    uid = update.effective_user.id
    from user_context import UserContext
    from crypto_utils import mask_secret
    ctx = UserContext.load(uid)
    lines = [
        "My Account",
        f"User ID: {ctx.user_id}",
        f"Username: @{ctx.tg_username}" if ctx.tg_username else "Username: -",
        f"Tier: {ctx.tier}",
        "",
        f"Capital: ${ctx.capital_usd:,.2f}",
        f"Risk/Trade: {ctx.risk_per_trade:.1%}",
        f"Max Open: {ctx.max_open_trades}",
        f"Daily Loss Limit: ${ctx.daily_loss_limit:,.2f}",
        f"Max Exposure: {ctx.max_portfolio_exposure:.0%}",
        "",
        f"Mode: {ctx.trade_mode}",
        f"Paper: {'Yes' if ctx.paper_trading else 'No'}",
        f"AutoTrade: {'ON' if ctx.autotrade_enabled else 'OFF'}",
        f"Exchange: {ctx.exchange_name}",
        f"API Key: {mask_secret(ctx.exchange_key) if ctx.exchange_key else 'Not set'}",
        "",
        f"AI Policy: {ctx.ai_fusion_policy}",
    ]
    await update.message.reply_text("\n".join(lines), reply_markup=back_keyboard())


async def golive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go Live Wizard: enforces prerequisites before enabling live trading.
    Checks: /liveready passes, paper mode completed, risk settings set,
    API key reminder (no-withdrawal), applies micro-risk safety profile."""
    uid = update.effective_user.id
    from user_context import UserContext
    from reconcile import check_live_readiness
    from storage import get_user_settings, upsert_user_settings, get_credential

    ctx = UserContext.load(uid)
    issues = []

    # 1. Live readiness
    readiness = check_live_readiness()
    if not readiness['ready']:
        issues.append("FAIL: /liveready check did not pass. Fix issues first.")

    # 2. Paper mode history (must have at least 5 closed paper trades)
    from storage import fetchone
    row = fetchone("SELECT COUNT(*) FROM trades WHERE user_id=? AND status='CLOSED'", (uid,))
    closed_count = int(row[0]) if row else 0
    if closed_count < 5:
        issues.append(f"FAIL: Need at least 5 closed paper trades (you have {closed_count}).")

    # 3. Exchange credentials
    cred = get_credential(uid, 'ccxt')
    if not cred:
        issues.append("FAIL: No exchange connected. Use Connect Exchange first.")

    # 4. Risk settings must be explicitly set
    settings = get_user_settings(uid) or {}
    if not settings:
        issues.append("FAIL: No user settings found. Configure risk settings first.")

    if issues:
        lines = ["Go-Live Wizard: NOT READY\n"] + issues
        lines.append("\nFix the above issues and run /golive again.")
        await update.message.reply_text("\n".join(lines), reply_markup=back_keyboard())
        return

    # All prerequisites passed — apply micro-risk safety profile
    upsert_user_settings(uid,
        mode='live',
        ai_mode='manual_confirm',  # Force manual confirm for first live run
    )
    # Apply micro-risk if user hasn't set stricter limits
    from storage import execute
    execute("UPDATE users SET risk_per_trade=MIN(risk_per_trade, 0.0025), "
            "max_open_trades=MIN(max_open_trades, 1) WHERE user_id=?", (uid,))

    lines = [
        "Go-Live Wizard: READY",
        "",
        "Safety profile applied:",
        "  Mode: LIVE",
        "  AI Mode: manual_confirm (you approve each trade)",
        "  Risk per trade: max 0.25%",
        "  Max open trades: 1",
        "",
        "IMPORTANT REMINDERS:",
        "  - Use a NO-WITHDRAWAL API key (read + trade only)",
        "  - /panic_stop is your emergency brake",
        "  - Monitor /health_stats and /reconcile daily",
        "  - Start with minimum capital",
        "",
        "You can now trade live. Be careful.",
    ]
    await update.message.reply_text("\n".join(lines), reply_markup=back_keyboard())


async def health_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show health telemetry counters."""
    uid = update.effective_user.id
    if not admin_only(uid):
        await update.message.reply_text("Not allowed.", reply_markup=back_keyboard())
        return
    from health_telemetry import format_health_stats
    await update.message.reply_text(format_health_stats(), reply_markup=back_keyboard())


async def visual_settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show visual settings menu."""
    uid = update.effective_user.id
    from user_context import UserContext
    ctx = UserContext.load(uid)

    def _icon(val): return 'ON' if val else 'OFF'

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Visuals: {_icon(ctx.visuals_enabled)}", callback_data="vtoggle_visuals_enabled"),
         InlineKeyboardButton(f"Style: {ctx.visuals_style}", callback_data="vcycle_visuals_style")],
        [InlineKeyboardButton(f"Density: {ctx.visuals_density}", callback_data="vcycle_visuals_density")],
        [InlineKeyboardButton(f"RSI: {_icon(ctx.show_rsi)}", callback_data="vtoggle_show_rsi"),
         InlineKeyboardButton(f"MACD: {_icon(ctx.show_macd)}", callback_data="vtoggle_show_macd")],
        [InlineKeyboardButton(f"Ichimoku: {_icon(ctx.show_ichimoku)}", callback_data="vtoggle_show_ichimoku"),
         InlineKeyboardButton(f"Volume: {_icon(ctx.show_volume)}", callback_data="vtoggle_show_volume")],
        [InlineKeyboardButton(f"Divergence Marks: {_icon(ctx.show_divergence_marks)}", callback_data="vtoggle_show_divergence_marks"),
         InlineKeyboardButton(f"S/R Levels: {_icon(ctx.show_levels)}", callback_data="vtoggle_show_levels")],
        [InlineKeyboardButton("Back", callback_data="cmd_menu")],
    ])
    await update.message.reply_text("Visual Settings", reply_markup=kb)


async def backtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run backtest. Usage: /backtest <pair> [days] [timeframe]
    Example: /backtest BTC/USDT 30 1h"""
    uid = update.effective_user.id
    args = context.args or []
    pair = args[0] if len(args) > 0 else SETTINGS.PAIR
    days = int(args[1]) if len(args) > 1 else 30
    timeframe = args[2] if len(args) > 2 else '1h'

    msg = await update.message.reply_text(f"Running backtest: {pair} {timeframe} ({days}d)...")

    try:
        from backtest import run_backtest, format_backtest_result, render_backtest_card
        result = run_backtest(pair, days=days, timeframe=timeframe,
                              capital=SETTINGS.CAPITAL_USD, risk_pct=SETTINGS.RISK_PER_TRADE)

        if result.total_bars < 50:
            await msg.edit_text(f"Not enough data for backtest ({result.total_bars} bars).",
                                reply_markup=back_keyboard())
            return

        summary = format_backtest_result(result)

        try:
            png = render_backtest_card(result)
            import io as _io
            await msg.delete()
            await update.effective_chat.send_photo(
                photo=_io.BytesIO(png), caption=summary, reply_markup=back_keyboard())
        except Exception:
            await msg.edit_text(summary, reply_markup=back_keyboard())
    except Exception as e:
        log.error("Backtest failed: %s", e)
        await msg.edit_text(f"Backtest failed: {e}", reply_markup=back_keyboard())


async def panic_stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Emergency stop: disable trading + close all positions for this user."""
    uid = update.effective_user.id
    # Set panic_stop in user_settings
    from storage import upsert_user_settings
    upsert_user_settings(uid, panic_stop=1)
    # Disable autotrade
    execute("UPDATE users SET autotrade_enabled=0 WHERE user_id=?", (uid,))

    # Close all open trades for this user
    closed = 0
    total_pnl = 0.0
    try:
        from user_context import UserContext
        ctx = UserContext.load(uid)
        from pair_manager import get_active_pairs
        from trade_executor import execute_autonomous_exit
        for pair in get_active_pairs(uid):
            result = execute_autonomous_exit(pair, "PANIC_STOP", ctx=ctx)
            closed += result.get('closed_count', 0)
            total_pnl += result.get('total_pnl', 0)
    except Exception as e:
        log.error("Panic stop close failed for user %d: %s", uid, e)

    lines = [
        "PANIC STOP ACTIVATED",
        f"AutoTrade: DISABLED",
        f"Positions closed: {closed}",
        f"PnL: ${total_pnl:+.2f}" if closed > 0 else "",
        "",
        "To resume: re-enable autotrade and clear panic stop.",
    ]
    await update.message.reply_text("\n".join(l for l in lines if l), reply_markup=back_keyboard())


# ---------------------------
# Screenshot analysis commands
# ---------------------------
async def analyze_screens_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a screenshot analysis session. Usage: /analyze_screens"""
    if not SETTINGS.FEATURE_SCREENSHOTS:
        await update.message.reply_text("Screenshot analysis is not enabled.", reply_markup=back_keyboard())
        return
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    from screenshot_analyzer import start_session
    session = start_session(uid, chat_id)
    await update.message.reply_text(
        f"Screenshot analysis session started.\n"
        f"Send up to {SETTINGS.SCREENSHOT_MAX_IMAGES} chart screenshots.\n"
        f"When done, send /done to trigger analysis.\n"
        f"Session expires in 10 minutes.",
        reply_markup=back_keyboard())


async def screenshot_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos during an active screenshot session."""
    uid = update.effective_user.id
    from screenshot_analyzer import get_session, add_image
    session = get_session(uid)
    if not session:
        return  # No active session, ignore photos

    # Download the photo
    photo = update.message.photo[-1]  # Highest resolution
    try:
        file = await context.bot.get_file(photo.file_id)
        file_path = os.path.join(session.temp_dir, f"chart_{session.image_count + 1}.jpg")
        await file.download_to_drive(file_path)

        if add_image(uid, file_path):
            remaining = SETTINGS.SCREENSHOT_MAX_IMAGES - session.image_count
            await update.message.reply_text(
                f"Image {session.image_count} received. "
                f"{remaining} remaining. Send /done when ready.")
        else:
            await update.message.reply_text(
                f"Maximum {SETTINGS.SCREENSHOT_MAX_IMAGES} images reached. Send /done to analyze.")
    except Exception as e:
        log.error("Failed to download screenshot: %s", e)
        await update.message.reply_text("Failed to download image. Try again.")


async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger analysis of collected screenshots. Usage: /done"""
    uid = update.effective_user.id
    from screenshot_analyzer import get_session, end_session, analyze_screenshots, format_analysis_result
    session = get_session(uid)
    if not session:
        await update.message.reply_text("No active screenshot session. Use /analyze_screens first.",
                                        reply_markup=back_keyboard())
        return

    if session.image_count == 0:
        await update.message.reply_text("No images received. Send screenshots first.",
                                        reply_markup=back_keyboard())
        return

    msg = await update.message.reply_text(
        f"Analyzing {session.image_count} screenshot(s)... This may take a moment.")

    try:
        result = await analyze_screenshots(session)
        text = format_analysis_result(result)

        # Telegram message max is 4096 chars. Split if too long.
        CHUNK = 3800
        if len(text) <= CHUNK:
            await msg.edit_text(text, reply_markup=back_keyboard())
        else:
            await msg.edit_text(text[:CHUNK])
            # Send remaining as follow-up messages
            remaining = text[CHUNK:]
            while remaining:
                part = remaining[:CHUNK]
                remaining = remaining[CHUNK:]
                if not remaining:
                    await update.effective_chat.send_message(part, reply_markup=back_keyboard())
                else:
                    await update.effective_chat.send_message(part)
    except Exception as e:
        log.error("Screenshot analysis failed: %s", e)
        await msg.edit_text(f"Analysis failed: {e}", reply_markup=back_keyboard())
    finally:
        end_session(uid)
        # After the (possibly multi-chunk) analysis output, surface the
        # control panel again so the user has one-tap access below it.
        try:
            import panel as _panel
            if _panel.is_enabled():
                await _panel.refresh_panel(context.application.bot, update.effective_chat.id, uid)
        except Exception:
            pass


async def reconcile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run exchange reconciliation. Usage: /reconcile [fix]"""
    uid = update.effective_user.id
    if not admin_only(uid):
        await update.message.reply_text("Not allowed.")
        return
    await update.message.reply_text("Running reconciliation...")
    from reconcile import reconcile_positions, auto_fix_issues, format_reconcile_report
    report = reconcile_positions()

    # Auto-fix if requested
    if context.args and context.args[0].lower() == 'fix':
        actions = auto_fix_issues(report)
        report['actions_taken'] = actions

    txt = format_reconcile_report(report)
    await update.message.reply_text(txt, reply_markup=back_keyboard())


async def liveready_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run live-readiness check. Usage: /liveready"""
    uid = update.effective_user.id
    if not admin_only(uid):
        await update.message.reply_text("Not allowed.")
        return
    await update.message.reply_text("Running live-readiness check...")
    from reconcile import check_live_readiness, format_readiness_report
    result = check_live_readiness()
    txt = format_readiness_report(result)
    await update.message.reply_text(txt, reply_markup=back_keyboard())


# ---------------------------
# Startup validation
# ---------------------------
async def post_init(application):
    """
    Idempotent startup sequence:
    1. Initialize DB
    2. Seed default pair
    3. Recover persisted config
    4. Recover stuck PENDING trades
    5. Validate state
    6. Notify admins
    """
    from storage import init_db
    from validators import run_all_checks
    from pair_manager import seed_default_pair
    from trade_executor import recover_pending_trades, get_trade_state_summary

    # 1. DB init (idempotent — CREATE IF NOT EXISTS)
    init_db()

    # 2. Seed default pair (idempotent — upsert)
    seed_default_pair()

    # 3. Recover persisted config from bot_state
    import config
    for key, attr in [('capital_usd', 'CAPITAL_USD'), ('max_portfolio_exposure', 'MAX_PORTFOLIO_EXPOSURE')]:
        row = fetchone("SELECT value FROM bot_state WHERE key=?", (key,))
        if row and row[0]:
            try:
                setattr(config.SETTINGS, attr, float(row[0]))
                log.info("Recovered config %s = %s from bot_state", attr, row[0])
            except Exception:
                pass

    # 4. Recover trades stuck in PENDING (from crash during execution)
    recovered = recover_pending_trades()
    if recovered > 0:
        log.warning("Recovered %d PENDING trades on startup", recovered)

    # 4b. Load health telemetry from previous run
    try:
        from health_telemetry import load_from_db
        load_from_db()
    except Exception:
        pass

    # 5. Record startup and trade state
    now = int(time.time())
    try:
        upsert_bot_state('last_startup', str(now), now)
        trade_state = get_trade_state_summary()
        upsert_bot_state('startup_trade_state', str(trade_state), now)
    except Exception:
        pass

    # 6. Notify admins with startup summary
    summary = run_all_checks(SETTINGS)
    startup_lines = [f"Bot Started\n", summary]
    if recovered > 0:
        startup_lines.append(f"\nRecovered {recovered} PENDING trade(s) from crash.")
    trade_state = get_trade_state_summary()
    if trade_state.get('open', 0) > 0:
        startup_lines.append(f"\nOpen trades: {trade_state['open']}")

    startup_msg = "\n".join(startup_lines)
    for aid in SETTINGS.TELEGRAM_ADMIN_IDS:
        try:
            await application.bot.send_message(chat_id=aid, text=startup_msg)
        except Exception as e:
            log.warning("Startup notify failed for %s: %s", aid, e)

# ---------------------------
# App builder + jobs
# ---------------------------
def build_app() -> Application:
    b = Application.builder().token(SETTINGS.TELEGRAM_BOT_TOKEN)

    if getattr(SETTINGS, "HTTPS_PROXY", None):
        os.environ["HTTPS_PROXY"] = SETTINGS.HTTPS_PROXY
        os.environ["HTTP_PROXY"] = SETTINGS.HTTPS_PROXY

    b.post_init(post_init)
    app = b.build()

    # --- Original command handlers (all rate-limited) ---
    app.add_handler(CommandHandler("start", rate_limited(start)))
    app.add_handler(CommandHandler("menu", rate_limited(menu_cmd)))
    app.add_handler(CommandHandler("help", rate_limited(help_cmd)))
    app.add_handler(CommandHandler("status", rate_limited(status)))
    app.add_handler(CommandHandler("settings", rate_limited(settings)))
    app.add_handler(CommandHandler("autotrade", rate_limited(autotrade)))
    app.add_handler(CommandHandler("mode", rate_limited(mode)))
    app.add_handler(CommandHandler("risk", rate_limited(risk)))
    app.add_handler(CommandHandler("sellnow", rate_limited(sellnow)))
    app.add_handler(CommandHandler("sl", rate_limited(set_sl)))
    app.add_handler(CommandHandler("tp", rate_limited(set_tp)))
    app.add_handler(CommandHandler("trail", rate_limited(set_trail)))
    app.add_handler(CommandHandler("cancel", rate_limited(cancel_guard)))
    app.add_handler(CommandHandler("signal", rate_limited(signal)))
    app.add_handler(CommandHandler("guards", rate_limited(guards)))
    app.add_handler(CommandHandler("checkguards", rate_limited(checkguards)))
    app.add_handler(CommandHandler("price", rate_limited(price)))

    # --- New Phase 5-7 commands ---
    app.add_handler(CommandHandler("positions", positions_cmd))
    app.add_handler(CommandHandler("trades", trades_cmd))
    app.add_handler(CommandHandler("pnl", pnl_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("pairs", pairs_cmd))
    app.add_handler(CommandHandler("addpair", addpair_cmd))
    app.add_handler(CommandHandler("rmpair", rmpair_cmd))
    app.add_handler(CommandHandler("ranking", ranking_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("ai", ai_cmd))
    app.add_handler(CommandHandler("killswitch", killswitch_cmd))
    app.add_handler(CommandHandler("blocked", blocked_cmd))
    app.add_handler(CommandHandler("capital", capital_cmd))
    app.add_handler(CommandHandler("maxexposure", maxexposure_cmd))
    app.add_handler(CommandHandler("divzones", divzones_cmd))
    app.add_handler(CommandHandler("divradar", divradar_cmd))

    # --- Production hardening commands ---
    app.add_handler(CommandHandler("reconcile", reconcile_cmd))
    app.add_handler(CommandHandler("liveready", liveready_cmd))

    # --- Multi-user commands ---
    app.add_handler(CommandHandler("setkeys", setkeys_cmd))
    app.add_handler(CommandHandler("myaccount", myaccount_cmd))
    app.add_handler(CommandHandler("panic_stop", panic_stop_cmd))
    app.add_handler(CommandHandler("backtest", rate_limited(backtest_cmd)))
    app.add_handler(CommandHandler("health_stats", rate_limited(health_stats_cmd)))
    app.add_handler(CommandHandler("golive", rate_limited(golive_cmd)))
    app.add_handler(CommandHandler("visuals", rate_limited(visual_settings_cmd)))

    # --- Screenshot analysis ---
    app.add_handler(CommandHandler("analyze_screens", rate_limited(analyze_screens_cmd)))
    app.add_handler(CommandHandler("done", rate_limited(done_cmd)))
    # Photo handler for screenshots (must be after other handlers)
    from telegram.ext import MessageHandler, filters as tg_filters
    app.add_handler(MessageHandler(tg_filters.PHOTO, screenshot_photo_handler))

    # Callback handler for inline buttons
    app.add_handler(CallbackQueryHandler(button_callback))

    # Text handler for pending input
    from telegram.ext import MessageHandler, filters
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    # Main strategy jobs
    schedule_jobs(app)

    # Auto-Exit guard job
    async def _guard_job(context):
        await auto_exit_task(context.application)

    app.job_queue.run_repeating(_guard_job, interval=SETTINGS.GUARD_CHECK_INTERVAL_SECONDS, first=15, name="auto_exit_guard")

    # --- Live dashboard auto-refresh (UI layer only) ---
    async def _panel_refresh_job(context):
        try:
            import panel as _panel
            if _panel.is_enabled():
                await _panel.auto_refresh_all(context.application.bot)
        except Exception as _e:
            log.debug("panel auto_refresh_all failed: %s", _e)

    app.job_queue.run_repeating(
        _panel_refresh_job,
        interval=45,
        first=60,
        name="panel_auto_refresh",
    )

    return app
