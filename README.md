# MACD/RSI Bot (Paper-ready pack)

## Quick start
```bash
cd macd_rsi_bot_ai2
cp .env.example .env # fill your TELEGRAM_BOT_TOKEN
./run_bot.sh
```

Then in Telegram:
```
/start
/help
/price
/trades
/pnl
/exportcsv
/sl 1100
/tp 1200
/trail 0.02
/guards
/checkguards
```
Daily summary is sent at 17:30 (TZ from `.env`).

## Files
- `config.py` - reads `.env`, global settings
- `storage.py` - sqlite helpers + `init_db()` creates tables
- `ai_decider.py` - remote + heuristic decider with thresholds
- `trade_executor.py` - open/close trades + manual guards
- `scheduler.py` - 10min analysis tick (`apscheduler`) + `run_cycle_once`
- `reports.py` - reporting helpers + CSV export
- `telegram_bot.py` - bot commands, auto-exit guard, reporting, daily summary
- `main.py` - entry point
- `requirements.txt`
- `run_bot.sh`
- `.env.example`
- `exports/`, `logs/`

## Notes
- Uses **ccxt** to fetch prices from the exchange in `.env` (default: Kraken).
- Paper mode by default: `PAPER_TRADING=true`.
- Auto-exit checks every 30s for SL/TP/Trail in `manual_guards`.
- Analysis cycle (heuristic) runs every 10 minutes and can notify admin.
- All DB tables are created automatically (file path from `DB_PATH`).
