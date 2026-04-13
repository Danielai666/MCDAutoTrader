# MCDAutoTrader Bot — Complete Guide

## Project Location
```
/Users/saiedbeikhosseini/Documents/projects/AutoTradermacdandmore/macd_rsi_bot/
```

## How to Start the Bot
```bash
cd /Users/saiedbeikhosseini/Documents/projects/AutoTradermacdandmore/macd_rsi_bot
.venv/bin/python3 -c "from telegram_bot import build_app; build_app().run_polling()"
```

## Telegram Bot
- **Username:** @AiMCDAutoTrader_bot
- **Name:** MCDAutoTrader
- **Type:** `/menu` or `/start` to see the button menu

---

## Architecture Overview

### Files & What They Do

| File | Purpose |
|---|---|
| `telegram_bot.py` | Telegram bot with inline button menus + all command handlers |
| `strategy.py` | Multi-timeframe signal generation with weighted scoring |
| `indicators.py` | Technical indicators: MACD, RSI, Stochastic, EMA, Volume MA, **ATR, ADX, Bollinger Bands** |
| `divergence.py` | Divergence detection with multi-bar pivot confirmation and strength scoring |
| `ai_decider.py` | Heuristic AI decision maker (ENTER/EXIT/HOLD) using ADX, RSI, BB context |
| `risk.py` | Risk management: daily loss gate, **ATR-based position sizing**, stop-loss calculation |
| `scheduler.py` | Runs analysis cycle every 10 minutes, opens/closes trades, sends notifications |
| `exchange.py` | Kraken exchange wrapper via ccxt (paper + live orders) |
| `trade_executor.py` | Opens/closes trades in DB, manages SL/TP/trailing guards |
| `storage.py` | SQLite database (bot.db) — users, trades, signals, manual_guards tables |
| `config.py` | All settings loaded from `.env` with defaults |
| `.env` | API keys, trading pair, risk settings (edit manually) |

### Signal Flow
```
Scheduler (every 10 min)
  → Fetch OHLCV from Kraken (30m, 1h, 4h, 1d)
  → Compute indicators per timeframe (MACD, RSI, Stoch, EMA, ATR, ADX, BB)
  → Detect divergences with strength scoring
  → Weighted scoring → BUY/SELL/HOLD per timeframe
  → ADX filter (blocks trades in choppy markets)
  → Merge multi-timeframe signals
  → AI heuristic decision (ENTER/EXIT/HOLD with confidence)
  → If ENTER: check risk gate → compute position size via ATR → open trade → set auto SL
  → If EXIT: close all open trades
  → Notify via Telegram
```

---

## Strategy Details (Improved)

### Weighted Scoring System (per timeframe)
Instead of requiring ALL conditions to align, signals use weighted points:

| Signal Component | Weight | Condition |
|---|---|---|
| Divergence | 1.5 × strength | Bullish/bearish divergence (strength 0-1) |
| EMA Trend | 1.0 | EMA9 > EMA21 (bullish) or EMA9 < EMA21 (bearish) |
| Stochastic | 0.75 | K > D in bullish zone, or K < D in bearish zone |
| Volume | 0.5 | Current volume > 20-period MA |
| Bollinger Position | 0.5 | Near lower band (bullish) or upper band (bearish) |
| MACD Histogram | 0.5 | Rising histogram (bullish) or falling (bearish) |

