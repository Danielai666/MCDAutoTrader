# Paper Burn-In Test Plan (48-72h)

## Prerequisites
- Bot deployed (Railway or local)
- DB initialized (SQLite or PostgreSQL)
- At least one admin user registered (/start)
- PAPER_TRADING=true
- At least one pair in watchlist
- autotrade_enabled=1 for test user

## Pass/Fail Checklist

### Phase 1: Startup Health (hour 0)
- [ ] Bot starts without errors
- [ ] /health passes all checks
- [ ] /liveready returns READY or READY WITH WARNINGS
- [ ] /reconcile returns CLEAN
- [ ] /health_stats shows uptime and zero errors
- [ ] Scheduler cycles are running (check /health_stats after 15 min)

### Phase 2: Signal Generation (hours 0-6)
- [ ] /signal returns PNG card (not text fallback)
- [ ] /status returns Market Overview PNG with gauges
- [ ] At least 1 signal generated (check /health_stats scheduler_cycles > 0)
- [ ] No scheduler stalls (scheduler_stalls = 0)
- [ ] No exchange errors (exchange_errors = 0)

### Phase 3: Autonomous Paper Trading (hours 6-24)
- [ ] At least 1 paper trade opened autonomously
- [ ] Trade appears in /positions
- [ ] SL/TP guards set automatically
- [ ] Guard check running (auto_exit_task every 30s)
- [ ] No duplicate trades (idempotency_rejects should be 0 or very low)
- [ ] Blocked trades logged with correct gate reasons

### Phase 4: Trade Lifecycle (hours 24-48)
- [ ] At least 1 trade closed (by SL, TP, or signal)
- [ ] Trade close report sent to user
- [ ] PnL correctly calculated in /report
- [ ] Equity curve updating (/status drawdown tracking)
- [ ] Daily report sent at user's local 20:00
- [ ] /backtest runs and returns PNG card

### Phase 5: Stability (hours 48-72)
- [ ] Bot still running without restart
- [ ] No scheduler stalls over 72h
- [ ] /health_stats shows healthy counters
- [ ] /reconcile still CLEAN
- [ ] Memory usage stable (no leaks)
- [ ] No rate limit hits on exchange

### Phase 6: Edge Cases (manual checks)
- [ ] /panic_stop works (disables trading, closes positions)
- [ ] /killswitch toggles correctly
- [ ] Re-enabling autotrade after panic_stop works
- [ ] /reconcile fix resolves stale states
- [ ] Multiple pairs trading simultaneously (if multi-pair enabled)
- [ ] Event risk gate blocks when score >= 75 (/health_stats blocked_event_risk)

## Failure Criteria (any = FAIL)
- Scheduler stalls > 3 in 72h
- Exchange errors > 10 in 72h
- Any trade with status=PENDING after 5 min
- Duplicate trades executed
- Crash/restart without recovery
- Data isolation breach (if multi-user)
- PnL calculation error

## How to Monitor
```
/health_stats    — telemetry counters
/reconcile       — state consistency
/liveready       — readiness check
/status          — equity + trades
/positions       — open trades
/report          — performance
```
