# MCDAutoTrader — Full Session Summary
**Date:** April 13, 2026
**Bot:** @AiMCDAutoTrader_bot
**GitHub:** https://github.com/Danielai666/MCDAutoTrader
**Railway:** Deployed and running 24/7
**Supabase Project:** MCDAutoTrader (pzxmfjlllfvqybwxfngh) — tables created, not yet connected
**Project Path:** `/Volumes/MiniSSD/aiMCDtrader/`

---

## How to Continue in a New Chat
Say this:
> Read /Volumes/MiniSSD/aiMCDtrader/SESSION_COMPLETE.md and continue working on this trading bot

---

## What Was Built (8 Phases)

### Phase 1: Foundation
**Files changed:** config.py, storage.py, validators.py (NEW), Procfile (NEW), .env.example, requirements.txt

- **config.py** — Expanded from 24 to 50+ settings organized into sections:
  - Feature flags: FEATURE_MULTI_PAIR, FEATURE_AI_FUSION, FEATURE_CANDLE_PATTERNS, FEATURE_HIDDEN_DIVERGENCE, FEATURE_MARKET_REGIME (all default false)
  - AI Fusion: CLAUDE_API_KEY, CLAUDE_MODEL, OPENAI_API_KEY, OPENAI_MODEL, AI_FUSION_POLICY, AI_TIMEOUT_SECONDS
  - Multi-pair: DEFAULT_PAIRS, MAX_WATCHED_PAIRS, PAIR_MODE
  - Risk: COOLDOWN_AFTER_TRADE_SECONDS, MAX_DAILY_TRADES, CONSECUTIVE_LOSS_COOLDOWN, CONSECUTIVE_LOSS_PAUSE_SECONDS, BREAK_EVEN_ATR_MULTIPLIER
  - Controls: KILL_SWITCH, DRY_RUN_MODE
  - Candle patterns: CANDLE_WICK_RATIO, CANDLE_BODY_RATIO
  - Market regime: REGIME_EMA_FAST, REGIME_EMA_SLOW, REGIME_ADX_THRESHOLD, REGIME_VOLATILITY_LOOKBACK
  - Scheduler: ANALYSIS_INTERVAL_SECONDS, GUARD_CHECK_INTERVAL_SECONDS, HEALTH_CHECK_INTERVAL_SECONDS
  - Database: DB_ENGINE, SUPABASE_URL, SUPABASE_DB_HOST, SUPABASE_DB_PORT, SUPABASE_DB_NAME, SUPABASE_DB_USER, SUPABASE_DB_PASSWORD, SUPABASE_SCHEMA

- **storage.py** — Dual database engine (SQLite local + PostgreSQL Supabase):
  - 9 tables total: users, signals, trades, manual_guards, trading_pairs, ai_decisions, blocked_trades, bot_state, performance_snapshots
  - Auto-migration for trades table (adds lifecycle, entry_snapshot, exit_snapshot, trade_type columns)
  - Query placeholder conversion (? for SQLite, %s for PostgreSQL)
  - `DB_ENGINE=sqlite` for local, `DB_ENGINE=postgres` for Supabase

- **validators.py** (NEW) — Startup validation:
  - `validate_config()` — checks all settings for errors/warnings
  - `validate_exchange()` — tests Kraken connectivity and pair validity
  - `validate_telegram()` — verifies bot token works
  - `validate_db()` — checks database accessibility
  - `run_all_checks()` — runs all validators, returns formatted summary

- **Procfile** (NEW) — Railway deployment: `worker: python -c "from telegram_bot import build_app; build_app().run_polling()"`
- **.env.example** — Complete template with all 50+ keys and comments
- **requirements.txt** — Added: anthropic, openai, python-telegram-bot[job-queue], psycopg2-binary

### Phase 2: Smarter Signals
**Files changed:** market_regime.py (NEW), candles.py (NEW), divergence.py, strategy.py

- **market_regime.py** (NEW) — Market regime detection:
  - `detect_regime(df)` returns RegimeResult with regime type and confidence
  - Types: trending_up, trending_down, ranging, volatile
  - Uses: EMA fast/slow crossover, ADX for trend strength, ATR percentile for volatility
  - Gated behind FEATURE_MARKET_REGIME flag

