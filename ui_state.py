# ui_state.py
# System-wide UX standard for state visibility.
#
# Every control in the bot MUST render through one of these three helpers:
#   1. render_setting_menu(...)      — before change: current state + meaning + options
#   2. render_change_confirmation(...) — after change: previous + new + effect
#   3. toggle_button_label(...)       — in-keyboard: state-aware button labels
#
# State introspection lives in one place (CONTROLS registry), so a handler
# only ever needs:
#     state = get_control_state(uid, 'autotrade')
#     text  = render_setting_menu('AutoTrade', state)
# and never reads user_settings / users / SETTINGS directly for UX text.
#
# Bilingual-safe: every label/meaning string goes through i18n.t() with a
# hardcoded English fallback if the key or translation isn't present.

from typing import Callable, Optional


# -------------------------------------------------------------------
# i18n-safe translator (best-effort; returns fallback on any failure)
# -------------------------------------------------------------------
def _tr(uid: Optional[int], key: str, fallback: str) -> str:
    try:
        from i18n import t as _t
        val = _t(uid, key) if uid is not None else _t(None, key)
        return val if val and val != key else fallback
    except Exception:
        return fallback


# -------------------------------------------------------------------
# Visual glyphs — unambiguous color semantics
# -------------------------------------------------------------------
GLYPH_ON = "🟢"         # active / enabled / healthy
GLYPH_OFF = "🔴"        # inactive / disabled / blocked
GLYPH_WARN = "🟡"       # partial / pending / caution
GLYPH_INFO = "🔵"       # neutral / informational
GLYPH_LIVE = "🔴"       # LIVE mode = real money = red (stop-sign semantics)
GLYPH_PAPER = "🧪"      # paper / sim
GLYPH_FIRE = "🔥"       # aggressive
GLYPH_SHIELD = "🛡"     # safe / conservative


# -------------------------------------------------------------------
# Control state introspection
# -------------------------------------------------------------------
def _get_user_flag(uid: int, column: str, default=0):
    try:
        from storage import fetchone
        row = fetchone(f"SELECT {column} FROM users WHERE user_id=?", (uid,))
        if row and row[0] is not None:
            return row[0]
    except Exception:
        pass
    return default


def _get_user_settings_flag(uid: int, key: str, default=0):
    try:
        from storage import get_user_settings
        s = get_user_settings(uid) or {}
        return s.get(key, default)
    except Exception:
        return default


def _state_autotrade(uid: int) -> dict:
    val = int(_get_user_flag(uid, "autotrade_enabled", 0))
    on = val == 1
    return {
        "raw": val,
        "on": on,
        "label": "ON" if on else "OFF",
        "glyph": GLYPH_ON if on else GLYPH_OFF,
        "meaning_en": ("bot can open trades automatically" if on
                       else "autonomous trading is disabled"),
        "meaning_key": "state_meaning_autotrade_on" if on else "state_meaning_autotrade_off",
        "effect_on_en": "bot is now allowed to execute trades",
        "effect_off_en": "bot will no longer open new trades automatically",
    }


def _state_panic(uid: int) -> dict:
    val = int(_get_user_settings_flag(uid, "panic_stop", 0) or 0)
    active = val == 1
    return {
        "raw": val,
        "on": active,
        "label": "ACTIVE" if active else "INACTIVE",
        "glyph": GLYPH_OFF if active else GLYPH_ON,
        "meaning_en": ("all trading blocked; open positions were closed" if active
                       else "trading permitted; no emergency brake"),
        "meaning_key": "state_meaning_panic_active" if active else "state_meaning_panic_inactive",
        "effect_on_en": "all autonomous trading is now blocked and open positions are closed",
        "effect_off_en": "panic brake released; autotrade must still be re-enabled manually",
    }


def _state_mode(uid: int) -> dict:
    try:
        from storage import fetchone
        row = fetchone("SELECT trade_mode FROM users WHERE user_id=?", (uid,))
        val = (row[0] if row and row[0] else "PAPER").upper()
    except Exception:
        val = "PAPER"
    is_live = val == "LIVE"
    return {
        "raw": val,
        "on": is_live,
        "label": val,
        "glyph": GLYPH_LIVE if is_live else GLYPH_PAPER,
        "meaning_en": ("real trades are placed on your connected exchange" if is_live
                       else "simulated trading only; no real funds at risk"),
        "meaning_key": "state_meaning_mode_live" if is_live else "state_meaning_mode_paper",
        "effect_on_en": "real trades are now allowed on your exchange account",
        "effect_off_en": "trading returns to paper simulation; no real funds at risk",
    }


