import time
from storage import fetchall
def realized_pnl_today()->float:
 start=int(time.time())-86400; rows=fetchall('SELECT COALESCE(SUM(pnl),0) FROM trades WHERE ts_close IS NOT NULL AND ts_close>=?',(start,))
 return float(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else 0.0
def can_enter(max_open_trades: int, daily_loss_limit: float)->bool:
 rows=fetchall('SELECT COUNT(*) FROM trades WHERE status="OPEN"'); open_count=int(rows[0][0]) if rows else 0
 if open_count>=max_open_trades: return False
 if realized_pnl_today()<=-abs(daily_loss_limit): return False
 return True
