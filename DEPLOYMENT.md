# Railway Deployment Guide

Complete reference for deploying MCDAutoTrader to Railway with Supabase PostgreSQL.

---

## 1. Prerequisites

Before deploying, make sure you have:

- [x] GitHub repo connected to Railway (`Danielai666/MCDAutoTrader`)
- [x] Supabase project created with project ref `pzxmfjlllfvqybwxfngh`
- [x] Supabase DB password (from Supabase Settings → Database)
- [x] Telegram bot token (from @BotFather)
- [x] Your Telegram user ID (344374586)
- [x] Fernet encryption key generated

To generate a new Fernet key locally:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 2. Supabase Connection Mode

**Use Transaction Pooler** (port 6543) — the standard recommended mode for serverless/container workloads like Railway.

| Setting | Value |
|---------|-------|
| Mode | Transaction Pooler |
| Host | `aws-0-ca-central-1.pooler.supabase.com` |
| Port | `6543` |
| Database | `postgres` |
| User | `postgres.pzxmfjlllfvqybwxfngh` (the `.` + project ref matters) |

---

## 3. Railway Environment Variables

**Important:** Paste this in Railway → Variables tab → **Raw Editor** (top right).

**Do NOT use smart/curly quotes** (`"` vs `"` / `"`). Copy from a plain text editor, not from Notes or Word. Railway's Raw Editor treats everything after `=` as the literal value — no surrounding quotes needed.

### Minimum config for Paper Trading Burn-In

```
# ─── Database (Required) ─────────────────────
DB_ENGINE=postgres
SUPABASE_DB_HOST=aws-0-ca-central-1.pooler.supabase.com
SUPABASE_DB_PORT=6543
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres.pzxmfjlllfvqybwxfngh
SUPABASE_DB_PASSWORD=<YOUR_SUPABASE_DB_PASSWORD>
SUPABASE_SCHEMA=trading_bot

# ─── Security (Required) ─────────────────────
CREDENTIAL_ENCRYPTION_KEY=<YOUR_FERNET_KEY>

# ─── Telegram (Required) ─────────────────────
TELEGRAM_BOT_TOKEN=<YOUR_BOT_TOKEN_FROM_BOTFATHER>
TELEGRAM_ADMIN_IDS=344374586
LIVE_TRADE_ALLOWED_IDS=344374586

# ─── Exchange (Leave blank for paper mode) ──
EXCHANGE=kraken
KRAKEN_API_KEY=
KRAKEN_API_SECRET=

# ─── AI (Leave blank — AI fusion is disabled) ──
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
CLAUDE_MODEL=claude-sonnet-4-20250514
AI_MODEL=gpt-4o-mini
AI_FUSION_POLICY=local_only

# ─── Trading Config ──────────────────────────
PAIR=BNB/USDC
PAIR_MODE=single
DEFAULT_PAIRS=BNB/USDC
PAPER_TRADING=true
DRY_RUN_MODE=false

# ─── Risk Limits ─────────────────────────────
CAPITAL_USD=1000
RISK_PER_TRADE=0.01
MAX_OPEN_TRADES=2
DAILY_LOSS_LIMIT_USD=50
MAX_PORTFOLIO_EXPOSURE=0.50

# ─── Feature Flags ───────────────────────────
FEATURE_HIDDEN_DIVERGENCE=true
FEATURE_CANDLE_PATTERNS=true
FEATURE_MARKET_REGIME=true
FEATURE_ICHIMOKU=true
FEATURE_AI_FUSION=false
FEATURE_MULTI_PAIR=false
FEATURE_MT5_BRIDGE=false
FEATURE_SCREENSHOTS=false

# ─── Environment ─────────────────────────────
ENV=production
LOG_LEVEL=INFO
```

### Enabling Live Trading (after paper burn-in passes)

Add these when you switch to live:
```
PAPER_TRADING=false
KRAKEN_API_KEY=<YOUR_KRAKEN_API_KEY>
KRAKEN_API_SECRET=<YOUR_KRAKEN_API_SECRET>
```

Important: **use a NO-WITHDRAWAL Kraken API key** (read + trade only).

### Enabling AI Fusion (optional)

Add these to enable Claude + OpenAI co-decisions:
```
FEATURE_AI_FUSION=true
AI_FUSION_POLICY=majority
OPENAI_API_KEY=<YOUR_OPENAI_KEY>
CLAUDE_API_KEY=<YOUR_CLAUDE_KEY>
```

---

## 4. Deployment Steps

### First-time setup:

