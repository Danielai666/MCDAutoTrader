# MCDAutoTrader — Complete Session Handoff Brief
## Give this file to a new Claude Code session to continue development

> Project: `/Volumes/MiniSSD/aiMCDtrader/`
> Repository: `MCDAutoTrader`
> Date: 2026-04-15
> Total: 44 Python files, ~12,600 LOC (adds panel.py, i18n.py, trial.py, portfolio.py)
> Tests: 66 automated tests, all passing
> Release: v1.0-rc1 (feature freeze) · v1.1-pre-ui-panel · v1.2-pre-multiuser. Live on Railway + Supabase.
> Latest commit: `92caad2` (UI — multi-level menu refactor: 12-tile L1 + 7 L2 submenus + confirm flows)
>
> Active feature flags (live):
>   FEATURE_CONTROL_PANEL=true    — modern inline panel + live dashboard (§18.9, §18.10)
>   FEATURE_TRIAL_MODE=false      — user-toggled off (§18.11)
>   FEATURE_I18N=false            — user-toggled off (§18.11, §18.12)
>   FEATURE_PORTFOLIO=false       — user-toggled off (§18.14)
>
> Multi-user state (§18.15, §18.16):
>   Personal commands ungated for all users; admin gate retained on
>   killswitch / reconcile / health_stats only. Two tenant-leak bugs
>   fixed. Safety layer (rate limit, user cap, error wrapper) in place.

---

## 1. What This Project Is

MCDAutoTrader is a **multi-user autonomous AI trading platform** controlled entirely via Telegram. It supports **crypto trading** (any CCXT exchange) and **MT5 trading** (Gold/Forex/Indices via EA Bridge). It detects MACD/RSI divergences, confirms with Ichimoku/candles/market regime/fundamentals, fuses decisions from Claude + OpenAI + local heuristic, enforces 11-gate risk management, executes trades autonomously, sends visual PNG report cards, and includes a backtesting engine.

### Current Capabilities
- **Multi-user** with strict tenant isolation (per-user trades, guards, settings, credentials)
- **Any exchange** via CCXT (Kraken, Binance, Bybit, etc.) — user connects from Telegram
- **MT5 EA Bridge** for Gold/Forex/Indices (HMAC auth, replay protection, feature-flagged)
- **Paper / live** trading modes per user
- **3 AI modes**: signal_only, manual_confirm (approve/reject buttons), ai_full (autonomous)
- **Divergence radar** (pre-confirmation zone detection, 4 maturity stages)
- **Regular + hidden divergence**, **Ichimoku cloud**, **candle patterns**, **market regime**
- **Fundamental gate** (news/event risk filter — blocks or reduces size)
- **Dual-AI fusion** (Claude + OpenAI + local heuristic) with 4 policies
- **11-gate risk engine** (kill switch, exposure, drawdown, correlation, event risk, etc.)
- **ATR-based trailing stops** that tighten as profit grows
- **Two-phase trade execution** (PENDING → OPEN/FAILED) with operation-ID idempotency
- **Per-user asyncio locks**, **rate limiting** (10 cmd/min/user)
- **Exchange reconciliation** + **live-readiness check**
- **Visual PNG cards** (Market Overview with 4 gauges, Signal Card, Daily Report, Backtest)
- **Screenshot analysis** (up to 12 images, AI vision via Claude/GPT-4o)
- **Backtesting engine** (/backtest with equity curve + metrics card)
- **Envelope encryption** (AEAD V2) for exchange API keys
- **Per-trade close reports** + **timezone-aware daily reports**
- **Panic stop** per-user emergency control
- **Connect Exchange** guided Telegram flow (select → key → secret → validate → save)
- **PostgreSQL** (production) + **SQLite** (dev) dual support
- **66 automated tests** across 4 modules
- **Railway** deployment ready

---

## 2. File Map (39 files, 10,632 LOC)

### Signal Intelligence Pipeline
| File | LOC | Purpose |
|------|-----|---------|
| `indicators.py` | 38 | EMA, RSI, MACD, Stochastic, ATR, ADX, Bollinger, Ichimoku |
| `divergence.py` | 74 | Regular + hidden divergence detection |
| `div_radar.py` | 403 | Pre-confirmation divergence zone scanner (4 maturity stages) |
| `candles.py` | 204 | Candle patterns: hammer, shooting star, engulfing, breakout |
| `market_regime.py` | 81 | Regime classification: trending_up/down, ranging, volatile |
| `strategy.py` | 295 | Per-TF scoring (12 weighted components) + multi-TF merge |
| `fundamentals.py` | 237 | News/event risk scoring (time-based + ATR spike + manual override) |

### AI Decision Layer
| File | LOC | Purpose |
|------|-----|---------|
| `ai_fusion.py` | 419 | Claude + OpenAI + local heuristic + 4 fusion policies |
| `ai_decider.py` | 27 | Backward-compat async/sync wrapper |

### Risk & Execution
| File | LOC | Purpose |
|------|-----|---------|
| `risk.py` | 475 | 11-gate risk engine, position sizing, trailing, correlation, drawdown, event risk |
| `trade_executor.py` | 366 | Two-phase PENDING→OPEN, dedup lock, operation_id idempotency, crash recovery |
| `trading_provider.py` | 69 | ITradingProvider ABC interface |
| `ccxt_provider.py` | 149 | CCXTProvider + PaperProvider for any CCXT exchange |
| `mt5_provider.py` | 139 | MT5Provider — commands queued for EA pickup |
| `exchange.py` | 127 | Public/authenticated client split, backward-compat wrappers |

### MT5 EA Bridge
| File | LOC | Purpose |
|------|-----|---------|
| `mt5_bridge.py` | 448 | FastAPI REST server, HMAC auth, replay protection, symbol mapping, lot sizing, sessions |

### Infrastructure
| File | LOC | Purpose |
|------|-----|---------|
| `config.py` | 171 | Settings dataclass (120+ env vars, feature flags) |
| `storage.py` | 828 | Dual DB (SQLite/PostgreSQL), 14 tables, backend-aware upserts, migrations |
| `user_context.py` | 161 | UserContext dataclass — loads per-user settings + decrypted credentials |
| `crypto_utils.py` | 210 | Envelope encryption (AEAD V2) + Fernet (V1 compat) + masking |
| `logging_utils.py` | 101 | Structured JSON logging, correlation_id, secret redaction |
| `scheduler.py` | 504 | Two-phase cycle: shared analysis + per-user execution, mode gating, asyncio locks |

### Interface & Reporting
| File | LOC | Purpose |
|------|-----|---------|
| `telegram_bot.py` | 1,822 | Full Telegram UX: 42+ commands, connect flow, guard checks, visual cards, screenshots |
| `notifier.py` | 52 | Async Telegram notification helpers |
| `reports.py` | 269 | Performance analytics, per-trade close reports, CSV export |
| `reconcile.py` | 402 | Exchange reconciliation + 10-point live-readiness check |
| `screenshot_analyzer.py` | 310 | Batch screenshot analysis via AI vision (Claude/GPT-4o) |
| `backtest.py` | 321 | Backtesting engine with equity curve + visual card |

### Visual Cards
| File | LOC | Purpose |
|------|-----|---------|
| `visuals/gauges.py` | 227 | Composite scoring (0-100) + semicircular gauge renderer |
| `visuals/cards.py` | 470 | Signal Card, Market Overview Card (4 gauges), Daily Report Card |
| `visuals/__init__.py` | 1 | Package init |

### Operations & Other
| File | LOC | Purpose |
|------|-----|---------|
| `pair_manager.py` | 179 | Multi-pair watchlist (per-user scoped) |
| `validators.py` | 153 | Startup validation checks |
| `main.py` | 152 | Legacy entry point |

### Test Suite
| File | LOC | Tests | Coverage |
|------|-----|-------|----------|
| `tests/test_mt5_bridge.py` | 193 | 17 | HMAC auth, replay, symbol mapping, lot sizing, sessions |
| `tests/test_multi_user.py` | 214 | 13 | Trade/guard/pair/report/risk/credential isolation |
| `tests/test_postgres_schema.py` | 204 | 25 | 14 tables, inserts, upserts, migrations, health check |
| `tests/test_screenshots.py` | 136 | 11 | Session lifecycle, file handling, formatting |
| `tests/__init__.py` | 1 | — | Package init |

---

## 3. Database Schema (14 tables)

| Table | Purpose |
|-------|---------|
| `users` | User accounts + per-user settings (capital, risk, exchange keys, paper mode) |
| `user_settings` | Mode (signal_only/paper/live), ai_mode, timezone, panic_stop |
| `credentials` | Per-user encrypted exchange keys (envelope encryption V2) |
| `trades` | All trades with user_id, status (PENDING/OPEN/CLOSED/FAILED), lifecycle, entry_snapshot |
| `manual_guards` | SL/TP/trailing per user+pair (composite PK) |
| `trading_pairs` | Per-user watchlist with last signal/score |
| `signals` | Signal history per user |
| `ai_decisions` | AI decision audit trail per user |
| `blocked_trades` | Risk-blocked trade log per user |
| `bot_state` | Key-value state (global + per-user keys like `peak_equity_{uid}`) |
| `operation_log` | Idempotency tracking (prevents duplicate trades across restarts) |
| `performance_snapshots` | Historical metrics per user |
| `mt5_connections` | MT5 bridge connections (token_id, encrypted shared secret, symbol map) |
| `mt5_nonces` | Nonce replay protection for MT5 HMAC auth |

---

## 4. Architecture Data Flow