def _state_killswitch(_uid: int) -> dict:
    try:
        from config import SETTINGS
        on = bool(SETTINGS.KILL_SWITCH)
    except Exception:
        on = False
    return {
        "raw": 1 if on else 0,
        "on": on,
        "label": "ON" if on else "OFF",
        "glyph": GLYPH_OFF if on else GLYPH_ON,
        "meaning_en": ("global kill switch engaged — ALL users are blocked" if on
                       else "global trading is permitted (subject to per-user guards)"),
        "meaning_key": "state_meaning_killswitch_on" if on else "state_meaning_killswitch_off",
        "effect_on_en": "global trading is now halted for every user",
        "effect_off_en": "global trading is now permitted (per-user guards still apply)",
    }


def _state_aggressive(_uid: int) -> dict:
    try:
        from config import (SETTINGS, get_ai_confidence_min, get_signal_score_min,
                            get_adx_trend_min)
        on = bool(SETTINGS.AGGRESSIVE_TEST_MODE)
        conf = get_ai_confidence_min()
        score = get_signal_score_min()
        adx = get_adx_trend_min()
    except Exception:
        on, conf, score, adx = False, 0.65, 0.60, 20.0
    if on:
        meaning = (f"lowered gates (conf≥{conf:.2f}, score≥{score:.2f}, ADX≥{adx:.0f}) "
                   f"— more signals, risk caps unchanged")
    else:
        meaning = (f"safe gates (conf≥{conf:.2f}, score≥{score:.2f}, ADX≥{adx:.0f}) "
                   f"— conservative signal filtering")
    return {
        "raw": 1 if on else 0,
        "on": on,
        "label": "ON" if on else "OFF",
        "glyph": GLYPH_FIRE if on else GLYPH_SHIELD,
        "meaning_en": meaning,
        "meaning_key": "state_meaning_aggressive_on" if on else "state_meaning_aggressive_off",
        "effect_on_en": ("signal thresholds lowered: bot generates more entry candidates; "
                         "stop-loss, exposure caps, daily loss limits unchanged"),
        "effect_off_en": "signal thresholds restored to safe defaults",
    }


def _state_daily_loss(uid: int) -> dict:
    from config import SETTINGS
    val = _get_user_flag(uid, "daily_loss_limit", SETTINGS.DAILY_LOSS_LIMIT_USD)
    try:
        val = float(val)
    except Exception:
        val = float(SETTINGS.DAILY_LOSS_LIMIT_USD)
    return {
        "raw": val,
        "on": None,
        "label": f"${val:,.2f}",
        "glyph": GLYPH_INFO,
        "meaning_en": f"autotrade halts for the day once realized PnL reaches −${val:,.0f}",
        "meaning_key": "state_meaning_daily_loss",
        "effect_on_en": f"daily realized-loss cap is now −${val:,.0f}",
        "effect_off_en": "daily loss limit updated",
    }


def _state_capital(uid: int) -> dict:
    from config import SETTINGS
    val = _get_user_flag(uid, "capital_usd", SETTINGS.CAPITAL_USD)
    try:
        val = float(val)
    except Exception:
        val = float(SETTINGS.CAPITAL_USD)
    return {
        "raw": val,
        "on": None,
        "label": f"${val:,.2f}",
        "glyph": GLYPH_INFO,
        "meaning_en": f"position sizing uses ${val:,.0f} as your account base",
        "meaning_key": "state_meaning_capital",
        "effect_on_en": f"position sizing will now use ${val:,.0f} as the base",
        "effect_off_en": "capital updated",
    }


def _state_max_exposure(uid: int) -> dict:
    from config import SETTINGS
    val = _get_user_flag(uid, "max_portfolio_exposure", SETTINGS.MAX_PORTFOLIO_EXPOSURE)
    try:
        val = float(val)
    except Exception:
        val = float(SETTINGS.MAX_PORTFOLIO_EXPOSURE)
    capital_row = _get_user_flag(uid, "capital_usd", SETTINGS.CAPITAL_USD)
    try:
        cap = float(capital_row)
    except Exception:
        cap = float(SETTINGS.CAPITAL_USD)
    return {
        "raw": val,
        "on": None,
        "label": f"{val * 100:.0f}%",
        "glyph": GLYPH_INFO,
        "meaning_en": f"open exposure is capped at {val*100:.0f}% of capital (${cap*val:,.0f})",
        "meaning_key": "state_meaning_max_exposure",
        "effect_on_en": f"open exposure is now capped at {val*100:.0f}% (${cap*val:,.0f})",
        "effect_off_en": "max exposure updated",
    }


