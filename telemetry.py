# telemetry.py
# Lightweight in-memory counters for operational visibility.
#
# Scope (per spec §4): "Track total users, active users, commands per minute.
# No heavy logging."
#
# Everything is in-memory — resets on Railway restart. Good enough for
# at-a-glance operator visibility. For historical metrics, use a proper
# observability stack (not in scope here).

import time
import logging

log = logging.getLogger(__name__)


# Ring buffer of command timestamps. Sized to a few minutes — we only
# compute 1-minute rate from it.
_cmd_timestamps: list = []
_CMD_RETENTION_SECONDS = 300  # 5 min window retained for flexibility


def record_command(uid: int = 0) -> None:
    """Increment the command counter. Called from the rate_limited wrapper
    so every accepted command is counted exactly once."""
    now = time.time()
    _cmd_timestamps.append(now)
    # Trim old entries to keep memory bounded
    cutoff = now - _CMD_RETENTION_SECONDS
    while _cmd_timestamps and _cmd_timestamps[0] < cutoff:
        _cmd_timestamps.pop(0)


def commands_per_minute() -> float:
    """Commands accepted in the last 60 seconds."""
    now = time.time()
    return sum(1 for t in _cmd_timestamps if now - t < 60)


def total_users() -> int:
    """Count of all rows in users table. Cheap — single COUNT query."""
    try:
        from storage import fetchone
        row = fetchone("SELECT COUNT(*) FROM users")
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as e:
        log.debug("telemetry.total_users failed: %s", e)
        return 0


def active_users(window_seconds: int = 86400) -> int:
    """Users who interacted in the last window OR have autotrade_enabled=1.
    Matches the _is_over_active_user_cap definition so the two stay in sync."""
    try:
        from storage import fetchone
        threshold = int(time.time()) - window_seconds
        row = fetchone(
            "SELECT COUNT(*) FROM users "
            "WHERE (last_seen_ts IS NOT NULL AND last_seen_ts >= ?) "
            "   OR autotrade_enabled = 1",
            (threshold,),
        )
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as e:
        log.debug("telemetry.active_users failed: %s", e)
        return 0


def render_summary() -> str:
    """Short plaintext block for /health_stats output."""
    cpm = commands_per_minute()
    total = total_users()
    active = active_users()
    return (
        f"Telemetry:\n"
        f"  Total users: {total}\n"
        f"  Active users (24h): {active}\n"
        f"  Commands / min: {cpm:.0f}"
    )
