import time
from typing import Optional
from config import SETTINGS
from storage import execute, fetchall, fetchone

def _now() -> int:
 return int(time.time())

def open_trade(pair: str, side: str, qty: float, entry: float) -> int:
 return execute(
 "INSERT INTO trades(pair,side,qty,entry,status) VALUES(?,?,?,?, 'OPEN')",
 (pair, side, float(qty), float(entry))
 )

def _fetch_price(pair: str) -> Optional[float]:
 try:
 import ccxt
 ex = ccxt.kraken()
 t = ex.fetch_ticker(pair)
 for k in ("last","close","bid","ask"):
 v = t.get(k)
 if isinstance(v,(int,float)) and v>0:
 return float(v)
 except Exception:
 return None
 return None

def close_all_for_pair(pair: str, reason: str = "") -> int:
 """Close all OPEN trades for a pair at current market price."""
 px = _fetch_price(pair)
 if px is None or px <= 0:
 # fallback: try to close at entry (neutral), though unlikely in real usage
 px = 0.0

 rows = fetchall('SELECT id, side, qty, entry FROM trades WHERE status="OPEN" AND pair=?', (pair,))
 closed = 0
 for tid, side, qty, entry in rows:
 qty = float(qty); entry = float(entry)
 if px > 0:
 pnl = (px-entry)*qty if side=="BUY" else (entry-px)*qty
 else:
 pnl = 0.0
 execute(
 'UPDATE trades SET exit=?, pnl=?, status="CLOSED", ts_close=?, notes=? WHERE id=?',
 (px if px>0 else entry, pnl, _now(), reason, tid)
 )
 closed += 1
 return closed

def set_manual_guard(user_id: int, pair: str, sl=None, tp=None, trail_pct=None):
 row = fetchone('SELECT stop_loss, take_profit, trail_pct, trail_stop, high_watermark FROM manual_guards WHERE user_id=? AND pair=?',(user_id,pair))
 if row:
 cur_sl, cur_tp, cur_trail = row["stop_loss"], row["take_profit"], row["trail_pct"]
 if sl is not None: cur_sl = sl
 if tp is not None: cur_tp = tp
 if trail_pct is not None:
 cur_trail = trail_pct
 # reset trail stop + watermark when trail changes
 execute('UPDATE manual_guards SET stop_loss=?, take_profit=?, trail_pct=?, trail_stop=NULL, high_watermark=NULL WHERE user_id=? AND pair=?',
 (cur_sl, cur_tp, cur_trail, user_id, pair))
 return
 execute('UPDATE manual_guards SET stop_loss=?, take_profit=? WHERE user_id=? AND pair=?',
 (cur_sl, cur_tp, user_id, pair))
 else:
 execute('INSERT INTO manual_guards(user_id,pair,stop_loss,take_profit,trail_pct,trail_stop,high_watermark) VALUES(?,?,?,?,NULL,NULL,NULL)',
 (user_id,pair,sl,tp))

def clear_manual_guard(user_id: int, pair: str, which: str):
 which = which.lower()
 if which == "sl":
 execute('UPDATE manual_guards SET stop_loss=NULL WHERE user_id=? AND pair=?',(user_id,pair))
 elif which == "tp":
 execute('UPDATE manual_guards SET take_profit=NULL WHERE user_id=? AND pair=?',(user_id,pair))
 elif which == "trail":
 execute('UPDATE manual_guards SET trail_pct=NULL, trail_stop=NULL, high_watermark=NULL WHERE user_id=? AND pair=?',(user_id,pair))
 elif which == "all":
 execute('DELETE FROM manual_guards WHERE user_id=? AND pair=?',(user_id,pair))

# Backward-compat stubs (to avoid import errors from older code)
def check_manual_guards(*_args, **_kwargs):
 return None
