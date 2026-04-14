# mt5_bridge.py
# MT5 EA Bridge: REST API server for MetaTrader 5 Expert Advisor communication.
# The EA runs on the user's MT5 terminal (VPS or local) and calls our endpoints.
# We NEVER store broker credentials — only a shared HMAC secret per bridge connection.
#
# Authentication: HMAC-SHA256 with nonce + timestamp to prevent replay attacks.
# Feature-flagged: FEATURE_MT5_BRIDGE must be true.

import time
import hmac
import hashlib
import json
import logging
import secrets
from typing import Optional
from config import SETTINGS
from storage import fetchone, fetchall, execute, upsert_bot_state

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# HMAC Authentication
# -------------------------------------------------------------------

def generate_bridge_token() -> tuple:
    """Generate a new bridge token ID and shared secret for a user.
    Returns (token_id: str, secret: str) — the secret is shown ONCE to the user.
    """
    token_id = f"mt5_{secrets.token_hex(8)}"
    shared_secret = secrets.token_hex(32)
    return token_id, shared_secret


def compute_hmac(secret: str, method: str, path: str, body: str,
                 timestamp: str, nonce: str) -> str:
    """Compute HMAC-SHA256 signature for request verification."""
    message = f"{method.upper()}|{path}|{body}|{timestamp}|{nonce}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_hmac(user_id: int, token_id: str, method: str, path: str,
                body: str, timestamp: str, nonce: str, signature: str) -> tuple:
    """
    Verify HMAC signature for an incoming EA request.
    Returns (ok: bool, reason: str).

    Checks:
    1. Token exists and is active
    2. Timestamp within replay window
    3. Nonce not already used
    4. HMAC signature matches
    """
    # 1. Load bridge connection
    row = fetchone(
        "SELECT bridge_secret_enc, is_active FROM mt5_connections "
        "WHERE user_id=? AND bridge_token_id=?",
        (user_id, token_id))
    if not row:
        return False, "Unknown bridge token"
    secret_enc, is_active = row
    if not is_active:
        return False, "Bridge token deactivated"

    # Decrypt shared secret
    try:
        from crypto_utils import decrypt_credential
        shared_secret = decrypt_credential(secret_enc)
    except Exception as e:
        return False, f"Secret decryption failed: {e}"

    # 2. Timestamp check (replay window)
    try:
        req_ts = int(timestamp)
    except ValueError:
        return False, "Invalid timestamp"
    now = int(time.time())
    if abs(now - req_ts) > SETTINGS.MT5_REPLAY_WINDOW_SECONDS:
        return False, f"Timestamp outside replay window ({abs(now - req_ts)}s)"

    # 3. Nonce check (prevent replay)
    existing_nonce = fetchone("SELECT nonce FROM mt5_nonces WHERE nonce=?", (nonce,))
    if existing_nonce:
        return False, "Nonce already used (replay attempt)"

    # Record nonce
    execute("INSERT INTO mt5_nonces(nonce, user_id, created_ts) VALUES(?,?,?)",
            (nonce, user_id, now))

    # Cleanup old nonces (older than 2x replay window)
    cutoff = now - (SETTINGS.MT5_REPLAY_WINDOW_SECONDS * 2)
    execute("DELETE FROM mt5_nonces WHERE created_ts < ?", (cutoff,))

    # 4. HMAC verification
    expected = compute_hmac(shared_secret, method, path, body, timestamp, nonce)
    if not hmac.compare_digest(expected, signature):
        return False, "HMAC signature mismatch"

    # Update last_seen
    execute("UPDATE mt5_connections SET last_seen_ts=? WHERE user_id=? AND bridge_token_id=?",
            (now, user_id, token_id))

    return True, "OK"


# -------------------------------------------------------------------
# Bridge connection management
# -------------------------------------------------------------------

