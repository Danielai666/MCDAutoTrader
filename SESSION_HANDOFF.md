# MCDAutoTrader — Complete Session Handoff Brief
## Give this file to a new Claude Code session to continue development

> Project: `/Volumes/MiniSSD/aiMCDtrader/`
> Repository: `MCDAutoTrader`
> Date: 2026-04-13
> Total: 40 Python files, 11,238 lines of code (including 748 lines of tests)
> Tests: 66 automated tests, all passing
> Release: v1.0-rc1 (feature freeze — Go-Live Trust Mode)
> Latest commit: `0c3c256`

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
   - Deploy to Railway + Supabase and verify
   - Test with 2+ Telegram users
   - /top10 market reporting
   - Strategy tuning
5. **Always run syntax check** after changes.
6. **Commit after each logical unit.**
7. **Preserve all existing commands and functionality.**