1. Railway → **New Project** → **Deploy from GitHub repo** → select `Danielai666/MCDAutoTrader`
2. Wait for initial build (will fail — that's expected until env vars are set)
3. Go to **Variables** tab → click **Raw Editor** (top right)
4. Delete any existing variables
5. Paste the minimum config block above (with your real values filled in)
6. Click **Update Variables**
7. Click **Deploy** (top right purple button)

### Redeploying after variable changes:

Railway does NOT hot-reload variables. After any variable change:
1. Go to **Deployments** tab
2. Click the three-dot menu on the latest deployment → **Redeploy**
3. Watch logs for success

---

## 5. Verifying Success

### Railway logs — success indicators:

```
INFO storage: PostgreSQL schema verified: trading_bot
INFO storage: Database initialized: PostgreSQL
INFO scheduler: Scheduler jobs registered: analysis=600s, health=3600s, daily=3600s
```

If you see `Database initialized: SQLite` instead, `DB_ENGINE` is missing or wrong.

### Supabase SQL Editor — verify schema and data:

```sql
-- Schema exists
SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'trading_bot';

-- All 14 tables exist
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'trading_bot' ORDER BY table_name;

-- User row appears after sending /start to bot
SELECT user_id, tg_username FROM trading_bot.users ORDER BY user_id DESC LIMIT 5;
```

### Telegram verification:

1. Open your bot chat
2. Send `/start` → should reply with welcome menu
3. Send `/health` → should show PostgreSQL OK + Exchange OK + Telegram OK
4. Send `/liveready` → should return READY or READY WITH WARNINGS

---

## 6. Common Issues

### `psycopg2.OperationalError: connection to server on socket "/var/run/postgresql/..." failed`
**Cause:** `SUPABASE_DB_HOST` is empty or unset.
**Fix:** Check Railway Variables tab, make sure `SUPABASE_DB_HOST=aws-0-ca-central-1.pooler.supabase.com` is set.

### `FATAL: (ENOTFOUND) tenant/user postgres.xxx not found`
**Cause:** Wrong user format or wrong project ref.
**Fix:** User must be `postgres.<project_ref>` with the dot. Verify project ref in your Supabase dashboard URL.

### `telegram.error.InvalidToken: The token was rejected by the server`
**Cause:** Bot token is wrong, expired, or revoked.
**Fix:** Open Telegram → @BotFather → `/mybots` → your bot → API Token → copy fresh token to Railway.

### Bot connects but doesn't respond to messages
**Cause:** Your Telegram user ID is not in `TELEGRAM_ADMIN_IDS`.
**Fix:** Verify `TELEGRAM_ADMIN_IDS=344374586` (your actual user ID, not the bot's).

### Deployment logs show smart quote errors
**Cause:** Pasted variables from a word processor that auto-converted `"` to `"` / `"`.
**Fix:** Copy variables from a plain-text source. Don't use quotes at all in Railway Raw Editor.

---

## 7. Go-Live Trust Mode (after burn-in)

After 48-72h of successful paper trading:

1. Fund your Kraken account with minimum capital (e.g. $100)
2. Create a NO-WITHDRAWAL Kraken API key
3. Update Railway variables:
   ```
   PAPER_TRADING=false
   KRAKEN_API_KEY=<your_key>
   KRAKEN_API_SECRET=<your_secret>
   ```
4. Redeploy
5. In Telegram, send `/golive` — the wizard will enforce prerequisites and apply micro-risk settings automatically:
   - Max risk per trade: 0.25%
   - Max open trades: 1
   - AI mode: manual_confirm (you approve each trade)

Monitor daily with:
- `/health_stats` — telemetry counters
- `/reconcile` — DB vs exchange state
- `/status` — equity + drawdown
- `/positions` — open trades
- `/report` — performance

---

## 8. Reference Values (Current Project)

These are the actual values for this project. Keep them private.

| Variable | Value |
|----------|-------|
| `SUPABASE_DB_USER` | `postgres.pzxmfjlllfvqybwxfngh` |
| `SUPABASE_DB_HOST` | `aws-0-ca-central-1.pooler.supabase.com` |
| `SUPABASE_DB_PORT` | `6543` |
| `SUPABASE_SCHEMA` | `trading_bot` |
| `TELEGRAM_ADMIN_IDS` | `344374586` |
| `LIVE_TRADE_ALLOWED_IDS` | `344374586` |

Supabase dashboard: https://supabase.com/dashboard/project/pzxmfjlllfvqybwxfngh
GitHub repo: https://github.com/Danielai666/MCDAutoTrader
