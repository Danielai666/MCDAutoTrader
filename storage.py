# storage.py
# Dual database support: SQLite (local dev) or PostgreSQL (production)
# Production target: PostgreSQL / Supabase
import logging
import threading
from config import SETTINGS

log = logging.getLogger(__name__)

_USE_POSTGRES = SETTINGS.DB_ENGINE.lower() == 'postgres'

# -------------------------------------------------------------------
# Connection management — thread-safe singleton for SQLite,
# per-call for PostgreSQL (stateless connections)
# -------------------------------------------------------------------
_sqlite_lock = threading.Lock()
_sqlite_conn = None


def _get_sqlite_conn():
    """Return a single shared SQLite connection (thread-safe via lock)."""
    global _sqlite_conn
    if _sqlite_conn is None:
        import sqlite3
        _sqlite_conn = sqlite3.connect(SETTINGS.DB_PATH, check_same_thread=False)
        _sqlite_conn.execute("PRAGMA journal_mode=WAL")
        _sqlite_conn.execute("PRAGMA busy_timeout=5000")
    return _sqlite_conn


def _get_pg_conn():
    import psycopg2
    conn = psycopg2.connect(
        host=SETTINGS.SUPABASE_DB_HOST,
        port=SETTINGS.SUPABASE_DB_PORT,
        dbname=SETTINGS.SUPABASE_DB_NAME,
        user=SETTINGS.SUPABASE_DB_USER,
        password=SETTINGS.SUPABASE_DB_PASSWORD,
        options=f'-c search_path={SETTINGS.SUPABASE_SCHEMA},public',
        connect_timeout=10,
    )
    conn.autocommit = False
    return conn


# -------------------------------------------------------------------
# Placeholder conversion: SQLite uses ? but PostgreSQL uses %s
# -------------------------------------------------------------------
def _q(query: str) -> str:
    if _USE_POSTGRES:
        # Convert ? to %s, but skip ?? (escaped question marks)
        result = []
        i = 0
        while i < len(query):
            if query[i] == '?' and (i + 1 >= len(query) or query[i + 1] != '?'):
                result.append('%s')
            else:
                result.append(query[i])
            i += 1
        return ''.join(result)
    return query