- **candles.py** (NEW) — Candle pattern detection (7 patterns):
  - Hammer (bullish reversal)
  - Shooting star (bearish reversal)
  - Bullish engulfing
  - Bearish engulfing
  - Rejection wick (bullish and bearish)
  - Breakout candle (with volume confirmation)
  - `detect_patterns(df)` returns list of CandlePattern with name, direction, strength
  - `summarize_patterns()` returns bullish/bearish counts, net score, strongest pattern
  - Gated behind FEATURE_CANDLE_PATTERNS flag

- **divergence.py** — Added hidden divergence:
  - `detect_hidden_divergence(price, osc)` — hidden bullish (price higher low, osc lower low) and hidden bearish (price lower high, osc higher high)
  - `detect_all_divergences(price, osc)` — returns both regular and hidden in one dict
  - Gated behind FEATURE_HIDDEN_DIVERGENCE flag

- **strategy.py** — Wired all new modules into tf_signal():
  - Hidden divergence adds weight 1.0 * strength (trend continuation signals)
  - Candle patterns add weight 0.75 * net_score
  - Market regime replaces simple 1d direction with rich regime classification
  - `build_score_breakdown()` — structured explainable output with per-timeframe components
  - All new features are feature-flag gated — when flags are false, behavior is identical to before

### Phase 3: Dual-AI Engine
**Files changed:** ai_fusion.py (NEW), ai_decider.py, scheduler.py

- **ai_fusion.py** (NEW, ~250 lines) — Three-source AI decision engine:
  - `AIDecision` dataclass: action, side, confidence, setup_quality, reasons, warnings, risk_flags, source, latency_ms
  - `FusionResult` dataclass: final_action, final_side, final_confidence, policy_used, decisions list, consensus_notes
  - `_build_prompt(features)` — builds structured market snapshot for LLMs (pair, regime, per-TF indicators, divergences, candle patterns)
  - `_call_claude(features)` — async call to Anthropic API with timeout
  - `_call_openai(features)` — async call to OpenAI API with timeout
  - `_local_heuristic(features)` — enhanced version of original heuristic using ADX, RSI, BB context
  - `_fuse_decisions(local, remotes, policy)` — 4 fusion policies:
    - `local_only` — only use local heuristic (default, no API cost)
    - `advisory` — local decides, remote shown as notes
    - `majority` — vote across all sources, ties = HOLD
    - `strict_consensus` — all must agree, else HOLD
  - `decide(features)` — main async entry: runs local + optional Claude/OpenAI concurrently, fuses, logs to ai_decisions table
  - Gated behind FEATURE_AI_FUSION flag

- **ai_decider.py** — Now thin wrapper over ai_fusion:
  - `decide_async(features)` — async, returns fusion result as dict
  - `decide(features)` — sync fallback for backward compatibility

- **scheduler.py** — Uses async `decide_async()`, includes fusion details in Telegram messages

### Phase 4: Risk Management Upgrades
**Files changed:** risk.py, scheduler.py

- **risk.py** — Expanded from 30 to ~170 lines:
  - `trade_count_today()` — count trades opened in last 24h
  - `last_trade_ts(pair)` — timestamp of most recent trade
  - `consecutive_losses(pair)` — count of consecutive losing trades
  - `is_in_cooldown(pair)` — True if within COOLDOWN_AFTER_TRADE_SECONDS
  - `is_consecutive_loss_paused()` — True if CONSECUTIVE_LOSS_COOLDOWN losses in a row
  - `is_duplicate_trade(pair, side)` — True if same pair+side already open
  - `can_enter_enhanced(pair, side)` — combined gate checking ALL of:
    1. Kill switch
    2. Open trades limit
    3. Daily loss limit
    4. Daily trade count
    5. Cooldown after trade
    6. Consecutive loss pause
    7. Duplicate trade prevention
    8. Dry run mode (allows but flags)
  - `log_blocked_trade()` — writes to blocked_trades table when entry is denied
  - `should_move_to_break_even()` — True if price moved BREAK_EVEN_ATR_MULTIPLIER * ATR in favor
  - `position_size(price, atr_value)` — ATR-based qty sizing
  - `atr_stop_loss(entry_price, atr_value, side)` — dynamic SL placement

- **scheduler.py** — Uses `can_enter_enhanced()` instead of simple `can_enter()`, blocked trades show reason in Telegram

### Phase 5: Multi-Pair Watchlist
**Files changed:** pair_manager.py (NEW), exchange.py, scheduler.py

