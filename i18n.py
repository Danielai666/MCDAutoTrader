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
        "btn_signal": "📈 Signal",
        "btn_status": "📊 Status",
        "btn_positions": "💼 Positions",
        "btn_risk": "🎯 Risk",
        "btn_ai_card": "🤖 AI Card",
        "btn_report": "📉 Report",
        "btn_autotrade": "🤖 Auto",
        "btn_mode": "⚙️ Mode",
        "btn_connect": "🔌 Connect",
        "btn_backtest": "📊 Backtest",
        "btn_analyze": "🔍 Analyze",
        "btn_insights": "🧠 Insights",
        "btn_guards": "🛡 Guards",
        "btn_risk_board": "⚠️ Risk Board",
        "btn_heatmap": "🔥 Heatmap",
        "btn_panic": "🛑 Panic",
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
        "btn_settings": "⚙️ Settings & Strategy",

        # --- Level-2 submenu button labels (added in §18.20 menu refactor) ---
        "btn_trial": "🧪 Trial",
        "btn_ai": "🧠 AI & Analysis",
        "btn_daily_limit": "📊 Daily Limit",
        "btn_capital": "💰 Capital",
        "btn_maxexposure": "📈 Max Exposure",
        "btn_myaccount": "👤 My Account",
        "btn_portfolio": "💼 Portfolio",
        "btn_language": "🌐 Language",
        "btn_trial_start": "▶️ Start Trial",
        "btn_trial_status": "📊 Status",
        "btn_trial_report": "📉 Report",
        "btn_trial_summary": "📋 Summary",
        "btn_trial_stop": "⏹ Stop",
        "btn_conservative": "🛡 Conservative",
        "btn_balanced": "⚖️ Balanced",
        "btn_aggressive": "🔥 Aggressive",
        "btn_notifications": "🔔 Notifications",
        "btn_voice": "🎙 Voice",
        "btn_yes_confirm": "✅ Yes, confirm",
        "confirm_sellnow_prompt": "Close ALL your open positions now?",
        "confirm_panic_prompt": "PANIC STOP — halt all trading immediately?",
        "confirm_disconnect_prompt": "Disconnect your exchange?",
        "coming_soon": "Coming soon.",
        "enter_capital": "Enter capital amount (USD):",
        "enter_maxexposure": "Enter max exposure (0.0–1.0, e.g. 0.4 for 40%):",
        "enter_trial_capital": "Enter trial capital (USD), e.g. 1000:",

        # --- Menu discoverability pass (§18.21) ---
        "btn_home": "🏠 Main Menu",
        "select_category_hint": "👇 Select a category to continue",
        "previews_title": "Categories",
        "btn_risk_short": "Risk",
        "btn_ai_short": "AI & Analysis",
        "btn_trial_short": "Trial",
        "btn_markets_short": "Markets",
        "preview_risk": "Limits · SL/TP · Exposure",
        "preview_ai": "Signals · Insights · Charts",
        "preview_trial": "Start · Status · Report",
        "preview_markets": "Active · Add · Ranking",
        "btn_quick_status": "⚡ Status",
        "btn_quick_signal": "⚡ Signal",
        "btn_quick_positions": "⚡ Positions",

        # --- §18.22 Advanced submenu + label updates ---
        "btn_advanced": "🛠 Advanced",
        "btn_advanced_short": "Advanced",
        "btn_account_short": "Account",
        "btn_check_guards": "🔍 Check",
        "preview_advanced": "Guards · Charts · Admin",
        "preview_account": "Connect · Portfolio · Language",

        # --- §18.24 Account dashboard (multi-user trial testing) ---
        "account_dashboard_title": "👤 Account Dashboard",
        "account_identity_header": "Identity",
        "account_mode_header": "Mode & Status",
        "account_exchange_header": "Exchange",
        "account_settings_header": "Settings",
        "account_trial_header": "Trial",
        "account_status_header": "Account Status",
        "account_user_id": "User ID",
        "account_username": "Username",
        "account_mode": "Mode",
        "account_autotrade": "AutoTrade",
        "account_trial_active": "Trial",
        "account_trial_day": "Trial Day",
        "account_trial_capital": "Trial Capital",
        "account_exchange": "Exchange",
        "account_connection": "Connection",
        "account_connected": "Connected",
        "account_not_connected": "Not connected",
        "account_api_key": "API Key",
        "account_language": "Language",
        "account_capital": "Capital",
        "account_daily_limit": "Daily Loss Limit",
        "account_max_exposure": "Max Exposure",
        "account_live_access": "Live Access",
        "account_live_allowed": "Allowed",
        "account_live_denied": "Trial only",
        "account_status_trial_active": "✅ Trial active",
        "account_status_trial_inactive": "ℹ️ No trial active",
        "account_status_exchange_ok": "✅ Exchange connected",
        "account_status_exchange_missing": "⚠️ No exchange connected",
        "account_status_paper_mode": "✅ Paper mode",
        "account_status_live_mode": "🔴 Live mode",
        "account_status_autotrade_on": "✅ AutoTrade ON",
        "account_status_autotrade_off": "ℹ️ AutoTrade OFF",
        "account_status_live_enabled": "✅ Live trading enabled",
        "account_status_live_disabled": "⚠️ Live trading not enabled",
        "btn_trial_shortcut": "🧪 Trial",
        "btn_settings_shortcut": "⚙️ Settings",
        "btn_refresh": "🔄 Refresh",
        "yes": "Yes",
        "no": "No",
        "account_ai_service": "AI Service",
        "account_ai_platform_provided": "Platform Provided",
        "account_status_ai_shared": "✅ AI service provided by platform",

        # --- Settings submenu ---
        "settings_title": "⚙️ Settings",
        "settings_language_header": "Language",
        "btn_lang_en": "🇬🇧 English",
        "btn_lang_fa": "🇮🇷 فارسی",
        "btn_back": "⬅️ Back",

        # --- Portfolio (read-only) ---
        "portfolio_title": "💼 Portfolio",
        "portfolio_report_title": "📉 Performance Report",
        "portfolio_exchange": "Exchange",
        "portfolio_sync": "Exchange Sync",
        "portfolio_total": "Total value",
        "portfolio_cash": "Available cash",
        "portfolio_positions_value": "In positions",
        "portfolio_assets": "Assets",
        "portfolio_pnl": "Realized PnL",
        "portfolio_roi": "ROI",
        "portfolio_trades": "Trades",
        "portfolio_win_rate": "Win rate",
        "portfolio_best": "Best trade",
        "portfolio_worst": "Worst trade",
        "portfolio_no_exchange": "No exchange connected.",
        "portfolio_connect_hint": "Use the Connect button to link your exchange.",
        "portfolio_short": "Portfolio",
        "portfolio_pnl_short": "PnL",
        "portfolio_unrealized_short": "Unrealized",
        "portfolio_fetching": "Fetching portfolio...",
        "portfolio_equity": "True Equity",
        "portfolio_unrealized": "Unrealized PnL",
        "portfolio_open_positions": "Open Positions",
        "portfolio_no_open": "No open positions.",
        "portfolio_real_label": "Real trade history (approx.)",

        # --- §18.26 Portfolio history + asset detail ---
        "portfolio_history_title": "📈 Portfolio History",
        "portfolio_history_empty": "Portfolio history not available yet. Run /portfolio to record your first snapshot.",
        "portfolio_history_first": "First snapshot recorded",
        "portfolio_history_insufficient": "Not enough history for change calc. Check back later.",
        "portfolio_history_from": "From",
        "portfolio_history_to": "To",
        "portfolio_history_span": "Span",
        "portfolio_history_start_value": "Start value",
        "portfolio_history_end_value": "End value",
        "portfolio_history_change": "Change",
        "portfolio_snapshot_count": "Snapshots stored",
        "portfolio_asset_title": "💎 Asset Detail",
        "portfolio_asset_not_found": "Asset not in your wallet.",
        "portfolio_asset_need_sync": "Run /portfolio first to load wallet data.",
        "portfolio_asset_amount": "Amount",
        "portfolio_asset_price": "Price (USD)",
        "portfolio_asset_value": "Value (USD)",
        "portfolio_asset_alloc": "Allocation",
        "portfolio_asset_positions": "Open positions",
        "btn_portfolio_report": "📉 Report",
        "btn_portfolio_history": "📈 History",

        # --- §18.27 Portfolio UX polish ---
        "portfolio_overview_title": "💼 Portfolio Overview",
        "portfolio_invested": "Invested",
        "portfolio_assets_breakdown": "Assets Breakdown",
        "portfolio_last_sync": "Last Sync",
        "portfolio_cash_short": "Cash",
        "portfolio_exposure_short": "Exposure",
        "portfolio_insight_title": "🧠 Portfolio Insight",
        "portfolio_insight_conservative": "Conservative (mostly cash)",
        "portfolio_insight_balanced": "Balanced (cash + invested)",
        "portfolio_insight_aggressive": "Aggressive (heavily invested)",
        "portfolio_insight_conservative_note": "Low exposure to volatility",
        "portfolio_insight_balanced_note": "Moderate exposure",
        "portfolio_insight_aggressive_note": "High exposure to market moves",
        "portfolio_seconds_ago": "sec ago",
        "portfolio_minutes_ago": "min ago",
        "portfolio_hours_ago": "hr ago",
        "portfolio_days_ago": "days ago",
        "btn_refresh_portfolio": "🔄 Refresh",

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
        "btn_signal": "📈 سیگنال",
        "btn_status": "📊 وضعیت",
        "btn_positions": "💼 پوزیشن‌ها",
        "btn_risk": "🎯 ریسک",
        "btn_ai_card": "🤖 کارت AI",
        "btn_report": "📉 گزارش",
        "btn_autotrade": "🤖 خودکار",
        "btn_mode": "⚙️ حالت",
        "btn_connect": "🔌 اتصال",
        "btn_backtest": "📊 بک‌تست",
        "btn_analyze": "🔍 تحلیل",
        "btn_insights": "🧠 بینش",
        "btn_guards": "🛡 گاردها",
        "btn_risk_board": "⚠️ برد ریسک",
        "btn_heatmap": "🔥 هیت‌مپ",
        "btn_panic": "🛑 توقف",
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
        "btn_settings": "⚙️ تنظیمات و استراتژی",

        # --- Level-2 submenu button labels (Farsi) ---
        "btn_trial": "🧪 آزمایشی",
        "btn_ai": "🧠 AI و تحلیل",
        "btn_daily_limit": "📊 حد ضرر روزانه",
        "btn_capital": "💰 سرمایه",
        "btn_maxexposure": "📈 حداکثر ریسک",
        "btn_myaccount": "👤 حساب من",
        "btn_portfolio": "💼 پورتفولیو",
        "btn_language": "🌐 زبان",
        "btn_trial_start": "▶️ شروع آزمایش",
        "btn_trial_status": "📊 وضعیت",
        "btn_trial_report": "📉 گزارش",
        "btn_trial_summary": "📋 خلاصه",
        "btn_trial_stop": "⏹ پایان",
        "btn_conservative": "🛡 محافظه‌کار",
        "btn_balanced": "⚖️ متعادل",
        "btn_aggressive": "🔥 تهاجمی",
        "btn_notifications": "🔔 اعلان‌ها",
        "btn_voice": "🎙 صدا",
        "btn_yes_confirm": "✅ تایید",
        "confirm_sellnow_prompt": "همه پوزیشن‌های باز بسته شوند؟",
        "confirm_panic_prompt": "توقف اضطراری — متوقف کردن فوری معاملات؟",
        "confirm_disconnect_prompt": "صرافی قطع شود؟",
        "coming_soon": "به‌زودی.",
        "enter_capital": "مقدار سرمایه (USD) را وارد کنید:",
        "enter_maxexposure": "حداکثر ریسک (0.0–1.0، مثلا 0.4 برای 40%):",
        "enter_trial_capital": "سرمایه آزمایشی (USD)، مثلا 1000:",

        # --- Menu discoverability pass (Farsi) ---
        "btn_home": "🏠 منو اصلی",
        "select_category_hint": "👇 یک بخش را انتخاب کنید",
        "previews_title": "بخش‌ها",
        "btn_risk_short": "ریسک",
        "btn_ai_short": "AI و تحلیل",
        "btn_trial_short": "آزمایش",
        "btn_markets_short": "بازارها",
        "preview_risk": "حدود · SL/TP · ریسک",
        "preview_ai": "سیگنال · بینش · چارت",
        "preview_trial": "شروع · وضعیت · گزارش",
        "preview_markets": "فعال · افزودن · رتبه",
        "btn_quick_status": "⚡ وضعیت",
        "btn_quick_signal": "⚡ سیگنال",
        "btn_quick_positions": "⚡ پوزیشن",

        # --- §18.22 Advanced submenu + label updates (Farsi) ---
        "btn_advanced": "🛠 پیشرفته",
        "btn_advanced_short": "پیشرفته",
        "btn_account_short": "حساب",
        "btn_check_guards": "🔍 بررسی",
        "preview_advanced": "گاردها · چارت · ادمین",
        "preview_account": "اتصال · پورتفولیو · زبان",

        # --- §18.24 Account dashboard (Farsi) ---
        "account_dashboard_title": "👤 داشبورد حساب",
        "account_identity_header": "هویت",
        "account_mode_header": "حالت و وضعیت",
        "account_exchange_header": "صرافی",
        "account_settings_header": "تنظیمات",
        "account_trial_header": "آزمایشی",
        "account_status_header": "وضعیت حساب",
        "account_user_id": "شناسه کاربر",
        "account_username": "نام کاربری",
        "account_mode": "حالت",
        "account_autotrade": "معامله خودکار",
        "account_trial_active": "آزمایشی",
        "account_trial_day": "روز آزمایشی",
        "account_trial_capital": "سرمایه آزمایشی",
        "account_exchange": "صرافی",
        "account_connection": "اتصال",
        "account_connected": "متصل",
        "account_not_connected": "قطع",
        "account_api_key": "کلید API",
        "account_language": "زبان",
        "account_capital": "سرمایه",
        "account_daily_limit": "حد ضرر روزانه",
        "account_max_exposure": "حداکثر ریسک",
        "account_live_access": "دسترسی واقعی",
        "account_live_allowed": "مجاز",
        "account_live_denied": "فقط آزمایشی",
        "account_status_trial_active": "✅ آزمایشی فعال",
        "account_status_trial_inactive": "ℹ️ آزمایشی غیرفعال",
        "account_status_exchange_ok": "✅ صرافی متصل است",
        "account_status_exchange_missing": "⚠️ صرافی متصل نیست",
        "account_status_paper_mode": "✅ حالت کاغذی",
        "account_status_live_mode": "🔴 حالت واقعی",
        "account_status_autotrade_on": "✅ معامله خودکار روشن",
        "account_status_autotrade_off": "ℹ️ معامله خودکار خاموش",
        "account_status_live_enabled": "✅ معامله واقعی مجاز است",
        "account_status_live_disabled": "⚠️ معامله واقعی فعال نیست",
        "btn_trial_shortcut": "🧪 آزمایشی",
        "btn_settings_shortcut": "⚙️ تنظیمات",
        "btn_refresh": "🔄 بروزرسانی",
        "yes": "بله",
        "no": "خیر",
        "account_ai_service": "سرویس AI",
        "account_ai_platform_provided": "ارائه شده توسط پلتفرم",
        "account_status_ai_shared": "✅ سرویس AI توسط پلتفرم تأمین می‌شود",

        # --- Settings submenu ---
        "settings_title": "⚙️ تنظیمات",
        "settings_language_header": "زبان",
        "btn_lang_en": "🇬🇧 English",
        "btn_lang_fa": "🇮🇷 فارسی",
        "btn_back": "⬅️ بازگشت",

        # --- Portfolio (read-only) ---
        "portfolio_title": "💼 پورتفولیو",
        "portfolio_report_title": "📉 گزارش عملکرد",
        "portfolio_exchange": "صرافی",
        "portfolio_sync": "همگام‌سازی",
        "portfolio_total": "ارزش کل",
        "portfolio_cash": "نقدینگی",
        "portfolio_positions_value": "در پوزیشن‌ها",
        "portfolio_assets": "دارایی‌ها",
        "portfolio_pnl": "سود/زیان محقق",
        "portfolio_roi": "بازدهی",
        "portfolio_trades": "تعداد معاملات",
        "portfolio_win_rate": "نرخ برد",
        "portfolio_best": "بهترین معامله",
        "portfolio_worst": "بدترین معامله",
        "portfolio_no_exchange": "صرافی متصل نیست.",
        "portfolio_connect_hint": "برای اتصال از دکمه «اتصال» استفاده کنید.",
        "portfolio_short": "پورتفولیو",
        "portfolio_pnl_short": "سود/زیان",
        "portfolio_unrealized_short": "سود/زیان باز",
        "portfolio_fetching": "در حال دریافت پورتفولیو...",
        "portfolio_equity": "ارزش واقعی",
        "portfolio_unrealized": "سود/زیان محقق‌نشده",
        "portfolio_open_positions": "پوزیشن‌های باز",
        "portfolio_no_open": "هیچ پوزیشن بازی وجود ندارد.",
        "portfolio_real_label": "تاریخچه واقعی (تقریبی)",

        # --- §18.26 Portfolio history + asset detail (Farsi) ---
        "portfolio_history_title": "📈 تاریخچه پورتفولیو",
        "portfolio_history_empty": "هنوز تاریخچه ای موجود نیست. برای ثبت اولین عکس دستور /portfolio را اجرا کنید.",
        "portfolio_history_first": "اولین ثبت انجام شد",
        "portfolio_history_insufficient": "داده کافی برای محاسبه تغییر وجود ندارد. بعداً بررسی کنید.",
        "portfolio_history_from": "از",
        "portfolio_history_to": "تا",
        "portfolio_history_span": "بازه",
        "portfolio_history_start_value": "ارزش ابتدا",
        "portfolio_history_end_value": "ارزش پایان",
        "portfolio_history_change": "تغییر",
        "portfolio_snapshot_count": "تعداد ثبت‌ها",
        "portfolio_asset_title": "💎 جزییات دارایی",
        "portfolio_asset_not_found": "این دارایی در کیف پول شما نیست.",
        "portfolio_asset_need_sync": "ابتدا /portfolio را اجرا کنید تا داده‌های کیف پول بارگذاری شود.",
        "portfolio_asset_amount": "مقدار",
        "portfolio_asset_price": "قیمت (USD)",
        "portfolio_asset_value": "ارزش (USD)",
        "portfolio_asset_alloc": "سهم",
        "portfolio_asset_positions": "پوزیشن‌های باز",
        "btn_portfolio_report": "📉 گزارش",
        "btn_portfolio_history": "📈 تاریخچه",

        # --- §18.27 Portfolio UX polish (Farsi) ---
        "portfolio_overview_title": "💼 نمای کلی پورتفولیو",
        "portfolio_invested": "سرمایه‌گذاری شده",
        "portfolio_assets_breakdown": "جزییات دارایی‌ها",
        "portfolio_last_sync": "آخرین همگام‌سازی",
        "portfolio_cash_short": "نقد",
        "portfolio_exposure_short": "ریسک",
        "portfolio_insight_title": "🧠 بینش پورتفولیو",
        "portfolio_insight_conservative": "محافظه‌کار (عمدتاً نقد)",
        "portfolio_insight_balanced": "متعادل (نقد + سرمایه‌گذاری)",
        "portfolio_insight_aggressive": "تهاجمی (سرمایه‌گذاری سنگین)",
        "portfolio_insight_conservative_note": "ریسک کم در برابر نوسانات",
        "portfolio_insight_balanced_note": "ریسک متوسط",
        "portfolio_insight_aggressive_note": "ریسک بالا در برابر نوسانات بازار",
        "portfolio_seconds_ago": "ثانیه قبل",
        "portfolio_minutes_ago": "دقیقه قبل",
        "portfolio_hours_ago": "ساعت قبل",
        "portfolio_days_ago": "روز قبل",
        "btn_refresh_portfolio": "🔄 بروزرسانی",

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
