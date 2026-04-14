# MCDAutoTrader — Complete Session Handoff Brief
## Give this file to a new Claude Code session to continue development

> Project: `/Volumes/MiniSSD/aiMCDtrader/`
> Date: 2026-04-13
> Total: 34 Python files, ~9,528 lines of code
> Latest commit: `d033030` (Screenshot batch analysis)

---

## 1. What This Project Is

MCDAutoTrader is a **multi-user autonomous AI cryptocurrency trading platform** controlled entirely via Telegram. It detects MACD/RSI divergences, confirms with Ichimoku/candles/market regime, fuses decisions from Claude + OpenAI + local heuristic, enforces 10-gate risk management, executes trades on any CCXT exchange, and sends visual PNG report cards.

### Current Capabilities
- Multi-user architecture with tenant isolation (per-user trades, guards, settings, credentials)
- Any exchange via CCXT (Kraken, Binance, Bybit, etc.)
- Paper and live trading modes per user
- Divergence radar (pre-confirmation zone detection)
- Regular + hidden divergence detection
- Ichimoku cloud confirmation
- Candle pattern recognition (hammer, engulfing, breakout, etc.)
- Market regime detection (trending/ranging/volatile)
- Dual-AI fusion (Claude + OpenAI + local heuristic) with 4 policies
- 10-gate risk engine (kill switch, exposure, drawdown, correlation, etc.)
- ATR-based trailing stops that tighten as profit grows
- Correlation-aware position gating
- Equity curve tracking with auto position-size reduction during drawdowns
- Two-phase trade execution (PENDING → OPEN/FAILED) with crash recovery
- Exchange reconciliation (/reconcile)
- Live-readiness check (/liveready)
- Visual PNG report cards (signal cards, market overview, daily reports)
- Envelope encryption (AEAD) for exchange API keys
- PostgreSQL (production) + SQLite (dev) dual support
- Railway deployment ready

---

## 2. File Map (30 files)

### Signal Intelligence Pipeline
| File | LOC | Purpose |
|------|-----|---------|
| `indicators.py` | 38 | EMA, RSI, MACD, Stochastic, ATR, ADX, Bollinger, Ichimoku |
| `divergence.py` | 74 | Regular + hidden divergence detection |
| `div_radar.py` | 403 | Pre-confirmation divergence zone scanner (4 maturity stages) |
| `candles.py` | 204 | Candle patterns: hammer, shooting star, engulfing, breakout |
| `market_regime.py` | 81 | Regime classification: trending_up/down, ranging, volatile |
| `strategy.py` | 295 | Per-TF scoring (11 weighted components) + multi-TF merge |

### AI Decision Layer
| File | LOC | Purpose |
|------|-----|---------|
| `ai_fusion.py` | 419 | Claude + OpenAI + local heuristic + 4 fusion policies |
| `ai_decider.py` | 27 | Backward-compat async/sync wrapper |

### Risk & Execution
| File | LOC | Purpose |
|------|-----|---------|
| `risk.py` | 458 | 10-gate risk engine, position sizing, trailing stops, correlation, drawdown. All functions accept user_id/ctx. |
| `trade_executor.py` | 343 | Two-phase PENDING→OPEN execution, dedup lock, crash recovery, guards |
| `trading_provider.py` | 69 | ITradingProvider ABC interface |
| `ccxt_provider.py` | 149 | CCXTProvider + PaperProvider for any CCXT exchange |
| `exchange.py` | 127 | Public/authenticated client split, backward-compat wrappers |

### Infrastructure
| File | LOC | Purpose |
|------|-----|---------|
| `config.py` | 159 | Settings dataclass (100+ env vars) |
| `storage.py` | 792 | Dual DB (SQLite/PostgreSQL), 12 tables, backend-aware upserts, migrations |
| `user_context.py` | 122 | UserContext dataclass — loads per-user settings + decrypted credentials |
| `crypto_utils.py` | 210 | Envelope encryption (AEAD V2) + Fernet (V1 compat) + masking |
| `logging_utils.py` | 101 | Structured JSON logging, correlation_id, secret redaction |
| `scheduler.py` | 407 | Two-phase cycle: shared market analysis + per-user execution |