- **pair_manager.py** (NEW) — Watchlist management:
  - `get_active_pairs()` — returns [SETTINGS.PAIR] when FEATURE_MULTI_PAIR=false, or queries trading_pairs table
  - `add_pair(pair)` — validates on exchange, checks MAX_WATCHED_PAIRS limit, adds to DB
  - `remove_pair(pair)` — deactivates pair
  - `toggle_pair(pair, active)` — enable/disable
  - `update_pair_signal(pair, direction, score)` — updates last signal info after each analysis
  - `get_pair_ranking()` — active pairs sorted by abs(last_score) descending
  - `list_all_pairs()` — all pairs with status
  - `validate_pair(pair)` — checks pair exists on exchange
  - `seed_default_pair()` — ensures SETTINGS.PAIR exists in trading_pairs table on startup

- **exchange.py** — Added:
  - `health_check()` — tests exchange connectivity
  - `validate_pair_on_exchange(pair)` — checks if pair exists

- **scheduler.py** — Multi-pair loop:
  - `_run_for_pair(app, pair, notify)` — extracted single-pair logic
  - `run_cycle_once()` — loops over `get_active_pairs()`, collects results per pair
  - Updates pair signal in watchlist after each analysis
  - Job locking via `_with_lock()` to prevent overlapping analysis runs
  - New jobs: health_check (hourly), daily_report (every 24h)

### Phase 6: Reporting + Notifications
**Files changed:** reports.py, notifier.py (NEW), trade_executor.py

- **reports.py** — Expanded from 74 to ~180 lines:
  - `performance_summary(pair, days)` — returns dict with: total_trades, winning, losing, win_rate, total_pnl, avg_win, avg_loss, expectancy, profit_factor, largest_win, largest_loss
  - `format_position_report()` — open positions with current price and unrealized PnL
  - `format_pnl_report(pair, days)` — formatted performance report
  - `daily_report(pair)` — daily summary (PnL, trades closed, open positions)
  - `blocked_trades_summary(days)` — recent blocked trades with reasons
  - `save_performance_snapshot(pair, period)` — persists metrics to performance_snapshots table
  - `export_trades_csv(filepath, pair)` — CSV export

- **notifier.py** (NEW) — Centralized Telegram notification helpers:
  - `notify_admins(app, text)` — send to all admin IDs
  - `notify_trade_opened(app, pair, side, qty, price, reason)`
  - `notify_trade_closed(app, pair, side, pnl, reason)`
  - `notify_blocked_trade(app, pair, side, reason)`
  - `notify_health_issue(app, issue)`
  - `notify_daily_report(app, report)`

- **trade_executor.py** — Updated `open_trade()` to accept entry_snapshot, supports PostgreSQL RETURNING

### Phase 7: Telegram Bot + Startup + Admin
**Files changed:** telegram_bot.py

- **telegram_bot.py** — Expanded from 680 to ~900 lines:
  - **3 new menu keyboards**: reporting_keyboard, pairs_keyboard, admin_keyboard
  - **Main menu** now has Report, Pairs, and Admin buttons
  - **12 new commands** (all have both typed and button versions):
    - `/positions` — open trades with unrealized PnL
    - `/trades [n]` — last N closed trades
    - `/pnl [days]` — performance report (win rate, expectancy, profit factor)
    - `/report` — full performance + daily summary
    - `/blocked [n]` — recent blocked trades
    - `/pairs` — watchlist with signal status per pair
    - `/addpair BTC/USDT` — validate and add pair to watchlist
    - `/rmpair BTC/USDT` — remove pair from watchlist
    - `/ranking` — pairs ranked by signal strength
    - `/health` — full system health check (config, exchange, DB, features)
    - `/ai` — last AI fusion decision details
    - `/killswitch` — toggle kill switch on/off
  - **Startup validation** via `post_init()`:
    - Calls `init_db()` to ensure all tables exist
    - Seeds default pair in trading_pairs table
    - Stores last_startup in bot_state
    - Sends startup summary to all admins
  - **Configurable guard interval** from SETTINGS.GUARD_CHECK_INTERVAL_SECONDS

### Phase 8: Deployment
- **GitHub:** Code pushed to https://github.com/Danielai666/MCDAutoTrader
- **Railway:** Deployed and running 24/7
- **Supabase:** MCDAutoTrader project created (pzxmfjlllfvqybwxfngh), trading_bot schema with 9 tables created, DNS was not yet propagated at session end

---

## Complete File Inventory (20 Python files)

