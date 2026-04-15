# panel.py
# Persistent inline control panel for the Telegram bot.
#
# Behaviour (per user spec):
#   - ONE inline message per user acts as the main control panel.
#   - Each action edits that same message in place (edit_message_text).
#   - If the edit fails (message deleted / too old / never existed), we
#     send a new panel and update the tracked message_id.
#   - A small ReplyKeyboardMarkup (Menu / Status / Panic Stop) sits above
#     the text input area so the user always has one-tap access.
#   - Controlled by FEATURE_CONTROL_PANEL; when disabled, the module's
#     keyboard/text helpers still return sane defaults so callers never
#     have to branch.
#
# Non-goals:
#   - No trading / strategy / DB schema changes.
#   - No removal of any existing callback_data values. This module builds
#     a new *layout* using the SAME callback_data strings the bot already
#     dispatches on, so all existing handlers keep working unchanged.

import logging
import time
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import SETTINGS

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Feature flag
# -------------------------------------------------------------------
def is_enabled() -> bool:
    return bool(getattr(SETTINGS, "FEATURE_CONTROL_PANEL", True))


# -------------------------------------------------------------------
# Per-user panel state (in memory)
# -------------------------------------------------------------------
# uid -> {'chat_id': int, 'message_id': int, 'updated_ts': float}
_panel_state: dict = {}

# uid -> {'direction': str, 'score': float, 'conf': float, 'ts': float}
_last_signal: dict = {}


def track_panel(uid: int, chat_id: int, message_id: int) -> None:
    """Record the (chat, message) id of the active control panel for a user."""
    _panel_state[uid] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "updated_ts": time.time(),
    }


def get_panel(uid: int) -> Optional[dict]:
    return _panel_state.get(uid)


def clear_panel(uid: int) -> None:
    _panel_state.pop(uid, None)


def track_last_signal(uid: int, direction: str, score: float = 0.0, conf: float = 0.0) -> None:
    """Lightweight hook — callers may record the most recent signal for header display."""
    _last_signal[uid] = {
        "direction": direction,
        "score": float(score or 0.0),
        "conf": float(conf or 0.0),
        "ts": time.time(),
    }


# -------------------------------------------------------------------
# Keyboard layout (reorganized grid — SAME callback_data values as before)
# -------------------------------------------------------------------
def build_panel_keyboard() -> InlineKeyboardMarkup:
    """
    Modern grid layout.
    Every callback_data MUST match an existing button_callback dispatch case.
    Extra buttons that existed in the old menu are placed in rows 7-10 so
    nothing is removed.
    """
    rows = [
        # Row 1 — Core read-outs
        [
            InlineKeyboardButton("📊 Signal", callback_data="cmd_signal"),
            InlineKeyboardButton("📈 Status", callback_data="cmd_status"),
            InlineKeyboardButton("💼 Positions", callback_data="cmd_positions_card"),
        ],
        # Row 2 — Risk / AI / Report
        [
            InlineKeyboardButton("⚙️ Risk", callback_data="menu_risk"),
            InlineKeyboardButton("🤖 AI Card", callback_data="cmd_ai_card"),
            InlineKeyboardButton("📉 Report", callback_data="menu_reporting"),
        ],
        # Row 3 — Trading controls
        [
            InlineKeyboardButton("🔁 AutoTrade", callback_data="menu_autotrade"),
            InlineKeyboardButton("🧪 Mode", callback_data="menu_mode"),
            InlineKeyboardButton("🔌 Connect", callback_data="cmd_connect"),
        ],
        # Row 4 — Analysis tools
        [
            InlineKeyboardButton("📊 Backtest", callback_data="cmd_backtest"),
            InlineKeyboardButton("🔍 Analyze", callback_data="cmd_analyze_screens"),
            InlineKeyboardButton("🧠 Insights", callback_data="cmd_ai"),
        ],
        # Row 5 — Guards / board / heatmap
        [
            InlineKeyboardButton("🛡 Guards", callback_data="cmd_guards"),
            InlineKeyboardButton("⚠️ Risk Board", callback_data="cmd_risk_board"),
            InlineKeyboardButton("🔥 Heatmap", callback_data="cmd_heatmap"),
        ],
        # Row 6 — Panic / account / admin
        [
            InlineKeyboardButton("🚨 PANIC", callback_data="cmd_panic_stop"),
            InlineKeyboardButton("👤 Account", callback_data="cmd_myaccount"),
            InlineKeyboardButton("🧩 Admin", callback_data="menu_admin"),
        ],
        # Row 7 — Extras (preserved from the old menu, none removed)
        [
            InlineKeyboardButton("💰 Price", callback_data="cmd_price"),
            InlineKeyboardButton("💚 Health", callback_data="cmd_health_stats"),
            InlineKeyboardButton("🚀 Go Live", callback_data="cmd_golive"),
        ],
        # Row 8 — Visuals / pairs / check guards
        [
            InlineKeyboardButton("🎨 Visuals", callback_data="cmd_visuals"),
            InlineKeyboardButton("🌐 Pairs", callback_data="menu_pairs"),
            InlineKeyboardButton("🔍 Check", callback_data="cmd_checkguards"),
        ],
        # Row 9 — Manual exit / guard setters / cancel
        [
            InlineKeyboardButton("🛑 Sell Now", callback_data="cmd_sellnow"),
            InlineKeyboardButton("📐 SL/TP/Trail", callback_data="menu_guards_set"),
            InlineKeyboardButton("❌ Cancel", callback_data="menu_cancel"),
        ],
        # Row 10 — Disconnect
        [InlineKeyboardButton("🔌 Disconnect", callback_data="cmd_disconnect")],
    ]
    return InlineKeyboardMarkup(rows)


