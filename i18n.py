# i18n.py
# Bilingual (English / Farsi) text dictionary + per-user language helper.
#
# Scope (per product spec):
#   - Translate user-facing Trial Mode strings, key panel headers,
#     trial-related button labels, and report headers.
#   - DO NOT translate symbols, numbers, log lines, internal keys,
#     strategy / risk / execution internals.
#
# Storage:
#   - Per-user language stored in users.language (TEXT, added by migration).
#   - Default = 'en'. 'fa' = Farsi.
#
# Usage:
#   from i18n import t, get_user_lang, set_user_lang
#   t(user_id, "trial_status")  -> localized string
#
# Feature flag:
#   FEATURE_I18N=false  ->  t() always returns English.

import logging
from typing import Optional
from config import SETTINGS

log = logging.getLogger(__name__)

DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("en", "fa")


def is_enabled() -> bool:
    return bool(getattr(SETTINGS, "FEATURE_I18N", True))


# -------------------------------------------------------------------
# Text dictionary
# -------------------------------------------------------------------
TEXT = {
    "en": {
        # --- Language picker ---
        "lang_set_en": "Language set to English.",
        "lang_set_fa": "Language set to Farsi.",
        "lang_usage": "Usage: /lang en  |  /lang fa",

        # --- Panel header ---
        "panel_title": "MCDAutoTrader Control Panel",
        "panel_select_action": "Select an action:",
        "panel_mode": "Mode",
        "panel_autotrade": "AutoTrade",
        "panel_open": "Open",
        "panel_pairs": "Pairs",
        "panel_last_signal": "Last Signal",
        "panel_last_action": "Last Action",
        "panel_system_healthy": "🟢 System: Healthy",
        "panel_system_busy": "🟡 System: Busy",
        "panel_system_error": "🔴 System: Error",
        "panel_system_killswitch": "🔴 System: Kill Switch",
        "panel_system_dryrun": "🟡 System: Dry Run",
        "autotrade_on": "ON",
        "autotrade_off": "OFF",

        # --- Trial mode ---
        "trial_title": "Trial Mode",
        "trial_status": "Trial Status",
        "trial_report": "Trial Report",
        "trial_summary": "Trial Summary",
        "trial_progress": "Trial Progress",
        "trial_capital": "Trial Capital",
        "trial_equity": "Equity",
        "trial_pnl": "PnL",
        "trial_roi": "ROI",
        "trial_day": "Day",
        "trial_days": "days",
        "trial_on": "ON",
        "trial_off": "OFF",
        "trial_active": "Active",
        "trial_not_active": "No active trial.",
        "trial_started": "Trial started.",
        "trial_start_usage": "Usage: /trial start <capital_usd> [days]",
        "trial_usage": (
            "Trial commands:\n"
            "/trial start <capital> [days] — begin trial (default 14 days)\n"
            "/trial status — running time, equity, PnL\n"
            "/trial report — recent trades + open positions\n"
            "/trial summary — full performance breakdown\n"
            "/trial go_live — convert to live after review\n"
            "/trial stop — end the current trial"
        ),
        "trial_invalid_capital": "Invalid capital. Example: /trial start 1000",
        "trial_running_time": "Running time",
        "trial_current_equity": "Current equity",
        "trial_total_pnl": "Total PnL",
        "trial_win_rate": "Win rate",
        "trial_trades_count": "Trades",
        "trial_max_drawdown": "Max drawdown",
        "trial_profit_factor": "Profit factor",
        "trial_recent_trades": "Recent trades",
        "trial_open_positions": "Open positions",
        "trial_no_trades": "No trades yet.",
        "trial_no_open": "No open positions.",
        "trial_summary_verdict_good": "Trial is performing well. You can consider going live.",
        "trial_summary_verdict_mixed": "Trial results are mixed. Consider more observation.",
        "trial_summary_verdict_bad": "Trial is underperforming. Continue paper before going live.",
        "trial_golive_confirm": (
            "Convert trial to LIVE trading?\n"
            "This switches your account from PAPER to LIVE. Trades will use real funds.\n"
            "Send: /trial go_live confirm"
        ),
        "trial_golive_done": "Converted to LIVE mode. Running reconciliation...",
        "trial_golive_denied": "Go-live denied: your account is not in the LIVE_TRADE_ALLOWED_IDS list.",
        "trial_stopped": "Trial stopped.",
        "go_live": "Go Live",
        "go_live_btn": "🚀 Go Live",

        # --- Inline panel button labels (emoji preserved, short for grid fit) ---
        "btn_signal": "📊 Signal",
        "btn_status": "📈 Status",
        "btn_positions": "💼 Positions",
        "btn_risk": "⚙️ Risk",
        "btn_ai_card": "🤖 AI Card",
        "btn_report": "📉 Report",
        "btn_autotrade": "🔁 AutoTrade",
        "btn_mode": "🧪 Mode",
        "btn_connect": "🔌 Connect",
        "btn_backtest": "📊 Backtest",
        "btn_analyze": "🔍 Analyze",
        "btn_insights": "🧠 Insights",
        "btn_guards": "🛡 Guards",
        "btn_risk_board": "⚠️ Risk Board",
        "btn_heatmap": "🔥 Heatmap",
        "btn_panic": "🚨 PANIC",
        "btn_account": "👤 Account",
        "btn_admin": "🧩 Admin",
        "btn_price": "💰 Price",
        "btn_health": "💚 Health",
        "btn_go_live": "🚀 Go Live",
        "btn_visuals": "🎨 Visuals",
        "btn_pairs": "🌐 Pairs",
        "btn_check": "🔍 Check",
        "btn_sell_now": "🛑 Sell Now",
        "btn_sltp_trail": "📐 SL/TP/Trail",
        "btn_cancel": "❌ Cancel",
        "btn_disconnect": "🔌 Disconnect",
        "btn_settings": "⚙️ Settings",

        # --- Settings submenu ---
        "settings_title": "⚙️ Settings",
        "settings_language_header": "Language",
        "btn_lang_en": "🇬🇧 English",
        "btn_lang_fa": "🇮🇷 فارسی",
        "btn_back": "⬅️ Back",

        # --- Bottom ReplyKeyboard (persistent row above text input) ---
        "rk_menu": "Menu",
        "rk_status": "Status",
        "rk_panic": "Panic Stop",

        # --- /langtest ---
        "langtest_current": "Current language",
        "langtest_sample": "Sample",

        # --- Generic ---
        "days_ago": "ago",
        "hours_ago": "ago",
        "minutes_ago": "ago",
        "seconds_ago": "ago",
        "not_allowed": "Not allowed.",
        "unknown_command": "Unknown command.",
    },

    "fa": {
        # --- Language picker ---
        "lang_set_en": "زبان به انگلیسی تنظیم شد.",
        "lang_set_fa": "زبان به فارسی تنظیم شد.",
        "lang_usage": "نحوه استفاده: /lang en  |  /lang fa",

        # --- Panel header ---
        "panel_title": "پنل کنترل MCDAutoTrader",
        "panel_select_action": "یک گزینه را انتخاب کنید:",
        "panel_mode": "حالت",
        "panel_autotrade": "معامله خودکار",
        "panel_open": "باز",
        "panel_pairs": "جفت‌ها",
        "panel_last_signal": "آخرین سیگنال",
        "panel_last_action": "آخرین اقدام",
        "panel_system_healthy": "🟢 سیستم: سالم",
        "panel_system_busy": "🟡 سیستم: در حال پردازش",
        "panel_system_error": "🔴 سیستم: خطا",
        "panel_system_killswitch": "🔴 سیستم: توقف اضطراری",
        "panel_system_dryrun": "🟡 سیستم: حالت آزمایشی",
        "autotrade_on": "روشن",
        "autotrade_off": "خاموش",

        # --- Trial mode ---
        "trial_title": "حالت آزمایشی",
        "trial_status": "وضعیت آزمایشی",
        "trial_report": "گزارش آزمایشی",
        "trial_summary": "خلاصه آزمایشی",
        "trial_progress": "پیشرفت آزمایشی",
        "trial_capital": "سرمایه آزمایشی",
        "trial_equity": "موجودی",
        "trial_pnl": "سود/زیان",
        "trial_roi": "بازدهی",
        "trial_day": "روز",
        "trial_days": "روز",
        "trial_on": "روشن",
        "trial_off": "خاموش",
        "trial_active": "فعال",
        "trial_not_active": "هیچ آزمایشی فعال نیست.",
        "trial_started": "دوره آزمایشی شروع شد.",
        "trial_start_usage": "نحوه استفاده: /trial start <سرمایه> [روز]",
        "trial_usage": (
            "دستورات آزمایشی:\n"
            "/trial start <سرمایه> [روز] — شروع آزمایش (پیش‌فرض 14 روز)\n"
            "/trial status — زمان فعال، موجودی، سود/زیان\n"
            "/trial report — معاملات اخیر و پوزیشن‌های باز\n"
            "/trial summary — خلاصه کامل عملکرد\n"
            "/trial go_live — تبدیل به حالت واقعی\n"
            "/trial stop — پایان دوره آزمایشی"
        ),
        "trial_invalid_capital": "سرمایه نامعتبر. مثال: /trial start 1000",
        "trial_running_time": "زمان فعال",
        "trial_current_equity": "موجودی فعلی",
        "trial_total_pnl": "سود/زیان کل",
        "trial_win_rate": "نرخ برد",
        "trial_trades_count": "تعداد معاملات",
        "trial_max_drawdown": "بیشترین افت سرمایه",
        "trial_profit_factor": "ضریب سود",
        "trial_recent_trades": "معاملات اخیر",
        "trial_open_positions": "پوزیشن‌های باز",
        "trial_no_trades": "هنوز معامله‌ای ثبت نشده است.",
        "trial_no_open": "هیچ پوزیشن بازی وجود ندارد.",
        "trial_summary_verdict_good": "عملکرد آزمایشی مناسب است. می‌توانید به حالت واقعی بروید.",
        "trial_summary_verdict_mixed": "نتایج ترکیبی است. مشاهده بیشتر توصیه می‌شود.",
        "trial_summary_verdict_bad": "عملکرد ضعیف است. پیش از ورود واقعی به مشاهده ادامه دهید.",
        "trial_golive_confirm": (
            "تبدیل آزمایشی به حالت واقعی؟\n"
            "حساب شما از حالت کاغذی به واقعی تغییر می‌کند. معاملات با سرمایه واقعی انجام خواهند شد.\n"
            "برای تایید ارسال کنید: /trial go_live confirm"
        ),
        "trial_golive_done": "به حالت واقعی تبدیل شد. در حال انجام تطبیق...",
        "trial_golive_denied": "ورود واقعی مجاز نیست: حساب شما در لیست مجاز قرار ندارد.",
        "trial_stopped": "دوره آزمایشی متوقف شد.",
        "go_live": "ورود به حالت واقعی",
        "go_live_btn": "🚀 واقعی",

        # --- Inline panel button labels (Farsi, kept short for grid fit) ---
        "btn_signal": "📊 سیگنال",
        "btn_status": "📈 وضعیت",
        "btn_positions": "💼 پوزیشن‌ها",
        "btn_risk": "⚙️ ریسک",
        "btn_ai_card": "🤖 کارت AI",
        "btn_report": "📉 گزارش",
        "btn_autotrade": "🔁 خودکار",
        "btn_mode": "🧪 حالت",
        "btn_connect": "🔌 اتصال",
        "btn_backtest": "📊 بک‌تست",
        "btn_analyze": "🔍 تحلیل",
        "btn_insights": "🧠 بینش",
        "btn_guards": "🛡 گاردها",
        "btn_risk_board": "⚠️ برد ریسک",
        "btn_heatmap": "🔥 هیت‌مپ",
        "btn_panic": "🚨 توقف",
        "btn_account": "👤 حساب",
        "btn_admin": "🧩 ادمین",
        "btn_price": "💰 قیمت",
        "btn_health": "💚 سلامت",
        "btn_go_live": "🚀 واقعی",
        "btn_visuals": "🎨 نمودار",
        "btn_pairs": "🌐 جفت‌ها",
        "btn_check": "🔍 بررسی",
        "btn_sell_now": "🛑 فروش",
        "btn_sltp_trail": "📐 SL/TP/تریل",
        "btn_cancel": "❌ لغو",
        "btn_disconnect": "🔌 قطع",
        "btn_settings": "⚙️ تنظیمات",

        # --- Settings submenu ---
        "settings_title": "⚙️ تنظیمات",
        "settings_language_header": "زبان",
        "btn_lang_en": "🇬🇧 English",
        "btn_lang_fa": "🇮🇷 فارسی",
        "btn_back": "⬅️ بازگشت",

        # --- Bottom ReplyKeyboard ---
        "rk_menu": "منو",
        "rk_status": "وضعیت",
        "rk_panic": "توقف",

        # --- /langtest ---
        "langtest_current": "زبان فعلی",
        "langtest_sample": "نمونه",

        # --- Generic ---
        "days_ago": "قبل",
        "hours_ago": "قبل",
        "minutes_ago": "قبل",
        "seconds_ago": "قبل",
        "not_allowed": "مجاز نیست.",
        "unknown_command": "دستور ناشناخته.",
    },
}