| File | Lines (est.) | Purpose |
|------|-------------|---------|
| telegram_bot.py | ~900 | Telegram UI: 28 commands, 7 inline menus, callbacks, auto-exit, startup |
| ai_fusion.py | ~250 | Dual-AI: Claude + OpenAI + local heuristic + 4 fusion policies |
| reports.py | ~180 | Performance analytics, PnL reports, trade summaries |
| risk.py | ~170 | Enhanced risk gates, cooldowns, position sizing, blocked trade logging |
| storage.py | ~160 | Dual DB engine (SQLite + PostgreSQL), 9 tables, migration |
| trade_executor.py | ~150 | Trade open/close, manual guards, lifecycle |
| scheduler.py | ~200 | Multi-pair analysis loop, job locking, health checks, daily reports |
| config.py | ~130 | 50+ settings from .env with defaults |
| candles.py | ~120 | 7 candle pattern detectors |
| pair_manager.py | ~120 | Multi-pair watchlist management |
| strategy.py | ~190 | Weighted scoring, regime filter, score breakdown |
| market_regime.py | ~80 | Regime detection (trending/ranging/volatile) |
| validators.py | ~100 | Startup config/exchange/DB validation |
| ai_decider.py | ~30 | Thin wrapper over ai_fusion |
| notifier.py | ~60 | Centralized Telegram notification helpers |
| divergence.py | ~70 | Regular + hidden divergence detection |
| indicators.py | ~30 | MACD, RSI, Stochastic, EMA, ATR, ADX, Bollinger Bands |
| exchange.py | ~25 | Kraken via ccxt, health check, pair validation |
| main.py | ~153 | Legacy CLI entry point (unused by Telegram bot) |
| backtest.py | ~3 | Placeholder stub |

---

## Database Tables (9 total)

1. **users** — Telegram user profiles, tier, autotrade toggle, trade mode, risk limits
2. **signals** — Historical signal log (timestamp, pair, timeframe, direction, reason)
3. **trades** — Trade records (entry/exit, PnL, status, lifecycle, snapshots)
4. **manual_guards** — Per-user SL/TP/trailing stop settings per pair
5. **trading_pairs** — Multi-pair watchlist (active/inactive, last signal, score)
6. **ai_decisions** — Full AI decision audit log (action, confidence, source, policy, reasons, warnings)
7. **blocked_trades** — Trades rejected by risk gates (pair, side, reason, snapshot)
8. **bot_state** — Key-value runtime state (last_startup, health status)
9. **performance_snapshots** — Periodic performance summaries (win rate, PnL, expectancy)

---

## All Telegram Commands (28 total)

### Analysis
| Command | Description |
|---------|-------------|
| `/signal` | Run full multi-TF analysis |
| `/price` | Current price from Kraken |
| `/market` | Market regime overview |

### Account
| `/start` | Register + show menu |
| `/menu` | Show button menu |
| `/help` | List all commands |
| `/status` | Tier, autotrade, mode, limits |
| `/settings` | Pair, timeframes, thresholds |

### Trading
| `/autotrade on\|off` | Enable/disable auto-trading |
| `/mode paper\|live` | Switch trading mode |
| `/sellnow` | Close all open trades |

### Risk
| `/risk daily <usd>` | Set daily loss limit |
| `/sl <price>` | Set stop-loss |
| `/tp <price>` | Set take-profit |
| `/trail <percent>` | Set trailing stop (e.g. 0.05 = 5%) |
| `/guards` | View current SL/TP/trail |
| `/checkguards` | Run analysis + check guards |
| `/cancel sl\|tp\|trail\|all` | Clear guards |

### Reporting (NEW)
| `/positions` | Open positions with unrealized PnL |
| `/trades [n]` | Last N closed trades |
| `/pnl [days]` | Performance report (win rate, expectancy) |
| `/report` | Full performance + daily summary |
| `/blocked [n]` | Recent blocked trades |

### Multi-Pair (NEW)
| `/pairs` | Watchlist with signal status |
| `/addpair BTC/USDT` | Add pair to watchlist |
| `/rmpair BTC/USDT` | Remove pair |
| `/ranking` | Pairs ranked by signal strength |

### Admin (NEW)
| `/health` | Full system health check |
| `/ai` | Last AI fusion decision |
| `/killswitch` | Toggle kill switch on/off |

---

## Feature Flags (in .env or Railway Variables)

All default to `false`. Set to `true` to activate:

```
FEATURE_CANDLE_PATTERNS=true    # Candle pattern detection in signals
FEATURE_HIDDEN_DIVERGENCE=true  # Hidden divergence (trend continuation)
FEATURE_MARKET_REGIME=true      # Rich regime classification
FEATURE_MULTI_PAIR=true         # Multi-pair watchlist (use /addpair to add)
FEATURE_AI_FUSION=true          # Dual-AI engine (needs API keys below)
```

