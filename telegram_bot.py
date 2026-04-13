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
# Inline Keyboard Menus
# ---------------------------
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Signal", callback_data="cmd_signal"),
         InlineKeyboardButton("💰 Price", callback_data="cmd_price")],
        [InlineKeyboardButton("📈 Status", callback_data="cmd_status"),
         InlineKeyboardButton("⚙️ Settings", callback_data="cmd_settings")],
        [InlineKeyboardButton("🛡️ Guards", callback_data="cmd_guards"),
         InlineKeyboardButton("🔍 Check Guards", callback_data="cmd_checkguards")],
        [InlineKeyboardButton("🤖 AutoTrade ➤", callback_data="menu_autotrade"),
         InlineKeyboardButton("📋 Mode ➤", callback_data="menu_mode")],
        [InlineKeyboardButton("🎯 Risk ➤", callback_data="menu_risk"),
         InlineKeyboardButton("🛑 Sell Now", callback_data="cmd_sellnow")],
        [InlineKeyboardButton("📐 SL / TP / Trail ➤", callback_data="menu_guards_set")],
        [InlineKeyboardButton("❌ Cancel Guards ➤", callback_data="menu_cancel")],
        [InlineKeyboardButton("📊 Report ➤", callback_data="menu_reporting"),
         InlineKeyboardButton("🌐 Pairs ➤", callback_data="menu_pairs")],
        [InlineKeyboardButton("🔧 Admin ➤", callback_data="menu_admin")],
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

def _paper_close_all(pair: str, px: float) -> Tuple[int, float]:
    now = int(time.time())
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

def _check_atr_trailing_stops(pair: str, price: float) -> Optional[str]:
    """
    Check ATR-based trailing stops for all open trades on this pair.
    Updates trail stops in DB and returns exit reason if triggered.
    """
    from risk import compute_atr_trailing_stop, is_atr_trail_triggered
    import json as _json

    if not SETTINGS.TRAILING_ENABLED:
        return None

    rows = fetchall(
        "SELECT id, side, entry, entry_snapshot FROM trades WHERE status='OPEN' AND pair=?",
        (pair,)
    )
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
    """Check guards for ALL pairs with open trades, not just the primary pair."""
    admin_id = _get_admin_id()
    if not admin_id:
        return

    # Get all distinct pairs with open trades
    rows = fetchall("SELECT DISTINCT pair FROM trades WHERE status='OPEN'")
    pairs_to_check = [r[0] for r in rows] if rows else []

    # Also check the primary pair (may have guards without open trades)
    if SETTINGS.PAIR not in pairs_to_check:
        pairs_to_check.append(SETTINGS.PAIR)

    for pair in pairs_to_check:
        try:
            await _check_pair_guards(application, admin_id, pair)
        except Exception as e:
            log.warning("auto-exit check failed for %s: %s", pair, e)


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

    # --- Check ATR-based trailing stops for open trades ---
    if not reason:
        reason = _check_atr_trailing_stops(pair, price)

    if not reason:
        return

    # Dedup notification
    key = (admin_id, pair, reason)
    now_ts = int(time.time())
    last_ts = LAST_NOTIFY.get(key, 0)
    if now_ts - last_ts < NOTIFY_COOLDOWN:
        return
    LAST_NOTIFY[key] = now_ts

    # Execute close
    closed = 0
    total_pnl = None
    try:
        if SETTINGS.PAPER_TRADING:
            closed, total_pnl = _paper_close_all(pair, price)
        else:
            closed = close_all_for_pair(pair, f"auto_exit: {reason}") or 0
    except Exception as e:
        log.exception("auto-exit: closing failed for %s: %s", pair, e)

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
    except Exception as e:
        log.warning("auto-exit: notify failed for %s: %s", pair, e)

