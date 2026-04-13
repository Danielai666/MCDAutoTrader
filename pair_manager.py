# pair_manager.py
# Multi-pair watchlist management
import time
import logging
from config import SETTINGS
from storage import execute, fetchone, fetchall

log = logging.getLogger(__name__)


def get_active_pairs() -> list:
    """Return list of active pair strings. Respects FEATURE_MULTI_PAIR flag."""
    if not SETTINGS.FEATURE_MULTI_PAIR:
        return [SETTINGS.PAIR]
    rows = fetchall("SELECT pair FROM trading_pairs WHERE is_active=1 ORDER BY pair")
    pairs = [r[0] for r in rows] if rows else []
    return pairs if pairs else [SETTINGS.PAIR]


def add_pair(pair: str, notes: str = '') -> tuple:
    """Validate pair on exchange and add to watchlist. Returns (success, message)."""
    pair = pair.upper().strip()
    if '/' not in pair:
        return False, f'Invalid format: {pair} (expected BASE/QUOTE)'

    # Check limit
    rows = fetchall("SELECT COUNT(*) FROM trading_pairs WHERE is_active=1")
    count = int(rows[0][0]) if rows else 0
    if count >= SETTINGS.MAX_WATCHED_PAIRS:
        return False, f'Max {SETTINGS.MAX_WATCHED_PAIRS} pairs reached'

    # Check if already exists
    existing = fetchone("SELECT pair, is_active FROM trading_pairs WHERE pair=?", (pair,))
    if existing:
        if existing[1] == 1:
            return False, f'{pair} already in watchlist'
        # Reactivate
        execute("UPDATE trading_pairs SET is_active=1 WHERE pair=?", (pair,))
        return True, f'{pair} reactivated'

    # Validate on exchange
    ok, msg = validate_pair(pair)
    if not ok:
        return False, msg

    execute(
        "INSERT INTO trading_pairs(pair, is_active, added_ts, notes) VALUES(?,1,?,?)",
        (pair, int(time.time()), notes)
    )
    return True, f'{pair} added to watchlist'


def remove_pair(pair: str) -> bool:
    """Deactivate a pair from watchlist."""
    pair = pair.upper().strip()
    execute("UPDATE trading_pairs SET is_active=0 WHERE pair=?", (pair,))
    return True


def toggle_pair(pair: str, active: bool) -> bool:
    execute("UPDATE trading_pairs SET is_active=? WHERE pair=?", (1 if active else 0, pair.upper().strip()))
    return True


def update_pair_signal(pair: str, direction: str, score: float):
    """Update the last signal info for a pair."""
    now = int(time.time())
    existing = fetchone("SELECT pair FROM trading_pairs WHERE pair=?", (pair,))
    if existing:
        execute(
            "UPDATE trading_pairs SET last_signal_ts=?, last_direction=?, last_score=? WHERE pair=?",
            (now, direction, score, pair)
        )
    else:
        execute(
            "INSERT INTO trading_pairs(pair, is_active, added_ts, last_signal_ts, last_direction, last_score) VALUES(?,1,?,?,?,?)",
            (pair, now, now, direction, score)
        )


def get_pair_ranking() -> list:
    """Active pairs sorted by abs(last_score) descending."""
    rows = fetchall(
        "SELECT pair, last_direction, last_score, last_signal_ts FROM trading_pairs WHERE is_active=1 ORDER BY ABS(COALESCE(last_score,0)) DESC"
    )
    return [
        {'pair': r[0], 'direction': r[1], 'score': r[2], 'last_ts': r[3]}
        for r in rows
    ] if rows else []


def list_all_pairs() -> list:
    """All pairs with status."""
    rows = fetchall("SELECT pair, is_active, last_direction, last_score, added_ts FROM trading_pairs ORDER BY pair")
    return [
        {'pair': r[0], 'active': bool(r[1]), 'direction': r[2], 'score': r[3], 'added_ts': r[4]}
        for r in rows
    ] if rows else []


def validate_pair(pair: str) -> tuple:
    """Check pair exists on exchange."""
    try:
        from exchange import get_client
        ex = get_client()
        ex.load_markets()
        if pair in ex.markets:
            return True, f'{pair} valid'
        return False, f'{pair} not found on {SETTINGS.EXCHANGE}'
    except Exception as e:
        return False, f'Validation failed: {e}'


def get_best_tradable_pairs(max_pairs: int = None) -> list:
    """Active pairs filtered and ranked for autonomous trading."""
    from risk import is_duplicate_trade
    ranking = get_pair_ranking()
    max_p = max_pairs or SETTINGS.MAX_PAIRS_PER_CYCLE
    now = int(time.time())
    cutoff = 2 * SETTINGS.ANALYSIS_INTERVAL_SECONDS
    result = []
    for p in ranking:
        if len(result) >= max_p:
            break
        if not p['direction'] or p['direction'] == 'HOLD':
            continue
        if p['last_ts'] and (now - p['last_ts']) > cutoff:
            continue
        side = 'BUY' if p['direction'] == 'BUY' else 'SELL'
        if is_duplicate_trade(p['pair'], side):
            continue
        result.append(p)
    return result


def seed_default_pair():
    """Ensure the default SETTINGS.PAIR exists in trading_pairs table."""
    from storage import upsert_trading_pair
    upsert_trading_pair(SETTINGS.PAIR, 1, int(time.time()))
