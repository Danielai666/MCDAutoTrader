# telegram_bot.py
import logging, time, os
from typing import Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import SETTINGS
from storage import execute, fetchone, fetchall
from trade_executor import close_all_for_pair, set_manual_guard, clear_manual_guard
from scheduler import schedule_jobs

log = logging.getLogger(__name__)

# ---------------------------
# Globals
# ---------------------------
PAIR_TXT = SETTINGS.PAIR
PAIR_DB  = PAIR_TXT.replace('/', '')

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
def _fetch_last_price() -> Optional[float]:
    try:
        import ccxt
        ex = ccxt.kraken()
        t = ex.fetch_ticker(SETTINGS.PAIR)
        for k in ("last", "close", "bid", "ask"):
            v = t.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
    except Exception as e:
        log.warning("auto-exit: fetch price failed: %s", e)
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
            "UPDATE trades SET exit=?, pnl=?, status='CLOSED', ts_close=? WHERE id=?",
            (px, pnl, now, tid),
        )
        total_pnl += pnl
        closed += 1
    return closed, total_pnl

async def auto_exit_task(application) -> None:
    admin_id = _get_admin_id()
    pair = SETTINGS.PAIR
    if not admin_id:
        return

    guard = _load_guard(admin_id, pair)
    if not guard:
        return

    price = _fetch_last_price()
    if not price or price <= 0:
        return

    reason = None

    sl = guard.get("sl")
    tp = guard.get("tp")
    if isinstance(sl, (int, float)) and price <= float(sl):
        reason = f"SL hit @ {float(sl):g} (px={price:g})"
    if not reason and isinstance(tp, (int, float)) and price >= float(tp):
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
            log.info("auto-exit: trail updated high=%.6f stop=%.6f", high_wm, trail_stop or -1)

    if not reason:
        return

    key = (admin_id, pair, reason)
    now_ts = int(time.time())
    last_ts = LAST_NOTIFY.get(key, 0)
    if now_ts - last_ts < NOTIFY_COOLDOWN:
        return
    LAST_NOTIFY[key] = now_ts

    closed = 0
    total_pnl = None
    try:
        if SETTINGS.PAPER_TRADING:
            closed, total_pnl = _paper_close_all(pair, price)
        else:
            closed = close_all_for_pair(pair, f"auto_exit: {reason}") or 0
    except Exception as e:
        log.exception("auto-exit: closing failed: %s", e)

    try:
        lines = [
            "⚠️ Auto-Exit Triggered",
            f"Pair: {pair}",
            f"Reason: {reason}",
            f"Price: {price:g}",
            f"Closed trades: {closed}",
        ]
        if total_pnl is not None:
            lines.append(f"PnL (paper): {total_pnl:.2f}")
        await application.bot.send_message(chat_id=admin_id, text="\n".join(lines))
    except Exception as e:
        log.warning("auto-exit: notify failed: %s", e)

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
    lines = [
        "📈 Status",
        f"Tier: {tier}",
        f"Auto-Trade: {'✅ ON' if auto else '⛔ OFF'}",
        f"Mode: {'🔴 LIVE' if mode_val == 'LIVE' else '📝 PAPER'}",
        f"Pair: {SETTINGS.PAIR}",
        f"Daily Loss Limit: ${dll}",
        f"Max Open Trades: {mot}",
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

# ---------------------------
# Text handler for pending input (SL/TP/Trail values)
# ---------------------------
async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in PENDING_INPUT:
        return  # not waiting for input, ignore

    pending = PENDING_INPUT.pop(uid)
    txt = update.message.text.strip()
    try:
        val = float(txt)
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Try again from menu.", reply_markup=back_keyboard())
        return

    ptype = pending["type"]
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
    execute(
        "INSERT OR IGNORE INTO users(user_id,tg_username,trial_start_ts) VALUES(?,?,?)",
        (uid, uname, int(time.time())),
    )
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

# ---------------------------
# App builder + jobs
# ---------------------------
def build_app() -> Application:
    b = Application.builder().token(SETTINGS.TELEGRAM_BOT_TOKEN)

    if getattr(SETTINGS, "HTTPS_PROXY", None):
        os.environ["HTTPS_PROXY"] = SETTINGS.HTTPS_PROXY
        os.environ["HTTP_PROXY"] = SETTINGS.HTTPS_PROXY

    app = b.build()

    # Command handlers
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

    # Callback handler for inline buttons
    app.add_handler(CallbackQueryHandler(button_callback))

    # Text handler for pending SL/TP/Trail input
    from telegram.ext import MessageHandler, filters
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    # Main strategy jobs
    schedule_jobs(app)

    # Auto-Exit guard job every 30s
    async def _guard_job(context):
        await auto_exit_task(context.application)

    app.job_queue.run_repeating(_guard_job, interval=30, first=15, name="auto_exit_guard")

    return app
