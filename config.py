import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load .env from current working directory
load_dotenv()

def _ids(v: str):
 return tuple(int(x.strip()) for x in v.split(',') if x.strip()) if v else tuple()

@dataclass
class Settings:
 # Core
 ENV: str = os.getenv('ENV', 'dev')
 TZ: str = os.getenv('TZ', 'America/Vancouver')
 DB_PATH: str = os.getenv('DB_PATH', './bot.db')
 LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

 # Market / Exchange
 EXCHANGE: str = os.getenv('EXCHANGE', 'kraken')
 PAIR: str = os.getenv('PAIR', 'BNB/USDC')
 TIMEFRAMES: tuple = tuple(map(str.strip, os.getenv('TIMEFRAMES','30m,1h,4h,1d').split(',')))
 CANDLE_LIMIT: int = int(os.getenv('CANDLE_LIMIT','300'))
 PAPER_TRADING: bool = os.getenv('PAPER_TRADING','true').lower()=='true'

 # Risk
 CAPITAL_USD: float = float(os.getenv('CAPITAL_USD','1000'))
 RISK_PER_TRADE: float = float(os.getenv('RISK_PER_TRADE','0.01'))
 MAX_OPEN_TRADES: int = int(os.getenv('MAX_OPEN_TRADES','2'))
 DAILY_LOSS_LIMIT_USD: float = float(os.getenv('DAILY_LOSS_LIMIT_USD','50'))
 ENABLE_EXIT_AUTOMATION: bool = os.getenv('ENABLE_EXIT_AUTOMATION','true').lower()=='true'

 # Telegram
 TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN','')
 TELEGRAM_ADMIN_IDS: tuple = _ids(os.getenv('TELEGRAM_ADMIN_IDS',''))
 HTTPS_PROXY: str = os.getenv('HTTPS_PROXY','')

 # Optional AI Decider (remote)
 AI_BASE_URL: str = os.getenv('AI_BASE_URL','')
 AI_API_KEY: str = os.getenv('AI_API_KEY','')

 # Payments (optional)
 PAYMENT_PROVIDER: str = os.getenv('PAYMENT_PROVIDER','')
 STRIPE_SECRET_KEY: str = os.getenv('STRIPE_SECRET_KEY','')

 # LIVE control
 LIVE_TRADE_ALLOWED_IDS: tuple = _ids(os.getenv('LIVE_TRADE_ALLOWED_IDS',''))
 KRAKEN_API_KEY: str = os.getenv('KRAKEN_API_KEY','')
 KRAKEN_API_SECRET: str = os.getenv('KRAKEN_API_SECRET','')

SETTINGS = Settings()

# Extra AI thresholds & model
try:
 SETTINGS.AI_CONFIDENCE_MIN = float(os.getenv("AI_CONFIDENCE_MIN", "0.65"))
except Exception:
 SETTINGS.AI_CONFIDENCE_MIN = 0.65

try:
 SETTINGS.SIGNAL_SCORE_MIN = float(os.getenv("SIGNAL_SCORE_MIN", "0.60"))
except Exception:
 SETTINGS.SIGNAL_SCORE_MIN = 0.60

SETTINGS.AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