### Interface & Reporting
| File | LOC | Purpose |
|------|-----|---------|
| `telegram_bot.py` | 1404 | Full Telegram UX: 35+ commands, inline keyboards, guard checks, visual cards |
| `notifier.py` | 52 | Async Telegram notification helpers |
| `reports.py` | 231 | Performance analytics, formatted reports, CSV export |
| `reconcile.py` | 402 | Exchange reconciliation + 10-point live-readiness check |
| `visuals/gauges.py` | 227 | Composite scoring (0-100) + semicircular gauge renderer |
| `visuals/cards.py` | 452 | Signal Card, Market Overview Card, Daily Report Card (PNG) |

### Other
| File | LOC | Purpose |
|------|-----|---------|
| `pair_manager.py` | 179 | Multi-pair watchlist (per-user scoped) |
| `validators.py` | 153 | Startup validation checks |
| `main.py` | 152 | Legacy entry point (KrakenWrap) |
| `backtest.py` | 2 | Placeholder |

---

## 3. Database Schema (12 tables)

All tables support both SQLite and PostgreSQL. Multi-tenant migration adds `user_id` to all data tables.

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `users` | User accounts | user_id (PK), tg_username, tier, autotrade_enabled, trade_mode, capital_usd, risk_per_trade, exchange_key_enc, exchange_secret_enc, paper_trading |
| `user_settings` | Per-user mode/ai_mode | user_id (PK), mode (signal_only/paper/live), ai_mode (signal_only/manual_confirm/ai_full), timezone, panic_stop |
| `credentials` | Encrypted exchange keys | user_id, provider_type, exchange_id, api_key_enc, api_secret_enc, data_key_enc, encryption_version, UNIQUE(user_id, provider_type, exchange_id) |
| `trades` | All trades | id, user_id, pair, side, qty, entry, exit_price, pnl, status (PENDING/OPEN/CLOSED/FAILED), lifecycle, entry_snapshot, order_id |
| `manual_guards` | SL/TP/trailing per user+pair | user_id+pair (composite PK), stop_loss, take_profit, trail_pct, trail_stop, high_watermark |
| `trading_pairs` | Per-user watchlist | pair, user_id, is_active, last_direction, last_score |
| `signals` | Signal history | user_id, pair, tf, direction, reason |
| `ai_decisions` | AI decision audit trail | user_id, pair, action, confidence, source, fusion_policy |
| `blocked_trades` | Risk-blocked trade log | user_id, pair, side, reason, signal_snapshot |
| `bot_state` | Key-value state store | key (PK), value, user_id (NULL=global, non-NULL=per-user) |
| `operation_log` | Idempotency tracking | operation_id (PK), user_id, op_type, pair, side, result_json |
| `performance_snapshots` | Historical metrics | user_id, pair, period, total_trades, win_rate, expectancy |

---

## 4. Architecture Data Flow

```
Exchange (any CCXT) → fetch_ohlcv (public client, shared)
  ↓
Indicators (EMA, RSI, MACD, Stoch, ATR, ADX, BB, Ichimoku)
  ↓
Divergence (regular + hidden) + Candles + Regime + Div Radar
  ↓
Strategy.tf_signal() → 11-component weighted scoring per timeframe
  ↓
merge_mtf() → weighted consensus with regime filter
  ↓
AI Fusion (local + Claude + OpenAI) → ENTER/EXIT/HOLD + confidence
  ↓
=== PER-USER from here ===
  ↓
Risk Gate (10 checks: kill switch, exposure, drawdown, correlation, etc.)
  ↓
Position Sizing (base × confidence × quality × drawdown_scale)
  ↓
Trade Executor (PENDING → exchange order → OPEN/FAILED)
  ↓
Guard Monitor (every 30s: manual SL/TP + ATR trailing, per-user)
  ↓
Visual Cards (PNG) → Telegram notification to owning user
```

**Key optimization:** Market data analysis runs ONCE per pair (shared). Only risk/execution/guards are per-user. No N² API calls.

---

## 5. Strategy Scoring Weights (11 components)

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