def create_bridge_connection(user_id: int, broker_label: str = '',
                              symbol_map: dict = None) -> dict:
    """Create a new MT5 bridge connection for a user.
    Returns {token_id, secret (plaintext, show once), broker_label}.
    """
    token_id, shared_secret = generate_bridge_token()

    # Encrypt the shared secret for storage
    from crypto_utils import encrypt_credential
    secret_enc = encrypt_credential(shared_secret)

    symbol_map_json = json.dumps(symbol_map) if symbol_map else None
    now = int(time.time())

    execute(
        "INSERT INTO mt5_connections(user_id, bridge_token_id, bridge_secret_enc, "
        "broker_label, symbol_map_json, is_active, created_ts) VALUES(?,?,?,?,?,1,?)",
        (user_id, token_id, secret_enc, broker_label, symbol_map_json, now))

    return {
        'token_id': token_id,
        'secret': shared_secret,  # Show ONCE to user, never stored in plaintext
        'broker_label': broker_label,
    }


def get_bridge_connection(user_id: int) -> Optional[dict]:
    """Get active bridge connection for a user."""
    row = fetchone(
        "SELECT bridge_token_id, broker_label, symbol_map_json, last_seen_ts "
        "FROM mt5_connections WHERE user_id=? AND is_active=1",
        (user_id,))
    if not row:
        return None
    return {
        'token_id': row[0],
        'broker_label': row[1],
        'symbol_map': json.loads(row[2]) if row[2] else {},
        'last_seen': row[3],
    }


def deactivate_bridge(user_id: int, token_id: str):
    """Deactivate a bridge connection."""
    execute("UPDATE mt5_connections SET is_active=0 WHERE user_id=? AND bridge_token_id=?",
            (user_id, token_id))


def update_symbol_map(user_id: int, token_id: str, symbol_map: dict):
    """Update the symbol mapping for a bridge connection."""
    execute("UPDATE mt5_connections SET symbol_map_json=? WHERE user_id=? AND bridge_token_id=?",
            (json.dumps(symbol_map), user_id, token_id))


# -------------------------------------------------------------------
# Symbol mapping
# -------------------------------------------------------------------

# Default canonical → common broker mappings
DEFAULT_SYMBOL_MAP = {
    'XAUUSD': ['GOLD', 'XAUUSDm', 'XAUUSD.', 'Gold'],
    'EURUSD': ['EURUSDm', 'EURUSD.'],
    'GBPUSD': ['GBPUSDm', 'GBPUSD.'],
    'USDJPY': ['USDJPYm', 'USDJPY.'],
    'BTCUSD': ['BTCUSDm', 'Bitcoin'],
}


def resolve_symbol(canonical: str, user_id: int = None) -> str:
    """Resolve canonical symbol to broker-specific symbol using user's mapping."""
    if user_id:
        conn = get_bridge_connection(user_id)
        if conn and conn.get('symbol_map'):
            mapped = conn['symbol_map'].get(canonical)
            if mapped:
                return mapped

    # No user mapping — return canonical as-is
    return canonical


def canonical_from_broker(broker_symbol: str, user_id: int = None) -> str:
    """Reverse-resolve broker symbol to canonical."""
    if user_id:
        conn = get_bridge_connection(user_id)
        if conn and conn.get('symbol_map'):
            for canonical, broker in conn['symbol_map'].items():
                if broker == broker_symbol:
                    return canonical
    return broker_symbol


# -------------------------------------------------------------------
# Lot sizing for MT5
# -------------------------------------------------------------------