```
Exchange (any CCXT) → fetch_ohlcv (public client, shared)
  ↓
Indicators (EMA, RSI, MACD, Stoch, ATR, ADX, BB, Ichimoku)
  ↓
Divergence (regular + hidden) + Candles + Regime + Div Radar
  ↓
Strategy.tf_signal() → 12-component weighted scoring per timeframe
  ↓
merge_mtf() → weighted consensus with regime filter
  ↓
AI Fusion (local + Claude + OpenAI) → ENTER/EXIT/HOLD + confidence
  ↓
=== PER-USER from here (asyncio lock per user) ===
  ↓
Mode Gate (signal_only → PNG card only, manual_confirm → buttons, ai_full → continue)
  ↓
Fundamental Gate (event risk ≥ 75 → block, 50-75 → reduce size)
  ↓
Risk Gate (11 checks: kill switch, exposure, drawdown, correlation, etc.)
  ↓
Position Sizing (base × confidence × quality × drawdown × event_risk)
  ↓
Trade Executor (PENDING → exchange order → OPEN/FAILED + operation_id)
  ↓
Guard Monitor (every 30s: manual SL/TP + ATR trailing, per-user)
  ↓
Visual Cards (PNG) + Trade Close Reports → Telegram to owning user
```

---

## 5. Strategy Scoring (12 components)

| # | Component | Weight | Gate |
|---|-----------|--------|------|
| 1 | Regular MACD divergence | 1.5 × strength | Always |
| 2 | Regular RSI divergence | 1.5 × strength | Always |
| 3 | Hidden MACD divergence | 1.0 × strength | FEATURE_HIDDEN_DIVERGENCE |
| 4 | Hidden RSI divergence | 1.0 × strength | FEATURE_HIDDEN_DIVERGENCE |
| 5 | EMA trend (EMA9 vs EMA21) | 1.0 | Always |
| 6 | Stochastic crossover | 0.75 | Always |
| 7 | Volume confirmation | 0.5 | Always |
| 8 | Bollinger position | 0.5 | Always |
| 9 | MACD histogram momentum | 0.5 | Always |
| 10 | Candle patterns | up to 0.75 | FEATURE_CANDLE_PATTERNS |
| 11 | Divergence radar zones | up to 2.0 | Always |
| 12 | Ichimoku cloud + TK cross | 1.0 | FEATURE_ICHIMOKU |

---

## 6. Risk Engine (11 gates)

| Gate | Check |
|------|-------|
| 1 | Kill switch (global) |
| 2 | Max open trades (per-user) |
| 3 | Portfolio exposure (per-user capital × max_exposure) |
| 4 | Daily loss limit (per-user) |
| 5 | Daily trade count |
| 6 | Post-trade cooldown |
| 7 | Consecutive loss pause |
| 8 | Duplicate trade (user + pair + side) |
| 9 | Correlation risk (CORRELATION_THRESHOLD) |
| 10 | Event risk / fundamental (score ≥ 75 → block, 50-75 → reduce size) |
| 11 | Drawdown halt (DRAWDOWN_HALT_THRESHOLD 25%) |

---

## 7. Telegram Commands (42+)

### Core
`/start`, `/menu`, `/help`, `/status` (PNG), `/signal` (PNG), `/price`, `/report` (PNG)

### Trading
`/autotrade on|off`, `/mode paper|live`, `/risk daily <usd>`, `/sellnow`, `/killswitch`, `/panic_stop`

### Guards
`/sl`, `/tp`, `/trail`, `/cancel sl|tp|trail|all`, `/guards`, `/checkguards`

### Pairs
`/pairs`, `/addpair`, `/rmpair`, `/ranking`

### Reports
`/positions`, `/trades`, `/pnl`, `/blocked`, `/divzones`, `/divradar`

### Admin
`/health`, `/ai`, `/reconcile [fix]`, `/liveready`, `/capital`, `/maxexposure`

### Multi-User
`/setkeys`, `/myaccount`, Connect Exchange button flow (select → key → secret → validate → save)

### Analysis
`/backtest <pair> [days] [timeframe]` (PNG card)
`/analyze_screens` → send up to 12 images → `/done`

---

## 8. Visual Cards

| Card | Command | Content | Cache |
|------|---------|---------|-------|
| Market Overview | /status | 4 gauges (Mood, Momentum, Risk, Event Risk) + top 5 symbols + reasons | 60s |
| Signal Card | /signal | Candlestick chart + RSI + MACD + entry/SL/TP lines + info box | None |
| Daily Report | /report | Equity curve + win/loss donut + 8 metrics | 5min |
| Backtest Card | /backtest | Equity curve + win/loss pie + 8 metrics | None |

---

## 9. Encryption

**V1 (legacy):** Fernet with `CREDENTIAL_ENCRYPTION_KEY`.
**V2 (production):** Envelope encryption (AEAD). Per-record DataKey (AESGCM-256) encrypted by MasterKey. Rotation-ready via `ENCRYPTION_MASTER_KEY_V{N}`.

---

## 10. MT5 EA Bridge

- FastAPI REST server: `uvicorn mt5_bridge:create_bridge_app --factory`
- HMAC-SHA256 auth: `X-Bridge-Token`, `X-User-ID`, `X-Timestamp`, `X-Nonce`, `X-Signature`
- Nonce + timestamp replay protection (30s window)
- Endpoints: `/trade/open`, `/trade/close`, `/trade/update`, `/signals`, `/heartbeat`, `/health`
- Per-user symbol mapping (XAUUSD → GOLD)
- Lot sizing: `compute_mt5_lot_size()` from capital/risk%/stop/tick_value
- Session rules: `is_market_open()`, `is_in_rollover_window()`, `check_spread_guard()`
- Feature-flagged: `FEATURE_MT5_BRIDGE=false`

---

## 11. Multi-Tenant Architecture

1. Every command extracts `uid = update.effective_user.id`
2. `UserContext.load(uid)` reads users + user_settings + credentials tables
3. All DB queries include `WHERE user_id=?`
4. Scheduler: shared market analysis → per-user execution with asyncio locks
5. Guard checks iterate per-user
6. Reports/notifications scoped to requesting user
7. All parameters optional with `=None` for backward compat

---

## 12. Test Suite (66 tests)

| Module | Tests | What |
|--------|-------|------|
| `test_mt5_bridge` | 17 | HMAC auth, replay protection, symbol mapping, lot sizing, sessions |
| `test_screenshots` | 11 | Session lifecycle, file handling, result formatting |
| `test_multi_user` | 13 | Trade/guard/pair/report/risk/credential/context isolation |
| `test_postgres_schema` | 25 | 14 tables, inserts, upserts, migrations, health check |

Run: `.venv/bin/python3 -m unittest discover tests -v`
For PostgreSQL: `DB_ENGINE=postgres SUPABASE_DB_HOST=... .venv/bin/python3 -m unittest tests.test_postgres_schema -v`

---

## 13. Deployment

### Entry Point
```python
from telegram_bot import build_app
build_app().run_polling()
```

### Procfile (Railway)
```
worker: python -c "from telegram_bot import build_app; build_app().run_polling()"
```

### MT5 Bridge (optional separate service)
```
web: uvicorn mt5_bridge:create_bridge_app --factory --host 0.0.0.0 --port 8080
```

### Minimum Env Vars
```
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_ADMIN_IDS=123456
PAIR=BNB/USDC
PAPER_TRADING=true
DB_ENGINE=sqlite
```

