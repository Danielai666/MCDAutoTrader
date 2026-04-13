import sqlite3
from typing import Optional, List
from config import SETTINGS

SCHEMA = '''
PRAGMA journal_mode=WAL;

-- Original tables
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    tg_username TEXT,
    tier TEXT DEFAULT "BASIC",
    trial_start_ts INTEGER,
    trial_end_ts INTEGER,
    ai_api_key TEXT,
    autotrade_enabled INTEGER DEFAULT 0,
    trade_mode TEXT DEFAULT "PAPER",
    daily_loss_limit REAL DEFAULT 50.0,
    max_open_trades INTEGER DEFAULT 2
);

CREATE TABLE IF NOT EXISTS signals(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER,
    pair TEXT,
    tf TEXT,
    direction TEXT,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS trades(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_open INTEGER,
    ts_close INTEGER,
    pair TEXT,
    side TEXT,
    qty REAL,
    entry REAL,
    exit REAL,
    pnl REAL,
    status TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS manual_guards(
    user_id INTEGER,
    pair TEXT,
    stop_loss REAL,
    take_profit REAL,
    trail_pct REAL,
    trail_stop REAL,
    high_watermark REAL,
    PRIMARY KEY(user_id, pair)
);

-- New tables (Phase 1)
CREATE TABLE IF NOT EXISTS trading_pairs(
    pair TEXT PRIMARY KEY,
    is_active INTEGER DEFAULT 1,
    added_ts INTEGER,
    last_signal_ts INTEGER,
    last_direction TEXT,
    last_score REAL,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ai_decisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    pair TEXT NOT NULL,
    action TEXT NOT NULL,
    side TEXT,
    confidence REAL,
    setup_quality REAL,
    reasons TEXT,
    warnings TEXT,
    risk_flags TEXT,
    source TEXT,
    fusion_policy TEXT,
    raw_response TEXT,
    was_executed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS blocked_trades(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    pair TEXT NOT NULL,
    side TEXT,
    reason TEXT NOT NULL,
    signal_snapshot TEXT
);

CREATE TABLE IF NOT EXISTS bot_state(
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_ts INTEGER
);

CREATE TABLE IF NOT EXISTS performance_snapshots(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    pair TEXT,
    period TEXT,
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    total_pnl REAL,
    avg_win REAL,
    avg_loss REAL,
    win_rate REAL,
    expectancy REAL
);
'''

def get_conn():
    return sqlite3.connect(SETTINGS.DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate_trades_table(conn)
    conn.close()

def _migrate_trades_table(conn):
    """Safely add new columns to trades table for existing DBs."""
    for col, typedef in [
        ('lifecycle', "TEXT DEFAULT 'open'"),
        ('entry_snapshot', 'TEXT'),
        ('exit_snapshot', 'TEXT'),
        ('trade_type', "TEXT DEFAULT 'auto'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {typedef}")
        except Exception:
            pass  # column already exists
    conn.commit()

def fetchone(q, p=()):
    conn = get_conn(); cur = conn.cursor(); cur.execute(q, p)
    r = cur.fetchone(); conn.close(); return r

def fetchall(q, p=()):
    conn = get_conn(); cur = conn.cursor(); cur.execute(q, p)
    r = cur.fetchall(); conn.close(); return r

def execute(q, p=()):
    conn = get_conn(); cur = conn.cursor(); cur.execute(q, p)
    conn.commit(); rid = cur.lastrowid; conn.close(); return rid