def compute_mt5_lot_size(capital: float, risk_pct: float, stop_distance_points: float,
                          tick_value: float, tick_size: float,
                          contract_size: float = 100000, min_lot: float = 0.01,
                          max_lot: float = 100.0) -> float:
    """
    Compute lot size for MT5 instruments.

    capital: account equity in USD
    risk_pct: risk per trade (e.g. 0.01 = 1%)
    stop_distance_points: distance from entry to SL in price points
    tick_value: value of one tick in account currency
    tick_size: price change per tick (e.g. 0.01 for XAUUSD)
    contract_size: units per lot (100000 for forex, 100 for gold)
    min_lot / max_lot: broker limits
    """
    if stop_distance_points <= 0 or tick_value <= 0 or tick_size <= 0:
        return min_lot

    risk_usd = capital * risk_pct
    ticks_in_stop = stop_distance_points / tick_size
    risk_per_lot = ticks_in_stop * tick_value

    if risk_per_lot <= 0:
        return min_lot

    lots = risk_usd / risk_per_lot
    # Round to 2 decimal places (standard lot step)
    lots = round(lots, 2)
    return max(min_lot, min(lots, max_lot))


# -------------------------------------------------------------------
# Session/rollover window checks
# -------------------------------------------------------------------

# Common session times (UTC hours)
FOREX_SESSIONS = {
    'sydney': (21, 6),    # 21:00 - 06:00 UTC
    'tokyo': (0, 9),      # 00:00 - 09:00 UTC
    'london': (7, 16),    # 07:00 - 16:00 UTC
    'newyork': (13, 22),  # 13:00 - 22:00 UTC
}

# Rollover/low liquidity windows to avoid
AVOID_WINDOWS = [
    (23, 1),   # Daily rollover
    (21, 22),  # Sydney open (can be volatile)
]


def is_market_open(symbol: str) -> bool:
    """Check if the market is likely open for the given symbol."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour

    # Forex/Gold: closed Saturday-Sunday (roughly Fri 22:00 - Sun 22:00 UTC)
    if weekday == 5:  # Saturday
        return False
    if weekday == 6 and hour < 22:  # Sunday before 22:00
        return False
    if weekday == 4 and hour >= 22:  # Friday after 22:00
        return False

    return True


def is_in_rollover_window() -> bool:
    """Check if we're in a daily rollover/low-liquidity window."""
    from datetime import datetime, timezone
    hour = datetime.now(timezone.utc).hour
    for start, end in AVOID_WINDOWS:
        if start <= end:
            if start <= hour < end:
                return True
        else:  # wraps midnight
            if hour >= start or hour < end:
                return True
    return False


def check_spread_guard(spread_pips: float) -> tuple:
    """Check if spread is within acceptable range.
    Returns (ok: bool, message: str).
    """
    max_spread = SETTINGS.MT5_MAX_SPREAD_PIPS
    if spread_pips > max_spread:
        return False, f"Spread {spread_pips:.1f} pips > max {max_spread:.1f}"
    return True, "OK"


# -------------------------------------------------------------------
# FastAPI REST endpoints (to be run as a separate service)
# -------------------------------------------------------------------

