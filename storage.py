import sqlite3
from typing import Any, Iterable, Optional
from config import SETTINGS

_CONN: Optional[sqlite3.Connection] = None

def _get_conn() -> sqlite3.Connection:
 global _CONN
 if _CONN is None:
 _CONN = sqlite3.connect(SETTINGS.DB_PATH, check_same_thread=False)
 _CONN.row_factory = sqlite3.Row
 return _CONN

def execute(sql: str, params: Iterable[Any] = ()):
 conn = _get_conn()
 cur = conn.cursor()
 cur.execute(sql, tuple(params))
 conn.commit()
 return cur.lastrowid

def fetchone(sql: str, params: Iterable[Any] = ()):
 cur = _get_conn().cursor()
 cur.execute(sql, tuple(params))
 return cur.fetchone()

def fetchall(sql: str, params: Iterable[Any] = ()):
 cur = _get_conn().cursor()
 cur.execute(sql, tuple(params))
 return cur.fetchall()

def init_db():
 conn = _get_conn()
 cur = conn.cursor()

 # users
 cur.execute('''
 CREATE TABLE IF NOT EXISTS users(
 user_id INTEGER PRIMARY KEY,
 tg_username TEXT,
 tier TEXT DEFAULT 'TRIAL',
 autotrade_enabled INTEGER DEFAULT 0,
 trade_mode TEXT DEFAULT 'PAPER',
 daily_loss_limit REAL DEFAULT 50,
 max_open_trades INTEGER DEFAULT 2,
 trial_start_ts INTEGER
 );
 ''')

 # trades
 cur.execute('''
 CREATE TABLE IF NOT EXISTS trades(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 pair TEXT NOT NULL,
 side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
 qty REAL NOT NULL,
 entry REAL NOT NULL,
 exit REAL,
 status TEXT NOT NULL DEFAULT 'OPEN',
 pnl REAL,
 ts_open INTEGER NOT NULL DEFAULT (strftime('%s','now')),
 ts_close INTEGER,
 notes TEXT
 );
 ''')
 cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_pair_status ON trades(pair,status);")

 # signals
 cur.execute('''
 CREATE TABLE IF NOT EXISTS signals(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 pair TEXT,
 timeframe TEXT,
 direction TEXT,
 score REAL,
 notes TEXT,
 ts INTEGER NOT NULL DEFAULT (strftime('%s','now'))
 );
 ''')

 # manual guards
 cur.execute('''
 CREATE TABLE IF NOT EXISTS manual_guards(
 user_id INTEGER NOT NULL,
 pair TEXT NOT NULL,
 stop_loss REAL,
 take_profit REAL,
 trail_pct REAL,
 trail_stop REAL,
 high_watermark REAL,
 PRIMARY KEY (user_id, pair)
 );
 ''')

 conn.commit()
