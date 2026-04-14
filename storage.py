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
CREATE TABLE IF NOT EXISTS credentials(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    provider_type TEXT NOT NULL DEFAULT 'ccxt',
    exchange_id TEXT NOT NULL DEFAULT 'kraken',
    api_key_enc TEXT NOT NULL,
    api_secret_enc TEXT NOT NULL,
    data_key_enc TEXT,
    encryption_version INTEGER DEFAULT 1,
    meta_json TEXT,
    is_active INTEGER DEFAULT 1,
    created_ts INTEGER,
    updated_ts INTEGER,
    UNIQUE(user_id, provider_type, exchange_id)
);
CREATE TABLE IF NOT EXISTS user_settings(
    user_id INTEGER PRIMARY KEY,
    mode TEXT DEFAULT 'signal_only',
    ai_mode TEXT DEFAULT 'signal_only',
    default_provider TEXT DEFAULT 'ccxt',
    default_exchange TEXT DEFAULT 'kraken',
    allowed_symbols_json TEXT,
    timeframe_policy TEXT DEFAULT '30m,1h,4h,1d',
    timezone TEXT DEFAULT 'UTC',
    panic_stop INTEGER DEFAULT 0,
    updated_ts INTEGER
);
CREATE TABLE IF NOT EXISTS operation_log(
    operation_id TEXT PRIMARY KEY,
    user_id INTEGER,
    op_type TEXT,
    pair TEXT,
    side TEXT,
    result_json TEXT,
    created_ts INTEGER
);
CREATE TABLE IF NOT EXISTS mt5_connections(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    bridge_token_id TEXT NOT NULL,
    bridge_secret_enc TEXT NOT NULL,
    broker_label TEXT DEFAULT '',
    symbol_map_json TEXT,
    is_active INTEGER DEFAULT 1,
    created_ts INTEGER,
    last_seen_ts INTEGER,
    UNIQUE(user_id, bridge_token_id)
);
CREATE TABLE IF NOT EXISTS mt5_nonces(
    nonce TEXT PRIMARY KEY,
    user_id INTEGER,
    created_ts INTEGER
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

CREATE TABLE IF NOT EXISTS credentials(
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    provider_type TEXT NOT NULL DEFAULT 'ccxt',
    exchange_id TEXT NOT NULL DEFAULT 'kraken',
    api_key_enc TEXT NOT NULL,
    api_secret_enc TEXT NOT NULL,
    data_key_enc TEXT,
    encryption_version INTEGER DEFAULT 1,
    meta_json TEXT,
    is_active INTEGER DEFAULT 1,
    created_ts BIGINT,
    updated_ts BIGINT,
    UNIQUE(user_id, provider_type, exchange_id)
);

CREATE TABLE IF NOT EXISTS user_settings(
    user_id BIGINT PRIMARY KEY,
    mode TEXT DEFAULT 'signal_only',
    ai_mode TEXT DEFAULT 'signal_only',
    default_provider TEXT DEFAULT 'ccxt',
    default_exchange TEXT DEFAULT 'kraken',
    allowed_symbols_json TEXT,
    timeframe_policy TEXT DEFAULT '30m,1h,4h,1d',
    timezone TEXT DEFAULT 'UTC',
    panic_stop INTEGER DEFAULT 0,
    updated_ts BIGINT
);

CREATE TABLE IF NOT EXISTS operation_log(
    operation_id TEXT PRIMARY KEY,
    user_id BIGINT,
    op_type TEXT,
    pair TEXT,
    side TEXT,
    result_json TEXT,
    created_ts BIGINT
);

CREATE TABLE IF NOT EXISTS mt5_connections(
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    bridge_token_id TEXT NOT NULL,
    bridge_secret_enc TEXT NOT NULL,
    broker_label TEXT DEFAULT '',
    symbol_map_json TEXT,
    is_active INTEGER DEFAULT 1,
    created_ts BIGINT,
    last_seen_ts BIGINT,
    UNIQUE(user_id, bridge_token_id)
);

CREATE TABLE IF NOT EXISTS mt5_nonces(
    nonce TEXT PRIMARY KEY,
    user_id BIGINT,
    created_ts BIGINT
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
        _migrate_multi_tenant(conn)
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


def _get_platform_owner_id() -> int:
    """Return the first admin ID as the platform owner. Used for migration defaults."""
    if SETTINGS.TELEGRAM_ADMIN_IDS:
        return SETTINGS.TELEGRAM_ADMIN_IDS[0]
    return 0


def _migrate_multi_tenant(conn):
    """Idempotent migration: add user_id to tables + per-user settings columns."""
    owner_id = _get_platform_owner_id()

    # Add user_id to data tables (existing rows get owner_id)
    for table in ['trades', 'signals', 'ai_decisions', 'blocked_trades',
                  'performance_snapshots']:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT {owner_id}")
        except Exception:
            pass

    # trading_pairs: add user_id (can't change PK in SQLite, so add column + unique index)
    try:
        conn.execute(f"ALTER TABLE trading_pairs ADD COLUMN user_id INTEGER DEFAULT {owner_id}")
    except Exception:
        pass
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_trading_pairs_user_pair ON trading_pairs(user_id, pair)")
    except Exception:
        pass

    # bot_state: add user_id (NULL = global, non-NULL = per-user)
    try:
        conn.execute("ALTER TABLE bot_state ADD COLUMN user_id INTEGER")
    except Exception:
        pass

    # Per-user settings columns on users table
    for col, typedef in [
        ('capital_usd', 'REAL DEFAULT 1000.0'),
        ('risk_per_trade', 'REAL DEFAULT 0.01'),
        ('exchange_key_enc', 'TEXT'),
        ('exchange_secret_enc', 'TEXT'),
        ('exchange_name', "TEXT DEFAULT 'kraken'"),
        ('paper_trading', 'INTEGER DEFAULT 1'),
        ('max_portfolio_exposure', 'REAL DEFAULT 0.50'),
        ('capital_per_trade_pct', 'REAL DEFAULT 0.10'),
        ('ai_fusion_policy', "TEXT DEFAULT 'local_only'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
        except Exception:
            pass

    # Indexes for performance
    for table in ['trades', 'signals', 'ai_decisions', 'blocked_trades']:
        try:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_user_id ON {table}(user_id)")
        except Exception:
            pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_user_status ON trades(user_id, status)")
    except Exception:
        pass

    # Visual settings columns on user_settings
    for col, typedef in [
        ('visuals_enabled', 'INTEGER DEFAULT 1'),
        ('visuals_style', "TEXT DEFAULT 'dark'"),
        ('visuals_density', "TEXT DEFAULT 'detailed'"),
        ('show_indicators', 'INTEGER DEFAULT 1'),
        ('show_ichimoku', 'INTEGER DEFAULT 1'),
        ('show_rsi', 'INTEGER DEFAULT 1'),
        ('show_macd', 'INTEGER DEFAULT 1'),
        ('show_levels', 'INTEGER DEFAULT 0'),
        ('show_divergence_marks', 'INTEGER DEFAULT 1'),
        ('show_volume', 'INTEGER DEFAULT 0'),
        ('chart_timeframes_json', "TEXT DEFAULT '[\"15m\",\"1h\",\"4h\",\"1d\"]'"),
        ('setup_completed_json', 'TEXT'),
    ]:
        try:
            conn.execute(f"ALTER TABLE user_settings ADD COLUMN {col} {typedef}")
        except Exception:
            pass


def _init_postgres():
    """Initialize PostgreSQL schema + multi-tenant migration — idempotent."""
    conn = _get_pg_conn()
    try:
        cur = conn.cursor()
        # Base schema
        schema_sql = POSTGRES_SCHEMA.format(schema=SETTINGS.SUPABASE_SCHEMA)
        for statement in schema_sql.split(';'):
            stmt = statement.strip()
            if stmt:
                cur.execute(stmt)
        conn.commit()

        # Multi-tenant migration (add user_id columns, per-user settings)
        owner_id = _get_platform_owner_id()
        migration_stmts = []
        for table in ['trades', 'signals', 'ai_decisions', 'blocked_trades',
                      'performance_snapshots']:
            migration_stmts.append(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id BIGINT DEFAULT {owner_id}")
        migration_stmts.append(
            f"ALTER TABLE trading_pairs ADD COLUMN IF NOT EXISTS user_id BIGINT DEFAULT {owner_id}")
        migration_stmts.append(
            "ALTER TABLE bot_state ADD COLUMN IF NOT EXISTS user_id BIGINT")
        for col, typedef in [
            ('capital_usd', 'DOUBLE PRECISION DEFAULT 1000.0'),
            ('risk_per_trade', 'DOUBLE PRECISION DEFAULT 0.01'),
            ('exchange_key_enc', 'TEXT'),
            ('exchange_secret_enc', 'TEXT'),
            ('exchange_name', "TEXT DEFAULT 'kraken'"),
            ('paper_trading', 'INTEGER DEFAULT 1'),
            ('max_portfolio_exposure', 'DOUBLE PRECISION DEFAULT 0.50'),
            ('capital_per_trade_pct', 'DOUBLE PRECISION DEFAULT 0.10'),
            ('ai_fusion_policy', "TEXT DEFAULT 'local_only'"),
        ]:
            migration_stmts.append(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {typedef}")
        # Indexes
        for table in ['trades', 'signals', 'ai_decisions', 'blocked_trades']:
            migration_stmts.append(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_user_id ON {table}(user_id)")
        migration_stmts.append(
            "CREATE INDEX IF NOT EXISTS idx_trades_user_status ON trades(user_id, status)")
        # Visual settings columns
        for col, typedef in [
            ('visuals_enabled', 'INTEGER DEFAULT 1'),
            ('visuals_style', "TEXT DEFAULT 'dark'"),
            ('visuals_density', "TEXT DEFAULT 'detailed'"),
            ('show_indicators', 'INTEGER DEFAULT 1'),
            ('show_ichimoku', 'INTEGER DEFAULT 1'),
            ('show_rsi', 'INTEGER DEFAULT 1'),
            ('show_macd', 'INTEGER DEFAULT 1'),
            ('show_levels', 'INTEGER DEFAULT 0'),
            ('show_divergence_marks', 'INTEGER DEFAULT 1'),
            ('show_volume', 'INTEGER DEFAULT 0'),
            ('chart_timeframes_json', "TEXT DEFAULT '[\"15m\",\"1h\",\"4h\",\"1d\"]'"),
            ('setup_completed_json', 'TEXT'),
        ]:
            migration_stmts.append(f"ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS {col} {typedef}")

        for stmt in migration_stmts:
            try:
                cur.execute(stmt)
            except Exception as e:
                log.debug("PG migration skip: %s", e)
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


# -------------------------------------------------------------------
# Credentials table helpers
# -------------------------------------------------------------------
def save_credential(user_id: int, provider_type: str, exchange_id: str,
                    api_key_enc: str, api_secret_enc: str,
                    data_key_enc: str = None, encryption_version: int = 2,
                    meta_json: str = None):
    """Save or update encrypted credentials for a user+provider+exchange combo."""
    import time as _t
    now = int(_t.time())
    if _USE_POSTGRES:
        execute(
            "INSERT INTO credentials(user_id, provider_type, exchange_id, api_key_enc, api_secret_enc, "
            "data_key_enc, encryption_version, meta_json, is_active, created_ts, updated_ts) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s) "
            "ON CONFLICT(user_id, provider_type, exchange_id) DO UPDATE SET "
            "api_key_enc=EXCLUDED.api_key_enc, api_secret_enc=EXCLUDED.api_secret_enc, "
            "data_key_enc=EXCLUDED.data_key_enc, encryption_version=EXCLUDED.encryption_version, "
            "meta_json=EXCLUDED.meta_json, updated_ts=EXCLUDED.updated_ts, is_active=1",
            (user_id, provider_type, exchange_id, api_key_enc, api_secret_enc,
             data_key_enc, encryption_version, meta_json, now, now)
        )
    else:
        existing = fetchone(
            "SELECT id FROM credentials WHERE user_id=? AND provider_type=? AND exchange_id=?",
            (user_id, provider_type, exchange_id))
        if existing:
            execute(
                "UPDATE credentials SET api_key_enc=?, api_secret_enc=?, data_key_enc=?, "
                "encryption_version=?, meta_json=?, updated_ts=?, is_active=1 "
                "WHERE user_id=? AND provider_type=? AND exchange_id=?",
                (api_key_enc, api_secret_enc, data_key_enc, encryption_version,
                 meta_json, now, user_id, provider_type, exchange_id))
        else:
            execute(
                "INSERT INTO credentials(user_id, provider_type, exchange_id, api_key_enc, api_secret_enc, "
                "data_key_enc, encryption_version, meta_json, is_active, created_ts, updated_ts) "
                "VALUES(?,?,?,?,?,?,?,?,1,?,?)",
                (user_id, provider_type, exchange_id, api_key_enc, api_secret_enc,
                 data_key_enc, encryption_version, meta_json, now, now))


def get_credential(user_id: int, provider_type: str = 'ccxt', exchange_id: str = None) -> dict:
    """Get active credential for a user. Returns dict or None."""
    if exchange_id:
        row = fetchone(
            "SELECT exchange_id, api_key_enc, api_secret_enc, data_key_enc, encryption_version, meta_json "
            "FROM credentials WHERE user_id=? AND provider_type=? AND exchange_id=? AND is_active=1",
            (user_id, provider_type, exchange_id))
    else:
        row = fetchone(
            "SELECT exchange_id, api_key_enc, api_secret_enc, data_key_enc, encryption_version, meta_json "
            "FROM credentials WHERE user_id=? AND provider_type=? AND is_active=1 "
            "ORDER BY updated_ts DESC",
            (user_id, provider_type))
    if not row:
        return None
    return {
        'exchange_id': row[0], 'api_key_enc': row[1], 'api_secret_enc': row[2],
        'data_key_enc': row[3], 'encryption_version': row[4], 'meta_json': row[5],
    }


def delete_credential(user_id: int, provider_type: str, exchange_id: str):
    """Soft-delete a credential (set is_active=0)."""
    execute(
        "UPDATE credentials SET is_active=0 WHERE user_id=? AND provider_type=? AND exchange_id=?",
        (user_id, provider_type, exchange_id))


# -------------------------------------------------------------------
# User settings helpers
# -------------------------------------------------------------------
def get_user_settings(user_id: int) -> dict:
    """Get user settings including visual preferences. Returns dict or None."""
    row = fetchone(
        "SELECT mode, ai_mode, default_provider, default_exchange, allowed_symbols_json, "
        "timeframe_policy, timezone, panic_stop, "
        "visuals_enabled, visuals_style, visuals_density, show_indicators, "
        "show_ichimoku, show_rsi, show_macd, show_levels, show_divergence_marks, "
        "show_volume, chart_timeframes_json, setup_completed_json "
        "FROM user_settings WHERE user_id=?", (user_id,))
    if not row:
        return None
    return {
        'mode': row[0], 'ai_mode': row[1], 'default_provider': row[2],
        'default_exchange': row[3], 'allowed_symbols_json': row[4],
        'timeframe_policy': row[5], 'timezone': row[6], 'panic_stop': row[7],
        'visuals_enabled': row[8], 'visuals_style': row[9],
        'visuals_density': row[10], 'show_indicators': row[11],
        'show_ichimoku': row[12], 'show_rsi': row[13],
        'show_macd': row[14], 'show_levels': row[15],
        'show_divergence_marks': row[16], 'show_volume': row[17],
        'chart_timeframes_json': row[18], 'setup_completed_json': row[19],
    }


_SETTINGS_ALLOWED_KEYS = (
    'mode', 'ai_mode', 'default_provider', 'default_exchange',
    'allowed_symbols_json', 'timeframe_policy', 'timezone', 'panic_stop',
    'visuals_enabled', 'visuals_style', 'visuals_density',
    'show_indicators', 'show_ichimoku', 'show_rsi', 'show_macd',
    'show_levels', 'show_divergence_marks', 'show_volume',
    'chart_timeframes_json', 'setup_completed_json',
)

def upsert_user_settings(user_id: int, **kwargs):
    """Update user settings. Only updates provided fields."""
    import time as _t
    now = int(_t.time())
    existing = get_user_settings(user_id)
    if existing:
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k in _SETTINGS_ALLOWED_KEYS:
                sets.append(f"{k}=?")
                vals.append(v)
        if sets:
            sets.append("updated_ts=?")
            vals.append(now)
            vals.append(user_id)
            execute(f"UPDATE user_settings SET {', '.join(sets)} WHERE user_id=?", tuple(vals))
    else:
        cols = ['user_id', 'updated_ts']
        vals = [user_id, now]
        for k, v in kwargs.items():
            if k in _SETTINGS_ALLOWED_KEYS:
                cols.append(k)
                vals.append(v)
        placeholders = ','.join(['?'] * len(cols))
        execute(f"INSERT INTO user_settings({','.join(cols)}) VALUES({placeholders})", tuple(vals))


# -------------------------------------------------------------------
# Operation log helpers (idempotency)
# -------------------------------------------------------------------
def check_operation_id(operation_id: str) -> dict:
    """Check if an operation already executed. Returns dict or None."""
    row = fetchone(
        "SELECT operation_id, user_id, op_type, pair, side, result_json "
        "FROM operation_log WHERE operation_id=?", (operation_id,))
    if not row:
        return None
    return {
        'operation_id': row[0], 'user_id': row[1], 'op_type': row[2],
        'pair': row[3], 'side': row[4], 'result_json': row[5],
    }


def record_operation(operation_id: str, user_id: int, op_type: str,
                     pair: str, side: str, result_json: str):
    """Record a completed operation for idempotency."""
    import time as _t
    execute(
        "INSERT INTO operation_log(operation_id, user_id, op_type, pair, side, result_json, created_ts) "
        "VALUES(?,?,?,?,?,?,?)",
        (operation_id, user_id, op_type, pair, side, result_json, int(_t.time()))
    )