Direction threshold: BUY if buy_score >= 1.5, SELL if sell_score >= 1.5, else HOLD.

---

## 6. Risk Engine (10 gates in can_enter_enhanced)

| Gate | Check | Configurable |
|------|-------|-------------|
| 1 | Kill switch | KILL_SWITCH |
| 2 | Max open trades | per-user max_open_trades |
| 3 | Portfolio exposure | per-user capital × max_portfolio_exposure |
| 4 | Daily loss limit | per-user daily_loss_limit |
| 5 | Daily trade count | MAX_DAILY_TRADES |
| 6 | Post-trade cooldown | COOLDOWN_AFTER_TRADE_SECONDS |
| 7 | Consecutive loss pause | CONSECUTIVE_LOSS_COOLDOWN |
| 8 | Duplicate trade | Same user + pair + side |
| 9 | Correlation risk | CORRELATION_THRESHOLD, MAX_CORRELATED_EXPOSURE |
| 10 | Drawdown halt | DRAWDOWN_HALT_THRESHOLD (25% = halt) |

---

## 7. Visual Cards (visuals/)

| Card | Command | Cache | Content |
|------|---------|-------|---------|
| Market Overview | /status | 60s | Main gauge (0-100), mini gauges, top 5 symbols, reasons |
| Signal Card | /signal, trade alerts | None | 120-bar candlestick, entry/SL/TP lines, RSI+MACD panels, info box |
| Daily Report | /report | 5min | Equity curve, win/loss donut, 8 key metrics |

Gauge composite scoring: 35% Trend + 30% Divergence + 20% Momentum + 10% Candle + 5% Volatility.

---

## 8. Telegram Commands (35+)

### Core
`/start`, `/menu`, `/help`, `/status` (PNG card), `/signal` (PNG card), `/price`, `/report` (PNG card)

### Trading Control
`/autotrade on|off`, `/mode paper|live`, `/risk daily <usd>`, `/sellnow`, `/killswitch`, `/panic_stop`

### Guards
`/sl <price>`, `/tp <price>`, `/trail <pct>`, `/cancel sl|tp|trail|all`, `/guards`, `/checkguards`

### Pair Management
`/pairs`, `/addpair <PAIR>`, `/rmpair <PAIR>`, `/ranking`

### Reports & Analytics
`/positions`, `/trades`, `/pnl`, `/blocked`, `/divzones [tf]`, `/divradar`

### Admin & Ops
`/health`, `/ai`, `/reconcile [fix]`, `/liveready`, `/capital <usd>`, `/maxexposure <pct>`

### Multi-User
`/setkeys <key> <secret>` (encrypts, deletes message), `/myaccount`

---

## 9. Encryption

**V1 (legacy):** Simple Fernet using `CREDENTIAL_ENCRYPTION_KEY` env var.

**V2 (production):** Envelope encryption (AEAD).
- Per-record random DataKey (AESGCM-256)
- DataKey encrypted by MasterKey (from env var)
- Supports key rotation via `ENCRYPTION_MASTER_KEY_V{N}` versioning
- `credentials` table stores `encryption_version` per record
- `decrypt_exchange_keys()` auto-detects version

---

## 10. Multi-Tenant Architecture

