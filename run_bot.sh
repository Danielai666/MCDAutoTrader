#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
 python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

python -m py_compile config.py storage.py ai_decider.py trade_executor.py scheduler.py telegram_bot.py main.py

echo "Starting bot..."
python main.py
