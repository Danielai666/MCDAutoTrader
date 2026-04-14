# MCDAutoTrader — Complete Session Handoff Brief
## Give this file to a new Claude Code session to continue development

> Project: `/Volumes/MiniSSD/aiMCDtrader/`
> Repository: `MCDAutoTrader`
> Date: 2026-04-13
> Total: 34 Python files, 9,528 lines of code
> Latest commit: `8adcb09`

---

## 1. What This Project Is

MCDAutoTrader is a **multi-user autonomous AI trading platform** controlled entirely via Telegram. It supports **crypto trading** (any CCXT exchange) and **MT5 trading** (Gold/Forex/Indices via EA Bridge). It detects MACD/RSI divergences, confirms with Ichimoku/candles/market regime/fundamentals, fuses decisions from Claude + OpenAI + local heuristic, enforces 11-gate risk management, executes trades autonomously, and sends visual PNG report cards.

### Current Capabilities
- **Multi-user** with strict tenant isolation (per-user trades, guards, settings, credentials)
- **Any exchange** via CCXT (Kraken, Binance, Bybit, etc.) — user connects from Telegram
- **MT5 EA Bridge** for Gold/Forex/Indices (HMAC-authenticated REST API, feature-flagged)
- **Paper / live** trading modes per user
- **3 AI modes**: signal_only, manual_confirm (approve/reject buttons), ai_full (autonomous)
- **Divergence radar** (pre-confirmation zone detection, 4 maturity stages)
- **Regular + hidden divergence** detection
- **Ichimoku cloud** confirmation (Tenkan/Kijun cross + cloud position)
- **Candle pattern** recognition (hammer, engulfing, breakout, etc.)
- **Market regime** detection (trending/ranging/volatile)
- **Fundamental gate** (news/event risk filter — blocks or reduces size)
- **Dual-AI fusion** (Claude + OpenAI + local heuristic) with 4 policies
- **11-gate risk engine** (kill switch, exposure, drawdown, correlation, event risk, etc.)
- **ATR-based trailing stops** that tighten as profit grows
- **Correlation-aware** position gating
- **Equity curve tracking** with auto position-size reduction during drawdowns
- **Two-phase trade execution** (PENDING → OPEN/FAILED) with crash recovery
- **Operation-ID idempotency** (prevents duplicate trades across restarts)
- **Per-user asyncio locks** (prevents concurrent execution for same user)
- **Exchange reconciliation** (/reconcile)
- **Live-readiness check** (/liveready)
- **Visual PNG report cards** (Market Overview with 4 gauges, Signal Card, Daily Report)
- **Screenshot analysis** (up to 12 images via Telegram, AI vision analysis)
- **Envelope encryption** (AEAD V2) for exchange API keys, rotation-ready
- **Rate limiting** (10 cmd/min/user on all commands)
- **Per-trade close reports** (auto-sent with PnL, R:R, duration)
- **Timezone-aware daily reports** (sent at user's local 20:00)
- **Panic stop** per-user emergency control
- **PostgreSQL** (production) + **SQLite** (dev) dual support
- **Railway** deployment ready

---

## 2. File Map (34 files, 9,528 LOC)

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
| `risk.py` | 475 | 11-gate risk engine, position sizing, trailing stops, correlation, drawdown, event risk |
| `trade_executor.py` | 366 | Two-phase PENDING→OPEN execution, dedup lock, operation_id idempotency, crash recovery |
| `trading_provider.py` | 69 | ITradingProvider ABC interface |
| `ccxt_provider.py` | 149 | CCXTProvider + PaperProvider for any CCXT exchange |
| `mt5_provider.py` | 139 | MT5Provider — commands queued for EA pickup |
| `exchange.py` | 127 | Public/authenticated client split, backward-compat wrappers |

### MT5 EA Bridge
| File | LOC | Purpose |
|------|-----|---------|
| `mt5_bridge.py` | 448 | FastAPI REST server, HMAC auth, nonce/timestamp replay protection, symbol mapping, lot sizing, session rules |

### Infrastructure
| File | LOC | Purpose |
|------|-----|---------|
| `config.py` | 171 | Settings dataclass (120+ env vars) |
| `storage.py` | 828 | Dual DB (SQLite/PostgreSQL), 14 tables, backend-aware upserts, migrations |
| `user_context.py` | 161 | UserContext dataclass — loads per-user settings + decrypted credentials |
| `crypto_utils.py` | 210 | Envelope encryption (AEAD V2) + Fernet (V1 compat) + masking |
| `logging_utils.py` | 101 | Structured JSON logging, correlation_id, secret redaction |
| `scheduler.py` | 504 | Two-phase cycle: shared analysis + per-user execution, mode gating, per-user locks |

### Interface & Reporting
| File | LOC | Purpose |
|------|-----|---------|
| `telegram_bot.py` | 1,785 | Full Telegram UX: 40+ commands, inline keyboards, connect flow, guard checks, visual cards, screenshot analysis |
| `notifier.py` | 52 | Async Telegram notification helpers |
| `reports.py` | 269 | Performance analytics, formatted reports, per-trade close reports, CSV export |
| `reconcile.py` | 402 | Exchange reconciliation + 10-point live-readiness check |
| `screenshot_analyzer.py` | 310 | Batch screenshot analysis via AI vision (Claude/GPT-4o) |

### Visual Cards
| File | LOC | Purpose |
|------|-----|---------|
| `visuals/gauges.py` | 227 | Composite scoring (0-100) + semicircular gauge renderer |
| `visuals/cards.py` | 470 | Signal Card, Market Overview Card (4 gauges incl. Event Risk), Daily Report Card |
| `visuals/__init__.py` | 1 | Package init |

### Operations
| File | LOC | Purpose |
|------|-----|---------|
| `pair_manager.py` | 179 | Multi-pair watchlist (per-user scoped) |
| `validators.py` | 153 | Startup validation checks |
| `main.py` | 152 | Legacy entry point |
| `backtest.py` | 2 | Placeholder |

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
| `bot_state` | Key-value state (global keys + per-user keys like `peak_equity_{uid}`) |
| `operation_log` | Idempotency tracking (operation_id prevents duplicate trades) |
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
=== PER-USER from here ===
  ↓
Mode Gate (signal_only → stop, manual_confirm → buttons, ai_full → continue)
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

| Gate | Check | Source |
|------|-------|--------|
| 1 | Kill switch | KILL_SWITCH global |
| 2 | Max open trades | per-user max_open_trades |
| 3 | Portfolio exposure | per-user capital × max_portfolio_exposure |
| 4 | Daily loss limit | per-user daily_loss_limit |
| 5 | Daily trade count | MAX_DAILY_TRADES |
| 6 | Post-trade cooldown | COOLDOWN_AFTER_TRADE_SECONDS |
| 7 | Consecutive loss pause | CONSECUTIVE_LOSS_COOLDOWN |
| 8 | Duplicate trade | Same user + pair + side |
| 9 | Correlation risk | CORRELATION_THRESHOLD |
| 10 | Event risk (fundamental) | score ≥ 75 → block, 50-75 → reduce size |
| 11 | Drawdown halt | DRAWDOWN_HALT_THRESHOLD (25%) |

---

## 7. Visual Cards

| Card | Command | Gauges | Cache |
|------|---------|--------|-------|
| Market Overview | /status | Market Mood, Momentum, Risk, Event Risk | 60s |
| Signal Card | /signal | N/A (candlestick chart + RSI + MACD + info box) | None |
| Daily Report | /report | N/A (equity curve + win/loss donut + 8 metrics) | 5min |

Gauge composite: 35% Trend + 30% Divergence + 20% Momentum + 10% Candle + 5% Volatility.

---

## 8. Telegram Commands (40+)

### Core
`/start`, `/menu`, `/help`, `/status` (PNG), `/signal` (PNG), `/price`, `/report` (PNG)

### Trading Control
`/autotrade on|off`, `/mode paper|live`, `/risk daily <usd>`, `/sellnow`, `/killswitch`, `/panic_stop`

### Guards
`/sl`, `/tp`, `/trail`, `/cancel sl|tp|trail|all`, `/guards`, `/checkguards`

### Pair Management
`/pairs`, `/addpair`, `/rmpair`, `/ranking`

### Reports & Analytics
`/positions`, `/trades`, `/pnl`, `/blocked`, `/divzones`, `/divradar`

### Admin & Ops
`/health`, `/ai`, `/reconcile [fix]`, `/liveready`, `/capital`, `/maxexposure`

### Multi-User
`/setkeys <key> <secret>`, `/myaccount`
Connect Exchange button flow (select exchange → enter key → enter secret → validate → save)

### Screenshot Analysis
`/analyze_screens` → send up to 12 chart images → `/done`

---

## 9. Encryption

**V1 (legacy):** Fernet with `CREDENTIAL_ENCRYPTION_KEY`.
**V2 (production):** Envelope encryption (AEAD). Per-record DataKey (AESGCM-256) encrypted by MasterKey. Rotation-ready via `ENCRYPTION_MASTER_KEY_V{N}`.

---

## 10. MT5 EA Bridge

- FastAPI REST server (separate service): `uvicorn mt5_bridge:create_bridge_app --factory`
- HMAC-SHA256 auth per request: `X-Bridge-Token`, `X-User-ID`, `X-Timestamp`, `X-Nonce`, `X-Signature`
- Nonce + timestamp replay protection (30s window, stored in mt5_nonces table)
- Endpoints: `/trade/open`, `/trade/close`, `/trade/update`, `/signals`, `/heartbeat`, `/health`
- Per-user symbol mapping (canonical XAUUSD → broker GOLD)
- Lot sizing: `compute_mt5_lot_size()` from capital/risk%/stop/tick_value
- Session rules: `is_market_open()`, `is_in_rollover_window()`, `check_spread_guard()`
- Feature-flagged: `FEATURE_MT5_BRIDGE=false`

---

## 11. Multi-Tenant Architecture

1. Every command extracts `uid = update.effective_user.id`
2. `UserContext.load(uid)` reads users + user_settings + credentials tables, decrypts keys
3. All queries include `WHERE user_id=?`
4. Scheduler: shared market analysis once → per-user execution with asyncio locks
5. Guard checks iterate per-user (only user's trades affected)
6. Reports/notifications scoped to requesting user
7. All parameters optional with `=None` default for backward compat

---

## 12. Deployment

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
CREDENTIAL_ENCRYPTION_KEY=xxx
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

## 13. Commit History (This Session — 20 commits)

| Commit | Description |
|--------|-------------|
| `0907f44` | ATR trailing stops, correlation risk gate, equity/drawdown management |
| `5caef43` | Production hardening: PostgreSQL, restart safety, reconciliation, execution integrity |
| `0cedab8` | BOT_REFERENCE.md complete technical reference |
| `7e3d99e` | Critical bug fixes: multi-pair guards, cached equity, per-TF exceptions |
| `d0b0f6a` | Multi-tenant Phase 1-2: UserContext, schema migration, exchange split |
| `1902bc8` | Multi-tenant Phase 3-4: user_id threading through risk, reports, pair manager |
| `5e3b427` | Multi-tenant Phase 5-7: per-user scheduler, guards, commands |
| `e954fb6` | Spec A.1-A.5: credentials table, envelope encryption, provider interface, Ichimoku |
| `0d3d704` | Visual reporting layer: signal cards, market overview, daily report |
| `19fa95f` | Idempotency, mode gating, per-user locks, panic_stop, rate limiter |
| `4146f48` | Manual confirm handler, connect exchange state machine |
| `dc03d7f` | Rate limiter on all commands, per-trade close reports, tz daily reports |
| `7e46ce9` | Fundamental gate — news/event risk filter + visual integration |
| `6698e62` | MT5 EA Bridge + provider + symbol mapping + lot sizing |
| `d033030` | Screenshot batch analysis (up to 12 images via Telegram) |

---

## 14. What's Complete

### Phase A (Spec "Must Now") — ALL DONE
- Multi-tenant data model + schema migrations (14 tables)
- Envelope encryption (AEAD V2) for exchange API keys
- ITradingProvider interface + CCXT + Paper + MT5 providers
- Per-user risk engine (11 gates including event risk)
- Two-phase trade execution with crash recovery + operation_id idempotency
- Per-user scheduler (shared analysis + isolated execution + asyncio locks)
- Per-user guard checks (SL/TP/ATR trailing)
- Mode/ai_mode gating (signal_only / manual_confirm / ai_full)
- Connect Exchange guided Telegram flow (state machine with secret deletion)
- Rate limiter on all commands (10/min/user)
- Per-trade close reports (auto-sent with PnL, R:R, duration)
- Timezone-aware daily reports (user's local 20:00)
- /panic_stop per-user emergency control
- Fundamental gate (news/event risk filter with visual gauge)
- Exchange reconciliation + live-readiness check

### Phase B (Spec "Next") — ALL DONE
- Visual PNG report cards (Market Overview, Signal Card, Daily Report)
- MT5 EA Bridge (FastAPI + HMAC auth + replay protection + symbol mapping + lot sizing)
- MT5Provider implementing ITradingProvider
- Screenshot batch analysis (up to 12 images, Claude/GPT-4o vision)

### Phase C (Fundamental Gate) — DONE
- News/event risk scoring (time-based + volatility spike + manual override)
- Integrated as risk gate 10 + position size reducer
- Event Risk gauge on Market Overview card

---

## 15. What Remains To Build

### Future Features
| Item | Priority | Complexity |
|------|----------|-----------|
| Backtesting command (/backtest) | Medium | Medium |
| Top-10 market dynamic reporting (/top10) | Medium | Low |
| Upcoming/new coin intelligence (/newcoins) | Low | Medium |
| Web dashboard | Low | High |
| Billing/subscription system | Low | High |
| Strategy threshold calibration | Medium | Low |

### Infrastructure / Testing
| Item | Priority |
|------|----------|
| Test against real Supabase PostgreSQL instance | High |
| Multi-user live testing with 2+ accounts | High |
| MT5 EA Bridge testing with real MetaTrader 5 | Medium |
| Screenshot analysis testing with real charts | Medium |

---

## 16. Known Technical Debt

| Issue | Severity |
|-------|----------|
| PostgreSQL not tested against real Supabase | Medium |
| main.py is legacy (actual entry is telegram_bot.build_app()) | Low |
| backtest.py is placeholder | Low |
| exchange.py has old wrapper functions alongside ITradingProvider | Low |
| No automated test suite | Medium |

---

## 17. Instructions for Next Session

1. **Read this file first.**
2. **Do not rewrite from scratch.** The architecture is stable (34 files pass syntax check).
3. **Priority order for next work:**
   - Test with real Supabase PostgreSQL
   - Test multi-user with 2+ Telegram accounts
   - Add /backtest command
   - Add /top10 market reporting
   - Strategy threshold tuning
4. **Always run syntax check:** `/usr/bin/python3 -c "import ast; ..."` on all .py files.
5. **Commit after each logical unit.**
6. **Preserve all existing commands and functionality.**
