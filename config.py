# config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _ids(v: str) -> tuple:
    return tuple(int(x.strip()) for x in v.split(',') if x.strip()) if v else tuple()

def _pairs(v: str) -> tuple:
    return tuple(x.strip() for x in v.split(',') if x.strip()) if v else tuple()

def _bool(key: str, default: str = 'false') -> bool:
    return os.getenv(key, default).lower() == 'true'

@dataclass
class Settings:
    # --- Core ---
    ENV: str = os.getenv('ENV', 'dev')
    TZ: str = os.getenv('TZ', 'America/Vancouver')
    DB_PATH: str = os.getenv('DB_PATH', './bot.db')
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

    # --- Database ---
    DB_ENGINE: str = os.getenv('DB_ENGINE', 'sqlite')  # 'sqlite' or 'postgres'
    SUPABASE_URL: str = os.getenv('SUPABASE_URL', '')
    SUPABASE_KEY: str = os.getenv('SUPABASE_KEY', '')
    SUPABASE_DB_HOST: str = os.getenv('SUPABASE_DB_HOST', '')
    SUPABASE_DB_PORT: int = int(os.getenv('SUPABASE_DB_PORT', '6543'))
    SUPABASE_DB_NAME: str = os.getenv('SUPABASE_DB_NAME', 'postgres')
    SUPABASE_DB_USER: str = os.getenv('SUPABASE_DB_USER', 'postgres')
    SUPABASE_DB_PASSWORD: str = os.getenv('SUPABASE_DB_PASSWORD', '')
    SUPABASE_SCHEMA: str = os.getenv('SUPABASE_SCHEMA', 'trading_bot')

    # --- Feature Flags ---
    FEATURE_MULTI_PAIR: bool = _bool('FEATURE_MULTI_PAIR')
    FEATURE_AI_FUSION: bool = _bool('FEATURE_AI_FUSION')
    FEATURE_CANDLE_PATTERNS: bool = _bool('FEATURE_CANDLE_PATTERNS')
    FEATURE_HIDDEN_DIVERGENCE: bool = _bool('FEATURE_HIDDEN_DIVERGENCE')
    FEATURE_MARKET_REGIME: bool = _bool('FEATURE_MARKET_REGIME')
    FEATURE_ICHIMOKU: bool = _bool('FEATURE_ICHIMOKU', 'true')
    FEATURE_MT5_BRIDGE: bool = _bool('FEATURE_MT5_BRIDGE')
    FEATURE_SCREENSHOTS: bool = _bool('FEATURE_SCREENSHOTS')
    FEATURE_CONTROL_PANEL: bool = _bool('FEATURE_CONTROL_PANEL', 'true')
    FEATURE_TRIAL_MODE: bool = _bool('FEATURE_TRIAL_MODE', 'true')
    FEATURE_I18N: bool = _bool('FEATURE_I18N', 'true')
    FEATURE_PORTFOLIO: bool = _bool('FEATURE_PORTFOLIO', 'true')

    # --- Production safety layer ---
    MAX_ACTIVE_USERS: int = int(os.getenv('MAX_ACTIVE_USERS', '20'))
    RATE_LIMIT_BURST_COUNT: int = int(os.getenv('RATE_LIMIT_BURST_COUNT', '5'))
    RATE_LIMIT_BURST_WINDOW: int = int(os.getenv('RATE_LIMIT_BURST_WINDOW', '10'))
    RATE_LIMIT_WINDOW_COUNT: int = int(os.getenv('RATE_LIMIT_WINDOW_COUNT', '10'))
    RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv('RATE_LIMIT_WINDOW_SECONDS', '60'))

    # --- Market / Exchange ---
    EXCHANGE: str = os.getenv('EXCHANGE', 'kraken')
    PAIR: str = os.getenv('PAIR', 'BNB/USDC')
    TIMEFRAMES: tuple = tuple(map(str.strip, os.getenv('TIMEFRAMES', '30m,1h,4h,1d').split(',')))
    CANDLE_LIMIT: int = int(os.getenv('CANDLE_LIMIT', '300'))
    PAPER_TRADING: bool = _bool('PAPER_TRADING', 'true')

    # --- Multi-Pair ---
    DEFAULT_PAIRS: tuple = _pairs(os.getenv('DEFAULT_PAIRS', 'BNB/USDC'))
    MAX_WATCHED_PAIRS: int = int(os.getenv('MAX_WATCHED_PAIRS', '10'))
    PAIR_MODE: str = os.getenv('PAIR_MODE', 'single')

    # --- Risk ---
    CAPITAL_USD: float = float(os.getenv('CAPITAL_USD', '1000'))
    RISK_PER_TRADE: float = float(os.getenv('RISK_PER_TRADE', '0.01'))
    MAX_OPEN_TRADES: int = int(os.getenv('MAX_OPEN_TRADES', '2'))
    DAILY_LOSS_LIMIT_USD: float = float(os.getenv('DAILY_LOSS_LIMIT_USD', '50'))
    ENABLE_EXIT_AUTOMATION: bool = _bool('ENABLE_EXIT_AUTOMATION', 'true')
    COOLDOWN_AFTER_TRADE_SECONDS: int = int(os.getenv('COOLDOWN_AFTER_TRADE_SECONDS', '300'))
    MAX_DAILY_TRADES: int = int(os.getenv('MAX_DAILY_TRADES', '10'))
    CONSECUTIVE_LOSS_COOLDOWN: int = int(os.getenv('CONSECUTIVE_LOSS_COOLDOWN', '3'))
    CONSECUTIVE_LOSS_PAUSE_SECONDS: int = int(os.getenv('CONSECUTIVE_LOSS_PAUSE_SECONDS', '3600'))
    BREAK_EVEN_ATR_MULTIPLIER: float = float(os.getenv('BREAK_EVEN_ATR_MULTIPLIER', '1.0'))

    # --- Autonomous Trading ---
    MAX_PORTFOLIO_EXPOSURE: float = float(os.getenv('MAX_PORTFOLIO_EXPOSURE', '0.50'))
    CAPITAL_PER_TRADE_PCT: float = float(os.getenv('CAPITAL_PER_TRADE_PCT', '0.10'))
    MIN_SETUP_QUALITY: float = float(os.getenv('MIN_SETUP_QUALITY', '0.3'))
    MAX_RISK_FLAGS: int = int(os.getenv('MAX_RISK_FLAGS', '2'))
    CONFIDENCE_SCALE_MIN: float = float(os.getenv('CONFIDENCE_SCALE_MIN', '0.5'))
    CONFIDENCE_SCALE_MAX: float = float(os.getenv('CONFIDENCE_SCALE_MAX', '1.0'))
    MAX_PAIRS_PER_CYCLE: int = int(os.getenv('MAX_PAIRS_PER_CYCLE', '3'))
    TP_ATR_MULTIPLIER: float = float(os.getenv('TP_ATR_MULTIPLIER', '2.0'))

    # --- Kill Switch / Dry Run ---
    KILL_SWITCH: bool = _bool('KILL_SWITCH')
    DRY_RUN_MODE: bool = _bool('DRY_RUN_MODE')

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_ADMIN_IDS: tuple = _ids(os.getenv('TELEGRAM_ADMIN_IDS', ''))
    HTTPS_PROXY: str = os.getenv('HTTPS_PROXY', '')

    # --- AI / Decider (legacy) ---
    AI_BASE_URL: str = os.getenv('AI_BASE_URL', '')
    AI_API_KEY: str = os.getenv('AI_API_KEY', '')
    AI_MODEL: str = os.getenv('AI_MODEL', 'gpt-4o-mini')
    AI_CONFIDENCE_MIN: float = float(os.getenv('AI_CONFIDENCE_MIN', '0.65'))
    SIGNAL_SCORE_MIN: float = float(os.getenv('SIGNAL_SCORE_MIN', '0.60'))

    # --- AI Fusion (dual-AI) ---
    CLAUDE_API_KEY: str = os.getenv('CLAUDE_API_KEY', '')
    CLAUDE_MODEL: str = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY', '')
    OPENAI_MODEL: str = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
    AI_FUSION_POLICY: str = os.getenv('AI_FUSION_POLICY', 'local_only')
    AI_TIMEOUT_SECONDS: int = int(os.getenv('AI_TIMEOUT_SECONDS', '15'))

    # --- Indicators / Strategy ---
    ATR_PERIOD: int = int(os.getenv('ATR_PERIOD', '14'))
    ADX_PERIOD: int = int(os.getenv('ADX_PERIOD', '14'))
    ADX_TREND_MIN: float = float(os.getenv('ADX_TREND_MIN', '20.0'))
    ADX_STRONG_TREND: float = float(os.getenv('ADX_STRONG_TREND', '40.0'))
    BB_PERIOD: int = int(os.getenv('BB_PERIOD', '20'))
    BB_STD: float = float(os.getenv('BB_STD', '2.0'))
    PIVOT_LOOKBACK: int = int(os.getenv('PIVOT_LOOKBACK', '3'))
    ATR_SL_MULTIPLIER: float = float(os.getenv('ATR_SL_MULTIPLIER', '1.5'))

    # --- ATR Trailing Stop ---
    TRAILING_ENABLED: bool = _bool('TRAILING_ENABLED', 'true')
    TRAILING_ATR_MULTIPLIER: float = float(os.getenv('TRAILING_ATR_MULTIPLIER', '2.5'))
    TRAILING_TIGHTEN_AFTER_ATR: float = float(os.getenv('TRAILING_TIGHTEN_AFTER_ATR', '2.0'))
    TRAILING_TIGHTEN_MULTIPLIER: float = float(os.getenv('TRAILING_TIGHTEN_MULTIPLIER', '1.5'))
    TRAILING_ACTIVATION_ATR: float = float(os.getenv('TRAILING_ACTIVATION_ATR', '1.0'))

    # --- Correlation Risk ---
    CORRELATION_CHECK_ENABLED: bool = _bool('CORRELATION_CHECK_ENABLED', 'true')
    CORRELATION_THRESHOLD: float = float(os.getenv('CORRELATION_THRESHOLD', '0.75'))
    CORRELATION_LOOKBACK_BARS: int = int(os.getenv('CORRELATION_LOOKBACK_BARS', '50'))
    CORRELATION_TIMEFRAME: str = os.getenv('CORRELATION_TIMEFRAME', '1h')
    MAX_CORRELATED_EXPOSURE: int = int(os.getenv('MAX_CORRELATED_EXPOSURE', '2'))

    # --- Drawdown Management ---
    DRAWDOWN_TRACKING_ENABLED: bool = _bool('DRAWDOWN_TRACKING_ENABLED', 'true')
    DRAWDOWN_SCALE_THRESHOLD: float = float(os.getenv('DRAWDOWN_SCALE_THRESHOLD', '0.10'))
    DRAWDOWN_HALT_THRESHOLD: float = float(os.getenv('DRAWDOWN_HALT_THRESHOLD', '0.25'))
    DRAWDOWN_SCALE_FACTOR: float = float(os.getenv('DRAWDOWN_SCALE_FACTOR', '0.50'))

    # --- Candle Patterns ---
    CANDLE_WICK_RATIO: float = float(os.getenv('CANDLE_WICK_RATIO', '2.0'))
    CANDLE_BODY_RATIO: float = float(os.getenv('CANDLE_BODY_RATIO', '0.3'))

    # --- Market Regime ---
    REGIME_EMA_FAST: int = int(os.getenv('REGIME_EMA_FAST', '20'))
    REGIME_EMA_SLOW: int = int(os.getenv('REGIME_EMA_SLOW', '50'))
    REGIME_ADX_THRESHOLD: float = float(os.getenv('REGIME_ADX_THRESHOLD', '25.0'))
    REGIME_VOLATILITY_LOOKBACK: int = int(os.getenv('REGIME_VOLATILITY_LOOKBACK', '20'))

    # --- Scheduler ---
    ANALYSIS_INTERVAL_SECONDS: int = int(os.getenv('ANALYSIS_INTERVAL_SECONDS', '600'))
    GUARD_CHECK_INTERVAL_SECONDS: int = int(os.getenv('GUARD_CHECK_INTERVAL_SECONDS', '30'))
    HEALTH_CHECK_INTERVAL_SECONDS: int = int(os.getenv('HEALTH_CHECK_INTERVAL_SECONDS', '3600'))

    # --- Payments (optional) ---
    PAYMENT_PROVIDER: str = os.getenv('PAYMENT_PROVIDER', '')
    STRIPE_SECRET_KEY: str = os.getenv('STRIPE_SECRET_KEY', '')

    # --- LIVE control ---
    LIVE_TRADE_ALLOWED_IDS: tuple = _ids(os.getenv('LIVE_TRADE_ALLOWED_IDS', ''))
    KRAKEN_API_KEY: str = os.getenv('KRAKEN_API_KEY', '')
    KRAKEN_API_SECRET: str = os.getenv('KRAKEN_API_SECRET', '')

    # --- Credential encryption (for multi-user exchange key storage) ---
    CREDENTIAL_ENCRYPTION_KEY: str = os.getenv('CREDENTIAL_ENCRYPTION_KEY', '')

    # --- MT5 EA Bridge ---
    MT5_BRIDGE_HOST: str = os.getenv('MT5_BRIDGE_HOST', '0.0.0.0')
    MT5_BRIDGE_PORT: int = int(os.getenv('MT5_BRIDGE_PORT', '8080'))
    MT5_REPLAY_WINDOW_SECONDS: int = int(os.getenv('MT5_REPLAY_WINDOW_SECONDS', '30'))
    MT5_MAX_SPREAD_PIPS: float = float(os.getenv('MT5_MAX_SPREAD_PIPS', '5.0'))

    # --- Screenshot analysis ---
    SCREENSHOT_MAX_IMAGES: int = int(os.getenv('SCREENSHOT_MAX_IMAGES', '12'))
    SCREENSHOT_VISION_MODEL: str = os.getenv('SCREENSHOT_VISION_MODEL', 'claude-sonnet-4-20250514')

    # --- AGGRESSIVE_TEST_MODE (controlled threshold relaxation) ---
    # When AGGRESSIVE_TEST_MODE=true, the threshold accessors below return the
    # AGGRESSIVE_* values in place of the safe defaults. This loosens signal
    # generation / AI decision gates ONLY. Risk caps (max open trades, daily
    # loss limit, portfolio exposure, cooldown, drawdown halt, kill switch,
    # correlation, duplicate guard, stop-loss) are NOT overridden.
    AGGRESSIVE_TEST_MODE: bool = _bool('AGGRESSIVE_TEST_MODE', 'false')
    AGGRESSIVE_AI_CONFIDENCE_MIN: float = float(os.getenv('AGGRESSIVE_AI_CONFIDENCE_MIN', '0.48'))
    AGGRESSIVE_SIGNAL_SCORE_MIN: float = float(os.getenv('AGGRESSIVE_SIGNAL_SCORE_MIN', '0.35'))
    AGGRESSIVE_MIN_SETUP_QUALITY: float = float(os.getenv('AGGRESSIVE_MIN_SETUP_QUALITY', '0.15'))
    AGGRESSIVE_ADX_TREND_MIN: float = float(os.getenv('AGGRESSIVE_ADX_TREND_MIN', '12.0'))
    AGGRESSIVE_MAX_RISK_FLAGS: int = int(os.getenv('AGGRESSIVE_MAX_RISK_FLAGS', '3'))
    AGGRESSIVE_TF_SCORE_MIN: float = float(os.getenv('AGGRESSIVE_TF_SCORE_MIN', '0.8'))
    AGGRESSIVE_MTF_MERGE_THRESHOLD: float = float(os.getenv('AGGRESSIVE_MTF_MERGE_THRESHOLD', '0.25'))

