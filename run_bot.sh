{\rtf1\ansi\ansicpg1252\cocoartf2865
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 cat > run_bot.sh <<'SH'\
#!/usr/bin/env bash\
set -euo pipefail\
cd "$(dirname "$0")"\
source .venv/bin/activate\
python - <<'PY'\
import sys,httpx; from dotenv import dotenv_values\
tok = dotenv_values('.env').get('TELEGRAM_BOT_TOKEN','')\
if not tok or ':' not in tok: \
    print("Bad/empty TELEGRAM_BOT_TOKEN in .env"); sys.exit(2)\
r = httpx.get(f"https://api.telegram.org/bot\{tok\}/getMe", timeout=10)\
print("Telegram getMe:", r.status_code, r.text[:120])\
if r.status_code!=200: sys.exit(3)\
PY\
exec python main.py\
SH\
chmod +x run_bot.sh\
}