# Registry — one name per control, one introspector per name.
CONTROLS: dict = {
    "autotrade":      _state_autotrade,
    "panic":          _state_panic,
    "mode":           _state_mode,
    "killswitch":     _state_killswitch,
    "aggressive":     _state_aggressive,
    "daily_loss":     _state_daily_loss,
    "capital":        _state_capital,
    "max_exposure":   _state_max_exposure,
}


def get_control_state(uid: Optional[int], control: str) -> dict:
    """Introspect and return a canonical state dict for a control.
    Always returns a dict with at least {raw, on, label, glyph, meaning_en, icon}."""
    fn = CONTROLS.get(control)
    default_icon = SECTION_ICON.get(control, "⚙️")
    if fn is None:
        return {"raw": None, "on": None, "label": "?", "glyph": "",
                "meaning_en": "", "meaning_key": "", "icon": default_icon}
    try:
        result = fn(uid) if uid is not None else fn(0)
        result.setdefault("icon", default_icon)
        return result
    except Exception:
        return {"raw": None, "on": None, "label": "?", "glyph": "",
                "meaning_en": "", "meaning_key": "", "icon": default_icon}


# -------------------------------------------------------------------
# Text renderers — the three canonical UX outputs
# -------------------------------------------------------------------
def _section_bar() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


def render_current_state(title: str, state: dict, uid: Optional[int] = None) -> str:
    """Compact status block. Single-use — usually embedded in a larger message."""
    label = state.get("label", "?")
    glyph = state.get("glyph", "")
    meaning = _tr(uid, state.get("meaning_key", ""), state.get("meaning_en", "")) \
        if state.get("meaning_key") else state.get("meaning_en", "")
    current_lbl = _tr(uid, "ui_current", "Current")
    effect_lbl = _tr(uid, "ui_effect", "Effect")
    lines = [
        f"*{title}*",
        f"{current_lbl}: *{label}* {glyph}",
    ]
    if meaning:
        lines.append(f"_{effect_lbl}: {meaning}_")
    return "\n".join(lines)


# Section icon per control name — uses the same registry key as CONTROLS.
# Falls back to ⚙️ when a caller passes a one-off title not in this map.
SECTION_ICON = {
    "autotrade":    "🤖",
    "panic":        "🚨",
    "mode":         "⚙️",
    "killswitch":   "🔴",
    "aggressive":   "🔥",
    "daily_loss":   "🎯",
    "capital":      "💰",
    "max_exposure": "📈",
}


def render_setting_menu(title: str, state: dict, options_hint: Optional[str] = None,
                        uid: Optional[int] = None, icon: Optional[str] = None) -> str:
    """Pre-change menu: full header with bar, current value, MEANING, options hint.

    Per UX standard:
      • Pre-change uses the label 'Meaning:' — explains what the CURRENT state
        does right now.
      • Post-change (render_change_confirmation) uses the label 'Effect:' —
        explains what just happened as a result of the user's action.

    `icon` — the section icon in the title row. If not passed, resolves from
    state.get('icon') or SECTION_ICON[state_name]. Defaults to ⚙️.

    Use this as the MESSAGE BODY of any control submenu."""
    label = state.get("label", "?")
    glyph = state.get("glyph", "")
    meaning = _tr(uid, state.get("meaning_key", ""), state.get("meaning_en", "")) \
        if state.get("meaning_key") else state.get("meaning_en", "")
    current_lbl = _tr(uid, "ui_current", "Current")
    meaning_lbl = _tr(uid, "ui_meaning", "Meaning")
    choose_lbl = _tr(uid, "ui_choose_action", "Choose an action:")
    section_icon = icon or state.get("icon") or "⚙️"
    bar = _section_bar()
    lines = [
        bar,
        f"{section_icon} *{title.upper()}*",
        bar,
        "",
        f"{current_lbl}: *{label}* {glyph}",
    ]
    if meaning:
        lines.append(f"{meaning_lbl}: _{meaning}_")
    lines.append("")
    if options_hint:
        lines.append(f"{options_hint}")
    else:
        lines.append(choose_lbl)
    return "\n".join(lines)