SETTINGS = Settings()


# -------------------------------------------------------------------
# Threshold accessors — honour AGGRESSIVE_TEST_MODE when active.
# All signal/decision gates call these instead of reading SETTINGS.*
# directly, so a single env flag switches the whole system between
# safe and aggressive thresholds with no per-site code changes.
# -------------------------------------------------------------------
def get_ai_confidence_min() -> float:
    return SETTINGS.AGGRESSIVE_AI_CONFIDENCE_MIN if SETTINGS.AGGRESSIVE_TEST_MODE else SETTINGS.AI_CONFIDENCE_MIN

def get_signal_score_min() -> float:
    return SETTINGS.AGGRESSIVE_SIGNAL_SCORE_MIN if SETTINGS.AGGRESSIVE_TEST_MODE else SETTINGS.SIGNAL_SCORE_MIN

def get_setup_quality_min() -> float:
    return SETTINGS.AGGRESSIVE_MIN_SETUP_QUALITY if SETTINGS.AGGRESSIVE_TEST_MODE else SETTINGS.MIN_SETUP_QUALITY

def get_adx_trend_min() -> float:
    return SETTINGS.AGGRESSIVE_ADX_TREND_MIN if SETTINGS.AGGRESSIVE_TEST_MODE else SETTINGS.ADX_TREND_MIN

