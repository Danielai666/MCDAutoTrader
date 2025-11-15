# telegram_bot.py -- English-only version
import logging
import os
import time
from typing import Optional, Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import SETTINGS
from storage import execute, fetchone, fetchall
from trade_executor import close_all_for_pair, set_manual_guard, clear_manual_guard
from scheduler import schedule_jobs # run_cycle_once is imported lazily inside handlers

log = logging.getLogger(__name__)

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
 """
 Try to fetch the last price for SETTINGS.PAIR from Kraken via ccxt.
 Returns float or None on failure.
 """
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
 return {
 "sl": sl,
 "tp": tp,
 "trail_pct": trail_pct,
 "trail_stop": trail_stop,
 "high_wm": high_wm,
 }

def _save_trailing(uid: int, pair: str, trail_stop: Optional[float], high_wm: Optional[float]):
 execute(
 "UPDATE manual_guards SET trail_stop=?, high_watermark=? WHERE user_id=? AND pair=?",
 (trail_stop, high_wm, uid, pair),
 )

def _paper_close_all(pair: str, px: float) -> Tuple[int, float]:
 """
 Close all OPEN trades for pair in PAPER mode and return (closed_count, total_pnl).
 """
 now = int(time.time())
 rows = fetchall('SELECT id, side, qty, entry FROM trades WHERE status="OPEN" AND pair=?', (pair,))
 total_pnl = 0.0
 closed = 0
 for tid, side, qty, entry in rows:
 qty = float(qty)
 entry = float(entry)
 if side == "BUY":
 pnl = (px - entry) * qty
 else: # SELL
 pnl = (entry - px) * qty
 execute(
 'UPDATE trades SET exit=?, pnl=?, status="CLOSED", ts_close=? WHERE id=?',
 (px, pnl, now, tid),
 )
 total_pnl += pnl
 closed += 1
 return closed, total_pnl