# -------------------------------------------------------------------
# Per-user language storage
# -------------------------------------------------------------------
_lang_cache: dict = {}  # uid -> lang (populated on read/write to avoid DB ping every render)


def _load_lang_from_db(uid: int) -> str:
    try:
        from storage import fetchone
        row = fetchone("SELECT language FROM users WHERE user_id=?", (uid,))
        if row and row[0]:
            lang = str(row[0]).lower().strip()
            if lang in SUPPORTED_LANGS:
                return lang
    except Exception as e:
        log.debug("i18n._load_lang_from_db failed: %s", e)
    return DEFAULT_LANG


def get_user_lang(uid: int) -> str:
    if not is_enabled():
        return DEFAULT_LANG
    if uid in _lang_cache:
        return _lang_cache[uid]
    lang = _load_lang_from_db(uid)
    _lang_cache[uid] = lang
    return lang


def set_user_lang(uid: int, lang: str) -> bool:
    if not is_enabled():
        return False
    lang = (lang or "").lower().strip()
    if lang not in SUPPORTED_LANGS:
        return False
    try:
        from storage import execute
        execute("UPDATE users SET language=? WHERE user_id=?", (lang, uid))
        _lang_cache[uid] = lang
        return True
    except Exception as e:
        log.warning("i18n.set_user_lang failed: %s", e)
        return False


# -------------------------------------------------------------------
# Translation helper
# -------------------------------------------------------------------
def t(uid: Optional[int], key: str) -> str:
    """
    Translate `key` for user `uid`. If i18n is disabled or the key is
    missing in the user's language, fall back to English. If the key is
    missing everywhere, return the key itself (safe, visible sentinel).
    """
    if not is_enabled() or uid is None:
        return TEXT.get("en", {}).get(key, key)
    lang = get_user_lang(uid)
    bucket = TEXT.get(lang, TEXT["en"])
    return bucket.get(key, TEXT["en"].get(key, key))


def is_rtl(uid: int) -> bool:
    return get_user_lang(uid) == "fa"