def get_max_risk_flags() -> int:
    return SETTINGS.AGGRESSIVE_MAX_RISK_FLAGS if SETTINGS.AGGRESSIVE_TEST_MODE else SETTINGS.MAX_RISK_FLAGS

def get_tf_score_min() -> float:
    # Safe default 1.2 matches strategy.py historical behaviour.
    return SETTINGS.AGGRESSIVE_TF_SCORE_MIN if SETTINGS.AGGRESSIVE_TEST_MODE else 1.2

def get_mtf_merge_threshold() -> float:
    # Safe default 0.4 matches merge_mtf historical behaviour.
    return SETTINGS.AGGRESSIVE_MTF_MERGE_THRESHOLD if SETTINGS.AGGRESSIVE_TEST_MODE else 0.4


def aggressive_mode_banner() -> str:
    """One-line operator banner. Empty when mode is off."""
    if not SETTINGS.AGGRESSIVE_TEST_MODE:
        return ''
    return (f"[AGGRESSIVE_TEST_MODE] conf_min={get_ai_confidence_min():.2f} "
            f"score_min={get_signal_score_min():.2f} quality_min={get_setup_quality_min():.2f} "
            f"adx_min={get_adx_trend_min():.0f} tf_score_min={get_tf_score_min():.1f} "
            f"mtf_merge={get_mtf_merge_threshold():.2f} risk_flags_max={get_max_risk_flags()}")