async def auto_exit_task(application) -> None:
 """
 Periodic guard checker: SL / TP / Trailing -> close open trades & notify admin.
 """
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

 # SL / TP
 sl = guard.get("sl")
 tp = guard.get("tp")
 if isinstance(sl, (int, float)) and price <= float(sl):
 reason = f"SL hit @ {float(sl):g} (px={price:g})"
 if not reason and isinstance(tp, (int, float)) and price >= float(tp):
 reason = f"TP hit @ {float(tp):g} (px={price:g})"

 # Trailing (long-only): update high watermark and trailing stop below it
 trail_pct = guard.get("trail_pct")
 if not reason and isinstance(trail_pct, (int, float)) and float(trail_pct) > 0:
 high_wm = guard.get("high_wm")
 trail_stop = guard.get("trail_stop")
 updated = False

 # update high watermark if new high
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

 # Execute closing
 closed = 0
 total_pnl = None
 try:
 if SETTINGS.PAPER_TRADING:
 closed, total_pnl = _paper_close_all(pair, price)
 else:
 closed = close_all_for_pair(pair, f"auto_exit: {reason}") or 0
 except Exception as e:
 log.exception("auto-exit: closing failed: %s", e)

 # Notify admin
 try:
 lines = [
 "[WARNING] Auto-Exit Triggered",
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
# Commands
# ---------------------------
async def guards(update: Update, context: ContextTypes.DEFAULT_TYPE):
 """Show current manual guards for this user and pair."""
 uid = update.effective_user.id
 row = fetchone(
 'SELECT stop_loss, take_profit, trail_pct, trail_stop, high_watermark '
 'FROM manual_guards WHERE user_id=? AND pair=?',
 (uid, SETTINGS.PAIR)
 )
 if not row:
 await update.message.reply_text('No manual guards set for this pair.')
 return
 sl, tp, trail_pct, trail_stop, hwm = row
 lines = [
 f"Pair: {SETTINGS.PAIR}",
 f"SL: {sl if sl is not None else '-'}",
 f"TP: {tp if tp is not None else '-'}",
 f"Trail %: {trail_pct if trail_pct is not None else '-'}",
 f"Trail Stop: {trail_stop if trail_stop is not None else '-'}",
 f"HWM: {hwm if hwm is not None else '-'}",
 ]
 await update.message.reply_text("\n".join(lines))

async def checkguards(update: Update, context: ContextTypes.DEFAULT_TYPE):
 """Run one full analysis + guard check cycle and return result text."""
 from scheduler import run_cycle_once
 msg = await update.message.reply_text('Checking guards & analysis now...')
 res = await run_cycle_once(context.application, notify=True)
 await msg.edit_text(res)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
 """Return current price for SETTINGS.PAIR from Kraken."""
 px = _fetch_last_price()
 if px:
 await update.message.reply_text(f"{SETTINGS.PAIR} price: {px:g}")
 else:
 await update.message.reply_text("Failed to fetch price.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
 uid = update.effective_user.id
 uname = update.effective_user.username or ""
 execute(
 "INSERT OR IGNORE INTO users(user_id,tg_username,trial_start_ts) VALUES(?,?,?)",
 (uid, uname, int(time.time())),
 )
 await update.message.reply_text(
 "Welcome! 7-day trial activated.\n"
 "Use /signal for multi-timeframe analysis.\n"
 "Use /help to see all commands."
 )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
 await update.message.reply_text(
 "/start\n/status\n/settings\n/signal\n"
 "/autotrade on|off\n/mode paper|live\n"
 "/risk daily <usd>\n"
 "/sl <price> /tp <price> /trail <percent>\n"
 "/cancel sl|tp|trail|all\n"
 "/sellnow\n"
 "/guards\n/checkguards\n/price"
 )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
 uid = update.effective_user.id
 row = fetchone(
 "SELECT tier, autotrade_enabled, trade_mode, daily_loss_limit, max_open_trades "
 "FROM users WHERE user_id=?",
 (uid,),
 )
 if not row:
 await update.message.reply_text("Not registered. Use /start.")
 return
 tier, auto, mode, dll, mot = row
 auto_txt = "ON" if auto else "OFF"
 lines = [
 f"Tier: {tier}",
 f"Auto-Trade: {auto_txt}",
 f"Mode: {mode}",
 f"Pair: {SETTINGS.PAIR}",
 f"Daily Loss Limit: {dll}",
 f"Max Open Trades: {mot}",
 ]
 await update.message.reply_text("\n".join(lines))

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
 tfs = ", ".join(SETTINGS.TIMEFRAMES) if isinstance(SETTINGS.TIMEFRAMES, (list, tuple)) else str(SETTINGS.TIMEFRAMES)
 await update.message.reply_text(
 f"PAIR: {SETTINGS.PAIR}\nTIMEFRAMES: {tfs}\nPAPER: {SETTINGS.PAPER_TRADING}"
 )

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
 await update.message.reply_text(f"Auto-Trade {'enabled' if val else 'disabled'}.")

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
 await update.message.reply_text(f"Mode set to {m}.")

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
 await update.message.reply_text(f"Daily loss limit set to {val} USD.")

async def sellnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
 uid = update.effective_user.id
 if not admin_only(uid):
 await update.message.reply_text("Not allowed.")
 return
 closed = close_all_for_pair(SETTINGS.PAIR, "manual_sellnow") or 0
 await update.message.reply_text(f"Closed {closed} open trade(s).")

async def set_sl(update: Update, context: ContextTypes.DEFAULT_TYPE):
 uid = update.effective_user.id
 if not context.args:
 await update.message.reply_text("Usage: /sl <price>")
 return
 try:
 price = float(context.args[0])
 except Exception:
 await update.message.reply_text("Invalid number.")
 return
 set_manual_guard(uid, SETTINGS.PAIR, sl=price, tp=None, trail_pct=None)
 await update.message.reply_text(f"Stop-loss set at {price}.")

async def set_tp(update: Update, context: ContextTypes.DEFAULT_TYPE):
 uid = update.effective_user.id
 if not context.args:
 await update.message.reply_text("Usage: /tp <price>")
 return
 try:
 price = float(context.args[0])
 except Exception:
 await update.message.reply_text("Invalid number.")
 return
 set_manual_guard(uid, SETTINGS.PAIR, sl=None, tp=price, trail_pct=None)
 await update.message.reply_text(f"Take-profit set at {price}.")

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
 await update.message.reply_text(f"Trailing set at {pct*100:.2f}%.")

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
 await update.message.reply_text(f"Cleared: {w}.")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
 from scheduler import run_cycle_once
 msg = await update.message.reply_text("Running analysis...")
 res = await run_cycle_once(context.application, notify=False)
 await msg.edit_text(res)

# ---------------------------
# App builder + jobs
# ---------------------------
def build_app() -> Application:
 b = Application.builder().token(SETTINGS.TELEGRAM_BOT_TOKEN)

 # Optional proxy from settings
 if getattr(SETTINGS, "HTTPS_PROXY", None):
 os.environ["HTTPS_PROXY"] = SETTINGS.HTTPS_PROXY
 os.environ["HTTP_PROXY"] = SETTINGS.HTTPS_PROXY

 app = b.build()

 # Commands
 app.add_handler(CommandHandler("start", start))
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

 # Main strategy jobs (existing)
 schedule_jobs(app)

 # Auto-Exit guard job every 30s
 async def _guard_job(context):
 await auto_exit_task(context.application)

 app.job_queue.run_repeating(_guard_job, interval=30, first=15, name="auto_exit_guard")

 return app
