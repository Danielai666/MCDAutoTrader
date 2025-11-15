import logging, os, time
from config import SETTINGS
from storage import init_db
from telegram_bot import build_app

def main():
 logging.basicConfig(level=getattr(logging, SETTINGS.LOG_LEVEL.upper(), logging.INFO))
 os.environ["TZ"] = SETTINGS.TZ
 if hasattr(time, "tzset"):
 try: time.tzset()
 except Exception: pass
 init_db()
 app = build_app()
 app.run_polling(allowed_updates=None)

if __name__ == "__main__":
 main()