def create_bridge_app():
    """Create FastAPI app for MT5 EA Bridge endpoints.
    Run separately: uvicorn mt5_bridge:create_bridge_app --factory
    """
    try:
        from fastapi import FastAPI, Request, HTTPException
        from fastapi.responses import JSONResponse
    except ImportError:
        log.warning("FastAPI not installed. MT5 bridge endpoints unavailable.")
        return None

    app = FastAPI(title="MCDAutoTrader MT5 Bridge", version="1.0")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """HMAC authentication middleware for all bridge endpoints."""
        if request.url.path in ("/health", "/docs", "/openapi.json"):
            return await call_next(request)

        # Extract auth headers
        token_id = request.headers.get("X-Bridge-Token", "")
        user_id_str = request.headers.get("X-User-ID", "")
        timestamp = request.headers.get("X-Timestamp", "")
        nonce = request.headers.get("X-Nonce", "")
        signature = request.headers.get("X-Signature", "")

        if not all([token_id, user_id_str, timestamp, nonce, signature]):
            raise HTTPException(status_code=401, detail="Missing authentication headers")

        try:
            user_id = int(user_id_str)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid user ID")

        body = (await request.body()).decode() if request.method in ("POST", "PUT") else ""

        ok, reason = verify_hmac(user_id, token_id, request.method,
                                  request.url.path, body, timestamp, nonce, signature)
        if not ok:
            log.warning("MT5 bridge auth failed for user %d: %s", user_id, reason)
            raise HTTPException(status_code=403, detail=reason)

        request.state.user_id = user_id
        request.state.token_id = token_id
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "mt5_bridge"}

    @app.post("/trade/open")
    async def open_trade(request: Request):
        """EA reports that it opened a trade."""
        data = await request.json()
        uid = request.state.user_id
        log.info("MT5 trade open from user %d: %s", uid, data.get('symbol'))

        # Record in trades table
        from storage import insert_trade
        canonical = canonical_from_broker(data.get('symbol', ''), uid)
        trade_id = insert_trade(
            pair=canonical,
            side=data.get('side', 'BUY'),
            qty=float(data.get('lots', 0)),
            price=float(data.get('price', 0)),
            reason=f"MT5_EA: {data.get('comment', '')}",
            entry_snapshot=json.dumps({
                'provider': 'mt5',
                'broker_symbol': data.get('symbol'),
                'ticket': data.get('ticket'),
                'sl': data.get('sl'),
                'tp': data.get('tp'),
            })
        )
        # Set user_id on the trade
        execute("UPDATE trades SET user_id=?, trade_type='mt5' WHERE id=?", (uid, trade_id))

        return {"status": "ok", "trade_id": trade_id}

    @app.post("/trade/close")
    async def close_trade_ep(request: Request):
        """EA reports that it closed a trade."""
        data = await request.json()
        uid = request.state.user_id
        ticket = data.get('ticket')
        log.info("MT5 trade close from user %d: ticket=%s", uid, ticket)

        # Find the trade by MT5 ticket in entry_snapshot
        from storage import fetchall as _fa
        rows = _fa("SELECT id, entry_snapshot FROM trades WHERE user_id=? AND status='OPEN' AND trade_type='mt5'", (uid,))
        trade_id = None
        for tid, snap_json in rows:
            if snap_json:
                try:
                    snap = json.loads(snap_json)
                    if str(snap.get('ticket')) == str(ticket):
                        trade_id = tid
                        break
                except Exception:
                    pass

        if trade_id:
            from trade_executor import close_trade
            pnl = close_trade(trade_id, float(data.get('close_price', 0)),
                              reason=f"MT5_EA_CLOSE: {data.get('comment', '')}")
            return {"status": "ok", "trade_id": trade_id, "pnl": pnl}
        return {"status": "not_found", "message": f"No matching trade for ticket {ticket}"}

    @app.post("/trade/update")
    async def update_trade(request: Request):
        """EA reports SL/TP modification."""
        data = await request.json()
        uid = request.state.user_id
        log.info("MT5 trade update from user %d: %s", uid, data)
        return {"status": "ok"}

    @app.get("/signals")
    async def get_signals(request: Request):
        """EA requests latest trading signals for its symbols."""
        uid = request.state.user_id
        conn = get_bridge_connection(uid)
        if not conn:
            return {"signals": []}

        # Get latest signals for user's pairs
        from storage import fetchall as _fa
        rows = _fa(
            "SELECT pair, direction, reason, ts FROM signals "
            "WHERE user_id=? ORDER BY ts DESC LIMIT 10", (uid,))
        signals = []
        for pair, direction, reason, ts in (rows or []):
            broker_sym = resolve_symbol(pair, uid)
            signals.append({
                'symbol': broker_sym,
                'canonical': pair,
                'direction': direction,
                'reason': reason,
                'timestamp': ts,
            })
        return {"signals": signals}

    @app.post("/heartbeat")
    async def heartbeat(request: Request):
        """EA sends periodic heartbeat."""
        uid = request.state.user_id
        return {"status": "ok", "server_time": int(time.time())}

    return app