# ---------------------------
# Commands (also used by callbacks)
# ---------------------------
async def _do_signal(app, chat_id, message_id=None):
    from scheduler import run_cycle_once
    if message_id:
        try:
            await app.bot.edit_message_text("⏳ Running analysis...", chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    res = await run_cycle_once(app, notify=False)
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
    from pair_manager import get_active_pairs
    _, current_exp, remaining = portfolio_exposure_check()
    max_exp = SETTINGS.CAPITAL_USD * SETTINGS.MAX_PORTFOLIO_EXPOSURE
    exp_pct = (current_exp / max_exp * 100) if max_exp > 0 else 0
    pnl_today = realized_pnl_today()

    # Equity & drawdown
    eq = get_equity_status()
    dd_bar = _drawdown_bar(eq['drawdown_pct'])

    lines = [
        "Bot Status",
        "",
        f"Auto-Trade: {'AUTONOMOUS' if auto else 'OFF'}",
        f"Mode: {'LIVE' if mode_val == 'LIVE' else 'PAPER'}",
        f"Kill Switch: {'ON' if SETTINGS.KILL_SWITCH else 'OFF'}",
        "",
        f"Equity: ${eq['equity']:,.2f} (peak: ${eq['peak_equity']:,.2f})",
        f"Drawdown: {eq['drawdown_pct']:.1%} (${eq['drawdown_usd']:,.2f}) {dd_bar}",
        f"Max Drawdown: {eq['max_drawdown_pct']:.1%}",
        f"Realized PnL: ${eq['realized_pnl']:,.2f} | Unrealized: ${eq['unrealized_pnl']:,.2f}",
        "",
        f"Exposure: ${current_exp:,.0f} / ${max_exp:,.0f} ({exp_pct:.0f}%)",
        f"Open Trades: {open_trade_count()}/{mot}",
        "",
        f"Today: {trade_count_today()} trades | PnL: ${pnl_today:,.2f}",
        f"Daily Loss Limit: ${dll}",
        "",
        f"Pairs: {len(get_active_pairs())} active",
        f"Cycle: every {SETTINGS.ANALYSIS_INTERVAL_SECONDS}s",
        f"AI Policy: {SETTINGS.AI_FUSION_POLICY}",
        f"Trailing: {'ATR' if SETTINGS.TRAILING_ENABLED else 'OFF'}",
        f"Correlation Guard: {'ON' if SETTINGS.CORRELATION_CHECK_ENABLED else 'OFF'}",
    ]
    await app.bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup=back_keyboard())

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
    await query.answer()
    data = query.data
    uid = query.from_user.id
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    app = context.application

    # --- Main Menu ---
    if data == "cmd_menu":
        await query.edit_message_text("📋 Main Menu", reply_markup=main_menu_keyboard())

    # --- Signal ---
    elif data == "cmd_signal":
        await _do_signal(app, chat_id, msg_id)

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
        txt = format_position_report()
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_pnl":
        from reports import format_pnl_report
        txt = format_pnl_report(days=30)
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_trades":
        from reports import get_recent_closed, format_trades_brief
        rows = get_recent_closed(n=10)
        txt = format_trades_brief(rows, "Recent closed")
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_blocked":
        from reports import blocked_trades_summary
        txt = blocked_trades_summary(days=7)
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    elif data == "cmd_report":
        from reports import format_pnl_report, daily_report
        txt = format_pnl_report(days=30) + "\n\n" + daily_report()
        await app.bot.send_message(chat_id=chat_id, text=txt, reply_markup=back_keyboard())

    # --- Pairs submenu ---
    elif data == "menu_pairs":
        await query.edit_message_text("🌐 Pair Management", reply_markup=pairs_keyboard())

    elif data == "cmd_pairs":
        from pair_manager import list_all_pairs
        pairs = list_all_pairs()
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
        ranking = get_pair_ranking()
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

# ---------------------------
# Text handler for pending input (SL/TP/Trail values)
# ---------------------------
async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in PENDING_INPUT:
        return  # not waiting for input, ignore

    pending = PENDING_INPUT.pop(uid)
    txt = update.message.text.strip()
    ptype = pending["type"]

    # Non-numeric inputs
    if ptype in ("addpair", "rmpair"):
        if ptype == "addpair":
            from pair_manager import add_pair
            ok, msg = add_pair(txt.upper())
            await update.message.reply_text(f"{'✅' if ok else '❌'} {msg}", reply_markup=back_keyboard())
        elif ptype == "rmpair":
            from pair_manager import remove_pair
            remove_pair(txt.upper())
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
    await update.message.reply_text(
        "👋 Welcome to MCDAutoTrader!\n\n"
        "Tap the menu below to get started:",
        reply_markup=main_menu_keyboard()
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 Main Menu", reply_markup=main_menu_keyboard())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 Tap /menu for the button menu\n\nOr type commands:\n"
        "/status  /settings  /signal\n/autotrade on|off  /mode paper|live\n"
        "/risk daily <usd>\n/sl <price>  /tp <price>  /trail <percent>\n"
        "/cancel sl|tp|trail|all\n/sellnow  /guards  /checkguards  /price",
        reply_markup=main_menu_keyboard()
    )

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

    # --- Original command handlers ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("autotrade", autotrade))
    app.add_handler(CommandHandler("mode", mode))
    app.add_handler(CommandHandler("risk", risk))
    app.add_handler(CommandHandler("sellnow", sellnow))
    app.add_handler(CommandHandler("sl", set_sl))
    app.add_handler(CommandHandler("tp", set_tp))
    app.add_handler(CommandHandler("trail", set_trail))
    app.add_handler(CommandHandler("cancel", cancel_guard))
    app.add_handler(CommandHandler("signal", signal))
    app.add_handler(CommandHandler("guards", guards))
    app.add_handler(CommandHandler("checkguards", checkguards))
    app.add_handler(CommandHandler("price", price))

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

    return app
