# MCDAutoTrader — Complete Technical Reference

> Last updated: 2026-04-13
> Version: Post-upgrade (ATR trailing, correlation risk, drawdown management)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture & Data Flow](#2-architecture--data-flow)
3. [Configuration (config.py)](#3-configuration-configpy)
4. [Database Layer (storage.py)](#4-database-layer-storagepy)
5. [Exchange Integration (exchange.py)](#5-exchange-integration-exchangepy)
6. [Technical Indicators (indicators.py)](#6-technical-indicators-indicatorspy)
7. [Divergence Detection (divergence.py)](#7-divergence-detection-divergencepy)
8. [Candle Pattern Recognition (candles.py)](#8-candle-pattern-recognition-candlespy)
9. [Market Regime Detection (market_regime.py)](#9-market-regime-detection-market_regimepy)
10. [Divergence Radar Engine (div_radar.py)](#10-divergence-radar-engine-div_radarpy)
11. [Strategy & Scoring (strategy.py)](#11-strategy--scoring-strategypy)
12. [AI Fusion Engine (ai_fusion.py)](#12-ai-fusion-engine-ai_fusionpy)
13. [AI Decider Wrapper (ai_decider.py)](#13-ai-decider-wrapper-ai_deciderpy)
14. [Risk Management (risk.py)](#14-risk-management-riskpy)
15. [Trade Executor (trade_executor.py)](#15-trade-executor-trade_executorpy)
16. [Pair Manager (pair_manager.py)](#16-pair-manager-pair_managerpy)
17. [Scheduler & Main Loop (scheduler.py)](#17-scheduler--main-loop-schedulerpy)
18. [Telegram Bot (telegram_bot.py)](#18-telegram-bot-telegram_botpy)
19. [Notifications (notifier.py)](#19-notifications-notifierpy)
20. [Reports & Analytics (reports.py)](#20-reports--analytics-reportspy)
21. [Startup Validation (validators.py)](#21-startup-validation-validatorspy)
22. [Entry Point (main.py)](#22-entry-point-mainpy)
23. [Deployment & Scripts](#23-deployment--scripts)
24. [Environment Variables — Full Reference](#24-environment-variables--full-reference)

---

## 1. System Overview

MCDAutoTrader is a fully autonomous cryptocurrency trading bot that combines:

- **MACD/RSI divergence detection** (regular + hidden + pre-confirmation radar)
- **Multi-indicator scoring** (9 weighted signal components)
- **Dual-AI fusion** (Claude + OpenAI + local heuristic with 4 consensus policies)
- **10-gate risk management** (including correlation checks and drawdown halting)
- **ATR-based dynamic trailing stops** (tightening as profit grows)
- **Equity curve tracking** with automatic position size reduction during drawdowns
- **Multi-pair autonomous trading** with ranked entry execution
- **Telegram command & control** interface with inline keyboards

The bot runs on **Kraken** exchange via CCXT, supports **paper** and **live** trading modes, and stores data in **SQLite** (local) or **PostgreSQL/Supabase** (remote).

---

## 2. Architecture & Data Flow

### File Dependency Graph

```
main.py
├── config.py (Settings dataclass)
├── storage.py (DB abstraction)
├── validators.py (startup checks)
├── telegram_bot.py
│   ├── trade_executor.py
│   ├── scheduler.py
│   │   ├── exchange.py (CCXT wrapper)
│   │   ├── strategy.py
│   │   │   ├── indicators.py
│   │   │   ├── divergence.py
│   │   │   ├── candles.py
│   │   │   ├── market_regime.py
│   │   │   └── div_radar.py
│   │   ├── ai_decider.py → ai_fusion.py
│   │   ├── risk.py
│   │   ├── pair_manager.py
��   │   ├── notifier.py
│   │   └── reports.py
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
   ▼
┌─────────────────────────────────────┐
│         INDICATOR LAYER             │
│  EMA, RSI, MACD, Stochastic,       │
│  ATR, ADX, Bollinger Bands, VolMA  │
└──────────────┬──────────────────────┘
               │
   ┌───────────┼───────────┬──────────────┐
   ���           ▼           ▼              ▼
Divergence  Candle     Market         Div Radar
(reg+hid)   Patterns   Regime         (pre-confirm)
   │           │           │              │
   └───────────┴───────────┴──────────────┘
               │
               ���
┌─────────────────────────────────────┐
│        STRATEGY LAYER               │
│  tf_signal() → per-TF scoring      │
│  merge_mtf() → weighted consensus  │
│  Score threshold: 1.5 minimum       │
└──────────────┬──────────���───────────┘
               │
               ▼
┌─────────────────────────────────────┐
│        AI FUSION LAYER              │
│  Local heuristic (always)           │
│  + Claude API (optional)            │
│  + OpenAI API (optional)            │
│  Policy: local/advisory/majority/   │
│          strict_consensus           │
│  Output: ENTER/EXIT/HOLD + conf    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│        RISK GATE (10 checks)        │
│  Kill switch → Open trade limit →   │
│  Portfolio exposure → Daily loss →   │
│  Daily trade count → Cooldown →     │
│  Consecutive loss pause →           │
│  Duplicate check → Correlation →    │
│  Drawdown halt                      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│      POSITION SIZING                │
│  Base: capital × risk / ATR         │
│  × confidence × quality × DD_scale │
│  Capped by portfolio limits         │
└──────────────┬───��──────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│      TRADE EXECUTION                │
│  DB record → Exchange order →       │
│  Set SL/TP guards                   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│      GUARD MONITORING (every 30s)   │
│  Manual SL/TP/Trail% checks         │
│  ATR trailing stop (dynamic)        │
│  → Auto-exit if triggered           │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│      REPORTING & NOTIFICATIONS      │
│  Telegram alerts, daily reports,    │
│  equity tracking, performance stats │
└───���─────────────────────────────────┘
```

---

## 3. Configuration (config.py)

Single `Settings` dataclass loaded from `.env` via `python-dotenv`. All parameters have defaults.

### `_ids(v: str) -> tuple`
Parse comma-separated integers (used for TELEGRAM_ADMIN_IDS, LIVE_TRADE_ALLOWED_IDS).

### `_pairs(v: str) -> tuple`
Parse comma-separated pair strings.

### `_bool(key: str, default: str) -> bool`
Read env var as boolean (`'true'` → `True`).

### `Settings` dataclass
See [Section 24](#24-environment-variables--full-reference) for the full list of 80+ parameters.

### `SETTINGS = Settings()`
Module-level singleton instance used by all other modules.

---

## 4. Database Layer (storage.py)

Dual-backend support: SQLite (local) or PostgreSQL (Supabase).

### Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `users` | Telegram users & settings | user_id (PK), tier, autotrade_enabled, trade_mode, daily_loss_limit |
| `trades` | All trade records | id (PK), pair, side, qty, entry, exit_price, pnl, status, lifecycle, ts_open, ts_close, entry_snapshot, exit_snapshot, trade_type, order_id |
| `signals` | Signal history log | id (PK), ts, pair, tf, direction, reason |
| `manual_guards` | SL/TP/trailing per user+pair | user_id+pair (PK), stop_loss, take_profit, trail_pct, trail_stop, high_watermark |
| `trading_pairs` | Multi-pair watchlist | pair (PK), is_active, last_direction, last_score, last_signal_ts |
| `ai_decisions` | AI decision audit trail | id (PK), ts, pair, action, side, confidence, setup_quality, reasons, source, fusion_policy |
| `blocked_trades` | Trades rejected by risk gates | id (PK), ts, pair, side, reason, signal_snapshot |
| `bot_state` | Key-value persistent state | key (PK), value, updated_ts |
| `performance_snapshots` | Historical performance metrics | id (PK), ts, pair, period, total_trades, win_rate, expectancy |

### Functions

#### `init_db()`
- SQLite: runs `SQLITE_SCHEMA` DDL + column migrations (lifecycle, entry_snapshot, exit_snapshot, trade_type, order_id)
- PostgreSQL: no-op (tables managed via Supabase migration)

#### `_migrate_sqlite_trades(conn)`
Adds new columns to the `trades` table if missing: `lifecycle`, `entry_snapshot`, `exit_snapshot`, `trade_type`, `order_id`.

#### `_q(query: str) -> str`
Converts `?` placeholders to `%s` for PostgreSQL compatibility.

#### `get_conn()`
Returns a database connection (SQLite or PostgreSQL based on `DB_ENGINE` setting).

#### `fetchone(q, p=()) -> tuple|None`
Execute query, return first row.

#### `fetchall(q, p=()) -> list`
Execute query, return all rows.

#### `execute(q, p=()) -> int`
Execute write query, return lastrowid (SQLite) or RETURNING value (PostgreSQL).

---

## 5. Exchange Integration (exchange.py)

Minimalist CCXT wrapper. Single-file module.

### `get_client() -> ccxt.Exchange`
Creates a CCXT exchange instance (default: Kraken) with rate limiting enabled.
Uses `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` if set.

### `fetch_ohlcv(pair, timeframe, limit) -> pd.DataFrame`
Fetches OHLCV candle data. Returns DataFrame with columns: `[ts, open, high, low, close, volume]`.
Timestamps converted to datetime.

### `market_price(pair) -> float`
Fetches current last price via `fetch_ticker()`.

### `place_market_order(pair, side, amount) -> dict`
- **Paper mode**: Returns mock order `{'id': 'paper-{pair}-{side}', 'status': 'filled', ...}`
- **Live mode**: Executes real market order via `create_order()`

### `health_check() -> tuple(bool, str)`
Calls `fetch_time()` to verify exchange connectivity.

### `validate_pair_on_exchange(pair) -> bool`
Loads exchange markets and checks if pair exists.

### `cancel_order(order_id, pair) -> dict`
Cancels an order. Paper mode returns mock cancellation.

### `get_balance(currency='USDC') -> float`
Returns free balance for a currency. Paper mode returns `CAPITAL_USD`.

---

## 6. Technical Indicators (indicators.py)

All indicators are pure vectorized Pandas/NumPy one-liners. No TA-lib dependency.

### `ema(s, p) -> Series`
Exponential Moving Average with span `p`.

### `rsi(s, period=14) -> Series`
Relative Strength Index. Gains/losses via rolling mean. Fills NaN with 50.

### `macd(s, fast=12, slow=26, signal=9) -> tuple(line, signal, histogram)`
MACD line, signal line, and histogram (line - signal).

### `stochastic(h, l, c, kp=14, dp=3) -> tuple(k, d)`
Stochastic oscillator %K and %D. Fills NaN with 50.

### `vol_ma(v, period=20) -> Series`
Simple moving average of volume.

### `ema_pair(c, p1=9, p2=21) -> tuple(ema1, ema2)`
Returns two EMAs at once.

### `atr(high, low, close, period=14) -> Series`
Average True Range using EMA smoothing.
`TR = max(H-L, |H-prev_C|, |L-prev_C|)`

### `adx(high, low, close, period=14) -> tuple(adx_line, plus_di, minus_di)`
Average Directional Index with +DI and -DI.

### `bollinger(close, period=20, std=2.0) -> tuple(upper, middle, lower)`
Bollinger Bands: `middle ± std × rolling_std`.

---

## 7. Divergence Detection (divergence.py)

### `_pivots(s, lookback=None) -> tuple(highs, lows)`
Finds last 2 pivot highs and pivot lows using rolling window comparison.
Lookback defaults to `SETTINGS.PIVOT_LOOKBACK` (3).

### `_strength(p1, p2, o1, o2) -> float`
Calculates divergence strength (0.1–1.0) based on:
`min(price_delta_pct + osc_delta_pct, 1.0)`

### `detect_divergence(price, osc) -> tuple(type, strength)`
Detects regular divergence:
- **Bearish**: Price makes higher high, oscillator makes lower high → reversal down
- **Bullish**: Price makes lower low, oscillator makes higher low → reversal up
- Returns `("none", 0.0)` if no divergence found or series < 50 bars

### `detect_hidden_divergence(price, osc) -> tuple(type, strength)`
Detects hidden (trend continuation) divergence:
- **Hidden bearish**: Price makes lower high, oscillator makes higher high → continuation down
- **Hidden bullish**: Price makes higher low, oscillator makes lower low → continuation up

### `detect_all_divergences(price, osc) -> dict`
Convenience function returning both regular and hidden divergences in one dict:
```python
{'regular': {'type': str, 'strength': float}, 'hidden': {'type': str, 'strength': float}}
```

---

## 8. Candle Pattern Recognition (candles.py)

### `CandlePattern` class
Attributes: `name`, `direction` ('bullish'/'bearish'), `strength` (0.0–1.0), `bar_index`.
Method: `to_dict()` for serialization.

### Helper functions
- `_body(o, c)` — Absolute body size
- `_range(h, l)` — Full candle range
- `_upper_wick(o, h, c)` — Upper shadow length
- `_lower_wick(o, l, c)` — Lower shadow length
- `_is_green(o, c)` / `_is_red(o, c)` — Candle direction checks

### Pattern detectors

#### `_check_hammer(o, h, l, c) -> float`
**Bullish reversal.** Small body at top, long lower wick.
Conditions: `lower_wick >= CANDLE_WICK_RATIO(2.0) × body` AND `body_pct <= CANDLE_BODY_RATIO(0.3)`.
Strength: `lower_wick / range`.

#### `_check_shooting_star(o, h, l, c) -> float`
**Bearish reversal.** Small body at bottom, long upper wick.
Same ratio conditions as hammer but for upper wick.

#### `_check_bullish_engulfing(po, ph, pl, pc, o, h, l, c) -> float`
Previous red candle fully engulfed by current green candle.
Strength: `curr_body / prev_body × 0.5`.

#### `_check_bearish_engulfing(po, ph, pl, pc, o, h, l, c) -> float`
Previous green candle fully engulfed by current red candle.

#### `_check_rejection_wick(o, h, l, c, direction) -> float`
Long wick in the opposite direction. Wick must be `>= 2.0 × body`.

#### `_check_breakout(df, idx, lookback=20) -> tuple(direction, strength)`
Close above highest high or below lowest low of prior `lookback` bars.
Strength weighted by volume factor: `0.5 × min(2.0, cur_vol / avg_vol)`.

### `detect_patterns(df, lookback=3) -> list[CandlePattern]`
Scans last `lookback` bars for all pattern types. Returns sorted by strength descending.

### `summarize_patterns(patterns) -> dict`
Returns:
```python
{
    'bullish_count': int, 'bearish_count': int,
    'bull_score': float, 'bear_score': float,
    'net_score': float,  # bull_score - bear_score
    'strongest': dict|None, 'patterns': list (top 5)
}
```

---

## 9. Market Regime Detection (market_regime.py)

### `RegimeResult` class
Attributes: `regime` (str), `confidence` (float), `details` (dict).
Method: `to_dict()`.

### `detect_regime(df) -> RegimeResult`
Analyzes OHLCV DataFrame to classify market state:

| Regime | Conditions | Confidence |
|--------|-----------|------------|
| `trending_up` | ADX >= `REGIME_ADX_THRESHOLD(25)` AND EMA_fast > EMA_slow | 0.5 + ADX/100 + EMA_gap%/10 |
| `trending_down` | ADX >= threshold AND EMA_fast < EMA_slow | same formula |
| `volatile` | ADX < threshold AND ATR percentile > 75% | 0.4 + ATR_pct/2 |
| `ranging` | ADX < threshold AND not high volatility | 0.5 + (1 - ADX/threshold) × 0.3 |

**Details dict** contains: ema_fast, ema_slow, ema_bullish, ema_gap_pct, adx, atr_percentile, is_trending, high_volatility.

Used by `merge_mtf()` to gate signals against the daily regime.

---

## 10. Divergence Radar Engine (div_radar.py)

Detects forming divergences **before full confirmation**. More aggressive than `divergence.py`.

### `DivZone` dataclass
Attributes: symbol, timeframe, direction, stage, probability, strength, confidence, trigger_price, invalidation, reasons, oscillator.
Property: `score = probability × strength × confidence`.

### Maturity Stages
| Stage | Probability Range | Meaning |
|-------|------------------|---------|
| `potential_zone` | 0.10–0.30 | Early signals detected |
| `developing` | 0.30–0.50 | Multiple signals aligning |
| `near_confirmed` | 0.50–0.70 | Strong setup, awaiting final confirmation |
| `confirmed` | 0.70–1.00 | Full divergence confirmed |

### `_find_pivots(s, lookback=5, count=5) -> tuple(highs, lows)`
Enhanced pivot detection. Returns last `count` pivot highs/lows with values.
Allows recent bars (lookback only on left side for last bar).

### `_scan_bearish(df, osc_series, osc_name, symbol, tf) -> list[DivZone]`
Detects forming bearish divergence via 5 independent signals:

| Signal | Probability Added | Condition |
|--------|------------------|-----------|
| Price near high but osc weaker | +0.30 | Price within 0.5% of prev high, osc 5%+ weaker |
| MACD histogram fading (3-bar) | +0.20 | 3 consecutive declining bars, still positive |
| MACD histogram declining (2-bar) | +0.10 | 2 declining bars |
| Weak volume on push higher | +0.15 | Price near high, volume < 80% of 20-bar average |
| RSI overbought but declining | +0.15 | RSI > 65 and declining (RSI only) |
| Confirmed HH/LH divergence | +0.30 | Classic higher-high price + lower-high oscillator |

Trigger price: `prev_high - 0.5 × ATR`.
Invalidation: `prev_high + 1.5 × ATR`.

### `_scan_bullish(df, osc_series, osc_name, symbol, tf) -> list[DivZone]`
Mirror of bearish scan for bullish divergence:
- Price near low but osc stronger → +0.30
- MACD histogram recovering → +0.20/+0.10
- Declining volume on push lower → +0.15
- RSI oversold but improving → +0.15
- Confirmed LL/HL divergence → +0.30

### `scan_divergence_zones(df, symbol, timeframe) -> list[DivZone]`
Main scan function. Runs both bearish and bullish scans on both RSI and MACD.
Deduplicates via `_merge_zones()`, sorts by composite score.

### `_merge_zones(zones) -> list[DivZone]`
Groups by (symbol, timeframe, direction). When both RSI and MACD agree:
- Probability boosted by `+0.3 × other.probability`
- Confidence averaged and boosted by `+0.1`
- Stage upgraded if merger is stronger

### `full_radar_scan(pairs, timeframes, fetch_fn) -> list[DivZone]`
Multi-pair, multi-timeframe scan. Iterates all combinations.

### `format_radar_report(zones, max_zones=10) -> str`
Telegram-formatted report with stage icons, probability, trigger/invalidation levels.

### `format_radar_brief(zones, tf_filter=None) -> str`
Short format optionally filtered by timeframe.

---

## 11. Strategy & Scoring (strategy.py)

### `tf_signal(df, symbol, timeframe) -> dict`
Computes a single-timeframe signal from OHLCV DataFrame.

**Step 1: Compute all indicators** — MACD, RSI, Stochastic, EMA(9,21), VolMA, ATR, ADX, Bollinger.

**Step 2: Detect divergences** — Regular (always) + Hidden (feature flag) + Candle patterns (feature flag) + Market regime (feature flag) + Divergence radar zones (always attempted).

**Step 3: ADX filter** — If `ADX < ADX_TREND_MIN(20)` → return HOLD immediately (choppy market rejection).

**Step 4: Weighted scoring** (9 components):

| # | Component | Weight | Condition |
|---|-----------|--------|-----------|
| 1 | Regular MACD divergence | 1.5 × strength | Bullish or bearish detected |
| 2 | Regular RSI divergence | 1.5 × strength | Bullish or bearish detected |
| 3 | Hidden MACD divergence | 1.0 × strength | Feature flag ON |
| 4 | Hidden RSI divergence | 1.0 × strength | Feature flag ON |
| 5 | EMA trend (EMA9 vs EMA21) | 1.0 fixed | Always applied |
| 6 | Stochastic crossover | 0.75 | K > D and K < 80 (bull) or K < D and K > 20 (bear) |
| 7 | Volume confirmation | 0.5 | Current vol > 20-bar MA (adds to both buy and sell) |
| 8 | Bollinger position | 0.5 | Below 0.2 (bull) or above 0.8 (bear) |
| 9 | MACD histogram momentum | 0.5 | Rising and positive (bull) or falling and negative (bear) |
| 10 | Candle patterns | min(0.75, net×0.5) | Feature flag ON |
| 11 | Divergence radar zones | probability × 2.0 | Up to 2.0 for confirmed zones |

**Step 5: Direction decision**
- `BUY` if `buy_score >= 1.5` and `buy_score > sell_score`
- `SELL` if `sell_score >= 1.5` and `sell_score > buy_score`
- `HOLD` otherwise
- Final `score = buy_score - sell_score`

**Returns:**
```python
{
    'direction': 'BUY'|'SELL'|'HOLD',
    'score': float,
    'reasons': str,
    'snapshot': {macd, rsi, stoch_k, stoch_d, ema9_gt_ema21, adx, atr, bb_position, candles?, regime?, div_radar?},
    'components': [{name, direction, weight, stage?}, ...]
}
```

### `_bb_pos(price, upper, lower) -> float`
Bollinger Band position: `(price - lower) / (upper - lower)`. Clamped 0.0–1.0.

### `merge_mtf(signals: dict) -> dict`
Merges per-timeframe signals into a single direction.

**Timeframe weights:** `{'30m': 1.0, '1h': 1.5, '4h': 2.0}` (1d used for regime only).

**Algorithm:**
1. Extract daily regime (or market regime if available)
2. Weighted sum of per-TF directions (-1/0/+1)
3. `merged > 0.4` → BUY, `merged < -0.4` → SELL
4. **Regime filter:** BUY blocked if regime=SELL, SELL blocked if regime=BUY → forced to HOLD

**Returns:** `{merged_direction, merged_score, regime, regime_detail?}`

### `build_score_breakdown(signals, merged) -> dict`
Structured breakdown for Telegram display and AI input. Per-timeframe components + regime + merged result.

---

## 12. AI Fusion Engine (ai_fusion.py)

### Data Classes

#### `AIDecision`
Fields: action (ENTER/EXIT/HOLD), side (BUY/SELL/None), confidence (0.0–1.0), setup_quality (0.0–1.0), reasons, warnings, risk_flags, source (local/claude/openai), raw_response, latency_ms.

#### `FusionResult`
Fields: final_action, final_side, final_confidence, policy_used, decisions (list of AIDecision), consensus_notes, was_overridden.

### `_build_prompt(features) -> str`
Constructs a market data prompt for AI providers. Includes:
- Symbol, merged direction/score, regime
- Per-timeframe: direction, score, ADX, RSI, ATR, MACD, Stochastic, BB position, EMA, candle patterns

### `_parse_ai_response(text, source) -> AIDecision`
Parses JSON from AI response. Robust handling:
- Strips markdown code blocks (```json ... ```)
- Falls back to HOLD on parse error

### AI Providers

#### `_call_claude(features) -> AIDecision`
Calls Anthropic API using `CLAUDE_MODEL` (default: claude-sonnet-4-20250514).
- Runs sync client in executor to avoid blocking event loop
- Timeout: `AI_TIMEOUT_SECONDS + 5`
- Returns HOLD with warning on failure

#### `_call_openai(features) -> AIDecision`
Calls OpenAI API using `OPENAI_MODEL` (default: gpt-4o-mini), temperature=0.3.
- Same executor pattern as Claude
- Returns HOLD with warning on failure

### `_local_heuristic(features) -> AIDecision`
Deterministic rule-based decision. Always available, no API needed.

**Base confidence:** `0.50 + |merged_score| × 0.15`

**Modulations:**
| Factor | Adjustment | Condition |
|--------|-----------|-----------|
| ADX strong trend | +0.10 | avg_adx >= ADX_STRONG_TREND(40) |
| ADX weak trend | -0.10 | avg_adx < ADX_TREND_MIN(20) |
| BB favorable | +0.05 | BUY near lower / SELL near upper |
| BB unfavorable | -0.08 | BUY near upper / SELL near lower |
| RSI overbought + BUY | -0.10 | avg_rsi > 75 |
| RSI oversold + SELL | -0.10 | avg_rsi < 25 |

**Decision logic:**
- `ENTER BUY` if direction=BUY AND score > SIGNAL_SCORE_MIN AND confidence >= AI_CONFIDENCE_MIN
- `EXIT SELL` if direction=SELL AND score < -SIGNAL_SCORE_MIN AND confidence >= AI_CONFIDENCE_MIN
- `HOLD` otherwise

Setup quality: `|merged_score| / 2`

### `_fuse_decisions(local, remotes, policy) -> FusionResult`
Combines all decisions according to the configured policy:

| Policy | Behavior |
|--------|----------|
| `local_only` | Use local heuristic only. Remotes ignored. |
| `advisory` | Local decides. Remote results logged but don't override. |
| `majority` | Action with most votes wins (2/3 or 3/3). Ties → HOLD. Confidence = average of winning voters. |
| `strict_consensus` | All sources must agree on action. Any disagreement → HOLD (confidence 0.3). |

### `_log_decision(pair, result)`
Writes decision to `ai_decisions` table with all reasons, warnings, risk_flags aggregated.

### `decide(features) -> FusionResult`
Main async entry point:
1. Run local heuristic (sync, always)
2. If `FEATURE_AI_FUSION=true` AND policy != `local_only`: fire Claude + OpenAI concurrently via `asyncio.gather()`
3. Apply timeout (`AI_TIMEOUT_SECONDS + 5`)
4. Fuse all decisions according to policy
5. Log to DB

---

## 13. AI Decider Wrapper (ai_decider.py)

Thin backward-compatibility layer.

### `decide_async(features) -> dict`
Async wrapper around `ai_fusion.decide()`. Returns:
```python
{'decision': str, 'confidence': float, 'notes': str, 'side': str|None, 'fusion': dict}
```

### `decide(features) -> dict`
Sync fallback using `_local_heuristic()` only. For non-async contexts.

---

## 14. Risk Management (risk.py)

### Basic Queries

#### `realized_pnl_today() -> float`
Sum of PnL for all closed trades in the last 24 hours.

#### `open_trade_count() -> int`
Count of trades with status='OPEN'.

#### `trade_count_today() -> int`
Count of trades opened in the last 24 hours.

#### `last_trade_ts(pair=None) -> int`
Unix timestamp of the most recent trade (optionally filtered by pair).

#### `consecutive_losses(pair=None) -> int`
Number of consecutive losing trades (from most recent, looking back up to 20).

### Entry Gate — `can_enter_enhanced(pair, side, signal_snapshot=None) -> tuple(bool, str)`

**10-gate risk filter.** Every trade must pass all gates. Blocked trades are logged to `blocked_trades` table.

| Gate | Check | Block Condition |
|------|-------|-----------------|
| 1. Kill Switch | `SETTINGS.KILL_SWITCH` | If True |
| 2. Open Trades | `open_trade_count()` | >= `MAX_OPEN_TRADES` |
| 2.5. Portfolio Exposure | `portfolio_exposure_check()` | Total exposure >= `CAPITAL_USD × MAX_PORTFOLIO_EXPOSURE` |
| 3. Daily Loss | `realized_pnl_today()` | <= `-DAILY_LOSS_LIMIT_USD` |
| 4. Daily Trade Count | `trade_count_today()` | >= `MAX_DAILY_TRADES` |
| 5. Cooldown | `is_in_cooldown(pair)` | Elapsed since last trade < `COOLDOWN_AFTER_TRADE_SECONDS` |
| 6. Consecutive Losses | `is_consecutive_loss_paused()` | >= `CONSECUTIVE_LOSS_COOLDOWN` losses, within pause window |
| 7. Duplicate Trade | `is_duplicate_trade(pair, side)` | Same pair+side already open |
| 8. Correlation Risk | `check_correlation_risk(pair, side)` | >= `MAX_CORRELATED_EXPOSURE` positions with correlation >= `CORRELATION_THRESHOLD` |
| 9. Drawdown Halt | `drawdown_position_scale()` | Returns 0.0 (drawdown >= `DRAWDOWN_HALT_THRESHOLD`) |
| 10. Dry Run | `SETTINGS.DRY_RUN_MODE` | Allowed but flagged |

### `can_enter(max_open_trades, daily_loss_limit) -> bool`
Legacy simplified gate (backward compatibility). Only checks gates 2 and 3.

### Cooldown Functions

#### `is_in_cooldown(pair=None) -> tuple(bool, str)`
True if less than `COOLDOWN_AFTER_TRADE_SECONDS` since last trade on this pair.

#### `is_consecutive_loss_paused() -> tuple(bool, str)`
True if `consecutive_losses() >= CONSECUTIVE_LOSS_COOLDOWN` and within `CONSECUTIVE_LOSS_PAUSE_SECONDS` window.

#### `is_duplicate_trade(pair, side) -> bool`
True if an OPEN trade exists with same pair and side.

### Position Sizing

#### `position_size(price, atr_value) -> float`
Base position size: `(RISK_PER_TRADE × CAPITAL_USD) / (ATR × ATR_SL_MULTIPLIER)`.

#### `confidence_scaled_position_size(price, atr_value, confidence, setup_quality, remaining_capital) -> float`
Enhanced sizing with 4 scaling factors:
1. **Confidence factor**: Normalized `[AI_CONFIDENCE_MIN → 1.0]` mapped to `[CONFIDENCE_SCALE_MIN → CONFIDENCE_SCALE_MAX]`
2. **Quality bonus**: `min(1.2, 1.0 + setup_quality × 0.2)`
3. **Drawdown scale**: `drawdown_position_scale()` (0.0–1.0)
4. **Capital caps**: min of `CAPITAL_PER_TRADE_PCT × CAPITAL_USD / price` and `remaining_capital / price`

### Stop Loss & Take Profit

#### `atr_stop_loss(entry_price, atr_value, side) -> float`
SL at `entry ± (ATR × ATR_SL_MULTIPLIER)`. Direction-aware.

#### `atr_take_profit(entry_price, atr_value, side) -> float`
TP at `entry ± (ATR × TP_ATR_MULTIPLIER)`.

### Break-Even Logic

#### `should_move_to_break_even(entry_price, current_price, atr_value, side) -> bool`
True if price moved `BREAK_EVEN_ATR_MULTIPLIER × ATR` in favorable direction.

### Portfolio Exposure

#### `portfolio_exposure_check() -> tuple(can_trade, current_exposure_usd, remaining_usd)`
Sums `qty × entry` for all OPEN trades. Compares against `CAPITAL_USD × MAX_PORTFOLIO_EXPOSURE`.

### Setup Quality Filter

#### `should_skip_weak_setup(setup_quality, risk_flags, confidence) -> tuple(bool, str)`
Rejects weak setups:
- `setup_quality < MIN_SETUP_QUALITY` → skip
- `len(risk_flags) > MAX_RISK_FLAGS` → skip
- `confidence < AI_CONFIDENCE_MIN` → skip

### ATR-Based Trailing Stops

#### `compute_atr_trailing_stop(entry_price, current_price, atr_value, side, current_trail_stop=None) -> dict`
Dynamic trailing stop that **tightens as profit grows**.

| Phase | Condition | Trail Distance |
|-------|-----------|---------------|
| Inactive | profit < `TRAILING_ACTIVATION_ATR(1.0)` ATR | No trail |
| Active (wide) | profit >= activation, < `TRAILING_TIGHTEN_AFTER_ATR(2.0)` ATR | `TRAILING_ATR_MULTIPLIER(2.5)` × ATR |
| Active (tight) | profit >= tighten threshold | `TRAILING_TIGHTEN_MULTIPLIER(1.5)` × ATR |

**Ratchet behavior:** Trail stop can only move in the favorable direction (up for buys, down for sells). Never widens.

**Returns:**
```python
{'active': bool, 'trail_stop': float|None, 'distance_atr': float, 'profit_atr': float, 'tightened': bool}
```

#### `is_atr_trail_triggered(current_price, trail_stop, side) -> bool`
True if price has breached the trailing stop (price <= trail for BUY, price >= trail for SELL).

### Correlation-Aware Risk

#### `get_correlation(pair_a, pair_b) -> float`
Computes Pearson correlation of returns between two pairs.
- Fetches `CORRELATION_LOOKBACK_BARS(50)` bars on `CORRELATION_TIMEFRAME(1h)`
- Uses `pct_change()` returns, requires minimum 10 aligned data points
- Returns 0.0 on error or insufficient data

#### `check_correlation_risk(pair, side) -> tuple(bool, str, list)`
Checks if entering this pair would create excessive correlated exposure.
- Gets all distinct pairs with OPEN trades
- Computes correlation with each
- Blocks if `>= MAX_CORRELATED_EXPOSURE(2)` positions have `abs(corr) >= CORRELATION_THRESHOLD(0.75)`
- Returns correlated pair list with correlation values

### Equity & Drawdown Tracking

#### `get_equity_status() -> dict`
Calculates real-time equity status:
- **Equity** = `CAPITAL_USD` + all realized PnL + unrealized PnL (live price lookup)
- **Peak equity** persisted in `bot_state` table (key: `peak_equity`), auto-updated on new highs
- **Drawdown %** = `(peak - equity) / peak`
- **Max drawdown** persisted in `bot_state` (key: `max_drawdown_pct`)

**Returns:**
```python
{
    'equity': float, 'peak_equity': float,
    'drawdown_usd': float, 'drawdown_pct': float,
    'max_drawdown_pct': float,
    'realized_pnl': float, 'unrealized_pnl': float
}
```

#### `drawdown_position_scale() -> float`
Position size multiplier based on current drawdown:

| Drawdown | Scale Factor |
|----------|-------------|
| < `DRAWDOWN_SCALE_THRESHOLD(10%)` | 1.0 (full size) |
| 10% – 25% | Linear from `DRAWDOWN_SCALE_FACTOR(0.50)` → 0.0 |
| >= `DRAWDOWN_HALT_THRESHOLD(25%)` | 0.0 (halt all trading) |

---

## 15. Trade Executor (trade_executor.py)

### `open_trade(pair, side, qty, price, reason, mode, entry_snapshot) -> int`
Creates a new trade record in DB with status='OPEN', lifecycle='open', trade_type='auto'.
- PostgreSQL: uses `RETURNING id`
- SQLite: uses `last_insert_rowid()`

### `close_trade(trade_id, exit_price, reason, exit_snapshot) -> float`
Closes a trade by ID. Calculates PnL:
- BUY: `(exit - entry) × qty`
- SELL: `(entry - exit) × qty`
Updates: exit_price, pnl, status='CLOSED', lifecycle='closed', ts_close.

### `close_all_for_pair(pair, reason) -> int`
Closes all OPEN trades for a pair. Returns count closed.
Handles both `BASE/QUOTE` and `BASEQUOTE` pair formats.

### `update_trade_lifecycle(trade_id, lifecycle)`
Updates lifecycle state. Valid states: pending, open, protected, trailing, closed, blocked.

### `get_open_trades_for_pair(pair) -> list[dict]`
Returns all open trades as list of dicts with: id, side, qty, entry, ts_open.

### `execute_autonomous_trade(pair, side, qty, price, sl_price, tp_price, reason, entry_snapshot) -> dict`
Full trade execution pipeline:
1. **Dry run check** — if `DRY_RUN_MODE`, log and return mock success
2. **Create DB record** via `open_trade()`
3. **Execute on exchange** via `place_market_order()` — store order_id
4. **Set SL/TP guards** via `set_manual_guard()` for the first admin

**Returns:**
```python
{'success': bool, 'trade_id': int, 'order_id': str, 'mode': 'PAPER'|'LIVE'|'DRY_RUN', 'error': str}
```

On order failure: marks trade as FAILED/blocked in DB.

### `execute_autonomous_exit(pair, reason) -> dict`
Closes all open trades for a pair:
1. Fetch current market price
2. For each open trade: place opposite order (if live), close in DB
3. Clear guards for the pair

**Returns:**
```python
{'success': bool, 'closed_count': int, 'total_pnl': float, 'mode': str, 'errors': list}
```

### Manual Guard Utilities

#### `set_manual_guard(uid, pair, sl, tp, trail_pct) -> int`
UPSERT guard row. Only updates provided fields; preserves others.
If `trail_pct` is set: resets `trail_stop` and `high_watermark` (re-initializes trailing).

#### `clear_manual_guard(uid, pair, which) -> int`
Clears specific guard fields. `which` in `{'sl', 'tp', 'trail', 'all'}`.

---

## 16. Pair Manager (pair_manager.py)

Multi-pair watchlist management. Active when `FEATURE_MULTI_PAIR=true`.

### `get_active_pairs() -> list[str]`
Returns active pair strings. Falls back to `SETTINGS.PAIR` if multi-pair disabled or no pairs found.

### `add_pair(pair, notes) -> tuple(bool, str)`
Validates format → checks limit → checks duplicate → validates on exchange → inserts.
Reactivates if previously deactivated.

### `remove_pair(pair) -> bool`
Sets `is_active=0` (soft delete).

### `toggle_pair(pair, active) -> bool`
Toggle active state.

### `update_pair_signal(pair, direction, score)`
Updates `last_signal_ts`, `last_direction`, `last_score` in DB. Creates row if missing.

### `get_pair_ranking() -> list[dict]`
Active pairs sorted by `ABS(last_score)` descending. Returns: pair, direction, score, last_ts.

### `list_all_pairs() -> list[dict]`
All pairs (active + inactive) with status info.

### `validate_pair(pair) -> tuple(bool, str)`
Calls `exchange.get_client().load_markets()` to verify pair exists on exchange.

### `get_best_tradable_pairs(max_pairs=None) -> list[dict]`
Filtered + ranked pairs for autonomous trading:
- Excludes HOLD signals
- Excludes stale signals (older than `2 × ANALYSIS_INTERVAL_SECONDS`)
- Excludes pairs with duplicate open trades
- Respects `MAX_PAIRS_PER_CYCLE`

### `seed_default_pair()`
Ensures `SETTINGS.PAIR` exists in `trading_pairs` table (called at startup).

---

## 17. Scheduler & Main Loop (scheduler.py)

APScheduler-based job orchestration via `python-telegram-bot[job-queue]`.

### Job Locking

#### `_with_lock(name, coro)`
Prevents concurrent execution of the same job. Uses in-memory `_running_jobs` set.

### Helper Functions

#### `_is_autotrade_enabled() -> bool`
Checks if any admin user has `autotrade_enabled=1`.

#### `_compute_signals(pair=None) -> dict`
Fetches OHLCV for all timeframes, runs `tf_signal()` on each, merges via `merge_mtf()`, builds score breakdown.

#### `_format(features, dec) -> str`
Formats signal + AI decision for Telegram display. Includes: pair, regime, merged direction/score, AI decision/confidence, fusion notes, ADX/ATR.

#### `_analyze_pair(app, pair) -> dict`
Full analysis pipeline for a single pair: signals → AI decision → format → update watchlist.

### Autonomous Execution Engine

#### `_execute_autonomous_cycle(app, pair_results) -> list[str]`
Processes all analyzed pairs in priority order:

**Phase 1: Process EXITs** (free capital/slots)
- For each EXIT decision: `execute_autonomous_exit(pair, 'AI_EXIT')`
- Log signal to `signals` table

**Phase 2: Rank ENTER candidates**
- Sort by `confidence × |merged_score|` descending

**Phase 3: Execute top candidates** (up to `MAX_PAIRS_PER_CYCLE`)
For each candidate:
1. Extract setup_quality and risk_flags from fusion
2. `should_skip_weak_setup()` → filter
3. `can_enter_enhanced()` → risk gate
4. `portfolio_exposure_check()` → capital available?
5. Fetch live market price
6. Get ATR from 1h snapshot
7. `confidence_scaled_position_size()` → position size (includes drawdown scaling)
8. `atr_stop_loss()` + `atr_take_profit()` → SL/TP levels
9. Build entry snapshot (includes `atr_at_entry` for trailing stops)
10. `execute_autonomous_trade()` → execute

Returns action log (list of strings).

### Main Cycle

#### `run_cycle_once(app, notify=True, pair=None) -> str`
- **Single pair** (manual /signal): analyze only, no execution
- **Multi-pair cycle**:
  1. Analyze ALL active pairs
  2. Build signal summary
  3. If autotrade ON: `_execute_autonomous_cycle()` + append equity/drawdown status line
  4. If autotrade OFF: signal report only
  5. Notify all registered users

### Background Jobs

#### `_health_check_job(app)`
Runs exchange `health_check()`. Stores result in `bot_state`. Sends Telegram alert on failure.

#### `_daily_report_job(app)`
Sends daily performance report to all admins.

### `schedule_jobs(app)`
Registers 3 repeating jobs on the APScheduler job queue:

| Job | Interval | First Run | Lock |
|-----|----------|-----------|------|
| `analysis_cycle` | `ANALYSIS_INTERVAL_SECONDS(600)` | 5s | Yes |
| `health_check` | `HEALTH_CHECK_INTERVAL_SECONDS(3600)` | 60s | Yes |
| `daily_report` | 86400s (24h) | 3600s | No |

---

## 18. Telegram Bot (telegram_bot.py)

Full interactive Telegram interface with inline keyboards.

### Global State
- `PAIR_TXT` / `PAIR_DB` — Current trading pair in both formats
- `LAST_NOTIFY` — Dedup cache for auto-exit notifications (300s cooldown)
- `PENDING_INPUT` — Per-user input state for SL/TP/trail value entry

### Keyboard Layouts

#### `main_menu_keyboard()`
```
[Signal] [Price]
[Status] [Settings]
[Guards] [Check Guards]
[AutoTrade] [Mode]
[Risk] [Sell Now]
[Reports] [Pairs]
[Admin]
```

#### `autotrade_keyboard()` — Enable/Disable + Back
#### `mode_keyboard()` — Paper/Live + Back
#### `risk_keyboard()` — $25/$50/$100/$200 presets + Back
#### `guards_set_keyboard()` — Set SL/TP/Trail + Cancel submenu + Back
#### `cancel_keyboard()` — Cancel SL/TP/Trail/All
#### `reporting_keyboard()` — Positions/PnL/Trades/Blocked/Full Report
#### `pairs_keyboard()` — List/Ranking/Add/Remove
#### `admin_keyboard()` — Health/AI/Kill Switch

### Utility Functions

#### `_drawdown_bar(dd_pct) -> str`
Visual drawdown indicator:
- < 5%: `[OK]`
- < 10% (DRAWDOWN_SCALE_THRESHOLD): `[LOW]`
- < 25% (DRAWDOWN_HALT_THRESHOLD): `[SCALING DOWN]`
- >= 25%: `[HALTED]`

#### `admin_only(uid) -> bool`
Checks if user is in `TELEGRAM_ADMIN_IDS`.

#### `_get_admin_id() -> int|None`
Returns first admin ID.

#### `_fetch_last_price() -> float|None`
Fetches current price via CCXT. Falls back through ticker keys: last, close, bid, ask.

#### `_load_guard(uid, pair) -> dict|None`
Loads manual guard settings from DB.

#### `_save_trailing(uid, pair, trail_stop, high_wm)`
Updates trail_stop and high_watermark in `manual_guards`.

#### `_paper_close_all(pair, px) -> tuple(closed, total_pnl)`
Paper-mode trade closing. Calculates PnL from current price.

### ATR Trailing Stop Check

#### `_check_atr_trailing_stops(pair, price) -> str|None`
Checks ATR-based trailing stops for all open trades on a pair:
1. Loads all OPEN trades for pair
2. Extracts `atr_at_entry` from entry_snapshot JSON
3. Loads current trail stop from `bot_state` (key: `atr_trail_{trade_id}`)
4. Computes new trail via `compute_atr_trailing_stop()`
5. Persists updated trail stop
6. Returns exit reason if triggered, or None
7. Updates trade lifecycle to 'trailing' if trail is active

### Auto-Exit Task

#### `auto_exit_task(application)`
Runs every `GUARD_CHECK_INTERVAL_SECONDS(30)`. Two-layer check:

**Layer 1: Manual guards** (SL/TP/Trail%)
- Fixed SL: exit if `price <= sl`
- Fixed TP: exit if `price >= tp`
- Trailing %: updates `high_watermark`, calculates trail_stop as `hwm × (1 - trail_pct)`, exits if breached

**Layer 2: ATR trailing stops** (for autonomous trades)
- `_check_atr_trailing_stops()` — dynamic, tightening trail

On trigger: closes all trades for pair, sends Telegram notification.

### Command Handlers

| Command/Callback | Function | Description |
|-----------------|----------|-------------|
| `/start` | `start()` | Register user, show main menu |
| `/menu` | `menu_cmd()` | Show main menu |
| `/help` | `help_cmd()` | Show command list |
| `/status` or `cmd_status` | `_do_status()` | Bot status: equity, drawdown, exposure, open trades, today's PnL, AI policy, trailing/correlation status |
| `/settings` or `cmd_settings` | `_do_settings()` | Show current config: pair, timeframes, paper mode, ADX/ATR/confidence thresholds |
| `/signal` or `cmd_signal` | `_do_signal()` | Run full analysis cycle for current pair |
| `/price` or `cmd_price` | `_do_price()` | Fetch and display current price |
| `/guards` or `cmd_guards` | `_do_guards()` | Display current SL/TP/trail settings |
| `cmd_checkguards` | `checkguards()` | Run analysis + guard check |
| `/autotrade on\|off` | `autotrade()` | Enable/disable autonomous trading (admin only) |
| `/mode paper\|live` | `mode()` | Switch trading mode (admin only, live requires approval) |
| `/risk daily <usd>` | `risk()` | Set daily loss limit |
| `/sl <price>` | via text handler | Set stop-loss |
| `/tp <price>` | via text handler | Set take-profit |
| `/trail <pct>` | via text handler | Set trailing stop percentage |
| `/cancel sl\|tp\|trail\|all` | via callback | Clear guard(s) |
| `/sellnow` | via callback | Emergency close all trades (admin only) |
| `cmd_positions` | reports | Show open positions with unrealized PnL |
| `cmd_pnl` | reports | 30-day performance report |
| `cmd_trades` | reports | Recent 10 closed trades |
| `cmd_blocked` | reports | Blocked trades last 7 days |
| `cmd_report` | reports | Full report (PnL + daily) |
| `cmd_pairs` | pair_manager | Show watchlist |
| `cmd_ranking` | pair_manager | Pair ranking by signal strength |
| `prompt_addpair` | pair_manager | Add pair to watchlist |
| `prompt_rmpair` | pair_manager | Remove pair from watchlist |
| `cmd_health` | validators | Run all startup checks |
| `cmd_ai` | DB query | Show last AI decision |
| `cmd_killswitch` | config toggle | Toggle kill switch (admin only) |

### `text_input_handler(update, context)`
Handles free-text input for SL/TP/trail values and pair add/remove. Uses `PENDING_INPUT` state machine.

### `build_app() -> Application`
Constructs the Telegram bot application:
1. Creates `ApplicationBuilder` with `TELEGRAM_BOT_TOKEN`
2. Optionally configures HTTPS proxy
3. Registers all command handlers and callback query handler
4. Returns configured Application

---

## 19. Notifications (notifier.py)

Centralized async Telegram notification helpers.

### `notify_admins(app, text)`
Broadcasts message to all `TELEGRAM_ADMIN_IDS`.

### `notify_trade_opened(app, pair, side, qty, price, reason)`
Formatted trade-opened notification.

### `notify_trade_closed(app, pair, side, pnl, reason)`
Formatted trade-closed notification with +/- PnL prefix.

### `notify_blocked_trade(app, pair, side, reason)`
Alert when a trade is blocked by risk gates.

### `notify_health_issue(app, issue)`
Health warning notification.

### `notify_daily_report(app, report)`
Daily performance report broadcast.

---

## 20. Reports & Analytics (reports.py)

### Trade Queries

#### `get_open_trades(pair=None) -> list[tuple]`
All open trades. Returns: id, pair, side, qty, entry, ts_open.

#### `get_recent_closed(n=5, pair=None) -> list[tuple]`
Last N closed trades. Returns: id, pair, side, qty, entry, exit_price, pnl, ts_close.

#### `daily_pnl_sum() -> float`
Sum of realized PnL from trades closed in last 24 hours.

### `performance_summary(pair=None, days=30) -> dict`
Comprehensive performance metrics:
```python
{
    'total_trades': int, 'winning': int, 'losing': int,
    'win_rate': float (%),
    'total_pnl': float, 'avg_win': float, 'avg_loss': float,
    'expectancy': float,  # (win_rate × avg_win) + ((1-win_rate) × avg_loss)
    'profit_factor': float,  # total_wins / total_losses
    'largest_win': float, 'largest_loss': float
}
```

### Formatted Reports

#### `format_position_report() -> str`
Open positions with live price lookup and unrealized PnL per trade.

#### `format_pnl_report(pair=None, days=30) -> str`
Full performance report: trades, win rate, PnL, avg win/loss, expectancy, profit factor, best/worst.

#### `daily_report(pair=None) -> str`
Daily summary: PnL today, trades closed, open positions, **equity/drawdown snapshot**.

#### `blocked_trades_summary(days=7) -> str`
Recent blocked trades with reasons.

#### `format_trades_brief(rows, kind) -> str`
Short-format trade list (up to 10).

#### `export_trades_csv(filepath, pair=None) -> str`
CSV export of all trades.

### `save_performance_snapshot(pair=None, period='daily')`
Persists current performance summary to `performance_snapshots` table.

---

## 21. Startup Validation (validators.py)

### `validate_config(settings) -> list[(level, message)]`
~15 configuration checks:
- **Errors**: Missing TELEGRAM_BOT_TOKEN/ADMIN_IDS, empty EXCHANGE, invalid PAIR format, CAPITAL_USD <= 0, live mode without API keys
- **Warnings**: RISK_PER_TRADE outside 0.001–0.20, MAX_OPEN_TRADES < 1, unknown AI_FUSION_POLICY, AI fusion enabled without API keys, unsupported timeframes

### `validate_exchange(settings) -> tuple(bool, str)`
Calls `fetch_ticker()` for the configured pair. Returns OK with price or error.

### `validate_telegram(settings) -> tuple(bool, str)`
Calls Telegram `getMe` API. Returns bot username on success.

### `validate_db(settings) -> tuple(bool, str)`
Initializes DB, counts users. Returns OK with user count.

### `run_all_checks(settings) -> str`
Runs all validators, returns formatted report with: time, mode, pair, features, and per-check results.

---

## 22. Entry Point (main.py)

Contains both the original `KrakenWrap` class (legacy) and the bot entry point.

### `KrakenWrap` class (legacy)
Original exchange wrapper with paper trading support. Methods: `fetch_ohlcv()`, `paper_buy()`, `paper_sell()`.
Replaced by `exchange.py` in current architecture but kept for backward compatibility.

### `load_config() -> dict`
Legacy config loader from env vars. Superseded by `config.py` Settings dataclass.

### Boot sequence (via `telegram_bot.build_app()`)
1. Load `.env`
2. Initialize database (`storage.init_db()`)
3. Run validators (`validators.run_all_checks()`)
4. Seed default pair (`pair_manager.seed_default_pair()`)
5. Build Telegram application
6. Register command handlers
7. Schedule background jobs
8. Start polling

---

## 23. Deployment & Scripts

### `Procfile` (Heroku)
```
worker: python -c "from telegram_bot import build_app; build_app().run_polling()"
```

### `scripts/bootstrap.sh`
Creates Python venv, installs requirements, copies `.env.example`.

### `scripts/run_paper.sh`
Activates venv, sets `MODE=paper`, runs `main.py`.

### `scripts/run_live.sh`
Activates venv, sets `MODE=live`, runs `main.py`. Requires API keys in `.env`.

### `backup_ai1.sh`
Comprehensive backup: code, DB, `.env`, frozen deps, restore script.

### `systemd/macd_rsi_bot.service`
```ini
Type=simple
WorkingDirectory=/opt/macd_rsi_bot
ExecStart=/opt/macd_rsi_bot/.venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
```

### Audio Alerts
- `audio/calm.wav` — Neutral/hold
- `audio/risk.wav` — Warning/sell
- `audio/trend.wav` — Bullish/buy

### Dependencies (`requirements.txt`)
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

## 24. Environment Variables — Full Reference

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
| `FEATURE_MULTI_PAIR` | `false` | Enable multi-pair watchlist |
| `FEATURE_AI_FUSION` | `false` | Enable dual-AI decision engine |
| `FEATURE_CANDLE_PATTERNS` | `false` | Enable candle pattern detection |
| `FEATURE_HIDDEN_DIVERGENCE` | `false` | Enable hidden divergence detection |
| `FEATURE_MARKET_REGIME` | `false` | Enable market regime classification |

### Exchange
| Variable | Default | Description |
|----------|---------|-------------|
| `EXCHANGE` | `kraken` | CCXT exchange name |
| `PAIR` | `BNB/USDC` | Default trading pair |
| `TIMEFRAMES` | `30m,1h,4h,1d` | Analysis timeframes |
| `CANDLE_LIMIT` | `300` | OHLCV bars to fetch |
| `PAPER_TRADING` | `true` | Paper trading mode |
| `KRAKEN_API_KEY` | | Kraken API key (live mode) |
| `KRAKEN_API_SECRET` | | Kraken API secret (live mode) |

### Multi-Pair
| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_PAIRS` | `BNB/USDC` | Default pair(s) to seed |
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
| `CONSECUTIVE_LOSS_COOLDOWN` | `3` | Consecutive losses before pause |
| `CONSECUTIVE_LOSS_PAUSE_SECONDS` | `3600` | Pause duration after loss streak |
| `BREAK_EVEN_ATR_MULTIPLIER` | `1.0` | ATR multiplier for break-even move |

### Autonomous Trading
| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_PORTFOLIO_EXPOSURE` | `0.50` | Max % of capital exposed |
| `CAPITAL_PER_TRADE_PCT` | `0.10` | Max capital per trade (10%) |
| `MIN_SETUP_QUALITY` | `0.3` | Minimum setup quality to trade |
| `MAX_RISK_FLAGS` | `2` | Max risk flags before skip |
| `CONFIDENCE_SCALE_MIN` | `0.5` | Min confidence scale factor |
| `CONFIDENCE_SCALE_MAX` | `1.0` | Max confidence scale factor |
| `MAX_PAIRS_PER_CYCLE` | `3` | Max new trades per cycle |
| `TP_ATR_MULTIPLIER` | `2.0` | Take profit distance in ATR |

### ATR Trailing Stops
| Variable | Default | Description |
|----------|---------|-------------|
| `TRAILING_ENABLED` | `true` | Enable ATR trailing stops |
| `TRAILING_ATR_MULTIPLIER` | `2.5` | Initial trail distance in ATR |
| `TRAILING_TIGHTEN_AFTER_ATR` | `2.0` | Profit (ATR) before tightening |
| `TRAILING_TIGHTEN_MULTIPLIER` | `1.5` | Tightened trail distance in ATR |
| `TRAILING_ACTIVATION_ATR` | `1.0` | Min profit (ATR) to activate trail |

### Correlation Risk
| Variable | Default | Description |
|----------|---------|-------------|
| `CORRELATION_CHECK_ENABLED` | `true` | Enable correlation gate |
| `CORRELATION_THRESHOLD` | `0.75` | Max allowed correlation |
| `CORRELATION_LOOKBACK_BARS` | `50` | Bars for correlation calculation |
| `CORRELATION_TIMEFRAME` | `1h` | Timeframe for correlation data |
| `MAX_CORRELATED_EXPOSURE` | `2` | Max correlated open positions |

### Drawdown Management
| Variable | Default | Description |
|----------|---------|-------------|
| `DRAWDOWN_TRACKING_ENABLED` | `true` | Enable drawdown management |
| `DRAWDOWN_SCALE_THRESHOLD` | `0.10` | Start reducing size at 10% DD |
| `DRAWDOWN_HALT_THRESHOLD` | `0.25` | Halt trading at 25% DD |
| `DRAWDOWN_SCALE_FACTOR` | `0.50` | Size multiplier at scale threshold |

### Kill Switch / Dry Run
| Variable | Default | Description |
|----------|---------|-------------|
| `KILL_SWITCH` | `false` | Emergency stop all trading |
| `DRY_RUN_MODE` | `false` | Log trades but don't execute |

### Telegram
| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | | Bot token from @BotFather |
| `TELEGRAM_ADMIN_IDS` | | Comma-separated admin user IDs |
| `HTTPS_PROXY` | | Optional HTTPS proxy for Telegram |

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
| `AI_FUSION_POLICY` | `local_only` | Fusion policy |
| `AI_TIMEOUT_SECONDS` | `15` | AI call timeout |

### Indicators / Strategy
| Variable | Default | Description |
|----------|---------|-------------|
| `ATR_PERIOD` | `14` | ATR calculation period |
| `ADX_PERIOD` | `14` | ADX calculation period |
| `ADX_TREND_MIN` | `20.0` | Min ADX for trend (below = HOLD) |
| `ADX_STRONG_TREND` | `40.0` | ADX threshold for strong trend bonus |
| `BB_PERIOD` | `20` | Bollinger Bands period |
| `BB_STD` | `2.0` | Bollinger Bands std deviation |
| `PIVOT_LOOKBACK` | `3` | Pivot detection lookback |
| `ATR_SL_MULTIPLIER` | `1.5` | Stop-loss distance in ATR |

### Candle Patterns
| Variable | Default | Description |
|----------|---------|-------------|
| `CANDLE_WICK_RATIO` | `2.0` | Min wick/body ratio for pattern |
| `CANDLE_BODY_RATIO` | `0.3` | Max body/range ratio for pattern |

### Market Regime
| Variable | Default | Description |
|----------|---------|-------------|
| `REGIME_EMA_FAST` | `20` | Fast EMA for regime detection |
| `REGIME_EMA_SLOW` | `50` | Slow EMA for regime detection |
| `REGIME_ADX_THRESHOLD` | `25.0` | ADX threshold for trending |
| `REGIME_VOLATILITY_LOOKBACK` | `20` | Bars for volatility percentile |

### Scheduler
| Variable | Default | Description |
|----------|---------|-------------|
| `ANALYSIS_INTERVAL_SECONDS` | `600` | Main analysis cycle (10 min) |
| `GUARD_CHECK_INTERVAL_SECONDS` | `30` | Guard check interval |
| `HEALTH_CHECK_INTERVAL_SECONDS` | `3600` | Health check interval (1 hr) |

### Payments (Optional)
| Variable | Default | Description |
|----------|---------|-------------|
| `PAYMENT_PROVIDER` | | Payment provider name |
| `STRIPE_SECRET_KEY` | | Stripe API key |

### Live Control
| Variable | Default | Description |
|----------|---------|-------------|
| `LIVE_TRADE_ALLOWED_IDS` | | User IDs allowed for live mode |
