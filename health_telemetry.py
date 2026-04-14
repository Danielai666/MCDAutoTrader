# health_telemetry.py
# Runtime health telemetry counters for monitoring bot behavior.
# Tracks: scheduler stalls, idempotency rejects, blocked trades by gate,
# exchange errors, rate limit hits, cycle durations.
# Persisted to bot_state for survive-restart. Reported via /health_stats.

import time
import json
import logging
import threading
from storage import upsert_bot_state, fetchone

log = logging.getLogger(__name__)

_lock = threading.Lock()

# In-memory counters (flushed to DB periodically)
_counters = {
    'scheduler_cycles': 0,
    'scheduler_stalls': 0,
    'scheduler_errors': 0,
    'idempotency_rejects': 0,
    'trades_opened': 0,
    'trades_closed': 0,
    'trades_failed': 0,
    'exchange_errors': 0,
    'rate_limit_hits': 0,
    'blocked_kill_switch': 0,
    'blocked_max_trades': 0,
    'blocked_exposure': 0,
    'blocked_daily_loss': 0,
    'blocked_daily_count': 0,
    'blocked_cooldown': 0,
    'blocked_consec_loss': 0,
    'blocked_duplicate': 0,
    'blocked_correlation': 0,
    'blocked_event_risk': 0,
    'blocked_drawdown': 0,
    'last_cycle_ts': 0,
    'last_cycle_duration_ms': 0,
    'uptime_start_ts': int(time.time()),
}

# Gate name → counter key mapping
GATE_COUNTER_MAP = {
    'Kill switch active': 'blocked_kill_switch',
    'Max open trades': 'blocked_max_trades',
    'Portfolio full': 'blocked_exposure',
    'Daily loss limit': 'blocked_daily_loss',
    'Max daily trades': 'blocked_daily_count',
    'Cooldown': 'blocked_cooldown',
    'consecutive losses': 'blocked_consec_loss',
    'Duplicate': 'blocked_duplicate',
    'correlation': 'blocked_correlation',
    'event risk': 'blocked_event_risk',
    'Drawdown halt': 'blocked_drawdown',
}


def increment(counter: str, amount: int = 1):
    """Increment a telemetry counter."""
    with _lock:
        if counter in _counters:
            _counters[counter] += amount
        else:
            _counters[counter] = amount


def record_blocked_trade(reason: str):
    """Increment the appropriate gate counter based on block reason."""
    for keyword, key in GATE_COUNTER_MAP.items():
        if keyword.lower() in reason.lower():
            increment(key)
            return
    # Generic block
    increment('blocked_other', 1)


def record_cycle(duration_ms: int):
    """Record a scheduler cycle completion."""
    with _lock:
        _counters['scheduler_cycles'] += 1
        _counters['last_cycle_ts'] = int(time.time())
        _counters['last_cycle_duration_ms'] = duration_ms


def record_stall():
    """Record a scheduler stall (cycle took too long or was skipped)."""
    increment('scheduler_stalls')


def get_counters() -> dict:
    """Get a snapshot of all counters."""
    with _lock:
        return dict(_counters)


def check_scheduler_health() -> tuple:
    """Check if scheduler is running normally.
    Returns (healthy: bool, message: str).
    """
    last_ts = _counters.get('last_cycle_ts', 0)
    if last_ts == 0:
        return True, 'No cycles yet (just started)'
    age = int(time.time()) - last_ts
    from config import SETTINGS
    max_age = SETTINGS.ANALYSIS_INTERVAL_SECONDS * 3
    if age > max_age:
        record_stall()
        return False, f'Scheduler stall: last cycle {age}s ago (max {max_age}s)'
    return True, f'Last cycle {age}s ago, duration {_counters.get("last_cycle_duration_ms", 0)}ms'


def flush_to_db():
    """Persist counters to bot_state for survive-restart."""
    try:
        data = json.dumps(get_counters())
        upsert_bot_state('health_telemetry', data, int(time.time()))
    except Exception as e:
        log.warning("Failed to flush telemetry: %s", e)


def load_from_db():
    """Restore counters from bot_state after restart."""
    try:
        row = fetchone("SELECT value FROM bot_state WHERE key='health_telemetry'")
        if row and row[0]:
            saved = json.loads(row[0])
            with _lock:
                for k, v in saved.items():
                    if k in _counters and k != 'uptime_start_ts':
                        _counters[k] = v
    except Exception:
        pass


def format_health_stats() -> str:
    """Format telemetry for Telegram display."""
    c = get_counters()
    uptime = int(time.time()) - c.get('uptime_start_ts', int(time.time()))
    uptime_h = uptime / 3600

    sched_ok, sched_msg = check_scheduler_health()

    lines = [
        "Health Telemetry",
        f"Uptime: {uptime_h:.1f}h",
        f"Scheduler: {'OK' if sched_ok else 'STALL'} ({sched_msg})",
        f"Cycles: {c.get('scheduler_cycles', 0)} | Errors: {c.get('scheduler_errors', 0)} | Stalls: {c.get('scheduler_stalls', 0)}",
        "",
        f"Trades: opened={c.get('trades_opened', 0)} closed={c.get('trades_closed', 0)} failed={c.get('trades_failed', 0)}",
        f"Idempotency rejects: {c.get('idempotency_rejects', 0)}",
        f"Exchange errors: {c.get('exchange_errors', 0)}",
        f"Rate limit hits: {c.get('rate_limit_hits', 0)}",
        "",
        "Blocked by gate:",
        f"  Kill switch: {c.get('blocked_kill_switch', 0)}",
        f"  Max trades: {c.get('blocked_max_trades', 0)}",
        f"  Exposure: {c.get('blocked_exposure', 0)}",
        f"  Daily loss: {c.get('blocked_daily_loss', 0)}",
        f"  Cooldown: {c.get('blocked_cooldown', 0)}",
        f"  Consec loss: {c.get('blocked_consec_loss', 0)}",
        f"  Duplicate: {c.get('blocked_duplicate', 0)}",
        f"  Correlation: {c.get('blocked_correlation', 0)}",
        f"  Event risk: {c.get('blocked_event_risk', 0)}",
        f"  Drawdown: {c.get('blocked_drawdown', 0)}",
    ]
    return "\n".join(lines)
