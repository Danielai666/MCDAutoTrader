# storage.py
# Dual database support: SQLite (local) or PostgreSQL (Supabase)
import logging
from config import SETTINGS

log = logging.getLogger(__name__)

_USE_POSTGRES = SETTINGS.DB_ENGINE.lower() == 'postgres'

# -------------------------------------------------------------------
# SQLite schema (used when DB_ENGINE=sqlite)
# -------------------------------------------------------------------
SQLITE_SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY, tg_username TEXT, tier TEXT DEFAULT "BASIC",
    trial_start_ts INTEGER, trial_end_ts INTEGER, ai_api_key TEXT,
    autotrade_enabled INTEGER DEFAULT 0, trade_mode TEXT DEFAULT "PAPER",
    daily_loss_limit REAL DEFAULT 50.0, max_open_trades INTEGER DEFAULT 2
);
CREATE TABLE IF NOT EXISTS signals(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, pair TEXT, tf TEXT,
    direction TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS trades(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_open INTEGER, ts_close INTEGER,
    pair TEXT, side TEXT, qty REAL, entry REAL, exit_price REAL, pnl REAL,
    status TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS manual_guards(
    user_id INTEGER, pair TEXT, stop_loss REAL, take_profit REAL,
    trail_pct REAL, trail_stop REAL, high_watermark REAL,
    PRIMARY KEY(user_id, pair)
);
CREATE TABLE IF NOT EXISTS trading_pairs(
    pair TEXT PRIMARY KEY, is_active INTEGER DEFAULT 1, added_ts INTEGER,
    last_signal_ts INTEGER, last_direction TEXT, last_score REAL, notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ai_decisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, pair TEXT NOT NULL,
    action TEXT NOT NULL, side TEXT, confidence REAL, setup_quality REAL,
    reasons TEXT, warnings TEXT, risk_flags TEXT, source TEXT, fusion_policy TEXT,
    raw_response TEXT, was_executed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS blocked_trades(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, pair TEXT NOT NULL,
    side TEXT, reason TEXT NOT NULL, signal_snapshot TEXT
);
CREATE TABLE IF NOT EXISTS bot_state(
    key TEXT PRIMARY KEY, value TEXT, updated_ts INTEGER
);
CREATE TABLE IF NOT EXISTS performance_snapshots(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, pair TEXT, period TEXT,
    total_trades INTEGER, winning_trades INTEGER, losing_trades INTEGER,
    total_pnl REAL, avg_win REAL, avg_loss REAL, win_rate REAL, expectancy REAL
);
'''

# -------------------------------------------------------------------
# Connection helpers
# -------------------------------------------------------------------
def _get_sqlite_conn():
    import sqlite3
    return sqlite3.connect(SETTINGS.DB_PATH, check_same_thread=False)

def _get_pg_conn():
    import psycopg2
    conn = psycopg2.connect(
        host=SETTINGS.SUPABASE_DB_HOST,
        port=SETTINGS.SUPABASE_DB_PORT,
        dbname=SETTINGS.SUPABASE_DB_NAME,
        user=SETTINGS.SUPABASE_DB_USER,
        password=SETTINGS.SUPABASE_DB_PASSWORD,
        options=f'-c search_path={SETTINGS.SUPABASE_SCHEMA},public',
    )
    conn.autocommit = False
    return conn

def get_conn():
    if _USE_POSTGRES:
        return _get_pg_conn()
    return _get_sqlite_conn()

# -------------------------------------------------------------------
# Placeholder conversion: SQLite uses ? but PostgreSQL uses %s
# -------------------------------------------------------------------
def _q(query: str) -> str:
    if _USE_POSTGRES:
        return query.replace('?', '%s')
    return query

# -------------------------------------------------------------------
# Init
# -------------------------------------------------------------------
def init_db():
    if _USE_POSTGRES:
        # Tables already created via Supabase migration
        log.info("Using PostgreSQL (Supabase) — schema: %s", SETTINGS.SUPABASE_SCHEMA)
        return

    # SQLite: run schema + migrations
    conn = _get_sqlite_conn()
    conn.executescript(SQLITE_SCHEMA)
    _migrate_sqlite_trades(conn)
    conn.close()

def _migrate_sqlite_trades(conn):
    # Add new columns if missing
    for col, typedef in [
        ('lifecycle', "TEXT DEFAULT 'open'"),
        ('entry_snapshot', 'TEXT'),
        ('exit_snapshot', 'TEXT'),
        ('trade_type', "TEXT DEFAULT 'auto'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {typedef}")
        except Exception:
            pass
    # Rename exit -> exit_price if old schema
    try:
        conn.execute("ALTER TABLE trades RENAME COLUMN exit TO exit_price")
    except Exception:
        pass  # already renamed or column doesn't exist
    conn.commit()

# -------------------------------------------------------------------
# Query helpers
# -------------------------------------------------------------------
def fetchone(q, p=()):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(_q(q), p)
        r = cur.fetchone()
        return r
    finally:
        conn.close()

def fetchall(q, p=()):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(_q(q), p)
        r = cur.fetchall()
        return r
    finally:
        conn.close()

def execute(q, p=()):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(_q(q), p)
        conn.commit()
        if _USE_POSTGRES:
            # PostgreSQL: try to get lastrowid via RETURNING, fallback to 0
            try:
                r = cur.fetchone()
                return r[0] if r else 0
            except Exception:
                return 0
        else:
            return cur.lastrowid
    finally:
        conn.close()
