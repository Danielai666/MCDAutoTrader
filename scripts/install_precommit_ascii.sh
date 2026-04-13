#!/usr/bin/env bash
set -euo pipefail
mkdir -p .git/hooks
cat > .git/hooks/pre-commit <<'SH'
#!/usr/bin/env bash
bad=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(py|sh|md|txt|ini|cfg|json|toml|ya?ml|env|service|conf|sql)$' | while read -r f; do
  if [ -f "$f" ] && LC_ALL=C grep -nP '[\x80-\xFF]' "$f" >/dev/null 2>&1; then
    echo "$f"
  fi
done)
if [ -n "$bad" ]; then
  echo "Non-ASCII characters found in staged text files:"
  echo "$bad"
  exit 1
fi
exit 0
SH
chmod +x .git/hooks/pre-commit
echo "[pre-commit] Installed ASCII guard."