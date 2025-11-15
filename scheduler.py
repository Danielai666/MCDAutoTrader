import time, logging
from typing import Optional
from config import SETTINGS
from storage import execute
from ai_decider import decide

log = logging.getLogger(__name__)

def _fetch_price(pair: str) -> Optional[float]:
 try:
 import ccxt
 ex = ccxt.kraken()
 t = ex.fetch_ticker(pair)
 for k in ("last","close","bid","ask"):
 v = t.get(k)
 if isinstance(v,(int,float)) and v>0:
 return float(v)
 except Exception as e:
 log.warning("fetch_price failed: %s", e)
 return None

async def run_cycle_once(application, notify: bool = False) -> str:
 """One analysis cycle: produce a dummy 'merged' signal and let AI decider filter it."""
 pair = SETTINGS.PAIR
 px = _fetch_price(pair)
 if not px:
 msg = f"[{pair}] price unavailable - HOLD"
 return msg

 # Simple placeholder score around 0 (no strong bias); you can replace with real TA.
 score = 0.0
 direction = "HOLD"
 features = {"merged":{"merged_direction":direction, "merged_score":score}, "price":px}
 decision = decide(features)
 conf = decision.get("confidence", 0.55)

 msg = f"Signal: dir={direction} score={score:.2f} -> decision={decision['decision']} (conf={conf:.2f}) | px={px:g}"
 if notify and application:
 try:
 admin_ids = getattr(SETTINGS, "TELEGRAM_ADMIN_IDS", ())
 if admin_ids:
 await application.bot.send_message(chat_id=admin_ids[0], text=msg)
 except Exception as e:
 log.warning("notify failed: %s", e)
 # store a row in signals table
 try:
 execute("INSERT INTO signals(pair,timeframe,direction,score,notes) VALUES(?,?,?,?,?)",
 (pair, "merged", direction, score, decision.get("notes","")))
 except Exception as e:
 log.debug("store signal failed: %s", e)
 return msg

def schedule_jobs(app):
 # every 10 minutes
 app.job_queue.run_repeating(lambda c: run_cycle_once(c.application, notify=False),
 interval=600, first=5, name="job")
