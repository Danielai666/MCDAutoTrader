# MACD+RSI Bot — Post-Backup Upgrade Kit

1) Restore your backup into `macd_rsi_bot/`.
2) Unzip this kit *over* that folder.
3) Bootstrap:
   ```bash
   cd macd_rsi_bot
   bash scripts/bootstrap.sh
   ```
4) Paper mode:
   ```bash
   bash scripts/run_paper.sh
   ```
5) Live mode (optional Kraken): fill keys in `.env`, then:
   ```bash
   bash scripts/run_live.sh
   ```