def render_change_confirmation(title: str, previous: dict, new: dict,
                               uid: Optional[int] = None,
                               effect_override: Optional[str] = None) -> str:
    """Post-change confirmation: Previous → New → Effect.

    `previous` and `new` are state dicts (as returned by get_control_state).
    If `effect_override` is provided it replaces the auto-selected effect
    line — useful for conditional effects like panic + closed positions."""
    prev_lbl = f"{previous.get('label', '?')} {previous.get('glyph', '')}".rstrip()
    new_lbl = f"{new.get('label', '?')} {new.get('glyph', '')}".rstrip()

    if effect_override is not None:
        effect_text = effect_override
    else:
        turning_on = bool(new.get("on")) and not bool(previous.get("on"))
        turning_off = (previous.get("on") is True) and (new.get("on") is False)
        if turning_on:
            effect_text = new.get("effect_on_en", "")
        elif turning_off:
            effect_text = new.get("effect_off_en", "")
        else:
            # numeric setting or no-op
            effect_text = new.get("effect_on_en") or new.get("meaning_en", "")

    updated_lbl = _tr(uid, "ui_updated", "updated")
    prev_w = _tr(uid, "ui_previous", "Previous")
    new_w = _tr(uid, "ui_new", "New")
    eff_w = _tr(uid, "ui_effect", "Effect")
    bar = _section_bar()
    lines = [
        bar,
        f"✅ *{title} {updated_lbl}*",
        bar,
        f"{prev_w}: {prev_lbl}",
        f"{new_w}: *{new_lbl}*",
    ]
    if effect_text:
        lines.append(f"{eff_w}: _{effect_text}_")
    return "\n".join(lines)


# -------------------------------------------------------------------
# Button-label helpers — keyboards read state and render state-aware labels
# -------------------------------------------------------------------
def toggle_button_label(control_label: str, state: dict) -> str:
    """'AutoTrade: ON 🟢' — for display-only buttons that show current state."""
    return f"{control_label}: {state.get('label', '?')} {state.get('glyph', '')}".rstrip()


def action_button_label(action_prefix: str, target_label: str,
                        target_glyph: str = "") -> str:
    """'Turn OFF 🔴' / 'Switch to LIVE 🔴' — for action buttons that change state."""
    text = f"{action_prefix} {target_label}".strip()
    if target_glyph:
        text = f"{text} {target_glyph}"
    return text


def opposite(state: dict) -> dict:
    """Construct the 'other side' of a binary state — for previewing action buttons.
    Returns a shallow dict with inverted label/glyph when possible."""
    cur_on = state.get("on")
    if cur_on is None:
        return {"label": "?", "glyph": ""}
    # Swap label + glyph using the state's own current values
    if cur_on:
        return {"label": _opposite_label(state, False), "glyph": _opposite_glyph(state, False),
                "on": False}
    return {"label": _opposite_label(state, True), "glyph": _opposite_glyph(state, True),
            "on": True}


def _opposite_label(state: dict, target_on: bool) -> str:
    lbl = state.get("label", "")
    # Heuristic: ON/OFF, ACTIVE/INACTIVE, LIVE/PAPER pairs
    mapping = {"ON": "OFF", "OFF": "ON",
               "ACTIVE": "INACTIVE", "INACTIVE": "ACTIVE",
               "LIVE": "PAPER", "PAPER": "LIVE"}
    return mapping.get(lbl.upper(), "OFF" if not target_on else "ON")


def _opposite_glyph(state: dict, target_on: bool) -> str:
    cur = state.get("glyph", "")
    # Simple swap: 🟢 <-> 🔴, 🧪 <-> 🔴, 🛡 <-> 🔥
    pairs = {GLYPH_ON: GLYPH_OFF, GLYPH_OFF: GLYPH_ON,
             GLYPH_PAPER: GLYPH_LIVE, GLYPH_LIVE: GLYPH_PAPER,
             GLYPH_SHIELD: GLYPH_FIRE, GLYPH_FIRE: GLYPH_SHIELD}
    return pairs.get(cur, GLYPH_ON if target_on else GLYPH_OFF)