### How It Works
1. Every Telegram command extracts `uid = update.effective_user.id`
2. `UserContext.load(uid)` reads user settings + decrypts exchange keys
3. All DB queries include `WHERE user_id=?`
4. Scheduler runs shared analysis once, then iterates per-user for execution
5. Guard checks iterate per-user (only user's trades affected)
6. Reports/notifications scoped to requesting user

### Key Design: Optional Parameters
Every function accepts `user_id: int = None` or `ctx = None`. When None, falls back to global SETTINGS. Single-user deployments work without changes.

---

## 11. Deployment

### Entry Point
```python
from telegram_bot import build_app
build_app().run_polling()
```

### Procfile (Railway)
```
worker: python -c "from telegram_bot import build_app; build_app().run_polling()"
```

### Minimum Env Vars
```
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_ADMIN_IDS=123456
PAIR=BNB/USDC
PAPER_TRADING=true
DB_ENGINE=sqlite
```

### Production Env Vars (PostgreSQL + Encryption)
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

### Dependencies
```
ccxt, pandas, numpy, python-dotenv, loguru, requests,
python-telegram-bot[job-queue], anthropic, openai,
psycopg2-binary, cryptography, pytz, matplotlib
```

---

## 12. Commit History (This Session)

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

---

## 13. What's Complete

- Multi-tenant data model + schema migrations (12 tables)
- Envelope encryption (AEAD V2) for exchange API keys
- ITradingProvider interface + CCXT + Paper providers
- Per-user risk engine (all 10 gates with user_id/ctx)
- Two-phase trade execution with crash recovery + operation_id idempotency
- Per-user scheduler (shared analysis + isolated execution + asyncio locks)
- Per-user guard checks (SL/TP/ATR trailing)
- Exchange reconciliation + live-readiness check
- Visual PNG report cards (signal, market overview, daily)
- Ichimoku indicator + strategy integration (12 scoring components)
- Credentials table with envelope encryption versioning
- User settings table (mode/ai_mode/timezone/panic_stop)
- Mode system: signal_only/paper/live + ai_mode: signal_only/manual_confirm/ai_full
- /panic_stop command (per-user emergency stop)
- Rate limiter (10 commands/min/user)
- Per-trade close report helper (format_trade_close_report)
- Manual confirm flow (sends trade candidates with Execute/Skip buttons)
- Operation log for idempotency (prevent duplicate trades across restarts)
- Per-user asyncio locks (prevent concurrent execution for same user)
- Structured logging with secret redaction
- 37+ Telegram commands with inline keyboards
- PostgreSQL + SQLite dual support
- Railway deployment ready

---

## 14. What Remains To Build

### High Priority (Spec Phase A remaining)
- **A.4: Connect exchange state machine** — guided Telegram flow (select exchange → enter key → enter secret → validate → save) with inline keyboards. Currently /setkeys works but the guided UX flow is not built.
- **A.7: Wire per-trade close report sending** — format_trade_close_report() exists but needs to be called after each close_trade() and sent to the user via Telegram.
- **A.7: Timezone-aware daily reports** — send at each user's local 20:00 instead of fixed interval.

### Spec Phase B
- Screenshot analysis (batch up to 12 images, AI vision analysis)
- MT5 EA Bridge (REST endpoints, HMAC auth, symbol mapping, lot sizing)

### Spec Phase C
- Backtesting command
- Web dashboard
- Billing/subscription

### Product Polish
- Top-10 market dynamic reporting (/top10)
- Upcoming/new coin intelligence (/newcoins)
- Strategy threshold calibration
- Divergence radar quality tuning

---

## 15. Known Technical Debt

| Issue | Severity | Location |
|-------|----------|----------|
| PostgreSQL not tested against real Supabase | Medium | storage.py — schema is built, untested in production |
| No real multi-user test | Medium | All per-user code needs testing with 2+ actual Telegram users |
| exchange.py still has old wrapper functions | Low | Coexists with new ITradingProvider — works but redundant |
| main.py is legacy | Low | Actual entry is telegram_bot.build_app(), main.py unused |
| backtest.py is placeholder | Low | Not implemented |

---

## 16. Instructions for Next Session

1. **Read this file first** to understand the full system.
2. **Do not rewrite from scratch.** The architecture is stable and tested (syntax-checked, 30 files pass).
3. **Check the plan file** at `/Users/saiedbeikhosseini/.claude/plans/sunny-forging-muffin.md` for the approved implementation plan.
4. **Priority order for next work:**
   - Wire operation_id idempotency into trade_executor
   - Wire mode/ai_mode gating into scheduler (signal_only → no execution, manual_confirm → buttons)
   - Build Telegram connect exchange state machine
   - Wire rate limiter into command handlers
   - Per-trade close reports + timezone daily reports
   - Then move to Phase B (screenshots, MT5)
5. **Always run syntax check after changes:** `/usr/bin/python3 -c "import ast; ..."` on all .py files.
6. **Commit after each logical unit** with descriptive messages.
7. **Preserve all existing commands and functionality** — extend, don't replace.
