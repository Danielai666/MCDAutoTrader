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
# uid -> {'chat_id': int, 'message_id': int, 'updated_ts': float,
#         'last_rendered_hash': str}
_panel_state: dict = {}

# uid -> {'direction': str, 'score': float, 'conf': float, 'ts': float}
_last_signal: dict = {}

# uid -> 'healthy' | 'busy' | 'error'
_user_state: dict = {}
# uid -> {'text': str, 'ts': float}
_last_action: dict = {}


def track_panel(uid: int, chat_id: int, message_id: int) -> None:
    """Record the (chat, message) id of the active control panel for a user."""
    _panel_state[uid] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "updated_ts": time.time(),
        "last_rendered_hash": "",
    }


# -------------------------------------------------------------------
# Live dashboard state: system status, last action, toast labels
# -------------------------------------------------------------------
def set_state(uid: int, state: str) -> None:
    """Per-user system state: 'healthy' | 'busy' | 'error'."""
    if state in ("healthy", "busy", "error"):
        _user_state[uid] = state


def get_state(uid: int) -> str:
    return _user_state.get(uid, "healthy")


def set_last_action(uid: int, text: str) -> None:
    _last_action[uid] = {"text": text, "ts": time.time()}


def get_last_action(uid: int) -> Optional[dict]:
    return _last_action.get(uid)


# Maps inline callback_data values to short, human-readable action labels.
# Used for:
#   - Telegram toast on button press (query.answer(text=...))
#   - "Last Action" line in the panel header
# Unlisted keys fall back to a generic "Working..." / "Action performed".
CALLBACK_LABELS = {
    "cmd_menu": "Menu",
    "cmd_signal": "Signal fetched",
    "cmd_price": "Price refreshed",
    "cmd_status": "Status refreshed",
    "cmd_settings": "Settings loaded",
    "cmd_guards": "Guards listed",
    "cmd_checkguards": "Guards checked",
    "cmd_positions": "Positions loaded",
    "cmd_positions_card": "Positions card rendered",
    "cmd_pnl": "PnL report",
    "cmd_trades": "Recent trades",
    "cmd_blocked": "Blocked signals",
    "cmd_report": "Full report",
    "cmd_pairs": "Pairs listed",
    "cmd_ranking": "Ranking loaded",
    "cmd_ai": "AI status",
    "cmd_ai_card": "AI card rendered",
    "cmd_heatmap": "Heatmap rendered",
    "cmd_risk_board": "Risk board rendered",
    "cmd_backtest": "Backtest started",
    "cmd_visuals": "Visuals rendered",
    "cmd_myaccount": "Account loaded",
    "cmd_health": "Health checked",
    "cmd_health_stats": "Health stats",
    "cmd_golive": "Go-live wizard",
    "cmd_panic_stop": "PANIC STOP",
    "cmd_analyze_screens": "Analyze session started",
    "cmd_connect": "Connect exchange",
    "cmd_disconnect": "Disconnect",
    "cmd_killswitch": "Kill switch toggled",
    "cmd_reconcile": "Reconcile",
    "cmd_liveready": "Live readiness",
    "cmd_sellnow": "Sell now",
    "cmd_autotrade_on": "AutoTrade ON",
    "cmd_autotrade_off": "AutoTrade OFF",
    "cmd_mode_paper": "Mode: PAPER",
    "cmd_mode_live": "Mode: LIVE",
    "cmd_cancel_sl": "SL cancelled",
    "cmd_cancel_tp": "TP cancelled",
    "cmd_cancel_trail": "Trail cancelled",
    "cmd_cancel_all": "Guards cancelled",
    # Submenus (fast, but still give feedback)
    "menu_autotrade": "AutoTrade menu",
    "menu_mode": "Mode menu",
    "menu_risk": "Risk menu",
    "menu_guards_set": "Guards setup menu",
    "menu_cancel": "Cancel menu",
    "menu_reporting": "Reporting menu",
    "menu_pairs": "Pairs menu",
    "menu_admin": "Admin menu",
    # Prompts (text-input flows)
    "prompt_sl": "Set Stop Loss",
    "prompt_tp": "Set Take Profit",
    "prompt_trail": "Set Trailing %",
    "prompt_addpair": "Add pair",
    "prompt_rmpair": "Remove pair",
}


def label_for(callback_data: str) -> str:
    """Short human label for a callback_data. Safe for unknown keys."""
    if not callback_data:
        return "Working"
    if callback_data in CALLBACK_LABELS:
        return CALLBACK_LABELS[callback_data]
    # Generic prefix-based fallbacks for patterns like cmd_risk_100
    if callback_data.startswith("cmd_risk_"):
        return f"Risk set ${callback_data.split('_')[-1]}"
    if callback_data.startswith("conn_ex_"):
        return f"Connecting {callback_data.split('_')[-1].upper()}"
    return callback_data.replace("_", " ").title()


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