- **BUY threshold:** buy_score >= 1.5
- **SELL threshold:** sell_score >= 1.5
- **ADX gate:** if ADX < 20 → force HOLD (choppy market, don't trade)

### Multi-Timeframe Merge
- Weights: 30m=1.0, 1h=1.5, 4h=2.0
- Daily timeframe acts as regime filter (won't buy in daily downtrend)
- Merged score > 0.4 = BUY, < -0.4 = SELL

### AI Heuristic Decision
- Averages ADX, RSI, BB position across all timeframes
- Boosts confidence if ADX > 40 (strong trend)
- Reduces confidence if buying near upper Bollinger band or RSI overbought
- Uses `SIGNAL_SCORE_MIN` (0.60) as score gate
- Uses `AI_CONFIDENCE_MIN` (0.65) as confidence floor — below = HOLD

### Position Sizing (ATR-based)
- Risk per trade: `RISK_PER_TRADE × CAPITAL_USD` (default: 1% of $1000 = $10)
- Stop-loss distance: ATR × 1.5
- Quantity: risk_usd / sl_distance
- Auto-sets SL guard when opening trade

---

## Telegram Commands (all also available as menu buttons)

### Analysis
| Command | Button | Description |
|---|---|---|
| `/signal` | 📊 Signal | Run full multi-TF analysis and show result |
| `/price` | 💰 Price | Fetch current price from Kraken |
| `/status` | 📈 Status | Show tier, auto-trade, mode, pair, limits |
| `/settings` | ⚙️ Settings | Show pair, timeframes, paper mode, thresholds |

### Trading
| Command | Button | Description |
|---|---|---|
| `/autotrade on` | ✅ AutoTrade ON | Enable automatic trading |
| `/autotrade off` | ⛔ AutoTrade OFF | Disable automatic trading |
| `/mode paper` | 📝 Paper Mode | Switch to paper (simulated) trading |
| `/mode live` | 🔴 Live Mode | Switch to live trading (needs approval) |
| `/sellnow` | 🛑 Sell Now | Close all open trades immediately |

### Risk Management
| Command | Button | Description |
|---|---|---|
| `/risk daily 50` | 🎯 Risk menu | Set daily loss limit ($25/$50/$100/$200/$500) |
| `/sl 580` | 🛑 Set SL | Set stop-loss at price |
| `/tp 620` | 🎯 Set TP | Set take-profit at price |
| `/trail 0.05` | 📐 Set Trail | Set trailing stop at 5% |
| `/guards` | 🛡️ Guards | View current SL/TP/trail settings |
| `/checkguards` | 🔍 Check Guards | Run analysis + check guards now |
| `/cancel sl` | Cancel SL | Remove stop-loss |
| `/cancel tp` | Cancel TP | Remove take-profit |
| `/cancel trail` | Cancel Trail | Remove trailing stop |
| `/cancel all` | Cancel ALL | Remove all guards |

### Other
| Command | Description |
|---|---|
| `/start` | Register + show main menu |
| `/menu` | Show main menu with buttons |
| `/help` | List all commands |

---

## Configuration (.env)

### Core Settings
```
ENV=dev
TZ=America/Vancouver
DB_PATH=./bot.db
LOG_LEVEL=INFO
```

### Market / Exchange
```
EXCHANGE=kraken
PAIR=BNB/USDC
TIMEFRAMES=30m,1h,4h,1d
CANDLE_LIMIT=300
PAPER_TRADING=true
```

### Risk
```
CAPITAL_USD=1000
RISK_PER_TRADE=0.01          # 1% of capital per trade
MAX_OPEN_TRADES=2
DAILY_LOSS_LIMIT_USD=50
ENABLE_EXIT_AUTOMATION=true
```

### Strategy / Indicators
```
ATR_PERIOD=14
ADX_PERIOD=14
ADX_TREND_MIN=20.0           # Below = choppy, force HOLD
ADX_STRONG_TREND=40.0        # Above = strong trend, boost confidence
BB_PERIOD=20
BB_STD=2.0
PIVOT_LOOKBACK=3             # Multi-bar pivot confirmation
ATR_SL_MULTIPLIER=1.5        # SL = entry ± (ATR × 1.5)
```

### AI / Decider
```
AI_BASE_URL=                  # Empty = use local heuristic
AI_API_KEY=
AI_MODEL=gpt-4o-mini
AI_CONFIDENCE_MIN=0.65        # Below = force HOLD
SIGNAL_SCORE_MIN=0.60         # Minimum merged score to trade
```

### Telegram
```
TELEGRAM_BOT_TOKEN=<your-token>
TELEGRAM_ADMIN_IDS=<your-telegram-id>
```

### Kraken
```
KRAKEN_API_KEY=<your-key>
KRAKEN_API_SECRET=<your-secret>
LIVE_TRADE_ALLOWED_IDS=<your-telegram-id>
```

---

## Database (bot.db)

### Tables
- **users** — Telegram users, tier, trial dates, autotrade toggle, trade mode, risk limits
- **trades** — Trade records: pair, side, qty, entry, exit, PnL, status (OPEN/CLOSED)
- **signals** — Signal history: timestamp, pair, timeframe, direction, reason
- **manual_guards** — Per-user SL/TP/trailing settings per pair

### Check trades
```bash
sqlite3 bot.db "SELECT * FROM trades ORDER BY id DESC LIMIT 10;"
```

### Check open trades
```bash
sqlite3 bot.db "SELECT * FROM trades WHERE status='OPEN';"
```

---

## Auto-Exit System
- Runs every **30 seconds**
- Checks SL, TP, and trailing stop against live Kraken price
- Closes all open trades if any guard is triggered
- Sends notification to admin via Telegram
- Throttles duplicate notifications (5-minute cooldown)

## Scheduler
- Runs full analysis every **10 minutes** (600 seconds)
- Fetches candles, computes signals, makes AI decision
- Opens/closes trades automatically if autotrade is enabled
- Sends analysis results to all registered users

---

## Venv & Dependencies
```bash
# Recreate venv if broken
python3 -m venv .venv
.venv/bin/pip install ccxt pandas numpy python-dotenv "python-telegram-bot[job-queue]"
```

### Required packages
- ccxt (Kraken exchange)
- pandas, numpy (data/indicators)
- python-dotenv (config)
- python-telegram-bot[job-queue] (Telegram + scheduler)

---

## Trade History
The bot has 2 closed trades on record:

| # | Pair | Side | Qty | Entry | Exit | PnL | Status |
|---|---|---|---|---|---|---|---|
| 1 | BNB/USDC | BUY | 0.1 | $1,100 | $1,107.01 | +$0.70 | CLOSED |
| 2 | BNB/USDC | BUY | 0.1 | $1,100 | $1,122.69 | +$2.27 | CLOSED |

---

## What Was Improved (This Session)
1. **indicators.py** — Added ATR, ADX, Bollinger Bands
2. **divergence.py** — Multi-bar pivot detection + strength scoring (0-1)
3. **strategy.py** — Weighted scoring system (threshold 1.5) + ADX choppy market filter
4. **ai_decider.py** — Smarter heuristic using ADX/RSI/BB context, uses SIGNAL_SCORE_MIN and AI_CONFIDENCE_MIN
5. **risk.py** — ATR-based position sizing and stop-loss calculation
6. **scheduler.py** — Wired position sizing, auto SL guard, enriched Telegram messages
7. **config.py** — Added 8 new configurable settings with defaults
8. **telegram_bot.py** — Full inline button menu (no more typing commands)
