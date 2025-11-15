import os, csv, time
from typing import Optional
from storage import fetchall
from config import SETTINGS

def export_trades_csv(out_dir: Optional[str] = None) -> str:
 if not out_dir:
 out_dir = os.path.join(os.getcwd(), "exports")
 os.makedirs(out_dir, exist_ok=True)
 ts = time.strftime("%Y%m%d_%H%M%S")
 path = os.path.join(out_dir, f"trades_{ts}.csv")
 rows = fetchall("SELECT id,pair,side,qty,entry,exit,status,pnl,ts_open,ts_close FROM trades ORDER BY id ASC")
 with open(path, "w", newline="") as f:
 w = csv.writer(f)
 w.writerow(["id","pair","side","qty","entry","exit","status","pnl","ts_open","ts_close"])
 for r in rows:
 w.writerow([r["id"], r["pair"], r["side"], r["qty"], r["entry"], r["exit"], r["status"], r["pnl"], r["ts_open"], r["ts_close"]])
 return path