# -------------------------------------------------------------------
# SQLite schema
# -------------------------------------------------------------------
SQLITE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY, tg_username TEXT, tier TEXT DEFAULT 'BASIC',
    trial_start_ts INTEGER, trial_end_ts INTEGER, ai_api_key TEXT,
    autotrade_enabled INTEGER DEFAULT 0, trade_mode TEXT DEFAULT 'PAPER',
    daily_loss_limit REAL DEFAULT 50.0, max_open_trades INTEGER DEFAULT 2
);
CREATE TABLE IF NOT EXISTS signals(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, pair TEXT, tf TEXT,
    direction TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS trades(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_open INTEGER, ts_close INTEGER,
    pair TEXT, side TEXT, qty REAL, entry REAL, exit_price REAL, pnl REAL,
    status TEXT, note TEXT, lifecycle TEXT DEFAULT 'open',
    entry_snapshot TEXT, exit_snapshot TEXT,
    trade_type TEXT DEFAULT 'auto', order_id TEXT
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
# PostgreSQL schema (for production deployment)
# -------------------------------------------------------------------
POSTGRES_SCHEMA = '''
CREATE SCHEMA IF NOT EXISTS {schema};
SET search_path TO {schema}, public;

CREATE TABLE IF NOT EXISTS users(
    user_id BIGINT PRIMARY KEY, tg_username TEXT, tier TEXT DEFAULT 'BASIC',
    trial_start_ts BIGINT, trial_end_ts BIGINT, ai_api_key TEXT,
    autotrade_enabled INTEGER DEFAULT 0, trade_mode TEXT DEFAULT 'PAPER',
    daily_loss_limit DOUBLE PRECISION DEFAULT 50.0,
    max_open_trades INTEGER DEFAULT 2
);

CREATE TABLE IF NOT EXISTS signals(
    id BIGSERIAL PRIMARY KEY, ts BIGINT, pair TEXT, tf TEXT,
    direction TEXT, reason TEXT
);

CREATE TABLE IF NOT EXISTS trades(
    id BIGSERIAL PRIMARY KEY, ts_open BIGINT, ts_close BIGINT,
    pair TEXT, side TEXT, qty DOUBLE PRECISION, entry DOUBLE PRECISION,
    exit_price DOUBLE PRECISION, pnl DOUBLE PRECISION,
    status TEXT, note TEXT, lifecycle TEXT DEFAULT 'open',
    entry_snapshot TEXT, exit_snapshot TEXT,
    trade_type TEXT DEFAULT 'auto', order_id TEXT
);

CREATE TABLE IF NOT EXISTS manual_guards(
    user_id BIGINT, pair TEXT,
    stop_loss DOUBLE PRECISION, take_profit DOUBLE PRECISION,
    trail_pct DOUBLE PRECISION, trail_stop DOUBLE PRECISION,
    high_watermark DOUBLE PRECISION,
    PRIMARY KEY(user_id, pair)
);

CREATE TABLE IF NOT EXISTS trading_pairs(
    pair TEXT PRIMARY KEY, is_active INTEGER DEFAULT 1, added_ts BIGINT,
    last_signal_ts BIGINT, last_direction TEXT,
    last_score DOUBLE PRECISION, notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ai_decisions(
    id BIGSERIAL PRIMARY KEY, ts BIGINT NOT NULL, pair TEXT NOT NULL,
    action TEXT NOT NULL, side TEXT, confidence DOUBLE PRECISION,
    setup_quality DOUBLE PRECISION,
    reasons TEXT, warnings TEXT, risk_flags TEXT, source TEXT,
    fusion_policy TEXT, raw_response TEXT, was_executed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS blocked_trades(
    id BIGSERIAL PRIMARY KEY, ts BIGINT NOT NULL, pair TEXT NOT NULL,
    side TEXT, reason TEXT NOT NULL, signal_snapshot TEXT
);

CREATE TABLE IF NOT EXISTS bot_state(
    key TEXT PRIMARY KEY, value TEXT, updated_ts BIGINT
);

CREATE TABLE IF NOT EXISTS performance_snapshots(
    id BIGSERIAL PRIMARY KEY, ts BIGINT NOT NULL, pair TEXT, period TEXT,
    total_trades INTEGER, winning_trades INTEGER, losing_trades INTEGER,
    total_pnl DOUBLE PRECISION, avg_win DOUBLE PRECISION,
    avg_loss DOUBLE PRECISION, win_rate DOUBLE PRECISION,
    expectancy DOUBLE PRECISION
);
'''


# -------------------------------------------------------------------
# Initialization
# -------------------------------------------------------------------
def init_db():
    if _USE_POSTGRES:
        _init_postgres()
    else:
        _init_sqlite()
    log.info("Database initialized: %s", "PostgreSQL" if _USE_POSTGRES else "SQLite")


def _init_sqlite():
    conn = _get_sqlite_conn()
    with _sqlite_lock:
        conn.executescript(SQLITE_SCHEMA)
        _migrate_sqlite_trades(conn)
        conn.commit()


def _migrate_sqlite_trades(conn):
    for col, typedef in [
        ('lifecycle', "TEXT DEFAULT 'open'"),
        ('entry_snapshot', 'TEXT'),
        ('exit_snapshot', 'TEXT'),
        ('trade_type', "TEXT DEFAULT 'auto'"),
        ('order_id', 'TEXT'),
    ]:
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {typedef}")
        except Exception:
            pass
    try:
        conn.execute("ALTER TABLE trades RENAME COLUMN exit TO exit_price")
    except Exception:
        pass


def _init_postgres():
    """Initialize PostgreSQL schema — idempotent."""
    conn = _get_pg_conn()
    try:
        cur = conn.cursor()
        schema_sql = POSTGRES_SCHEMA.format(schema=SETTINGS.SUPABASE_SCHEMA)
        for statement in schema_sql.split(';'):
            stmt = statement.strip()
            if stmt:
                cur.execute(stmt)
        conn.commit()
        log.info("PostgreSQL schema verified: %s", SETTINGS.SUPABASE_SCHEMA)
    except Exception as e:
        conn.rollback()
        log.error("PostgreSQL schema init failed: %s", e)
        raise
    finally:
        conn.close()


# -------------------------------------------------------------------
# Query helpers — backend-aware, with proper error handling
# -------------------------------------------------------------------
def fetchone(q, p=()):
    if _USE_POSTGRES:
        return _pg_fetchone(q, p)
    return _sqlite_fetchone(q, p)


def fetchall(q, p=()):
    if _USE_POSTGRES:
        return _pg_fetchall(q, p)
    return _sqlite_fetchall(q, p)


def execute(q, p=()):
    if _USE_POSTGRES:
        return _pg_execute(q, p)
    return _sqlite_execute(q, p)


# --- SQLite implementations (shared connection, locked) ---

def _sqlite_fetchone(q, p):
    conn = _get_sqlite_conn()
    with _sqlite_lock:
        cur = conn.cursor()
        cur.execute(q, p)
        return cur.fetchone()


def _sqlite_fetchall(q, p):
    conn = _get_sqlite_conn()
    with _sqlite_lock:
        cur = conn.cursor()
        cur.execute(q, p)
        return cur.fetchall()


def _sqlite_execute(q, p):
    conn = _get_sqlite_conn()
    with _sqlite_lock:
        cur = conn.cursor()
        cur.execute(q, p)
        conn.commit()
        return cur.lastrowid


# --- PostgreSQL implementations (per-call connection, explicit rollback) ---

def _pg_fetchone(q, p):
    conn = _get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(_q(q), p)
        r = cur.fetchone()
        conn.commit()
        return r
    except Exception as e:
        conn.rollback()
        log.error("PG fetchone error: %s | query: %s", e, q[:200])
        raise
    finally:
        conn.close()


def _pg_fetchall(q, p):
    conn = _get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(_q(q), p)
        r = cur.fetchall()
        conn.commit()
        return r
    except Exception as e:
        conn.rollback()
        log.error("PG fetchall error: %s | query: %s", e, q[:200])
        raise
    finally:
        conn.close()


def _pg_execute(q, p):
    conn = _get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(_q(q), p)
        conn.commit()
        # Try to fetch RETURNING result
        try:
            r = cur.fetchone()
            return r[0] if r else 0
        except Exception:
            return 0
    except Exception as e:
        conn.rollback()
        log.error("PG execute error: %s | query: %s", e, q[:200])
        raise
    finally:
        conn.close()


# -------------------------------------------------------------------
# Backend-aware upsert helper
# -------------------------------------------------------------------
def upsert_bot_state(key: str, value: str, ts: int):
    """Upsert into bot_state — works on both SQLite and PostgreSQL."""
    if _USE_POSTGRES:
        execute(
            "INSERT INTO bot_state(key, value, updated_ts) VALUES(%s,%s,%s) "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_ts=EXCLUDED.updated_ts",
            (key, value, ts)
        )
    else:
        execute(
            "INSERT OR REPLACE INTO bot_state(key, value, updated_ts) VALUES(?,?,?)",
            (key, value, ts)
        )


def upsert_manual_guard(uid: int, pair: str, sl, tp, trail_pct, trail_stop, high_wm):
    """Upsert into manual_guards — works on both SQLite and PostgreSQL."""
    if _USE_POSTGRES:
        execute(
            "INSERT INTO manual_guards(user_id, pair, stop_loss, take_profit, trail_pct, trail_stop, high_watermark) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(user_id, pair) DO UPDATE SET "
            "stop_loss=EXCLUDED.stop_loss, take_profit=EXCLUDED.take_profit, "
            "trail_pct=EXCLUDED.trail_pct, trail_stop=EXCLUDED.trail_stop, "
            "high_watermark=EXCLUDED.high_watermark",
            (uid, pair, sl, tp, trail_pct, trail_stop, high_wm)
        )
    else:
        execute(
            "INSERT OR REPLACE INTO manual_guards(user_id, pair, stop_loss, take_profit, trail_pct, trail_stop, high_watermark) "
            "VALUES(?,?,?,?,?,?,?)",
            (uid, pair, sl, tp, trail_pct, trail_stop, high_wm)
        )


def upsert_user(uid: int, username: str, ts: int):
    """Upsert user — works on both backends."""
    if _USE_POSTGRES:
        execute(
            "INSERT INTO users(user_id, tg_username, trial_start_ts) VALUES(%s,%s,%s) "
            "ON CONFLICT(user_id) DO NOTHING",
            (uid, username, ts)
        )
    else:
        execute(
            "INSERT OR IGNORE INTO users(user_id, tg_username, trial_start_ts) VALUES(?,?,?)",
            (uid, username, ts)
        )


def upsert_trading_pair(pair: str, is_active: int, added_ts: int, notes: str = ''):
    """Upsert trading pair — works on both backends."""
    if _USE_POSTGRES:
        execute(
            "INSERT INTO trading_pairs(pair, is_active, added_ts, notes) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(pair) DO UPDATE SET is_active=EXCLUDED.is_active",
            (pair, is_active, added_ts, notes)
        )
    else:
        # Try insert, ignore if exists
        existing = fetchone("SELECT pair FROM trading_pairs WHERE pair=?", (pair,))
        if not existing:
            execute(
                "INSERT INTO trading_pairs(pair, is_active, added_ts, notes) VALUES(?,?,?,?)",
                (pair, is_active, added_ts, notes)
            )


def insert_trade(pair: str, side: str, qty: float, price: float,
                 reason: str, entry_snapshot: str = None) -> int:
    """Insert trade and return the new trade ID — works on both backends."""
    import time
    now = int(time.time())
    if _USE_POSTGRES:
        row = fetchone(
            "INSERT INTO trades(pair, side, qty, entry, status, ts_open, note, lifecycle, entry_snapshot, trade_type) "
            "VALUES(%s,%s,%s,%s, 'OPEN', %s, %s, 'open', %s, 'auto') RETURNING id",
            (pair, side.upper(), float(qty), float(price), now, reason or "open_trade", entry_snapshot))
        return int(row[0]) if row else 0
    else:
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO trades(pair, side, qty, entry, status, ts_open, note, lifecycle, entry_snapshot, trade_type) "
                "VALUES(?,?,?,?, 'OPEN', ?, ?, 'open', ?, 'auto')",
                (pair, side.upper(), float(qty), float(price), now, reason or "open_trade", entry_snapshot))
            conn.commit()
            return cur.lastrowid


def append_trade_note(trade_id: int, note_text: str):
    """Safely append to trade note field — works on both backends."""
    if not note_text:
        return
    # Use CONCAT-style update that works on both
    execute(
        "UPDATE trades SET note = CASE WHEN note IS NULL THEN ? ELSE note || ? END WHERE id=?",
        (note_text, note_text, trade_id)
    )


# -------------------------------------------------------------------
# Health check
# -------------------------------------------------------------------
def check_db_health() -> tuple:
    """Returns (ok: bool, message: str, details: dict)."""
    details = {'engine': 'postgres' if _USE_POSTGRES else 'sqlite'}
    try:
        row = fetchone("SELECT COUNT(*) FROM users")
        details['users'] = int(row[0]) if row else 0

        row = fetchone("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
        details['open_trades'] = int(row[0]) if row else 0

        row = fetchone("SELECT COUNT(*) FROM trading_pairs WHERE is_active=1")
        details['active_pairs'] = int(row[0]) if row else 0

        row = fetchone("SELECT COUNT(*) FROM bot_state")
        details['state_keys'] = int(row[0]) if row else 0

        return True, f"DB OK ({details['engine']})", details
    except Exception as e:
        return False, f"DB error: {e}", details