### To Activate Dual-AI (requires API keys):
```
FEATURE_AI_FUSION=true
AI_FUSION_POLICY=advisory       # or: majority, strict_consensus, local_only
CLAUDE_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
CLAUDE_MODEL=claude-sonnet-4-20250514
OPENAI_MODEL=gpt-4o-mini
AI_TIMEOUT_SECONDS=15
```

---

## Deployment Info

### Railway (currently running)
- Procfile: `worker: python -c "from telegram_bot import build_app; build_app().run_polling()"`
- Variables: set in Railway dashboard
- DB: SQLite (local to Railway container, resets on redeploy)

### Supabase (ready but not connected)
- Project: MCDAutoTrader (pzxmfjlllfvqybwxfngh)
- Schema: trading_bot (9 tables created)
- To switch: set these in Railway variables:
  ```
  DB_ENGINE=postgres
  SUPABASE_DB_HOST=db.pzxmfjlllfvqybwxfngh.supabase.co
  SUPABASE_DB_PORT=5432
  SUPABASE_DB_NAME=postgres
  SUPABASE_DB_USER=postgres.pzxmfjlllfvqybwxfngh
  SUPABASE_DB_PASSWORD=<your-password>
  SUPABASE_SCHEMA=trading_bot
  ```
- Note: Direct host DNS was not resolving at session end. Try pooler instead:
  ```
  SUPABASE_DB_HOST=aws-0-ca-central-1.pooler.supabase.com
  SUPABASE_DB_PORT=6543
  ```

### GitHub
- Repo: https://github.com/Danielai666/MCDAutoTrader
- Branch: main
- All code committed and pushed

---

## What's Still TODO (for future sessions)

### Not Yet Implemented from Master Spec
1. **Partial fill handling** — trades assume full fill
2. **Trade duration tracking** — no duration_seconds column yet
3. **Equity curve** — no equity tracking over time
4. **Backtesting** — backtest.py is still a stub
5. **Multi-channel notifications** — only Telegram (no Discord, email, SMS)
6. **Connection pooling** — creates new DB connection per query
7. **Hot config reload** — settings changes require bot restart
8. **Export to Supabase** — migrate existing SQLite trades to PostgreSQL

### Known Issues
1. **Supabase DNS** — `db.pzxmfjlllfvqybwxfngh.supabase.co` was not resolving. May work now (DNS propagation). Pooler host `aws-0-ca-central-1.pooler.supabase.com:6543` returned "tenant not found" — project may need more time.
2. **Railway SQLite** — SQLite data resets on each Railway redeploy. Should switch to Supabase PostgreSQL for persistence.
3. **Password exposed in chat** — Supabase DB password was pasted in chat. Should be changed at: https://supabase.com/dashboard/project/pzxmfjlllfvqybwxfngh/settings/database
4. **reports.py exit column** — PostgreSQL uses `exit_price` but SQLite uses `exit`. May need query compatibility fix.
5. **.venv on laptop** — Was recreated with Python 3.9.6 (system python). Original was Python 3.11.7 (pyenv, broken).

### Performance Tuning Ideas
1. Lower AI_CONFIDENCE_MIN from 0.65 to 0.55 for more trades
2. Lower ADX_TREND_MIN from 20 to 15 for more signals in mild trends
3. Enable FEATURE_CANDLE_PATTERNS for extra confirmation
4. Try AI_FUSION_POLICY=majority with both Claude + OpenAI keys
5. Adjust COOLDOWN_AFTER_TRADE_SECONDS (default 300s = 5 min)

---

## Quick Reference

### Start bot locally
```bash
cd /Volumes/MiniSSD/aiMCDtrader
.venv/bin/python3 -c "from telegram_bot import build_app; build_app().run_polling()"
```

### Stop local bot
```bash
pkill -f "telegram_bot"
```

### Check SQLite trades
```bash
sqlite3 bot.db "SELECT * FROM trades ORDER BY id DESC LIMIT 10;"
```

### Check blocked trades
```bash
sqlite3 bot.db "SELECT * FROM blocked_trades ORDER BY id DESC LIMIT 10;"
```

### Check AI decisions
```bash
sqlite3 bot.db "SELECT * FROM ai_decisions ORDER BY id DESC LIMIT 5;"
```