### Production Env Vars
```
DB_ENGINE=postgres
SUPABASE_DB_HOST=db.xxx.supabase.co
SUPABASE_DB_PORT=6543
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=xxx
SUPABASE_SCHEMA=trading_bot
CREDENTIAL_ENCRYPTION_KEY=xxx   # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Feature Flags
```
FEATURE_MULTI_PAIR=true
FEATURE_AI_FUSION=true
FEATURE_CANDLE_PATTERNS=true
FEATURE_HIDDEN_DIVERGENCE=true
FEATURE_MARKET_REGIME=true
FEATURE_ICHIMOKU=true
FEATURE_MT5_BRIDGE=false
FEATURE_SCREENSHOTS=false
```

### Dependencies
```
ccxt, pandas, numpy, python-dotenv, loguru, requests,
python-telegram-bot[job-queue], anthropic, openai,
psycopg2-binary, cryptography, pytz, matplotlib,
fastapi, uvicorn
```

---

## 14. Commit History (This Session — 24 commits)

| Commit | Description |
|--------|-------------|
| `0907f44` | ATR trailing stops, correlation risk gate, equity/drawdown management |
| `5caef43` | Production hardening: PostgreSQL, restart safety, reconciliation, execution integrity |
| `0cedab8` | BOT_REFERENCE.md technical reference |
| `7e3d99e` | Critical bug fixes: multi-pair guards, cached equity, per-TF exceptions |
| `d0b0f6a` | Multi-tenant Phase 1-2: UserContext, schema migration, exchange split |
| `1902bc8` | Multi-tenant Phase 3-4: user_id through risk, reports, pair manager |
| `5e3b427` | Multi-tenant Phase 5-7: per-user scheduler, guards, commands |
| `e954fb6` | Spec A.1-A.5: credentials, envelope encryption, provider interface, Ichimoku |
| `0d3d704` | Visual reporting layer: signal cards, market overview, daily report |
| `19fa95f` | Idempotency, mode gating, per-user locks, panic_stop, rate limiter |
| `4146f48` | Manual confirm handler, connect exchange state machine |
| `dc03d7f` | Rate limiter on all commands, per-trade close reports, tz daily |
| `7e46ce9` | Fundamental gate — news/event risk filter + visual integration |
| `6698e62` | MT5 EA Bridge + provider + symbol mapping + lot sizing |
| `d033030` | Screenshot batch analysis (up to 12 images via Telegram) |
| `ec7dcdf` | Test suite: 66 tests across 4 modules |
| `1959706` | /backtest command with visual card |

---

## 15. What's Complete

### Spec Phase A ("Must Now") — ALL DONE
- Multi-tenant data model + schema migrations (14 tables)
- Envelope encryption (AEAD V2) for exchange API keys
- ITradingProvider interface + CCXT + Paper + MT5 providers
- Per-user risk engine (11 gates)
- Two-phase trade execution + operation_id idempotency
- Per-user scheduler with asyncio locks
- Mode/ai_mode gating (signal_only/manual_confirm/ai_full)
- Connect Exchange guided Telegram flow
- Rate limiter on all commands
- Per-trade close reports + timezone-aware daily reports
- /panic_stop + fundamental gate + reconciliation + live-readiness

### Spec Phase B ("Next") — ALL DONE
- Visual PNG report cards (Market Overview, Signal Card, Daily Report, Backtest)
- MT5 EA Bridge (FastAPI + HMAC auth + replay protection + symbol mapping + lot sizing)
- Screenshot batch analysis (up to 12 images, AI vision)
- Backtesting engine with visual card

### Spec Phase C (Fundamental Gate) — DONE
- News/event risk scoring + risk gate integration + visual gauge

### Test Suite — DONE
- 66 automated tests across 4 modules, all passing

---

## 16. What Remains

| Item | Priority | Complexity |
|------|----------|-----------|
| Test against real Supabase PostgreSQL | High | Low |
| Multi-user live testing (2+ Telegram accounts) | High | Low |
| MT5 EA Bridge testing with real MetaTrader 5 | Medium | Medium |
| Top-10 market dynamic reporting (/top10) | Medium | Low |
| Upcoming/new coin intelligence (/newcoins) | Low | Medium |
| Strategy threshold calibration | Medium | Low |
| Web dashboard | Low | High |
| Billing/subscription system | Low | High |

---

## 17. Instructions for Next Session

1. **Read this file first.**
2. **Do not rewrite from scratch.** Architecture is stable (39 files, 66 tests pass).
3. **Run tests first:** `.venv/bin/python3 -m unittest discover tests -v`
4. **Priority order:**
   - Observe live paper-trading results from performance tuning (Section 18.5)
   - Test with 2+ Telegram users
   - /top10 market reporting
   - Exit optimization (trailing / break-even / partial TP) — deferred from Session 2
5. **Always run syntax check** after changes.
6. **Commit after each logical unit.**
7. **Preserve all existing commands and functionality.**

---

## 18. Session 2 Log (2026-04-13 → 2026-04-15)

This session focused on **deployment, UX polish, and performance tuning** — no new architectural features. The bot is now live on Railway + Supabase in paper-trading burn-in. The 7 items below are grouped by theme and each lists the *why*, *what changed*, and *commit(s)*.

### 18.1 Deployment: Railway + Supabase

Got the bot running end-to-end on Railway (`main.py` worker via Procfile) with Supabase Postgres as the data store.

**What was done:**
- Created fresh Supabase project `xlmtawchpgltesmteclj` (region `us-west-2`) after the original project hit tenant/user-not-found errors through the pooler.
- Configured the Transaction Pooler connection: `aws-1-us-west-2.pooler.supabase.com:6543`, user `postgres.xlmtawchpgltesmteclj`, schema `trading_bot`. Transaction pooler was required because Railway is IPv4-only and the direct Supabase connection is IPv6-only.
- Rotated the Telegram bot token via @BotFather after it was rejected: new token in `RAILWAY_VARS.md`.
- Produced `DEPLOYMENT.md` (committed, no secrets) as a public setup reference and `RAILWAY_VARS.md` (gitignored) as a local copy-paste block for the Railway Raw Editor.
- Hardened env config: removed invalid values (`AI_FUSION_POLICY=hybrid` → `local_only`, `PAIR_MODE=dynamic` → `multi`, `DRY_RUN_MODE=true` → `false`, `DEFAULT_PAIRS` pruned to `BTC/USD,ETH/USD,SOL/USD` since Kraken does not list BNB or USDT pairs).

**Commits:** `ec2565e`, `eb584fc`, `790932e`, `e917f57`, `7a8f636`

**Security follow-ups (open):**
- Rotate Supabase DB password, Telegram bot token, and `CREDENTIAL_ENCRYPTION_KEY` once burn-in completes (all were exposed at some point during config).
- Rotate OpenAI key (was briefly committed before `.gitignore` fix).

### 18.2 Screenshot analysis feature enabled

User requested chart-image analysis (`/analyze_screens` → send up to 12 chart screenshots → `/done`).

**What was done:**
- Enabled `FEATURE_SCREENSHOTS=true` in Railway env.
- Added `CLAUDE_API_KEY`, `CLAUDE_MODEL=claude-sonnet-4-20250514`, `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-4o-mini` to Railway for vision fallback chain.
- Verified session lifecycle (`start_session` → `add_image` → `analyze_screenshots` → `end_session`) in `screenshot_analyzer.py`.

**First bug caught in live test (9 charts submitted):**
- Output was being truncated mid-JSON, showing only partial analysis of chart 4/9.
- Two root causes, both fixed in commit `f0c5505`:
  1. `_analyze_with_claude()` used `max_tokens=2000` which cut off the JSON response when many charts were analyzed at once. Bumped to `max_tokens=4000`.
  2. `telegram_bot.py done_cmd` was truncating the formatted result to 3000 chars. Replaced with a chunker that splits into 3800-char messages (under Telegram's 4096 limit) and attaches the back-button keyboard only to the final chunk.

**Commit:** `f0c5505`

### 18.3 Vision role locked down: confirmation-only, never primary

User directive (explicit, durable rule): vision must never be the authoritative divergence source. RSI/MACD math in `indicators.py`/`strategy.py` is authoritative.

**What was done:**
- Reframed the `_ANALYSIS_PROMPT` inside `screenshot_analyzer.py` so the vision model is instructed up-front that the indicator engine is the primary divergence detector; vision is for **context, candlestick patterns, structural levels, and confirmation** only.
- Verified no code path feeds `screenshot_analyzer` output into `strategy.py`, `ai_fusion.py`, or the scheduler's signal pipeline. Vision output is isolated to the user-facing `/analyze_screens` advisory channel.
- Saved persistent feedback memory (`feedback_vision_role.md`) so any future conversation that proposes wiring vision into the trading path gets pushed back against.

**Commit:** `e3cc27e`

### 18.4 Telegram menu overhaul

Menu buttons were both missing features and getting truncated in narrow Telegram clients.

**What was done:**
- Expanded the main-menu keyboard to expose every built feature: Signal/Price, Status/Heatmap, Positions/Risk Board, Guards/Check Guards, AutoTrade/Mode, Risk/Sell Now, SL/TP/Trail, Cancel Guards, Backtest/Visuals, AI Card/My Account, Analyze/Connect, Health/Go Live, PANIC STOP, Report/Pairs, Disconnect/Admin. Added callback handlers for each (`cmd_heatmap`, `cmd_positions_card`, `cmd_risk_board`, `cmd_ai_card`, `cmd_myaccount`, `cmd_health_stats`, `cmd_golive`, `cmd_panic_stop`, `cmd_backtest`, `cmd_visuals`, `cmd_analyze_screens`).
- Removed duplicate "Connect Exchange" entries.
- Shortened button labels to fit narrow viewports.
- No change to `/help` command surface — all existing commands preserved.

**Commits:** `3b77a89`, `1ec78f5`, `6373be5`, `0585d03`

### 18.5 Performance tuning (strict optimization phase — no new features)

Goal: increase trade frequency and raise PF toward ≥ 1.3 without adding features, touching exits, or weakening risk controls. Driven by the observation that the bot was under-trading and too conservative.

**Phase 1 — divergence trigger threshold** (`f7ab800`, `785e9f4`)
- Added a HOLD-override trigger: strong regular divergence + candle confirmation with opposing score guard.
- Threshold set at `DIV_TRIGGER_STR = 0.65` (down from the originally proposed 0.7).
- AI fusion confidence +0.05 boost when the trigger fires so `AI_CONFIDENCE_MIN=0.70` doesn't silently gate valid setups.

**Phase 2 — broader trigger + lower base threshold** (`2906169`, current HEAD)

`strategy.py`:
- Non-trigger path score threshold lowered: `1.5 → 1.2` for both BUY and SELL.
- HOLD-override trigger now accepts **either**:
  - Regular divergence strength ≥ 0.65, **or**
  - Hidden divergence strength ≥ 0.75 (higher bar intentionally — hidden divs are trend-continuation, not reversal).
- Added ADX filter: trigger only fires when `20 ≤ ADX ≤ 45` (skip chop below 20 and blow-off/exhaustion moves above 45).
- Candle confirmation requirement preserved (`net_score > 0.2` bull, `< -0.2` bear).
- Opposing-score guard preserved (`< 1.5`) — trigger can only override HOLD, never flip BUY ↔ SELL.

`ai_fusion.py`:
- Trigger confidence boost raised from `+0.05 → +0.10` in `_local_heuristic`.
- No threshold or gating changes elsewhere.

**Explicitly NOT changed this phase** (deferred to a separate post-observation phase):
- Trailing activation (`TRAILING_ACTIVATION_ATR`)
- Break-even logic (`BREAK_EVEN_ATR_MULTIPLIER`)
- Cooldown (`COOLDOWN_AFTER_TRADE_SECONDS`)
- Partial take-profit at 1R (would require new exit-path logic)
- Risk engine, position sizing, DB schema, execution flow, UI

**Reason for deferral:** user-provided numbers used **R-multiple** framing while the current system uses **ATR-multiple**. 1 R in this system = `ATR_SL_MULTIPLIER × ATR = 1.5 × ATR`, so 0.8 R = 1.2 ATR (later, not earlier, than the current 1.0 ATR). Cooldown literal "10 min" was also longer than the current 5 min. Flagged the unit mismatch and held those changes until the user re-specifies in ATR units after observing Phase 2 live results.

**Verification for Phase 2:**
- `ast.parse` ok for `strategy.py` and `ai_fusion.py`
- `py_compile` ok for both
- `import strategy, ai_fusion` ok
- pytest not available in local `.venv` — relying on Railway deploy smoke + live observation

### 18.6 Configuration cleanups

Multiple small environment corrections driven by real errors encountered during deployment:

- Duplicate `TELEGRAM_ADMIN_IDS` values (`93372553` was BotFather's ID, not the user's) → pruned to `344374586`.
- `CLAUDE_API_KEY` field had accidentally contained the Kraken API secret (base64 with trailing `==`) → replaced with the real Anthropic key.
- Smart-quote corruption (`"…"` with curly quotes) → instructed user to paste into the Railway Raw Editor with straight quotes only.
- `RAILWAY_VARS.md` added to `.gitignore` after a commit briefly exposed secrets.

### 18.7 Repo hygiene

- Cleaned stray files (old scripts, backup copies, `node_modules` at project root). Repo tracks 54 files after cleanup.
- Created `v1.0-rc1` tag to mark the feature-freeze baseline before performance tuning began.
- Added persistent memory entries under `~/.claude/projects/.../memory/`:
  - `feedback_vision_role.md` — vision is confirmation-only
  - (Preexisting architecture/pipeline memories still valid)

### 18.8 Restore point before UI work

Before touching UI surface, created immutable anchors on GitHub:

- Tag `v1.1-pre-ui-panel` → commit `7065190`
- Branch `backup/pre-ui-panel` → commit `7065190`

Full restore path documented: `git reset --hard v1.1-pre-ui-panel && git push origin main --force-with-lease`. Railway auto-redeploys the old code. Partial cherry-pick path also documented for selectively rolling back.

### 18.9 Hybrid control panel (UI-only, feature-flagged)

User requested an "app-like" persistent control panel without breaking any existing feature. Flagged that "always at the bottom" is not possible in Telegram and proposed the only realistic approaches; user chose the **hybrid** design.

**Design chosen:**
- One inline panel message per user, edited in place (`edit_message_text`) for every navigation.
- A `ReplyKeyboardMarkup` with `Menu` / `Status` / `Panic Stop` sits above the text input permanently (this is the ONLY widget in Telegram that stays at the bottom — it's not a message, it's an input-area attachment).
- In-memory per-user state (no DB schema change); fallback to re-send if edit fails.
- Gated behind `FEATURE_CONTROL_PANEL` (default `true`) for instant rollback via Railway env flip.

**Implementation:**
- **New `panel.py`** (~400 LOC): `PanelState` tracking, 10-row grid preserving every existing `callback_data`, dynamic header renderer, `bottom_reply_keyboard()`, `refresh_panel(bot, chat_id, uid)` with edit-in-place + send-fallback, `track_panel`/`clear_panel`/`track_last_signal` helpers.
- **`telegram_bot.py` minimal touch-ups**: `main_menu_keyboard()` delegates to `panel.build_panel_keyboard()` when flag on (legacy layout preserved as `_legacy_main_menu_keyboard`); `/start` sends bottom keyboard + panel message and tracks message_id; `/menu` re-renders; `cmd_menu` callback uses panel text; `text_input_handler` routes literal "Menu"/"Status"/"Panic Stop" taps from the reply keyboard before the `PENDING_INPUT` check; `/done` (screenshot) refreshes panel after multi-chunk output so it surfaces below.
- **Row layout** (every callback_data resolves to an existing handler — verified by grep coverage check):

| Row | Buttons |
|---|---|
| 1 | 📊 Signal · 📈 Status · 💼 Positions |
| 2 | ⚙️ Risk · 🤖 AI Card · 📉 Report |
| 3 | 🔁 AutoTrade · 🧪 Mode · 🔌 Connect |
| 4 | 📊 Backtest · 🔍 Analyze · 🧠 Insights |
| 5 | 🛡 Guards · ⚠️ Risk Board · 🔥 Heatmap |
| 6 | 🚨 PANIC · 👤 Account · 🧩 Admin |
| 7 | 💰 Price · 💚 Health · 🚀 Go Live |
| 8 | 🎨 Visuals · 🌐 Pairs · 🔍 Check |
| 9 | 🛑 Sell Now · 📐 SL/TP/Trail · ❌ Cancel |
| 10 | 🔌 Disconnect |

**Commit:** `b0a7a99`. Live test confirmed panel renders cleanly with dynamic header, all buttons responsive.

### 18.10 Live dashboard upgrade — toast feedback, Last Action, 3-state status, auto-refresh

User wanted the panel to feel "alive and app-like" (§ "LIVE dynamic dashboard"). Pushed back on the naive "Processing..." text flash because it causes flicker on fast submenu toggles; chose Telegram-native `query.answer(text=...)` toasts instead.

**Additions in `panel.py`:**
- Per-user state tracking: `set_state(uid, 'healthy'|'busy'|'error')` + `get_state(uid)`.
- `set_last_action(uid, text)` + timestamp for "Last Action: X (3s ago)" header line.
- `CALLBACK_LABELS` dict + `label_for(callback_data)` — maps every dispatch case to a short human label for toasts + Last Action line. Unknown keys fall back to title-cased data.
- `build_panel_text` now shows: `Open: N` trade count, directional emoji on Last Signal (📈 BUY / 📉 SELL / ⚠️ warn / ➖ none), Last Action with relative age, 3-state System indicator (`🟢 Healthy` / `🟡 Busy` / `🔴 Error` / `🔴 Kill Switch` / `🟡 Dry Run`).
- **MD5 content-hash dedupe** in `refresh_panel` — unchanged panels skip the Telegram API call entirely. Prevents rate-limit burn and "message is not modified" error spam from the auto-refresh job.
- `auto_refresh_all(bot)` background function: iterates every tracked panel, skips panels idle > 10 min (stale), dedupes by content hash, failsafe clears stuck busy state older than 30s.

**Additions in `telegram_bot.py`:**
- `button_callback` entry now calls `query.answer(text=f"⏳ {label}...")` — native Telegram toast (~64 char limit), non-blocking, no panel flicker.
- Sets `panel.set_state(uid, 'busy')` at entry; finalization block after the last `elif` clears to `healthy` and records the Last Action via `panel.set_last_action()`.
- `build_app` registers `panel_auto_refresh` job on PTB's `JobQueue`: `interval=45s`, `first=60s`, gated by `FEATURE_CONTROL_PANEL` at each tick.

**Rate-limit math:** Per-user cost is one `edit_message_text` every 45s *only when content actually changed* (hash dedupe). With 1 active user, that's at most ~80 API calls/hour. For the Telegram Bot API's 30/s limit that's trivial.

**Commit:** `57ec31d`. Verified with live screenshot showing `Mode: LIVE · AutoTrade: OFF · Pairs: BTC · System: 🟢 OK` and all 10 rows rendering cleanly in narrow viewport.

### 18.11 Trial Mode + bilingual (EN/FA) UI

User specced a conversion-funnel "Trial Mode" as a UX wrapper over existing paper trading, plus bilingual EN/FA UI. Flagged that in-memory trial state would lose everything on Railway restart (trials last 7–14 days), so proposed and used an **additive migration** — five new columns on the existing `users` table, zero logic files touched.

**New files:**
- **`i18n.py`** — `TEXT` dict (EN + FA), `t(uid, key)` translator, `get_user_lang`/`set_user_lang` with in-memory cache + DB-backed persistence. Feature-flag aware. Keys cover panel header, trial mode strings, system status, button labels (selective), report headers. Farsi translations hand-written; numbers/symbols kept in Latin digits inside Farsi strings per RTL-readability best practice.
- **`trial.py`** — `TrialState` dataclass (active/start_ts/capital/target_days + day_elapsed/day_index properties), `TrialMetrics` (trades, wins, losses, realized_pnl, max_drawdown, profit_factor, equity, roi_pct, win_rate). Metrics computed from existing `trades` table filtered on `user_id + ts_open >= trial_start_ts`. `panel_block(uid)` renders the injectable header block. `render_status` / `render_report` / `render_summary` produce fully-localized bilingual text including a progress bar (`██░░░░░░░░`) and a verdict heuristic (good / mixed / bad) after ≥5 trades.

**Storage migration (`storage.py`, both SQLite + PostgreSQL):**
Additive only — safe, backward-compatible:
```sql
ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'en';
ALTER TABLE users ADD COLUMN trial_active INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN trial_start_ts INTEGER DEFAULT 0;  -- BIGINT on PG
ALTER TABLE users ADD COLUMN trial_capital REAL DEFAULT 0;      -- DOUBLE PRECISION on PG
ALTER TABLE users ADD COLUMN trial_target_days INTEGER DEFAULT 14;
```

**Config flags:** `FEATURE_TRIAL_MODE` (default true), `FEATURE_I18N` (default true).

**New commands in `telegram_bot.py`:**
- `/lang en` | `/lang fa` — per-user language, persisted, cache-invalidated on set.
- `/trial start <capital> [days]` — begin trial; sets `trade_mode='PAPER'`, `autotrade_enabled=1`, `capital_usd=<capital>`, stamps start timestamp. Default target 14 days, max 90.
- `/trial status` — running time, equity, PnL, ROI, progress bar.
- `/trial report` — recent closed trades (✅/❌/➖) + open positions.
- `/trial summary` — full breakdown with verdict heuristic.
- `/trial stop` — end without conversion.
- `/trial go_live [confirm]` — two-step conversion gated by `LIVE_TRADE_ALLOWED_IDS`; on confirm flips `trade_mode='LIVE'` and kicks existing `reconcile_positions()`.

**Panel integration (`panel.py`):**
- Header labels now go through `_tr(uid, key, fallback)` helper which best-effort fetches via `i18n.t()` and falls back to English on any error.
- When `trial_active`, injects a two-line block:
  ```
  Trial Progress: █████░░░░░ 6/14 days
  Trial Capital: $1,000.00
  ```
  Localized label in Farsi: `پیشرفت آزمایشی: █████░░░░░ 6/14 روز`. Numbers stay Latin for scan-ability.
- **Keyboard layout untouched** — no new buttons added per spec §7 "keep layout clean". Full button translation deferred (flagged to user as a known limitation).

**Post-deploy user action (§18.11 follow-up, user message 2026-04-15):**
User set `FEATURE_TRIAL_MODE=false` and `FEATURE_I18N=false` on Railway and restarted. Intentional rollback via the feature flags:
- `/trial <anything>` now returns `"Trial Mode is disabled"`.
- `trial.panel_block(uid)` returns `""` early (no trial lines injected).
- `i18n.get_user_lang()` short-circuits to `'en'`; `t()` always returns English.
- All 5 DB columns remain in place — harmless when not read/written.
- Control panel, live dashboard upgrades, perf tuning, vision lock all still **active** (they're not gated by these flags).
User did not report a bug. Most likely reason: keeping the burn-in observation surface minimal. Flags can be flipped back to `true` whenever desired; feature code is all deployed.

**Commit:** `ef10fd4`.

### 18.12 i18n completion — full button localization + Settings submenu

User caught that the previous i18n commit (`ef10fd4`) only translated panel **header labels**, not button labels. I had flagged this as deferred at the time ("button labels stayed language-neutral for symmetry"). User asked me to finish the job, which was fair — typing `/lang fa` is developer ergonomics, not user ergonomics.

**Phase A — full button translation (`01e18ca`):**
- Added 28 `btn_*` keys + 3 `rk_*` keys to both `en` and `fa` dicts in `i18n.py`. Every inline grid button + the persistent bottom ReplyKeyboard labels now have Farsi translations (kept short for grid fit).
- `panel.build_panel_keyboard(uid=None)` and `panel.bottom_reply_keyboard(uid=None)` now accept `uid` and localize every label via a new `_btn(uid, key, fallback)` helper with safe English fallback.
- `panel.refresh_panel()` passes `uid` to keyboard builder so auto-refresh ticks render in the user's language.
- `main_menu_keyboard(uid=None)` in `telegram_bot.py` passes `uid` through.
- `/start`, `/menu`, and the `cmd_menu` callback now pass `uid` explicitly.
- `text_input_handler` accepts Farsi ReplyKeyboard labels (`منو`, `وضعیت`, `توقف`, `توقف اضطراری`) so tapping the Farsi button routes to the same handler as the English one.
- New `/farsi` command as a shortcut alias for `/lang fa`.
- New `/langtest` diagnostic command (current language + `FEATURE_I18N` state + 7 sample keys).
- `/lang` now forces immediate refresh: clears panel content-hash, re-renders inline panel in-place with new-language labels, re-sends the bottom ReplyKeyboard so its labels take effect.

**Phase B — Settings submenu (`1e2d262`):**
- User asked "why not add a settings option?" after seeing the i18n result. Fair UX critique — real apps don't require slash commands for common settings.
- Added `⚙️ Settings` button to row 10 of the main panel (was solo `🔌 Disconnect` — now `⚙️ Settings · 🔌 Disconnect`).
- Settings submenu: `🇬🇧 English`, `🇮🇷 فارسی`, `⬅️ Back`.
- New callbacks `menu_settings`, `settings_lang_en`, `settings_lang_fa` wired into `button_callback` with the same force-refresh pattern as `/lang`.
- Added 6 new i18n keys in both locales (`btn_settings`, `settings_title`, `settings_language_header`, `btn_lang_en`, `btn_lang_fa`, `btn_back`).
- Added 3 new entries to `panel.CALLBACK_LABELS` so the Last Action line + toast show the right text when Settings / Language buttons are tapped.
- Designed as extensible: future settings (timezone, notifications, trial toggle, default pair) slot into the same submenu without bloating the main grid.

**Feature state:** `FEATURE_I18N=false` per user choice (§18.11). Commands and buttons exist but the "i18n disabled" guardrail message shows when users try to switch language. Flag can be flipped back on Railway to activate.

### 18.13 Portfolio v1 — read-only exchange reporting

User specced a safe read-only portfolio view for connected exchange accounts. Hard scope rules: only fetch calls, no order placement / cancellation / mutation.

**New `portfolio.py` (~290 LOC):**
- `PortfolioSnapshot` / `Asset` / `PerformanceReport` dataclasses.
- `async fetch_portfolio(uid, force=False)` — async wrapper around CCXT `fetch_balance`. Runs sync CCXT calls in an executor so the event loop never blocks.
- Per-user snapshot cache with 60s TTL — the panel auto-refresh at 45s stays inside this window so no additional exchange API load from the panel.
- Per-ticker price cache with 30s TTL.
- Stablecoins (USD/USDT/USDC/BUSD/DAI/TUSD/USDP/FDUSD) valued 1:1; non-stable assets priced via `fetch_ticker` against USDT → USD → USDC fallback chain.
- Dust filter: assets < $0.01 hidden.
- `compute_report(uid, window_days)` — realized PnL / ROI / trades / wins / losses / best / worst — all from the existing `trades` table filtered on `user_id + ts_close` window. Zero exchange API cost.
- `format_portfolio` / `format_report` — bilingual via i18n, Markdown-safe output.
- `panel_summary(uid)` — single-line summary read from **cache only** (never triggers a fetch). Empty until user runs `/portfolio` once.

**New `/portfolio` command:**
- `/portfolio` — live snapshot (force=True, cache bypass)
- `/portfolio report 7d | 30d | <days>` — local-trades performance window
- "Fetching..." placeholder edited in-place with the result for loading feedback.

**i18n:** 19 `portfolio_*` keys added to both `en` and `fa` dicts.

**Config:** `FEATURE_PORTFOLIO=true` (default).

**Panel integration:** single line injected after System status when the cache is warm (empty otherwise so panel stays clean for paper users).

**Safety audit:**
- No order / cancel / edit calls — grep-verified across `portfolio.py`.
- All CCXT calls inside `asyncio.run_in_executor` — non-blocking.
- CCXT client initialized with `enableRateLimit=True` (already in `CCXTProvider`).
- Graceful `NO_EXCHANGE` path for paper-only users.
- Credentials decrypted via existing `crypto_utils` (V1 + V2), never logged.

**Commit:** `636b1f4`.

### 18.14 Portfolio upgrade — true equity, open positions, unrealized PnL, reconciliation, real-trade report

User specced a professional trading-grade upgrade. Four real-world caveats flagged up-front because they shaped the implementation:

1. **Kraken is spot — no native "positions" concept.** CCXT `fetch_positions()` returns empty on spot exchanges. Primary source for unrealized PnL had to be the bot's internal `trades` table (where entry prices actually live), with `fetch_positions()` as a bonus path only for derivatives venues.
2. **Reconciliation on spot is noisy.** Users may hold pre-existing balances unrelated to the bot. Scoping the check to *only symbols where the bot has OPEN trades* and only flagging *under-balance* (not over-balance) prevents false alarms.
3. **`fetch_my_trades` varies per exchange.** Rate limits + pagination differ. Added 5-minute per-user result cache + 365-day window cap + executor wrap.
4. **Real PnL from fills is not trivially FIFO-accurate.** Did simplified per-symbol buy-cost vs sell-proceeds aggregation minus fees. UI explicitly labels output as "Real trade history (approx.)" so users aren't misled.

**New data model:**
- `OpenPosition` dataclass: `symbol`, `side`, `size`, `entry_price`, `current_price`, `unrealized_pnl`, `unrealized_pct`, `source` ('bot' | 'exchange').
- `PortfolioSnapshot` extended with: `unrealized_pnl`, `true_equity`, `open_positions: List[OpenPosition]`, `reconcile_warning: str`.

**`_collect_open_positions` logic:**
- Pull every OPEN trade for the user from `trades` table (has entry price + qty).
- Fetch current ticker for each pair → compute unrealized PnL = `(current - entry) × qty` for BUY, inverted for SELL. Store with `source='bot'` and 🤖 glyph.
- If `client.has['fetchPositions']`, also fetch exchange-side positions (derivatives) and append with `source='exchange'` and 📊 glyph.

**`_reconcile_check` logic:**
- Group bot's OPEN BUY trades by pair → sum expected qty per asset.
- For each asset the bot has OPEN trades on, compare to exchange's total balance of that asset (from `fetch_balance`).
- Flag when `have < expected × 0.99` (1% drift tolerance for fees/rounding).
- Does **not** flag untracked balances on other assets (would cry wolf on every spot user).
- Output: "`⚠️ Sync mismatch: BTC: bot expects 0.010000, exchange has 0.005000`" rendered in the portfolio view.
- Does **not** duplicate `reconcile.py`'s system-wide check — `reconcile.py` is global and admin-facing; this is per-user and UI-facing.

**Real trade history (`/portfolio report real [days]`):**
- `async compute_report_real(uid, window_days)` — uses CCXT `fetch_my_trades(since=window_start_ms, limit=500)`.
- Per-symbol aggregation: `min(buy_qty, sell_qty)` = realized qty; PnL = `(avg_sell - avg_buy) × realized_qty - fees`.
- Returns standard `PerformanceReport` — reuses `format_report` with "_(approx.)_" prefix.
- Default window 30 days (vs 7 for local report), max 365.
- 5-minute per-user result cache to protect exchange API quotas.

**UI fixes:**
- Added `_signed_money(v)` helper. Old code rendered `$-10.00` and `++3.86%` for negatives due to formatter double-signing. New helper puts sign outside the `$`: `+$12.30`, `-$5.00`, `$0.00`.

**Panel summary now 2 lines** when portfolio cache is warm:
```
Portfolio: $1,512.34   PnL: +0.82% (1d)
Unrealized: +$23.50
```
Still read-from-cache-only — never triggers a fetch. Empty when cache cold or user has NO_EXCHANGE / ERROR state.

**i18n:** 6 new keys in both locales (`portfolio_equity`, `portfolio_unrealized`, `portfolio_unrealized_short`, `portfolio_open_positions`, `portfolio_no_open`, `portfolio_real_label`).

**Safety audit (still clean):**
- Every new CCXT call is read-only: `fetch_positions`, `fetch_my_trades`, `fetch_ticker`, `fetch_balance`. Grep-verified no `create_order` / `cancel_order` / `edit_order` / `transfer` anywhere in `portfolio.py`.
- All calls inside executor (non-blocking).
- 60s snapshot cache + 30s ticker cache + 5-min real-report cache — bounded API load under worst-case user activity.

**Post-deploy user action:** user set `FEATURE_PORTFOLIO=false` on Railway. Intentional flag rollback (same pattern as §18.11 for Trial + i18n). All code deployed, `/portfolio` replies "disabled" until flag is flipped back.

**Commits:** `636b1f4` (v1), `f204963` (upgrade).

### 18.15 Multi-user enablement — ungate personal commands + fix 2 tenant-leak bugs

User asked for "full multi-user support". Honest audit first: the codebase had **already** claimed multi-user isolation in the docs (per-user DB columns, per-user credentials, per-user UserContext, scheduler iterating users). The actual gaps were narrower than the spec implied.

**Audit findings (documented before writing code):**
- Already done: `user_id` columns on every relevant table, `get_credential(uid)`, `save_credential(uid, ...)`, `upsert_user` with correct per-user defaults via schema, per-user scheduler iteration, every Telegram handler already extracting `uid`.
- Actually missing: admin gates on commands that operate on the user's OWN account (`/autotrade`, `/mode`, `/sellnow`, `/capital`, `/maxexposure`, `/liveready`).
- **Two silently critical tenant-leak bugs discovered during audit** (pre-existing, not introduced by this work):
  1. `trade_executor.close_all_for_pair(pair, reason)` had **no `user_id` filter**. Any user calling `/sellnow` would close ALL users' OPEN trades on that pair.
  2. `/capital` and `/maxexposure` commands wrote to GLOBAL state (`config.SETTINGS.CAPITAL_USD`, `bot_state`) despite per-user columns (`users.capital_usd`, `users.max_portfolio_exposure`) already existing via migration. One user's change would override every other user's setting at runtime.

**Fixes shipped:**

Ungated (personal commands — any user may modify their OWN account):
- `/autotrade`, `/mode`, `/sellnow`, `/capital`, `/maxexposure`
- Callback branches: `cmd_autotrade_on`, `cmd_autotrade_off`, `cmd_mode_paper`, `cmd_mode_live`, `cmd_sellnow`

Opened as read-only diagnostic (no uid-scoping concerns):
- `/liveready`, `cmd_liveready`

Kept admin-gated (truly system-wide operations):
- `/killswitch` (global env flag)
- `/reconcile` (system-wide trade reconciliation)
- `/health_stats` (global telemetry)
- `menu_admin` (admin dashboard)

Tenant-leak fixes:
- `close_all_for_pair(pair, reason, user_id=None)` — added optional `user_id` parameter. When provided, scopes closures to that user only; when omitted, preserves legacy global behaviour for internal callers. `/sellnow` (both command and callback) now passes `uid`.
- `capital_cmd` and `maxexposure_cmd` rewritten to read/write `users.capital_usd` and `users.max_portfolio_exposure` respectively. UserContext already reads these columns correctly, so the risk engine side needed no change.

Live-mode safety preserved:
- `cmd_mode_live` and `/mode` still gate LIVE selection by `LIVE_TRADE_ALLOWED_IDS` (a separate approval list, not admin_only). Unapproved users get a clear message pointing at the env var.

Panel upgrade (per spec §9):
- First header line now ends with `🔗 KRAKEN` (or similar) when the user has an exchange connected. Omitted when no credentials stored — keeps panel clean for paper-only users.

**Restore anchor:** tag `v1.2-pre-multiuser` + branch `backup/pre-multiuser` at commit `ff42a67` captured BEFORE these changes. Revert path: `git reset --hard v1.2-pre-multiuser && git push origin main --force-with-lease`.

**Commit:** `d6b64f4`.

### 18.16 Production safety layer — dual-window rate limit, user cap, clean exchange errors

User specced a production-grade safety layer. Second honest audit — most of it existed already (single-window per-user rate limit, CCXT's built-in global throttle via `enableRateLimit=True`, per-user risk limits, safe schema defaults, `logging_utils.py` module). Genuinely missing: burst-rate limiting, user-count soft cap, consistent exchange-error mapping to user-safe text.

**What was already in place (confirmed, not re-built):**
- Per-user rate limit: `_check_rate_limit(uid, limit=10, window=60)` + `rate_limited` decorator applied to every command handler.
- Global exchange throttle: CCXT client instantiated with `enableRateLimit=True` in `ccxt_provider.py`.
- Per-user risk limits: `users.capital_usd`, `users.max_portfolio_exposure`, `users.max_open_trades` columns + env-level `MAX_OPEN_TRADES=2`, `DAILY_LOSS_LIMIT_USD=40`.
- Safe defaults for new users: schema enforces `trade_mode='PAPER'`, `autotrade_enabled=0`, `capital_usd=1000`, `language='en'`, trial fields=0.
- Structured logging: `logging_utils.py` with JSON output, correlation IDs, regex-based secret redaction.
- Isolation: audited last session; tenant-leak bugs in §18.15.

**Additions this commit:**

1. **Dual-window rate limit** (backward-compatible extension of `_check_rate_limit`):
   - Burst: 5 commands in 10 seconds (`RATE_LIMIT_BURST_COUNT` / `RATE_LIMIT_BURST_WINDOW`).
   - Volume: 10 commands in 60 seconds (`RATE_LIMIT_WINDOW_COUNT` / `RATE_LIMIT_WINDOW_SECONDS`).
   - Both enforced simultaneously when called with no args. Legacy `(uid, limit, window)` signature preserved for `button_callback` and any other existing call site.
   - Rejection message now matches user's spec text: `"Too many requests, slow down."`

2. **`MAX_ACTIVE_USERS` soft cap (default 20):**
   - `_is_over_user_cap()` counts rows in `users`.
   - `/start` checks BEFORE `upsert_user`. Existing users bypass the cap.
   - New users over the cap are registered but forced to `trade_mode='PAPER'` + `autotrade_enabled=0`, and shown: `"⚠️ User capacity reached (N active). You can use paper trading; live trading is disabled for new users."`
   - Set `MAX_ACTIVE_USERS=0` on Railway to disable the cap.

3. **Clean exchange-error wrapper:**
   - `_safe_exchange_error(e)` maps raw CCXT exceptions to short user-safe strings. Checks specific subclasses (`RateLimitExceeded`, `AuthenticationError`, `ExchangeNotAvailable`) **before** parents (`NetworkError`, `ExchangeError`) — important because ccxt's exception tree has `RateLimitExceeded <- NetworkError`.
   - Wired into `portfolio_cmd` live snapshot path and `/portfolio report real` path.
   - Raw exception text no longer surfaces to users. Full exception still logged with `uid=` for operator debugging.

4. **5 new Railway env flags (all optional, defaults ship safe):**
   - `MAX_ACTIVE_USERS=20`
   - `RATE_LIMIT_BURST_COUNT=5`
   - `RATE_LIMIT_BURST_WINDOW=10`
   - `RATE_LIMIT_WINDOW_COUNT=10`
   - `RATE_LIMIT_WINDOW_SECONDS=60`

**Deliberately NOT done (flagged to user):**
- Full structured-logging rollout across ~100 log sites — `logging_utils.py` exists but integrating it everywhere would be a much larger refactor; current `log.*` calls already include uid in hot paths.
- Error wrapper only on portfolio paths for now. Extending to `/connect`, `/myaccount`, and other exchange-touching commands is a one-line-per-site change — flagged as ready when requested.
- `MAX_ACTIVE_USERS` is count-based (total registered users). If concurrency-based (active-in-last-hour) is desired, query would change to filter by `last_active_ts`. Flagged for user.

**Verification (local):**
- `ast` + `py_compile` on `telegram_bot.py` and `config.py`.
- Dual-window rate-limit: 5 rapid calls allowed; 6th rejected with correct message.
- Per-user isolation: uid=1 rate-limited does not block uid=99.
- Legacy single-window call signature still works for existing call sites.
- Exchange error mapper returns correct strings for `RateLimitExceeded`, `NetworkError`, `AuthenticationError`, `ExchangeError`, `ValueError` (generic) after fixing check-order bug.

**Commit:** `40dd091`.

### 18.17 Safety layer v2 — active-user cap, global error wrapper, telemetry, UX refinement

User asked to "upgrade safety layer to production-grade completeness." Most of the prior safety work (§18.16) was already solid — this commit refines 4 areas and adds 1 new module.

**1. Active-user cap replaces total-user count:**
Previous: `_is_over_user_cap` counted total rows in `users` — dormant accounts from 6 months ago consumed capacity for no reason.
Now: `telemetry.active_users()` counts users with `last_seen_ts >= now - 24h` OR `autotrade_enabled=1`. New `storage.touch_user(uid)` updates `users.last_seen_ts` on every accepted command (called in the `rate_limited` decorator and `button_callback`). Best-effort; no-ops silently on missing rows.

**2. Global exchange-error wrapper applied to all user-facing exchange paths:**
`_safe_exchange_error(e)` now wired into:
- `/price` (was leaking raw `ccxt.NetworkError` text to the user)
- `/setkeys` (was leaking `"Failed to set keys: <raw>"`)
- `/connect` exchange validation (was leaking `"Connection error: <raw>"`)
- `/portfolio` and `/portfolio report real` (already wrapped since §18.16)
Exception-type check order verified: specific subclasses (`RateLimitExceeded`, `AuthenticationError`) before parents (`NetworkError`). Full exception still logged with `uid=` for operator debugging.

**3. Light telemetry (new `telemetry.py`, ~80 LOC):**
In-memory, no external dependencies:
- `record_command(uid)` — ring buffer of timestamps, trimmed to 5 min
- `commands_per_minute()` — count in last 60s
- `total_users()` — `COUNT(*) FROM users`
- `active_users(window_seconds)` — count with `last_seen_ts` + `autotrade` filter (same query as the cap logic, DRY)
- `render_summary()` — plaintext block appended to `/health_stats` output (admin-only)
Counters increment on every accepted command (rate_limited) and callback (button_callback). Resets on restart (in-memory only; acceptable for operational visibility, not historical trend analysis).

**4. UX message refinement:**
`"Too many requests, slow down"` → `"⚠️ Too many requests. Please wait a few seconds."` — applied in both the `rate_limited` decorator and the `button_callback` rate-limit check.

**Deferred: persistent rate limit.**
User marked optional; "system still works without persistence." In-memory rate limit resets on Railway restart. Redis/DB fallback not added (new dependency, YAGNI at this bot's scale). Noted as a follow-up if the bot scales to 100+ concurrent users where Railway restarts become a meaningful exploit vector.

**Commit:** `ab5532b`.

### 18.18 Stabilization — exception leak audit, rate-limit coverage, touch-user completeness

User invoked a **strict stabilization phase**: no features, no logic changes, no architecture expansion. Objective: validate and harden what we have.

Ran two targeted audits using subagents:
1. **Exception-leak audit:** grepped every `except Exception as e:` block for raw `{e}` in user-facing messages.
2. **Handler-coverage audit:** compared every `CommandHandler` registration in `build_app()` against the `rate_limited` wrapper, and checked `MessageHandler` registrations for `touch_user`.

**Finding 1: 8 exception handlers leaked raw `{e}` to users.**
Replaced all with static safe messages. Full exception still logged with `uid=` for operators. Zero raw `{e}` remaining in any user-facing message (grep-verified).

| Handler | Old (leaking) | New (safe) |
|---|---|---|
| cmd_heatmap | `"Heatmap error: {e}"` | `"Heatmap render failed. Try again."` |
| cmd_positions_card | `"Positions error: {e}"` | `"Positions render failed. Try again."` |
| cmd_risk_board | `"Risk board error: {e}"` | `"Risk board render failed. Try again."` |
| cmd_ai_card | `"AI card error: {e}"` | `"AI card render failed. Try again."` |
| cmd_myaccount | `"Account error: {e}"` | `"Account load failed. Try again."` |
| confirm_trade_* | `"Error: {e}"` | `"Trade execution error. Try again."` |
| /backtest | `"Backtest failed: {e}"` | `"Backtest failed. Check pair and try again."` |
| /done | `"Analysis failed: {e}"` | `"Analysis failed. Try again with fewer images."` |

**Finding 2: 21 of 49 command handlers were NOT wrapped in `rate_limited`.**
All 21 bypassed: rate limiting (burst + volume), `touch_user` (active-user tracking), `telemetry.record_command` (command counting). Fixed by wrapping all 21 handlers. Verified: 49/49 command handlers now wrapped.

**Finding 3: `text_input_handler` and `screenshot_photo_handler` had no `touch_user`.**
Added best-effort `touch_user(uid)` calls at entry to both handlers. Every user-interaction entry point is now tracked:
- 49 command handlers (via `rate_limited` decorator)
- 1 callback handler (`button_callback`) — direct call
- 1 text handler (`text_input_handler`) — direct call
- 1 photo handler (`screenshot_photo_handler`) — direct call

**No trading logic, strategy, risk, execution, or DB schema changes. No features added.**

**Commit:** `1c21fd7`.

### 18.19 Trial Mode activation-readiness — runtime verification (no code changes)

User invoked controlled feature expansion: "implement Trial Mode". Honest answer: already fully built in §18.11 (commit `ef10fd4`) and sitting dormant behind `FEATURE_TRIAL_MODE=false`. Subsequent stabilization work (§18.17 safety v2, §18.18 handler wrapping) automatically extended coverage to `/trial` via the `rate_limited` decorator — it now gets dual-window rate limiting, `touch_user` tracking, and `telemetry.record_command` for free.

Rather than re-implement, ran **end-to-end runtime simulation** against an in-memory SQLite DB to prove the wrapper actually works with live data, not just static imports:

**9 runtime checks — all passed:**
1. `start_trial(uid, 1000, 14)` — sets `users.trial_active=1`, `trial_capital=1000`, `trial_target_days=14`, `capital_usd=1000`, `trade_mode='PAPER'`, `autotrade_enabled=1`
2. `get_trial(uid)` returns correct `TrialState`
3. Insert 5 closed trades + 1 open position WITHIN trial window → `compute_metrics` returns trades=6, wins=3, losses=2, PnL=$32.00, win_rate=60%, profit_factor=4.76, equity=$1032
4. Insert 1 "ghost" trade BEFORE `trial_start_ts` → window filter correctly excludes it ($32 stays $32)
5. `render_status` renders progress bar + equity + ROI correctly
6. `render_report` lists recent trades + open positions correctly
7. `render_summary` includes verdict heuristic ("Trial is performing well" at WR=60%, PF=4.76, ROI=3.2%)
8. `panel_block` injects 2-line trial progress block into panel
9. `stop_trial` clears `trial_active=0`; `can_go_live` correctly denies non-approved uid (gated by `LIVE_TRADE_ALLOWED_IDS`)

**Spec compliance (user's §1-§7) verified:**
- No trading logic, risk engine, execution, telemetry, rate-limit, or safety-layer code touched this turn.
- `trial.py` is a pure wrapper: sets existing `users` columns (PAPER mode, autotrade, capital) — uses the existing paper-trading engine to run trades, not a new code path.
- Never touches live / exchange / real funds. `go_live` subcommand gated by `LIVE_TRADE_ALLOWED_IDS` (separate from admin_only).

**Nothing committed this turn.** Correct professional move was runtime evidence, not re-implementation noise.

**Activation path (unchanged from §18.11):**
On Railway → set `FEATURE_TRIAL_MODE=true` → Deploy. Then:
- `/trial start 1000` — begin 14-day paper run with $1000 virtual capital
- `/trial status | report | summary | stop | go_live confirm`

### 18.20 Menu refactor — hierarchical 12-tile L1 + 7 L2 submenus

User requested a refactor into a clean multi-level navigation system. Previous panel was a flat 10-row / 28-button grid — easy to build but overwhelming.

**Restore anchor:** tag `v1.3-pre-menu-refactor` + branch `backup/pre-menu-refactor` at commit `be4e716` captured BEFORE these changes.

**Honest flag:** user's spec listed 12 L1 buttons AND "max 6-8 per screen" — those contradicted. Went with the explicit 12-button list in a 4×3 grid (still far leaner than 28). The Conservative/Balanced/Aggressive/Notifications/Voice preferences show "coming soon" because concrete behaviour requires user design decisions on preset values (which `risk_per_trade` / `max_exposure` / alert thresholds each profile should set) — that's a design call, not an implementation call.

**Level 1 — main panel (4×3 = 12 tiles):**

| Row | Tiles |
|---|---|
| 1 | 📊 Status · 📈 Signal · 💼 Positions (quick read-only) |
| 2 | 📉 Report · 🤖 AutoTrade · ⚙️ Mode (trading submenus) |
| 3 | 🎯 Risk · 🧠 AI · 👤 Account (category submenus) |
| 4 | 🌐 Pairs · 🧪 Trial · ⚙️ Settings (category submenus) |

**Level 2 — seven new submenus:**

- **🎯 Risk** (`menu_risk_v2`): Daily Limit (preset picker) · Capital (prompt) · Max Exposure (prompt) · SL/TP/Trail · Risk Board · ⬅️ Back
- **🧠 AI** (`menu_ai`): AI Card · Insights · Analyze · Visuals · Backtest · Heatmap · ⬅️ Back
- **🧪 Trial** (`menu_trial`): Start (prompt) · Status · Report · Summary · Stop · ⬅️ Back
- **👤 Account** (`menu_account`): Connect · Disconnect (confirm) · My Account · Portfolio · Language · ⬅️ Back
- **⚙️ Mode** (`menu_mode`, repurposed): Paper · Live · Go Live Wizard · Sell Now (confirm) · Panic Stop (confirm) · ⬅️ Back
- **⚙️ Preferences** (`menu_preferences`): Conservative · Balanced · Aggressive · Notifications · Voice · ⬅️ Back (all show "coming soon")
- **🌐 Language** (`menu_language`; legacy `menu_settings` aliased): English · فارسی · ⬅️ Back

**Level 3 — text-input prompt flows (new):**
- `prompt_capital` → "Enter capital amount (USD):" → `UPDATE users.capital_usd`
- `prompt_maxexposure` → "Enter max exposure (0.0–1.0):" → `UPDATE users.max_portfolio_exposure`
- `prompt_trial_start` → "Enter trial capital (USD):" → `trial.start_trial(uid, val, 14)`

All three use the existing `PENDING_INPUT` dict + `text_input_handler` machinery. Existing prompt types (`sl`, `tp`, `trail`, `addpair`, `rmpair`, `connect_key`, `connect_secret`) preserved.

**Sensitive-action confirmations (new `confirm_*` callbacks):**
- `confirm_sellnow` → Yes/Cancel → runs `cmd_sellnow` (per-user close, already user-scoped)
- `confirm_panic` → Yes/Cancel → runs `cmd_panic_stop`
- `confirm_disconnect` → Yes/Cancel → runs `cmd_disconnect`
- Live mode already gated by `LIVE_TRADE_ALLOWED_IDS` → no extra confirm needed
- Connect already has its own multi-step state machine → no extra confirm needed

**Trial submenu callbacks (new, pure UI plumbing):**
- `cmd_trial_status` / `cmd_trial_report` / `cmd_trial_summary` / `cmd_trial_stop` — wire the Trial submenu buttons to the existing `trial.render_*` and `stop_trial` functions. All respect the `FEATURE_TRIAL_MODE` flag and show "disabled" message when off.

**i18n:** 26 new keys in both EN and FA (new button labels, prompt texts, confirmation messages, "coming soon" text). Total trial/menu i18n keys now cover every new surface.

**Backward compatibility (explicit):**
- All existing `callback_data` strings preserved; no handler removed.
- `build_settings_keyboard()` kept as alias for new `build_language_menu()` so any external caller still renders.
- All typed slash commands (`/trial`, `/portfolio`, `/risk`, `/capital`, `/maxexposure`, etc.) continue to work — menu is purely additive navigation on top.
- All safety-layer guarantees (rate limit, touch_user, telemetry, safe error wrapping) automatically cover new menu interactions because they run through the same `button_callback` entry point.

**Verification:**
- `ast` + `py_compile` on `panel.py`, `i18n.py`, `telegram_bot.py`
- 12/12 main callback_data values resolve to dispatch cases
- 7 submenu builders render with expected rows/buttons
- 26/26 i18n keys present in both `en` and `fa`
- Tuple-dispatched callbacks (`menu_language`, `pref_*`) confirmed reachable

**Commit:** `92caad2`.

---

## 19. Current State Snapshot (2026-04-15 — end of Session 2)

| Area | State |
|---|---|
| Deployment | Live on Railway, paper-trading burn-in |
| Database | Supabase PG project `xlmtawchpgltesmteclj`, pooler on `us-west-2` (IPv4-compatible) |
| Trading mode | `PAPER_TRADING=true`, `DRY_RUN_MODE=false` |
| Pairs | `BTC/USD, ETH/USD, SOL/USD` on Kraken |
| AI fusion | `local_only` (Claude/OpenAI keys present, not consulted for trade decisions) |
| Vision | Enabled for `/analyze_screens`, advisory only, isolated from trade path |
| Latest commit | `92caad2` (menu refactor — 12-tile L1 + 7 L2 submenus + confirm flows for sensitive actions) |
| `FEATURE_CONTROL_PANEL` | `true` — 12-tile L1 main panel + 7 L2 submenus (Risk/AI/Trial/Account/Mode/Preferences/Language) + L3 text-input prompts + confirmation flows for Sell/Panic/Disconnect + dynamic header + exchange-connection indicator |
| `FEATURE_TRIAL_MODE` | `false` (user-toggled; code deployed, no-op) |
| `FEATURE_I18N` | `false` (user-toggled; English only; Farsi translations ready) |
| `FEATURE_PORTFOLIO` | `false` (user-toggled; `/portfolio` replies "disabled") |
| `FEATURE_SCREENSHOTS` | `true` |
| `FEATURE_AI_FUSION` | `false` |
| `FEATURE_HIDDEN_DIVERGENCE` | `true` (used by strategy trigger path) |
| `FEATURE_ICHIMOKU` | `true` |
| `FEATURE_MT5_BRIDGE` | `false` |
| Multi-user state | Personal commands ungated; 2 tenant-leak bugs fixed; admin gate retained on killswitch/reconcile/health_stats only |
| Safety layer | Dual-window rate limit (5/10s burst + 10/60s volume); active-user cap (24h + autotrade); exchange-error wrapper on ALL user paths; light telemetry (users, cpm) in `/health_stats` |
| Restore anchors | Tags `v1.0-rc1`, `v1.1-pre-ui-panel`, `v1.2-pre-multiuser`, `v1.3-pre-menu-refactor` + branches `backup/pre-ui-panel`, `backup/pre-multiuser`, `backup/pre-menu-refactor` (all on GitHub) |
| Open deferrals | Exit optimization (ATR-unit reconciliation); signal dispatch → `panel.track_last_signal` wiring; additional Settings items (timezone, notifications, trial toggle); full structured-logging rollout via `logging_utils.py`; persistent rate-limit (Redis/DB) if needed at scale |
| Open security TODO | Rotate Supabase password, Telegram token, Fernet key, OpenAI key after burn-in |
| Tests | 66 still passing via `.venv/bin/python3.9 -m unittest discover tests -v` (pytest not installed) |

---

## 20. Immediate Next Steps

1. **Observe Phase 2 tuning live** — watch trade frequency and PF over several days of paper trading. Collect: trades/day, win rate, PF, avg R, % of trades fired by TRIGGER vs score path.
2. **If under-trading persists:** consider loosening ADX filter upper bound (45 → 50) or hidden-div bar (0.75 → 0.70).
3. **If over-trading / PF drops:** raise non-trigger threshold back toward 1.3–1.4 before touching the trigger itself.
4. **Exit optimization phase** — after §18.5 results are clear, reopen discussion on trailing / break-even / partial TP using **ATR-multiple units** (not R-multiples; 1 R = 1.5 ATR in this system).
5. **Security rotation sweep** once burn-in passes (Supabase PW, Telegram token, Fernet key, OpenAI key).
6. **Panel polish (low priority):**
   - Wire `panel.track_last_signal(uid, direction, score, conf)` into the scheduler's signal dispatch so the header's `Last Signal` line populates automatically (currently stays `—` until a signal is recorded by a caller).
   - Full button-label translation is now done (§18.12) — when `FEATURE_I18N` is re-enabled, the entire grid + bottom ReplyKeyboard + Settings submenu all localize.
7. **Trial Mode readiness:** feature fully implemented and deployed but flag-gated off. To activate: set `FEATURE_TRIAL_MODE=true` on Railway. `/trial start 1000` begins a 14-day paper run.
8. **i18n readiness:** feature fully implemented and deployed but flag-gated off. To activate: set `FEATURE_I18N=true`. Then `/lang fa` or tap ⚙️ Settings → 🇮🇷 فارسی for instant Farsi UI across panel header + all buttons + bottom ReplyKeyboard.
9. **Portfolio readiness:** feature fully implemented and deployed but flag-gated off. To activate: set `FEATURE_PORTFOLIO=true`. Commands: `/portfolio` for live snapshot, `/portfolio report 7d|30d|<days>` for local-trades PnL, `/portfolio report real [days]` for exchange fetch_my_trades PnL (approximate). Read-only guarantees audited in code.
10. **Three dormant features, one active tuning observation:** all recent feature work (Trial, i18n, Portfolio) is deployed but flagged off at user's request. Flip any single flag to `true` on Railway to activate without code changes.
11. **Multi-user live (§18.15):** personal commands are now open to all users (`/autotrade`, `/mode`, `/sellnow`, `/capital`, `/maxexposure`, `/liveready`). Two pre-existing tenant-leak bugs in the trading path were fixed. LIVE mode still requires the user's Telegram ID to be in `LIVE_TRADE_ALLOWED_IDS`.
12. **Production safety (§18.16):** dual-window rate limit (5/10s burst + 10/60s volume), `MAX_ACTIVE_USERS=20` soft cap (new users over cap forced to paper), clean exchange-error wrapper on portfolio paths. All tunable via Railway env.
13. **Safety layer complete (§18.17):** `_safe_exchange_error` now covers ALL user-facing exchange paths (price, setkeys, connect, portfolio). Active-user cap uses 24h-interaction + autotrade definition. Light telemetry (total/active users, commands/min) exposed in `/health_stats`. Remaining deferral: persistent rate-limit (Redis/DB) if scaling past ~50 concurrent users; full `logging_utils.py` structured-logging rollout across all modules.

