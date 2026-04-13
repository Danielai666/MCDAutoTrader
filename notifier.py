# notifier.py
# Centralized Telegram notification helpers
import logging
from config import SETTINGS

log = logging.getLogger(__name__)


async def notify_admins(app, text: str):
    for aid in SETTINGS.TELEGRAM_ADMIN_IDS:
        try:
            await app.bot.send_message(chat_id=aid, text=text)
        except Exception as e:
            log.warning("Failed to notify admin %s: %s", aid, e)


async def notify_trade_opened(app, pair: str, side: str, qty: float, price: float, reason: str = ''):
    text = (
        f"Trade Opened\n"
        f"Pair: {pair}\n"
        f"Side: {side}\n"
        f"Qty: {qty:.6f}\n"
        f"Price: ${price:.2f}\n"
        f"Reason: {reason}"
    )
    await notify_admins(app, text)


async def notify_trade_closed(app, pair: str, side: str, pnl: float, reason: str = ''):
    emoji = '+' if pnl >= 0 else ''
    text = (
        f"Trade Closed\n"
        f"Pair: {pair}\n"
        f"Side: {side}\n"
        f"PnL: {emoji}${pnl:.2f}\n"
        f"Reason: {reason}"
    )
    await notify_admins(app, text)


async def notify_blocked_trade(app, pair: str, side: str, reason: str):
    text = f"Trade Blocked\nPair: {pair} {side}\nReason: {reason}"
    await notify_admins(app, text)


async def notify_health_issue(app, issue: str):
    text = f"Health Warning\n{issue}"
    await notify_admins(app, text)


async def notify_daily_report(app, report: str):
    await notify_admins(app, f"Daily Report\n{report}")