def _system_status(uid: int) -> str:
    """Three-state health indicator. Per-user runtime state takes precedence,
    then global kill-switch / dry-run flags, else Healthy."""
    # Runtime state set by button_callback pre/post hooks
    state = _user_state.get(uid, "healthy")
    if state == "busy":
        return "🟡 System: Busy"
    if state == "error":
        return "🔴 System: Error"
    # Global flags override Healthy
    try:
        if getattr(SETTINGS, "KILL_SWITCH", False):
            return "🔴 System: Kill Switch"
        if getattr(SETTINGS, "DRY_RUN_MODE", False):
            return "🟡 System: Dry Run"
    except Exception:
        pass
    return "🟢 System: Healthy"


def _signal_glyph(direction: str) -> str:
    """Directional emoji for the last signal line."""
    d = (direction or "").upper()
    if d in ("BUY", "BULL", "BULLISH"):
        return "📈"
    if d in ("SELL", "BEAR", "BEARISH"):
        return "📉"
    if d in ("WARN", "WARNING", "RISK"):
        return "⚠️"
    return "➖"


def _open_trades_count(uid: int) -> int:
    """Best-effort active-trade count for the header."""
    try:
        from storage import fetchone
        row = fetchone(
            "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND user_id=?",
            (uid,),
        )
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


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
        glyph = _signal_glyph(sig.get("direction", ""))
        last_sig = f"{glyph} {sig['direction']} (s={sig['score']:.2f}, c={sig['conf']:.2f})"
    else:
        last_sig = "—"

    status = _system_status(uid)
    open_n = _open_trades_count(uid)

    last_act = _last_action.get(uid)
    if last_act:
        act_age = int(time.time() - last_act["ts"])
        if act_age < 60:
            act_age_str = f"{act_age}s ago"
        elif act_age < 3600:
            act_age_str = f"{act_age // 60}m ago"
        else:
            act_age_str = f"{act_age // 3600}h ago"
        last_action_line = f"Last Action: `{last_act['text']}` _({act_age_str})_"
    else:
        last_action_line = "Last Action: `—`"

    return (
        "*MCDAutoTrader Control Panel*\n"
        f"Mode: `{mode}`   AutoTrade: `{autotrade}`   Open: `{open_n}`\n"
        f"Pairs: `{pairs_str}`\n"
        f"Last Signal: {last_sig}\n"
        f"{last_action_line}\n"
        f"{status}\n\n"
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

    # Content-hash dedupe: if nothing changed, skip the API call. This prevents
    # the auto-refresh job from spamming Telegram with "message is not modified"
    # errors and saves rate-limit budget.
    import hashlib
    content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()

    # Try edit first
    if tracked and tracked.get("chat_id") == chat_id:
        if tracked.get("last_rendered_hash") == content_hash:
            return  # nothing changed — skip API call entirely
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=tracked["message_id"],
                text=text,
                reply_markup=markup,
                parse_mode="Markdown",
            )
            tracked["updated_ts"] = time.time()
            tracked["last_rendered_hash"] = content_hash
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
        if uid in _panel_state:
            _panel_state[uid]["last_rendered_hash"] = content_hash
    except Exception as e:
        log.warning("panel.refresh_panel send failed for uid=%s: %s", uid, e)


async def auto_refresh_all(bot) -> None:
    """
    Background job: periodically refresh every tracked panel.

    Safety rails:
      - Skips users whose panel hasn't been interacted with in > 10 min
        (stale — no point polling Telegram for it).
      - refresh_panel() dedupes by content hash, so unchanged panels do NOT
        hit the Telegram API at all.
      - Catches per-user exceptions so one failing panel never blocks the rest.
      - Also auto-clears a stale 'busy' state > 30s old (failsafe if a handler
        forgot to reset it on an unusual exit path).
    """
    if not is_enabled():
        return

    now = time.time()
    STALE_AFTER = 600  # 10 min
    BUSY_TIMEOUT = 30  # seconds

    # Snapshot keys — panel state can mutate during iteration.
    uids = list(_panel_state.keys())
    for uid in uids:
        tracked = _panel_state.get(uid)
        if not tracked:
            continue
        if now - tracked.get("updated_ts", 0) > STALE_AFTER:
            continue

        # Clear stuck busy state so header doesn't lie.
        if _user_state.get(uid) == "busy":
            last_act = _last_action.get(uid)
            if last_act and now - last_act.get("ts", 0) > BUSY_TIMEOUT:
                _user_state[uid] = "healthy"

        try:
            await refresh_panel(bot, tracked["chat_id"], uid)
        except Exception as e:
            log.debug("auto_refresh_all for uid=%s failed: %s", uid, e)


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
