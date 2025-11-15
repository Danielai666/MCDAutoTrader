#!/usr/bin/env bash
set -euo pipefail

PROJ="$PWD"
STAMP="$(date +%Y%m%d-%H%M%S)"
LABEL="ai1"
BKROOT="$HOME/Backups/MACDBOT"
BKDIR="$BKROOT/${LABEL}-${STAMP}"
mkdir -p "$BKDIR"

# 
if [ -d ".venv" ]; then
 source .venv/bin/activate
 pip freeze > "$BKDIR/requirements.lock.txt"
else
 pip3 freeze > "$BKDIR/requirements.lock.txt"
fi

# DB
[ -f "bot.db" ] && sqlite3 bot.db ".backup '$BKDIR/bot.db'" && sqlite3 bot.db ".dump" > "$BKDIR/bot.dump.sql"
[ -f "db.sqlite3" ] && sqlite3 db.sqlite3 ".backup '$BKDIR/db.sqlite3'" && sqlite3 db.sqlite3 ".dump" > "$BKDIR/db.dump.sql"

# env () 
[ -f ".env" ] && install -m 600 .env "$BKDIR/.env"

# ( .venv )
tar --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
 --exclude='.DS_Store' --exclude='*.pyc' \
 -czf "$BKDIR/code.tar.gz" -C "$PROJ" .

# 
python3 - <<'PY' > "$BKDIR/config_snapshot.txt"
from dotenv import dotenv_values; import json, os
cfg = dotenv_values('.env') if os.path.exists('.env') else {}
keys = ["ENV","TZ","DB_PATH","EXCHANGE","PAIR","TIMEFRAMES","CANDLE_LIMIT",
 "PAPER_TRADING","CAPITAL_USD","RISK_PER_TRADE","MAX_OPEN_TRADES",
 "DAILY_LOSS_LIMIT_USD","ENABLE_EXIT_AUTOMATION","AI_CONFIDENCE_MIN",
 "SIGNAL_SCORE_MIN","AI_MODEL"]
print(json.dumps({k: cfg.get(k) for k in keys}, indent=2, ensure_ascii=False))
PY

# 
( cd "$BKDIR" && shasum -a 256 * > checksums.sha256 )

# 
cat > "$BKDIR/restore_quick.sh" <<'RESTORE'
#!/usr/bin/env bash
set -euo pipefail
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$HOME/restore_macdbot}"
mkdir -p "$TARGET"
tar -xzf "$SRC_DIR/code.tar.gz" -C "$TARGET"
[ -f "$SRC_DIR/.env" ] && install -m 600 "$SRC_DIR/.env" "$TARGET/.env"
[ -f "$SRC_DIR/bot.db" ] && cp "$SRC_DIR/bot.db" "$TARGET/bot.db"
cd "$TARGET"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r "$SRC_DIR/requirements.lock.txt"
echo "Restore OK at $TARGET"
RESTORE
chmod +x "$BKDIR/restore_quick.sh"

# 
mkdir -p "$BKROOT"
echo "$BKDIR" > "$BKROOT/LAST"

echo "[OK] Backup saved to: $BKDIR"
ls -lh "$BKDIR"
