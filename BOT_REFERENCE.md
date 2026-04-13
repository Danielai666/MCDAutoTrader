# MCDAutoTrader — Complete Technical Reference

> Last updated: 2026-04-13
> Version: Post-production-hardening (PostgreSQL, reconciliation, execution integrity)
> Commit: 5caef43

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture & Data Flow](#2-architecture--data-flow)
3. [Configuration — config.py](#3-configuration--configpy)
4. [Database Layer — storage.py](#4-database-layer--storagepy)
5. [Exchange Integration — exchange.py](#5-exchange-integration--exchangepy)
6. [Technical Indicators — indicators.py](#6-technical-indicators--indicatorspy)
7. [Divergence Detection — divergence.py](#7-divergence-detection--divergencepy)
8. [Candle Pattern Recognition — candles.py](#8-candle-pattern-recognition--candlespy)
9. [Market Regime Detection — market_regime.py](#9-market-regime-detection--market_regimepy)
10. [Divergence Radar Engine — div_radar.py](#10-divergence-radar-engine--div_radarpy)
11. [Strategy & Scoring — strategy.py](#11-strategy--scoring--strategypy)
12. [AI Fusion Engine — ai_fusion.py](#12-ai-fusion-engine--ai_fusionpy)
13. [AI Decider Wrapper — ai_decider.py](#13-ai-decider-wrapper--ai_deciderpy)
14. [Risk Management — risk.py](#14-risk-management--riskpy)
15. [Trade Executor — trade_executor.py](#15-trade-executor--trade_executorpy)
16. [Pair Manager — pair_manager.py](#16-pair-manager--pair_managerpy)
17. [Scheduler & Main Loop — scheduler.py](#17-scheduler--main-loop--schedulerpy)
18. [Telegram Bot — telegram_bot.py](#18-telegram-bot--telegram_botpy)
19. [Notifications — notifier.py](#19-notifications--notifierpy)
20. [Reports & Analytics — reports.py](#20-reports--analytics--reportspy)
21. [Exchange Reconciliation — reconcile.py](#21-exchange-reconciliation--reconcilepy)
22. [Startup Validation — validators.py](#22-startup-validation--validatorspy)
23. [Entry Point — main.py](#23-entry-point--mainpy)
24. [Deployment & Scripts](#24-deployment--scripts)
25. [Database Schema Reference](#25-database-schema-reference)
26. [Environment Variables — Full Reference](#26-environment-variables--full-reference)
27. [Production Hardening Summary](#27-production-hardening-summary)
28. [Operational Runbook](#28-operational-runbook)

---

## 1. System Overview

MCDAutoTrader is a production-hardened autonomous cryptocurrency trading bot that combines:

- **MACD/RSI divergence detection** (regular + hidden + pre-confirmation radar)
- **Multi-indicator scoring** (11 weighted signal components)
- **Dual-AI fusion** (Claude + OpenAI + local heuristic with 4 consensus policies)
- **10-gate risk management** (including correlation checks and drawdown halting)
- **ATR-based dynamic trailing stops** (tightening as profit grows)
- **Equity curve tracking** with automatic position size reduction during drawdowns
- **Multi-pair autonomous trading** with ranked entry execution
- **Two-phase trade execution** (PENDING→OPEN with crash recovery)
- **Exchange reconciliation** (DB vs exchange state cross-check)
- **Live-readiness assessment** (10-point production readiness check)
- **Telegram command & control** interface with inline keyboards

The bot runs on **Kraken** exchange via CCXT, supports **paper** and **live** trading modes, and stores data in **SQLite** (local dev) or **PostgreSQL/Supabase** (production).

### File Count and Lines

| Category | Files | Approx LOC |
|----------|-------|------------|
| Signal pipeline | indicators.py, divergence.py, candles.py, market_regime.py, div_radar.py, strategy.py | ~1,050 |
| AI engine | ai_fusion.py, ai_decider.py | ~450 |
| Risk & execution | risk.py, trade_executor.py | ~800 |
| Infrastructure | storage.py, exchange.py, config.py, scheduler.py | ~1,000 |
| Interface | telegram_bot.py, notifier.py, reports.py | ~1,400 |
| Production ops | reconcile.py, validators.py, pair_manager.py | ~700 |
| **Total** | **22 modules** | **~5,400** |

---

## 2. Architecture & Data Flow

### File Dependency Graph

```
main.py
├── config.py (Settings dataclass — SETTINGS singleton)
├── storage.py (DB abstraction — SQLite / PostgreSQL)
├── validators.py (startup checks)
├── telegram_bot.py
│   ├── trade_executor.py
│   │   └── storage.py (insert_trade, append_trade_note, upsert helpers)
│   ├── reconcile.py (exchange reconciliation + live-readiness)
│   ├── scheduler.py
│   │   ├── exchange.py (CCXT wrapper)
│   │   ├── strategy.py
│   │   │   ├── indicators.py (EMA, RSI, MACD, ATR, ADX, BB, Stochastic)
│   │   │   ├── divergence.py (regular + hidden)
│   │   │   ├── candles.py (hammer, engulfing, breakout, etc.)
│   │   │   ├── market_regime.py (trending/ranging/volatile)
│   │   │   └── div_radar.py (pre-confirmation divergence zones)
│   │   ├── ai_decider.py → ai_fusion.py (Claude + OpenAI + local)
│   │   ├── risk.py (10-gate + sizing + trailing + correlation + drawdown)
│   │   ├── pair_manager.py (multi-pair watchlist)
│   │   ├── notifier.py (Telegram alerts)
│   │   └── reports.py (performance analytics)
│   └── pair_manager.py
└── scheduler.py
```

### Data Flow (End-to-End)

```
Exchange (Kraken via CCXT)
   │ fetch_ohlcv(pair, timeframe, limit)
   ▼
DataFrame [ts, open, high, low, close, volume]
   │
   ���
┌─────────────────────────────────────┐
│         INDICATOR LAYER             │
│  EMA, RSI, MACD, Stochastic,       │
│  ATR, ADX, Bollinger Bands, VolMA  │
└──────────────┬──────────────────────┘
               ���
   ┌───────────┼───────────┬──────────────┐
   │           ▼           ▼              ▼
Divergence  Candle     Market         Div Radar
(reg+hid)   Patterns   Regime         (pre-confirm)
   │           │           │              │
   └───────────┴───────────┴──────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│     STRATEGY LAYER (strategy.py)    │
│  tf_signal() → per-TF scoring      │
│  merge_mtf() → weighted consensus  │
│  Score threshold: 1.5 minimum       │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│    AI FUSION LAYER (ai_fusion.py)   │
│  Local heuristic (always)           │
│  + Claude API (optional)            │
│  + OpenAI API (optional)            │
│  Policy: local/advisory/majority/   │
│          strict_consensus           │
��  Output: ENTER/EXIT/HOLD + conf    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│     RISK GATE (10 checks)           │
│  1. Kill switch                     │
│  2. Open trade limit                │
│  3. Portfolio exposure              │
│  4. Daily loss limit                │
│  5. Daily trade count               │
│  6. Cooldown timer                  │
│  7. Consecutive loss pause          │
│  8. Duplicate trade check           │
│  9. Correlation risk                │
│ 10. Drawdown halt                   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│    POSITION SIZING (risk.py)        │
���  Base: capital x risk / ATR         │
│  x confidence x quality x DD_scale │
│  Capped by portfolio limits         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  TRADE EXECUTION (trade_executor)   │
│  Phase 1: DB insert (PENDING)       │
│  Phase 2: Exchange order            │
│  Phase 3: DB update (OPEN/FAILED)   │
│  Phase 4: Set SL/TP guards          │
│  Dedup lock: 10s per pair:side      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  GUARD MONITORING (every 30s)       │
│  Layer 1: Manual SL/TP/Trail%       │
│  Layer 2: ATR trailing stop         │
│  → Auto-exit if triggered           │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  REPORTING & NOTIFICATIONS          │
│  Telegram alerts, daily reports,    │
│  equity tracking, performance stats │
└─────────────────────────────────────┘
```

---

## 3. Configuration — config.py

**156 lines.** Single `Settings` dataclass loaded from `.env` via `python-dotenv`.

### Helper functions

| Function | Purpose |
|----------|---------|
| `_ids(v: str) -> tuple` | Parse comma-separated integers |
| `_pairs(v: str) -> tuple` | Parse comma-separated pair strings |
| `_bool(key: str, default: str) -> bool` | Read env var as boolean |

### `Settings` dataclass (line 18)

155+ fields organized into sections. See [Section 26](#26-environment-variables--full-reference) for full list.

### `SETTINGS = Settings()` (line 155)

Module-level singleton used by every other module.

---

## 4. Database Layer — storage.py

**470 lines.** Dual-backend support with production-grade PostgreSQL handling.

### Connection Management

| Function | Backend | Behavior |
|----------|---------|----------|
| `_get_sqlite_conn()` | SQLite | Shared singleton connection, WAL mode, 5s busy timeout |
| `_get_pg_conn()` | PostgreSQL | Per-call connection with 10s connect timeout, autocommit=False |

**Thread safety:** SQLite uses `threading.Lock` (`_sqlite_lock`) for all operations. PostgreSQL uses per-call connections (inherently safe).

### Placeholder Conversion

`_q(query: str) -> str` — Converts `?` to `%s` for PostgreSQL. Handles edge cases (does not convert `??`).

### Schema

**SQLite schema** (line 67): `CREATE TABLE IF NOT EXISTS` with `AUTOINCREMENT`, `INTEGER`, `REAL`, `TEXT`.

**PostgreSQL schema** (line 117): `CREATE TABLE IF NOT EXISTS` with `BIGSERIAL`, `BIGINT`, `DOUBLE PRECISION`, `TEXT`. Creates schema namespace via `CREATE SCHEMA IF NOT EXISTS {schema}`.

### Initialization

| Function | Purpose |
|----------|---------|
| `init_db()` | Dispatches to SQLite or PostgreSQL init |
| `_init_sqlite()` | Runs schema DDL + column migrations |
| `_migrate_sqlite_trades(conn)` | Adds lifecycle, entry_snapshot, exit_snapshot, trade_type, order_id columns |
| `_init_postgres()` | Creates schema and all tables (idempotent) |

### Query Helpers

| Function | Purpose |
|----------|---------|
| `fetchone(q, p=())` | Execute query, return first row |
| `fetchall(q, p=())` | Execute query, return all rows |
| `execute(q, p=())` | Execute write query, return lastrowid or RETURNING value |

**PostgreSQL error handling:** Explicit `conn.rollback()` on exception, error logging with query substring.

### Backend-Aware Upsert Helpers

These replace all raw `ON CONFLICT` SQL throughout the codebase:

| Function | Purpose |
|----------|---------|
| `upsert_bot_state(key, value, ts)` | PG: `ON CONFLICT DO UPDATE`. SQLite: `INSERT OR REPLACE` |
| `upsert_manual_guard(uid, pair, sl, tp, trail_pct, trail_stop, high_wm)` | PG: `ON CONFLICT DO UPDATE`. SQLite: `INSERT OR REPLACE` |
| `upsert_user(uid, username, ts)` | PG: `ON CONFLICT DO NOTHING`. SQLite: `INSERT OR IGNORE` |
| `upsert_trading_pair(pair, is_active, added_ts, notes)` | PG: `ON CONFLICT DO UPDATE`. SQLite: check-then-insert |
| `insert_trade(pair, side, qty, price, reason, entry_snapshot) -> int` | PG: `RETURNING id`. SQLite: `lastrowid` |
| `append_trade_note(trade_id, note_text)` | Safe `CASE WHEN` pattern (no `\|\|` coercion issues) |

### Health Check

`check_db_health() -> tuple(ok, message, details)` — Queries users, open trades, active pairs, state keys.

---

## 5. Exchange Integration — exchange.py

**40 lines.** Minimalist CCXT wrapper.

| Function | Returns | Notes |
|----------|---------|-------|
| `get_client()` | ccxt.Exchange | Creates instance with rate limiting |
| `fetch_ohlcv(pair, timeframe, limit)` | DataFrame | Columns: ts, open, high, low, close, volume |
| `market_price(pair)` | float | Current last price via fetch_ticker |
| `place_market_order(pair, side, amount)` | dict | Paper: mock order. Live: real CCXT order |
| `health_check()` | tuple(bool, str) | Calls fetch_time() |
| `validate_pair_on_exchange(pair)` | bool | Loads markets, checks pair exists |
| `cancel_order(order_id, pair)` | dict | Paper: mock cancel. Live: real cancel |
| `get_balance(currency='USDC')` | float | Paper: returns CAPITAL_USD. Live: fetch_balance |

---

## 6. Technical Indicators — indicators.py

**30 lines.** Pure vectorized Pandas/NumPy. No TA-lib dependency.

| Function | Signature | Output |
|----------|-----------|--------|
| `ema` | `(s, p)` | Exponential Moving Average |
| `rsi` | `(s, period=14)` | Relative Strength Index (fills NaN with 50) |
| `macd` | `(s, fast=12, slow=26, signal=9)` | (line, signal, histogram) |
| `stochastic` | `(h, l, c, kp=14, dp=3)` | (%K, %D) |
| `vol_ma` | `(v, period=20)` | Volume simple moving average |
| `ema_pair` | `(c, p1=9, p2=21)` | (EMA1, EMA2) |
| `atr` | `(high, low, close, period=14)` | Average True Range (EMA smoothed) |
| `adx` | `(high, low, close, period=14)` | (ADX line, +DI, -DI) |
| `bollinger` | `(close, period=20, std=2.0)` | (upper, middle, lower) |

---

## 7. Divergence Detection — divergence.py

**75 lines.**

| Function | Returns | Description |
|----------|---------|-------------|
| `_pivots(s, lookback)` | (highs[-2:], lows[-2:]) | Find last 2 pivot highs/lows |
| `_strength(p1, p2, o1, o2)` | float (0.1–1.0) | price_delta + osc_delta, capped |
| `detect_divergence(price, osc)` | (type, strength) | Regular bearish/bullish or "none" |
| `detect_hidden_divergence(price, osc)` | (type, strength) | Hidden bearish/bullish (trend continuation) |
| `detect_all_divergences(price, osc)` | dict | Both regular and hidden combined |

**Regular divergence:**
- Bearish: price higher-high + osc lower-high (reversal down)
- Bullish: price lower-low + osc higher-low (reversal up)

**Hidden divergence:**
- Hidden bearish: price lower-high + osc higher-high (continuation down)
- Hidden bullish: price higher-low + osc lower-low (continuation up)

Requires minimum 50 bars.

---

## 8. Candle Pattern Recognition — candles.py

**205 lines.**

### `CandlePattern` class (line 7)
Fields: `name`, `direction` ('bullish'/'bearish'), `strength` (0.0–1.0), `bar_index`.

### Pattern Detectors

| Function | Pattern | Direction | Strength basis |
|----------|---------|-----------|----------------|
| `_check_hammer` | Small body top, long lower wick | Bullish | lower_wick / range |
| `_check_shooting_star` | Small body bottom, long upper wick | Bearish | upper_wick / range |
| `_check_bullish_engulfing` | Green candle engulfs previous red | Bullish | curr_body / prev_body x 0.5 |
| `_check_bearish_engulfing` | Red candle engulfs previous green | Bearish | curr_body / prev_body x 0.5 |
| `_check_rejection_wick` | Long wick opposite direction | Either | wick / range |
| `_check_breakout` | Close above HH or below LL | Either | 0.5 x volume_factor |

Config: `CANDLE_WICK_RATIO=2.0`, `CANDLE_BODY_RATIO=0.3`.

### `detect_patterns(df, lookback=3) -> list[CandlePattern]`
Scans last `lookback` bars. Returns sorted by strength descending.

### `summarize_patterns(patterns) -> dict`
Returns: bullish_count, bearish_count, bull_score, bear_score, net_score, strongest, patterns (top 5).

---

## 9. Market Regime Detection — market_regime.py

**82 lines.**

### `RegimeResult` class (line 8)
Fields: `regime`, `confidence` (0��1), `details` (dict with ema/adx/atr metrics).

### `detect_regime(df) -> RegimeResult` (line 22)

| Regime | Conditions | Confidence formula |
|--------|-----------|-------------------|
| `trending_up` | ADX >= 25 AND EMA_fast > EMA_slow | 0.5 + ADX/100 + EMA_gap%/10 |
| `trending_down` | ADX >= 25 AND EMA_fast < EMA_slow | same |
| `volatile` | ADX < 25 AND ATR percentile > 75% | 0.4 + ATR_pct/2 |
| `ranging` | ADX < 25 AND not high volatility | 0.5 + (1 - ADX/25) x 0.3 |

---

## 10. Divergence Radar Engine — div_radar.py

**404 lines.** Detects divergence **before full confirmation**.

### `DivZone` dataclass (line 20)
Fields: symbol, timeframe, direction, stage, probability (0–1), strength (0–1), confidence (0–1), trigger_price, invalidation, reasons, oscillator.
Property: `score = probability x strength x confidence`.

### Maturity Stages

| Stage | Probability | Meaning |
|-------|------------|---------|
| `potential_zone` | 0.10–0.30 | Early signals |
| `developing` | 0.30–0.50 | Multiple signals aligning |
| `near_confirmed` | 0.50–0.70 | Strong setup |
| `confirmed` | 0.70–1.00 | Full divergence confirmed |

### Bearish Scan Signals (`_scan_bearish`)

| Signal | Prob | Condition |
|--------|------|-----------|
| Price near high but osc weaker | +0.30 | Within 0.5% of prev high, osc 5%+ weaker |
| MACD histogram fading (3-bar) | +0.20 | 3 declining bars, still positive |
| MACD histogram declining (2-bar) | +0.10 | 2 declining bars |
| Weak volume on push higher | +0.15 | Volume < 80% of 20-bar average |
| RSI overbought declining | +0.15 | RSI > 65 and declining |
| Confirmed HH price + LH osc | +0.30 | Classic divergence pattern |

### Bullish Scan Signals (`_scan_bullish`)
Mirror of bearish: price near low + osc stronger, histogram recovering, declining volume, RSI oversold improving, confirmed LL/HL.

### Main Functions

| Function | Purpose |
|----------|---------|
| `scan_divergence_zones(df, symbol, timeframe)` | Scan single DF for all zones (RSI + MACD, both directions) |
| `_merge_zones(zones)` | Deduplicate same-direction zones, boost probability |
| `full_radar_scan(pairs, timeframes, fetch_fn)` | Multi-pair, multi-TF scan |
| `format_radar_report(zones, max_zones=10)` | Telegram report |
| `format_radar_brief(zones, tf_filter=None)` | Short TF-filtered format |

---

## 11. Strategy & Scoring — strategy.py

**258 lines.**

### `tf_signal(df, symbol, timeframe) -> dict` (line 8)

**Step 1:** Compute all indicators.
**Step 2:** Detect divergences + candles + regime + radar.
**Step 3:** ADX filter — if `ADX < ADX_TREND_MIN(20)` → return HOLD.
**Step 4:** Weighted scoring (11 components):

| # | Component | Weight | Condition |
|---|-----------|--------|-----------|
| 1 | Regular MACD divergence | 1.5 x strength | Bullish or bearish |
| 2 | Regular RSI divergence | 1.5 x strength | Bullish or bearish |
| 3 | Hidden MACD divergence | 1.0 x strength | Feature flag ON |
| 4 | Hidden RSI divergence | 1.0 x strength | Feature flag ON |
| 5 | EMA trend (EMA9 vs EMA21) | 1.0 fixed | Always |
| 6 | Stochastic crossover | 0.75 | K > D and K < 80 (bull) |
| 7 | Volume confirmation | 0.5 | Vol > 20-bar MA |
| 8 | Bollinger position | 0.5 | Below 0.2 or above 0.8 |
| 9 | MACD histogram momentum | 0.5 | Rising+positive or falling+negative |
| 10 | Candle patterns | min(0.75, net x 0.5) | Feature flag ON |
| 11 | Divergence radar zones | probability x 2.0 | Up to 2.0 for confirmed |

**Direction:** BUY if `buy_score >= 1.5 and > sell_score`. SELL if `sell_score >= 1.5 and > buy_score`. Else HOLD.

**Returns:** `{direction, score, reasons, snapshot, components}`

### `merge_mtf(signals) -> dict` (line 206)

Weights: `{'30m': 1.0, '1h': 1.5, '4h': 2.0}`. Daily used for regime only.
Regime filter: BUY blocked if regime=SELL, SELL blocked if regime=BUY.
**Returns:** `{merged_direction, merged_score, regime, regime_detail?}`

### `build_score_breakdown(signals, merged) -> dict` (line 238)
Structured breakdown for AI input and Telegram display.

---

## 12. AI Fusion Engine — ai_fusion.py

**420 lines.**

### Data Classes

**`AIDecision`** (line 18): action, side, confidence, setup_quality, reasons, warnings, risk_flags, source, raw_response, latency_ms.

**`FusionResult`** (line 41): final_action, final_side, final_confidence, policy_used, decisions, consensus_notes, was_overridden.

### AI Providers

| Provider | Function | Model | Notes |
|----------|----------|-------|-------|
| Local | `_local_heuristic(features)` | Rule-based | Always available, sync |
| Claude | `_call_claude(features)` | CLAUDE_MODEL | Async via executor, optional |
| OpenAI | `_call_openai(features)` | OPENAI_MODEL | Async via executor, optional |

### Local Heuristic Algorithm

Base confidence: `0.50 + |merged_score| x 0.15`

| Modulation | Adjustment | Condition |
|-----------|-----------|-----------|
| Strong trend | +0.10 | avg_adx >= ADX_STRONG_TREND(40) |
| Weak trend | -0.10 | avg_adx < ADX_TREND_MIN(20) |
| BB favorable | +0.05 | BUY near lower / SELL near upper |
| BB unfavorable | -0.08 | BUY near upper / SELL near lower |
| RSI extreme | -0.10 | BUY + RSI > 75 / SELL + RSI < 25 |

Decision: ENTER if direction matches, score > SIGNAL_SCORE_MIN, confidence >= AI_CONFIDENCE_MIN.

### Fusion Policies

| Policy | Behavior |
|--------|----------|
| `local_only` | Local heuristic only |
| `advisory` | Local decides; remotes logged for reference |
| `majority` | 2/3 or 3/3 agreement wins; ties → HOLD |
| `strict_consensus` | All must agree or → HOLD |

### `decide(features) -> FusionResult` (line 382)
Main async entry. Runs local always, fires Claude + OpenAI concurrently if enabled, fuses, logs to `ai_decisions` table.

---

## 13. AI Decider Wrapper — ai_decider.py

**28 lines.** Backward-compatibility layer.

| Function | Mode | Returns |
|----------|------|---------|
| `decide_async(features)` | Async | `{decision, confidence, notes, side, fusion}` |
| `decide(features)` | Sync | `{decision, confidence, notes, side}` (local only) |

---

## 14. Risk Management — risk.py

**462 lines.**

### Query Functions

| Function | Returns |
|----------|---------|
| `realized_pnl_today()` | float — sum of closed PnL last 24h |
| `open_trade_count()` | int — count of OPEN trades |
| `trade_count_today()` | int — trades opened last 24h |
| `last_trade_ts(pair=None)` | int — unix timestamp of most recent trade |
| `consecutive_losses(pair=None)` | int — streak from most recent, up to 20 |

### Entry Gate — `can_enter_enhanced(pair, side, signal_snapshot=None)`

Returns `(allowed: bool, reason: str)`. Blocked trades logged to `blocked_trades` table.

| Gate | Check | Block condition |
|------|-------|----------------|
| 1 | Kill switch | `SETTINGS.KILL_SWITCH == True` |
| 2 | Open trades | `open_trade_count() >= MAX_OPEN_TRADES` |
| 2.5 | Portfolio exposure | Exposure >= `CAPITAL_USD x MAX_PORTFOLIO_EXPOSURE` |
| 3 | Daily loss | `realized_pnl_today() <= -DAILY_LOSS_LIMIT_USD` |
| 4 | Daily trade count | `trade_count_today() >= MAX_DAILY_TRADES` |
| 5 | Cooldown | Elapsed < `COOLDOWN_AFTER_TRADE_SECONDS` |
| 6 | Consecutive losses | >= `CONSECUTIVE_LOSS_COOLDOWN` losses in window |
| 7 | Duplicate trade | Same pair + side already OPEN |
| 8 | Correlation risk | >= `MAX_CORRELATED_EXPOSURE` positions with corr >= `CORRELATION_THRESHOLD` |
| 9 | Drawdown halt | `drawdown_position_scale() == 0.0` |
| 10 | Dry run | Allowed but flagged |

### Position Sizing

| Function | Formula |
|----------|---------|
| `position_size(price, atr)` | `(RISK_PER_TRADE x CAPITAL_USD) / (ATR x ATR_SL_MULTIPLIER)` |
| `confidence_scaled_position_size(...)` | base x confidence_factor x quality_bonus x drawdown_scale, capped |
| `atr_stop_loss(entry, atr, side)` | `entry +/- (ATR x ATR_SL_MULTIPLIER)` |
| `atr_take_profit(entry, atr, side)` | `entry +/- (ATR x TP_ATR_MULTIPLIER)` |
| `should_move_to_break_even(...)` | True if profit >= `BREAK_EVEN_ATR_MULTIPLIER x ATR` |
| `portfolio_exposure_check()` | `(can_trade, current_usd, remaining_usd)` |
| `should_skip_weak_setup(quality, flags, conf)` | Rejects below MIN_SETUP_QUALITY or MAX_RISK_FLAGS |

### ATR Trailing Stops

`compute_atr_trailing_stop(entry, current, atr, side, current_trail) -> dict`

| Phase | Condition | Trail distance |
|-------|-----------|---------------|
| Inactive | profit < `TRAILING_ACTIVATION_ATR(1.0)` ATR | No trail |
| Active (wide) | profit >= activation | `TRAILING_ATR_MULTIPLIER(2.5)` x ATR |
| Active (tight) | profit >= `TRAILING_TIGHTEN_AFTER_ATR(2.0)` | `TRAILING_TIGHTEN_MULTIPLIER(1.5)` x ATR |

Trail ratchets only in favorable direction. Returns: `{active, trail_stop, distance_atr, profit_atr, tightened}`.

`is_atr_trail_triggered(current_price, trail_stop, side) -> bool` — True if price breached trail.

### Correlation Risk

| Function | Purpose |
|----------|---------|
| `get_correlation(pair_a, pair_b)` | Pearson correlation of returns over `CORRELATION_LOOKBACK_BARS` on `CORRELATION_TIMEFRAME` |
| `check_correlation_risk(pair, side)` | Blocks if too many correlated positions. Returns `(ok, reason, correlated_pairs)` |

### Equity & Drawdown

| Function | Purpose |
|----------|---------|
| `get_equity_status()` | Returns `{equity, peak_equity, drawdown_usd, drawdown_pct, max_drawdown_pct, realized_pnl, unrealized_pnl}` |
| `drawdown_position_scale()` | Returns 0.0–1.0 scale factor. 0.0 at DRAWDOWN_HALT_THRESHOLD (25%), linear reduction from DRAWDOWN_SCALE_THRESHOLD (10%) |

---

## 15. Trade Executor — trade_executor.py

**336 lines.** Production-hardened with two-phase execution and crash recovery.

### Trading Primitives

| Function | Returns | Notes |
|----------|---------|-------|
| `open_trade(pair, side, qty, price, reason, mode, entry_snapshot)` | trade_id | Uses `insert_trade()` from storage |
| `close_trade(trade_id, exit_price, reason, exit_snapshot)` | PnL (float) | Calculates PnL, uses `append_trade_note()` |
| `close_all_for_pair(pair, reason)` | count closed | Handles both pair formats |
| `update_trade_lifecycle(trade_id, lifecycle)` | None | States: pending, open, protected, trailing, closed, blocked |
| `get_open_trades_for_pair(pair)` | list[dict] | id, side, qty, entry, ts_open |

### Execution Dedup

`_check_execution_lock(pair, side) -> bool` — 10-second per pair:side dedup window. Prevents duplicate simultaneous trades from scheduler races.

### `execute_autonomous_trade(...)` — Hardened Sequence

```
1. Dedup check (10s lock)
2. Create DB record → status=PENDING, lifecycle=pending
3. Place exchange order
4. On success → status=OPEN, lifecycle=open, store order_id
5. On failure → status=FAILED, lifecycle=blocked, store error
6. Set SL/TP guards
```

Every path ends in a clear, recoverable state. Returns `{success, trade_id, order_id, mode, error}`.

### `execute_autonomous_exit(pair, reason)`

Closes all open trades for pair. For live mode, places opposite orders. Cleans up guards and ATR trail state from bot_state. Returns `{success, closed_count, total_pnl, mode, errors}`.

### Manual Guard Utilities

| Function | Purpose |
|----------|---------|
| `set_manual_guard(uid, pair, sl, tp, trail_pct)` | UPSERT with partial field updates. Uses `upsert_manual_guard()` |
| `clear_manual_guard(uid, pair, which)` | Clear sl/tp/trail/all |

### Trade State Recovery

| Function | Purpose |
|----------|---------|
| `recover_pending_trades()` | On startup, marks all PENDING trades as FAILED. Returns count recovered. |
| `get_trade_state_summary()` | Count by status: OPEN, PENDING, CLOSED, FAILED |

---

## 16. Pair Manager — pair_manager.py

**140 lines.** Multi-pair watchlist management.

| Function | Purpose |
|----------|---------|
| `get_active_pairs()` | Active pair strings. Falls back to SETTINGS.PAIR if multi-pair disabled |
| `add_pair(pair, notes)` | Validate format → check limit → validate on exchange → insert |
| `remove_pair(pair)` | Soft-delete (is_active=0) |
| `toggle_pair(pair, active)` | Toggle active state |
| `update_pair_signal(pair, direction, score)` | Update last signal info (check-then-update/insert) |
| `get_pair_ranking()` | Sorted by abs(last_score) descending |
| `list_all_pairs()` | All pairs with status |
| `validate_pair(pair)` | Check on exchange via CCXT |
| `get_best_tradable_pairs(max_pairs)` | Filtered + ranked for autonomous trading |
| `seed_default_pair()` | Ensure SETTINGS.PAIR exists in DB (uses `upsert_trading_pair()`) |

---

## 17. Scheduler & Main Loop — scheduler.py

**358 lines.** APScheduler-based job orchestration.

### Job Locking
`_with_lock(name, coro)` — Prevents concurrent execution of same job via in-memory set.

### Scheduler Dedup
`_jobs_scheduled = False` — Global guard prevents duplicate registration. On init, removes any stale jobs by name before registering new ones.

### Core Functions

| Function | Purpose |
|----------|---------|
| `_compute_signals(pair)` | Fetch OHLCV → tf_signal → merge_mtf → build_score_breakdown |
| `_analyze_pair(app, pair)` | Full analysis for one pair: signals → AI decision → format → update watchlist |
| `_execute_autonomous_cycle(app, pair_results)` | Process EXITs first → rank ENTERs → execute top candidates |
| `run_cycle_once(app, notify, pair)` | Single pair: analyze only. Multi-pair: analyze all + optional autonomous execution |

### Autonomous Cycle Flow

1. **Process EXITs** (free capital/slots)
2. **Rank ENTER candidates** by `confidence x |merged_score|`
3. For each (up to MAX_PAIRS_PER_CYCLE):
   - Setup quality filter
   - Risk gate (can_enter_enhanced)
   - Portfolio exposure check
   - Fetch live price + ATR
   - Confidence-scaled position size (includes drawdown scale)
   - Calculate SL/TP
   - Build entry snapshot (includes `atr_at_entry` for trailing stops)
   - `execute_autonomous_trade()`

### Scheduled Jobs

| Job | Interval | First run | Lock |
|-----|----------|-----------|------|
| analysis_cycle | `ANALYSIS_INTERVAL_SECONDS` (600s) | 10s | Yes |
| health_check | `HEALTH_CHECK_INTERVAL_SECONDS` (3600s) | 60s | Yes |
| daily_report | 86400s | 3600s | No |

---

## 18. Telegram Bot �� telegram_bot.py

**~1200 lines.** Full interactive Telegram interface.

### Keyboard Layouts

| Keyboard | Buttons |
|----------|---------|
| `main_menu_keyboard()` | Signal, Price, Status, Settings, Guards, Check Guards, AutoTrade, Mode, Risk, Sell Now, Reports, Pairs, Admin |
| `admin_keyboard()` | Health, AI Status, Kill Switch, Reconcile, Live Ready?, Back |
| `guards_set_keyboard()` | Set SL, Set TP, Set Trail %, Cancel submenu, Back |
| `reporting_keyboard()` | Positions, PnL, Trades, Blocked, Full Report |
| `pairs_keyboard()` | List, Ranking, Add, Remove |

### Auto-Exit Task (runs every 30s)

**Layer 1: Manual guards** — Fixed SL/TP and percentage-based trailing.
**Layer 2: ATR trailing stops** — `_check_atr_trailing_stops(pair, price)` reads `atr_at_entry` from entry_snapshot, loads/updates trail state from bot_state, triggers exit if breached.

### Startup Sequence (`post_init`)

1. `init_db()` (idempotent)
2. `seed_default_pair()` (idempotent)
3. Recover persisted config from bot_state (capital_usd, max_portfolio_exposure)
4. `recover_pending_trades()` — mark crash-orphaned PENDING as FAILED
5. Record startup time and trade state
6. Notify admins with startup summary

### All Telegram Commands

| Command | Function | Description |
|---------|----------|-------------|
| `/start` | `start()` | Register user, show main menu |
| `/menu` | `menu_cmd()` | Show main menu |
| `/help` | `help_cmd()` | Show command list |
| `/status` | `_do_status()` | Equity, drawdown, exposure, trades, AI policy, trailing/correlation status |
| `/settings` | `_do_settings()` | Current config |
| `/signal` | `_do_signal()` | Run full analysis cycle |
| `/price` | `_do_price()` | Current market price |
| `/guards` | `_do_guards()` | Display SL/TP/trail settings |
| `/checkguards` | `checkguards()` | Run analysis + guard check |
| `/autotrade on\|off` | `autotrade()` | Toggle autonomous trading (admin) |
| `/mode paper\|live` | `mode()` | Switch trading mode (admin) |
| `/risk daily <usd>` | `risk()` | Set daily loss limit |
| `/sl <price>` | text handler | Set stop-loss |
| `/tp <price>` | text handler | Set take-profit |
| `/trail <pct>` | text handler | Set trailing stop percentage |
| `/cancel sl\|tp\|trail\|all` | `cancel_guard()` | Clear guard(s) |
| `/sellnow` | callback | Emergency close all trades (admin) |
| `/positions` | reports | Open positions with unrealized PnL |
| `/trades` | reports | Recent 10 closed trades |
| `/pnl` | reports | 30-day performance report |
| `/report` | reports | Full report (PnL + daily) |
| `/blocked` | reports | Blocked trades last N days |
| `/pairs` | pair_manager | Show watchlist |
| `/addpair <PAIR>` | pair_manager | Add pair to watchlist |
| `/rmpair <PAIR>` | pair_manager | Remove pair |
| `/ranking` | pair_manager | Pair ranking by signal strength |
| `/health` | validators | Full startup validation |
| `/ai` | DB query | Last AI decision |
| `/killswitch` | config toggle | Toggle kill switch (admin) |
| `/capital <usd>` | config + bot_state | Set capital |
| `/maxexposure <pct>` | config + bot_state | Set max portfolio exposure |
| `/divzones [tf]` | div_radar | Divergence radar zones |
| `/divradar` | div_radar | Full multi-pair radar scan |
| `/reconcile [fix]` | reconcile | Exchange reconciliation. `fix` auto-resolves safe issues |
| `/liveready` | reconcile | 10-point live-readiness assessment |

---

## 19. Notifications — notifier.py

**53 lines.** Async Telegram notification helpers.

| Function | Purpose |
|----------|---------|
| `notify_admins(app, text)` | Broadcast to all TELEGRAM_ADMIN_IDS |
| `notify_trade_opened(app, pair, side, qty, price, reason)` | Trade opened alert |
| `notify_trade_closed(app, pair, side, pnl, reason)` | Trade closed alert with PnL |
| `notify_blocked_trade(app, pair, side, reason)` | Blocked trade alert |
| `notify_health_issue(app, issue)` | Health warning |
| `notify_daily_report(app, report)` | Daily report broadcast |

---

## 20. Reports & Analytics — reports.py

**199 lines.**

### Trade Queries

| Function | Returns |
|----------|---------|
| `get_open_trades(pair=None)` | List: id, pair, side, qty, entry, ts_open |
| `get_recent_closed(n=5, pair=None)` | List: id, pair, side, qty, entry, exit_price, pnl, ts_close |
| `daily_pnl_sum()` | float — closed PnL last 24h |

### `performance_summary(pair=None, days=30) -> dict`

Returns: total_trades, winning, losing, win_rate (%), total_pnl, avg_win, avg_loss, expectancy, profit_factor, largest_win, largest_loss.

### Formatted Reports

| Function | Content |
|----------|---------|
| `format_position_report()` | Open positions with live price + unrealized PnL |
| `format_pnl_report(pair, days)` | Full performance: trades, win rate, expectancy, profit factor |
| `daily_report(pair)` | Daily PnL, closed count, open positions, equity/drawdown snapshot |
| `blocked_trades_summary(days)` | Recent blocked trades with reasons |
| `format_trades_brief(rows, kind)` | Short trade list (up to 10) |
| `export_trades_csv(filepath, pair)` | CSV export |
| `save_performance_snapshot(pair, period)` | Persist to performance_snapshots table |

---

## 21. Exchange Reconciliation — reconcile.py

**403 lines.** New module for production safety.

### `reconcile_positions() -> dict`

Cross-checks DB open trades vs exchange state:

| Issue type | Detection |
|-----------|-----------|
| `stale_pending` | Trade in PENDING status > 5 minutes |
| `db_orphan` | DB says OPEN but exchange has no position for that base currency |
| `untracked_position` | Exchange has position but no OPEN trade in DB |
| `exchange_error` | Cannot fetch exchange positions |
| `missing_order_id` | OPEN trade with no order_id |
| `missing_trail_state` | lifecycle=trailing but no trail state in bot_state |

Returns: `{ts, db_open_trades, exchange_positions, issues, actions_taken, clean}`.

### `reconcile_orders() -> dict`
Checks recently failed trades (last 24h).

### `auto_fix_issues(report) -> list[str]`
Automatically fixes:
- Stale PENDING → mark FAILED
- Missing trail state → reset lifecycle to 'open'

### `check_live_readiness() -> dict`

10-point production readiness check:

| Check | What it verifies |
|-------|-----------------|
| 1. Database | `check_db_health()` passes |
| 2. Exchange | `health_check()` passes |
| 3. Telegram | Connected (responding to command) |
| 4. Scheduler | Last health check within 3x interval |
| 5. Trade State | No PENDING trades (0 = clean) |
| 6. Reconciliation | `reconcile_positions()` reports clean |
| 7. Watchlist | At least 1 active pair |
| 8. AI Providers | API keys present if AI fusion enabled |
| 9. Exchange Keys | Present if not paper mode |
| 10. Risk Config | RISK_PER_TRADE <= 5%, CAPITAL_USD > 0, DAILY_LOSS_LIMIT > 0 |

**Verdicts:**
- `READY` — all checks pass, no warnings
- `READY WITH WARNINGS` — all critical checks pass but warnings exist
- `NOT READY` — critical check(s) failed

---

## 22. Startup Validation — validators.py

**154 lines.**

| Function | Checks |
|----------|--------|
| `validate_config(settings)` | Token, admin IDs, exchange, pair format, risk ranges, AI policy, live mode keys, timeframes |
| `validate_exchange(settings)` | `fetch_ticker()` for configured pair |
| `validate_telegram(settings)` | HTTP `getMe` call |
| `validate_db(settings)` | `check_db_health()` |
| `run_all_checks(settings)` | All of the above + feature flags + trade state summary + trailing/correlation/drawdown status |

---

## 23. Entry Point — main.py

**150 lines.** Contains legacy `KrakenWrap` class and `load_config()`. The actual production entry point is:

```python
from telegram_bot import build_app
build_app().run_polling()
```

`build_app()` creates the Telegram application, registers all handlers, sets `post_init` for startup sequence, and schedules all background jobs.

---

## 24. Deployment & Scripts

### Procfile (Heroku/Railway)
```
worker: python -c "from telegram_bot import build_app; build_app().run_polling()"
```

### scripts/bootstrap.sh
Creates Python venv, installs requirements, copies .env.example.

### scripts/run_paper.sh / run_live.sh
Activates venv, sets MODE, runs main.py.

### backup_ai1.sh
Comprehensive backup: code, DB, .env, frozen deps, restore script.

### systemd/macd_rsi_bot.service
```ini
Type=simple
WorkingDirectory=/opt/macd_rsi_bot
ExecStart=/opt/macd_rsi_bot/.venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
```

### Audio Alerts
`audio/calm.wav`, `audio/risk.wav`, `audio/trend.wav` — system sound notifications.

### Dependencies (requirements.txt)
```
ccxt>=4.3.74
pandas>=2.2.2
numpy>=1.26
python-dotenv>=1.0.1
loguru>=0.7.2
requests>=2.31.0
python-telegram-bot[job-queue]>=21.0
anthropic>=0.39.0
openai>=1.50.0
psycopg2-binary>=2.9.0
```

---

## 25. Database Schema Reference

### Tables

#### `users`
| Column | SQLite Type | PG Type | Notes |
|--------|-----------|---------|-------|
| user_id | INTEGER PK | BIGINT PK | Telegram user ID |
| tg_username | TEXT | TEXT | |
| tier | TEXT DEFAULT 'BASIC' | TEXT DEFAULT 'BASIC' | |
| trial_start_ts | INTEGER | BIGINT | Unix timestamp |
| trial_end_ts | INTEGER | BIGINT | |
| ai_api_key | TEXT | TEXT | |
| autotrade_enabled | INTEGER DEFAULT 0 | INTEGER DEFAULT 0 | 0/1 |
| trade_mode | TEXT DEFAULT 'PAPER' | TEXT DEFAULT 'PAPER' | PAPER/LIVE |
| daily_loss_limit | REAL DEFAULT 50.0 | DOUBLE PRECISION DEFAULT 50.0 | |
| max_open_trades | INTEGER DEFAULT 2 | INTEGER DEFAULT 2 | |

#### `trades`
| Column | SQLite Type | PG Type | Notes |
|--------|-----------|---------|-------|
| id | INTEGER PK AUTOINCREMENT | BIGSERIAL PK | |
| ts_open | INTEGER | BIGINT | Unix timestamp |
| ts_close | INTEGER | BIGINT | |
| pair | TEXT | TEXT | e.g. BNB/USDC |
| side | TEXT | TEXT | BUY/SELL |
| qty | REAL | DOUBLE PRECISION | |
| entry | REAL | DOUBLE PRECISION | Entry price |
| exit_price | REAL | DOUBLE PRECISION | Exit price |
| pnl | REAL | DOUBLE PRECISION | Realized PnL |
| status | TEXT | TEXT | PENDING/OPEN/CLOSED/FAILED |
| note | TEXT | TEXT | Accumulated notes |
| lifecycle | TEXT DEFAULT 'open' | TEXT DEFAULT 'open' | pending/open/protected/trailing/closed/blocked |
| entry_snapshot | TEXT | TEXT | JSON with signals, ATR, confidence |
| exit_snapshot | TEXT | TEXT | JSON with exit context |
| trade_type | TEXT DEFAULT 'auto' | TEXT DEFAULT 'auto' | auto/manual |
| order_id | TEXT | TEXT | Exchange order ID |

#### `manual_guards`
| Column | Type | Notes |
|--------|------|-------|
| user_id | INTEGER/BIGINT | PK (composite) |
| pair | TEXT | PK (composite) |
| stop_loss | REAL/DOUBLE PRECISION | |
| take_profit | REAL/DOUBLE PRECISION | |
| trail_pct | REAL/DOUBLE PRECISION | Percentage-based trailing |
| trail_stop | REAL/DOUBLE PRECISION | Current trail stop level |
| high_watermark | REAL/DOUBLE PRECISION | Highest price reached |

#### `trading_pairs`
| Column | Type | Notes |
|--------|------|-------|
| pair | TEXT PK | e.g. BNB/USDC |
| is_active | INTEGER DEFAULT 1 | 0/1 |
| added_ts | INTEGER/BIGINT | |
| last_signal_ts | INTEGER/BIGINT | |
| last_direction | TEXT | BUY/SELL/HOLD |
| last_score | REAL/DOUBLE PRECISION | |
| notes | TEXT DEFAULT '' | |

#### `ai_decisions`
| Column | Type | Notes |
|--------|------|-------|
| id | AUTOINCREMENT/BIGSERIAL | PK |
| ts | INTEGER/BIGINT NOT NULL | |
| pair | TEXT NOT NULL | |
| action | TEXT NOT NULL | ENTER/EXIT/HOLD |
| side | TEXT | BUY/SELL |
| confidence | REAL/DOUBLE PRECISION | 0.0–1.0 |
| setup_quality | REAL/DOUBLE PRECISION | 0.0–1.0 |
| reasons | TEXT | JSON array |
| warnings | TEXT | JSON array |
| risk_flags | TEXT | JSON array |
| source | TEXT | local,claude,openai |
| fusion_policy | TEXT | |
| raw_response | TEXT | |
| was_executed | INTEGER DEFAULT 0 | 0/1 |

#### `blocked_trades`
| Column | Type | Notes |
|--------|------|-------|
| id | AUTOINCREMENT/BIGSERIAL | PK |
| ts | INTEGER/BIGINT NOT NULL | |
| pair | TEXT NOT NULL | |
| side | TEXT | |
| reason | TEXT NOT NULL | |
| signal_snapshot | TEXT | JSON |

#### `bot_state`
| Column | Type | Notes |
|--------|------|-------|
| key | TEXT PK | e.g. peak_equity, atr_trail_42, last_startup |
| value | TEXT | |
| updated_ts | INTEGER/BIGINT | |

#### `performance_snapshots`
| Column | Type | Notes |
|--------|------|-------|
| id | AUTOINCREMENT/BIGSERIAL | PK |
| ts | INTEGER/BIGINT NOT NULL | |
| pair | TEXT | |
| period | TEXT | daily/weekly |
| total_trades | INTEGER | |
| winning_trades | INTEGER | |
| losing_trades | INTEGER | |
| total_pnl | REAL/DOUBLE PRECISION | |
| avg_win | REAL/DOUBLE PRECISION | |
| avg_loss | REAL/DOUBLE PRECISION | |
| win_rate | REAL/DOUBLE PRECISION | |
| expectancy | REAL/DOUBLE PRECISION | |

---

## 26. Environment Variables — Full Reference

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `ENV` | `dev` | Environment name |
| `TZ` | `America/Vancouver` | Timezone |
| `DB_PATH` | `./bot.db` | SQLite database path |
| `LOG_LEVEL` | `INFO` | Logging level |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_ENGINE` | `sqlite` | `sqlite` or `postgres` |
| `SUPABASE_URL` | | Supabase project URL |
| `SUPABASE_KEY` | | Supabase API key |
| `SUPABASE_DB_HOST` | | PostgreSQL host |
| `SUPABASE_DB_PORT` | `6543` | PostgreSQL port |
| `SUPABASE_DB_NAME` | `postgres` | Database name |
| `SUPABASE_DB_USER` | `postgres` | Database user |
| `SUPABASE_DB_PASSWORD` | | Database password |
| `SUPABASE_SCHEMA` | `trading_bot` | Schema name |

### Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `FEATURE_MULTI_PAIR` | `false` | Multi-pair watchlist |
| `FEATURE_AI_FUSION` | `false` | Dual-AI decision engine |
| `FEATURE_CANDLE_PATTERNS` | `false` | Candle pattern detection |
| `FEATURE_HIDDEN_DIVERGENCE` | `false` | Hidden divergence detection |
| `FEATURE_MARKET_REGIME` | `false` | Market regime classification |

### Exchange

| Variable | Default | Description |
|----------|---------|-------------|
| `EXCHANGE` | `kraken` | CCXT exchange name |
| `PAIR` | `BNB/USDC` | Default trading pair |
| `TIMEFRAMES` | `30m,1h,4h,1d` | Analysis timeframes (comma-separated) |
| `CANDLE_LIMIT` | `300` | OHLCV bars to fetch |
| `PAPER_TRADING` | `true` | Paper trading mode |
| `KRAKEN_API_KEY` | | Kraken API key (live mode) |
| `KRAKEN_API_SECRET` | | Kraken API secret (live mode) |

### Multi-Pair

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_PAIRS` | `BNB/USDC` | Default pair(s) |
| `MAX_WATCHED_PAIRS` | `10` | Max pairs in watchlist |
| `PAIR_MODE` | `single` | `single` or `multi` |

### Risk Management

| Variable | Default | Description |
|----------|---------|-------------|
| `CAPITAL_USD` | `1000` | Starting capital |
| `RISK_PER_TRADE` | `0.01` | Risk per trade (1%) |
| `MAX_OPEN_TRADES` | `2` | Max concurrent open trades |
| `DAILY_LOSS_LIMIT_USD` | `50` | Daily loss limit |
| `ENABLE_EXIT_AUTOMATION` | `true` | Allow auto-exit |
| `COOLDOWN_AFTER_TRADE_SECONDS` | `300` | Cooldown between trades |
| `MAX_DAILY_TRADES` | `10` | Max trades per day |
| `CONSECUTIVE_LOSS_COOLDOWN` | `3` | Losses before pause |
| `CONSECUTIVE_LOSS_PAUSE_SECONDS` | `3600` | Pause duration |
| `BREAK_EVEN_ATR_MULTIPLIER` | `1.0` | ATR for break-even move |

### Autonomous Trading

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_PORTFOLIO_EXPOSURE` | `0.50` | Max % of capital exposed |
| `CAPITAL_PER_TRADE_PCT` | `0.10` | Max capital per trade |
| `MIN_SETUP_QUALITY` | `0.3` | Minimum setup quality |
| `MAX_RISK_FLAGS` | `2` | Max risk flags before skip |
| `CONFIDENCE_SCALE_MIN` | `0.5` | Min confidence scale factor |
| `CONFIDENCE_SCALE_MAX` | `1.0` | Max confidence scale factor |
| `MAX_PAIRS_PER_CYCLE` | `3` | Max new trades per cycle |
| `TP_ATR_MULTIPLIER` | `2.0` | Take profit in ATR |

### ATR Trailing Stops

| Variable | Default | Description |
|----------|---------|-------------|
| `TRAILING_ENABLED` | `true` | Enable ATR trailing stops |
| `TRAILING_ATR_MULTIPLIER` | `2.5` | Initial trail distance |
| `TRAILING_TIGHTEN_AFTER_ATR` | `2.0` | Profit before tightening |
| `TRAILING_TIGHTEN_MULTIPLIER` | `1.5` | Tightened trail distance |
| `TRAILING_ACTIVATION_ATR` | `1.0` | Min profit to activate |

### Correlation Risk

| Variable | Default | Description |
|----------|---------|-------------|
| `CORRELATION_CHECK_ENABLED` | `true` | Enable correlation gate |
| `CORRELATION_THRESHOLD` | `0.75` | Max allowed correlation |
| `CORRELATION_LOOKBACK_BARS` | `50` | Bars for calculation |
| `CORRELATION_TIMEFRAME` | `1h` | Timeframe for data |
| `MAX_CORRELATED_EXPOSURE` | `2` | Max correlated positions |

### Drawdown Management

| Variable | Default | Description |
|----------|---------|-------------|
| `DRAWDOWN_TRACKING_ENABLED` | `true` | Enable drawdown management |
| `DRAWDOWN_SCALE_THRESHOLD` | `0.10` | Start reducing at 10% DD |
| `DRAWDOWN_HALT_THRESHOLD` | `0.25` | Halt at 25% DD |
| `DRAWDOWN_SCALE_FACTOR` | `0.50` | Size multiplier at threshold |

### Kill Switch / Dry Run

| Variable | Default | Description |
|----------|---------|-------------|
| `KILL_SWITCH` | `false` | Emergency stop |
| `DRY_RUN_MODE` | `false` | Log trades, don't execute |

### Telegram

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | | Bot token from @BotFather |
| `TELEGRAM_ADMIN_IDS` | | Comma-separated admin user IDs |
| `HTTPS_PROXY` | | Optional proxy |

### AI Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_BASE_URL` | | Legacy AI base URL |
| `AI_API_KEY` | | Legacy AI API key |
| `AI_MODEL` | `gpt-4o-mini` | Legacy AI model |
| `AI_CONFIDENCE_MIN` | `0.65` | Minimum confidence to trade |
| `SIGNAL_SCORE_MIN` | `0.60` | Minimum score to trade |
| `CLAUDE_API_KEY` | | Anthropic API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model |
| `OPENAI_API_KEY` | | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model |
| `AI_FUSION_POLICY` | `local_only` | local_only/advisory/majority/strict_consensus |
| `AI_TIMEOUT_SECONDS` | `15` | AI call timeout |

### Indicators / Strategy

| Variable | Default | Description |
|----------|---------|-------------|
| `ATR_PERIOD` | `14` | ATR period |
| `ADX_PERIOD` | `14` | ADX period |
| `ADX_TREND_MIN` | `20.0` | Min ADX for trend |
| `ADX_STRONG_TREND` | `40.0` | Strong trend bonus threshold |
| `BB_PERIOD` | `20` | Bollinger Bands period |
| `BB_STD` | `2.0` | Bollinger Bands std |
| `PIVOT_LOOKBACK` | `3` | Pivot detection lookback |
| `ATR_SL_MULTIPLIER` | `1.5` | Stop-loss in ATR |

### Candle Patterns

| Variable | Default | Description |
|----------|---------|-------------|
| `CANDLE_WICK_RATIO` | `2.0` | Min wick/body ratio |
| `CANDLE_BODY_RATIO` | `0.3` | Max body/range ratio |

### Market Regime

| Variable | Default | Description |
|----------|---------|-------------|
| `REGIME_EMA_FAST` | `20` | Fast EMA |
| `REGIME_EMA_SLOW` | `50` | Slow EMA |
| `REGIME_ADX_THRESHOLD` | `25.0` | Trending threshold |
| `REGIME_VOLATILITY_LOOKBACK` | `20` | Volatility lookback |

### Scheduler

| Variable | Default | Description |
|----------|---------|-------------|
| `ANALYSIS_INTERVAL_SECONDS` | `600` | Main cycle (10 min) |
| `GUARD_CHECK_INTERVAL_SECONDS` | `30` | Guard check interval |
| `HEALTH_CHECK_INTERVAL_SECONDS` | `3600` | Health check (1 hr) |

### Payments (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `PAYMENT_PROVIDER` | | Payment provider |
| `STRIPE_SECRET_KEY` | | Stripe API key |

### Live Control

| Variable | Default | Description |
|----------|---------|-------------|
| `LIVE_TRADE_ALLOWED_IDS` | | User IDs for live mode |

---

## 27. Production Hardening Summary

### What was hardened (commit 5caef43)

| Area | Before | After |
|------|--------|-------|
| **DB backend** | SQLite-specific patterns throughout | All queries backend-agnostic. PG schema auto-creates. |
| **ON CONFLICT** | 12 raw ON CONFLICT clauses in 5 files | All isolated in storage.py upsert helpers with proper branching |
| **Trade execution** | Single-phase (insert + order in one step) | Two-phase: PENDING → exchange order → OPEN/FAILED |
| **Crash recovery** | None | `recover_pending_trades()` on every startup |
| **Execution dedup** | None | 10s per pair:side lock prevents duplicate trades |
| **Scheduler** | Could register duplicate jobs | `_jobs_scheduled` guard + stale job removal |
| **Reconciliation** | None | DB vs exchange cross-check with auto-fix |
| **Live readiness** | No formal check | 10-point readiness assessment |
| **String concat** | Raw `\|\|` operator (PG coercion risk) | Safe `CASE WHEN` pattern via `append_trade_note()` |
| **SQLite threading** | `check_same_thread=False` (race conditions) | Shared connection + `threading.Lock` |
| **PG connections** | No error handling | Explicit rollback on exception, error logging |
| **Trade state** | Only OPEN/CLOSED | PENDING/OPEN/CLOSED/FAILED lifecycle |

### What remains as known limits

| Limit | Severity | Notes |
|-------|----------|-------|
| No PG connection pooling | Low | Per-call connections fine at bot's concurrency (~1/30s) |
| No partial fill handling | Low | Kraken market orders rarely partial-fill |
| Paper mode has no slippage | Low | Inherent to paper simulation |
| Exchange reconciliation is currency-level, not position-level | Medium | Kraken API doesn't expose position IDs easily |

### Bot readiness assessment

| Level | Status |
|-------|--------|
| Paper-ready | YES |
| Supervised-live-ready | YES (with daily /reconcile and /liveready) |
| Fully autonomous-live-ready | After 1-2 weeks supervised paper proving |

---

## 28. Operational Runbook

### Local Development

```bash
cd /Volumes/MiniSSD/aiMCDtrader
cp env. .env          # Edit with your values
pip install -r requirements.txt
python -c "from telegram_bot import build_app; build_app().run_polling()"
```

### Railway Deployment

```bash
# Procfile already configured
railway up
```

Set env vars in Railway dashboard.

### Supabase/PostgreSQL Setup

1. Create Supabase project
2. Set env vars:
```
DB_ENGINE=postgres
SUPABASE_DB_HOST=db.xxxx.supabase.co
SUPABASE_DB_PORT=6543
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=your-password
SUPABASE_SCHEMA=trading_bot
```
3. First startup auto-creates schema and all tables

### Minimum Required Environment Variables

```
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_ADMIN_IDS=123456
PAIR=BNB/USDC
PAPER_TRADING=true
DB_ENGINE=sqlite
```

### Verify Production Health

1. `/liveready` — 10-point readiness check
2. `/health` — startup validation report
3. `/reconcile` — cross-check DB vs exchange
4. `/reconcile fix` — auto-fix safe issues
5. `/status` — equity, drawdown, exposure

### Paper Mode Proving (Before Live)

1. Set `PAPER_TRADING=true`, `FEATURE_MULTI_PAIR=true`
2. `/autotrade on`
3. Monitor 1-2 weeks via `/status`, `/positions`, `/pnl`
4. Check `/reconcile` daily
5. When satisfied:
   - Set `PAPER_TRADING=false`
   - Add `KRAKEN_API_KEY` and `KRAKEN_API_SECRET`
   - Run `/liveready` to confirm
   - Start with small `CAPITAL_USD` (e.g. $100)

### Emergency Procedures

| Situation | Command |
|-----------|---------|
| Stop all trading immediately | `/killswitch` |
| Close all positions now | `/sellnow` |
| Check for state issues | `/reconcile` |
| Fix state issues | `/reconcile fix` |
| Check if safe to trade | `/liveready` |