def bottom_reply_keyboard() -> ReplyKeyboardMarkup:
    """Always-visible row above the Telegram text input."""
    return ReplyKeyboardMarkup(
        [[
            KeyboardButton("Menu"),
            KeyboardButton("Status"),
            KeyboardButton("Panic Stop"),
        ]],
        resize_keyboard=True,
        is_persistent=True,
    )


# -------------------------------------------------------------------
# Dynamic header
# -------------------------------------------------------------------
def _load_user_row(uid: int) -> dict:
    """Best-effort fetch of the user's mode + autotrade flag from the users table."""
    try:
        from storage import fetchone
        row = fetchone(
            "SELECT trade_mode, autotrade_enabled FROM users WHERE user_id=?",
            (uid,),
        )
        if not row:
            return {}
        return {
            "mode": (row[0] or "PAPER").upper(),
            "autotrade": bool(row[1]),
        }
    except Exception as e:
        log.debug("panel._load_user_row failed: %s", e)
        return {}


def _active_pairs(uid: int) -> list:
    try:
        from pair_manager import get_active_pairs
        pairs = get_active_pairs(user_id=uid)
        if pairs:
            return list(pairs)
    except Exception:
        pass
    # Fallback — global defaults
    try:
        return list(SETTINGS.DEFAULT_PAIRS or [])
    except Exception:
        return []


def _system_status() -> str:
    """Coarse OK/Warning signal — kill switch or panic state trigger Warning."""
    try:
        if getattr(SETTINGS, "KILL_SWITCH", False):
            return "⚠️ KILL SWITCH"
        if getattr(SETTINGS, "DRY_RUN_MODE", False):
            return "🟡 DRY RUN"
    except Exception:
        pass
    return "🟢 OK"


def build_panel_text(uid: int) -> str:
    user = _load_user_row(uid)
    mode = user.get("mode", "PAPER")
    autotrade = "ON" if user.get("autotrade") else "OFF"

    pairs = _active_pairs(uid)
    pairs_str = ", ".join(p.split("/")[0] for p in pairs[:5]) if pairs else "—"
    if len(pairs) > 5:
        pairs_str += f" (+{len(pairs) - 5})"

    sig = _last_signal.get(uid)
    if sig:
        last = f"{sig['direction']} (s={sig['score']:.2f}, c={sig['conf']:.2f})"
    else:
        last = "—"

    status = _system_status()

    return (
        "*MCDAutoTrader Control Panel*\n"
        f"Mode: `{mode}`   AutoTrade: `{autotrade}`\n"
        f"Pairs: `{pairs_str}`\n"
        f"Last Signal: `{last}`\n"
        f"System: {status}\n\n"
        "Select an action:"
    )


# -------------------------------------------------------------------
# Refresh (edit-in-place with fallback to send)
# -------------------------------------------------------------------
async def refresh_panel(bot, chat_id: int, uid: int, status_line: Optional[str] = None) -> None:
    """
    Try to edit the user's tracked panel message. If the edit fails for any
    reason (message deleted, too old, never sent, different chat), send a
    fresh panel message and re-track it.

    `status_line`, if provided, is appended to the header for one render —
    useful to show a small "✅ AutoTrade enabled" acknowledgement line.
    """
    if not is_enabled():
        return

    text = build_panel_text(uid)
    if status_line:
        text += f"\n\n_{status_line}_"

    markup = build_panel_keyboard()
    tracked = _panel_state.get(uid)

    # Try edit first
    if tracked and tracked.get("chat_id") == chat_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=tracked["message_id"],
                text=text,
                reply_markup=markup,
                parse_mode="Markdown",
            )
            tracked["updated_ts"] = time.time()
            return
        except Exception as e:
            # Edit failed (deleted, too old, identical content, etc.). Fall through to send.
            log.debug("panel.refresh_panel edit failed for uid=%s: %s", uid, e)

    # Send fresh
    try:
        msg = await bot.send_message(
            chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown"
        )
        track_panel(uid, chat_id, msg.message_id)
    except Exception as e:
        log.warning("panel.refresh_panel send failed for uid=%s: %s", uid, e)


async def send_with_panel_refresh(bot, chat_id: int, uid: int, send_coro) -> None:
    """
    Helper: await a send coroutine (e.g. sending a chart), then refresh the
    control panel so it surfaces again below the out-of-band output.

    Usage:
        await send_with_panel_refresh(
            bot, chat_id, uid,
            bot.send_photo(chat_id=chat_id, photo=buf, caption=...),
        )
    """
    try:
        await send_coro
    finally:
        try:
            await refresh_panel(bot, chat_id, uid)
        except Exception as e:
            log.debug("panel refresh after send failed: %s", e)
