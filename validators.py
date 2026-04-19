# validators.py
# Startup validation for config, exchange, Telegram, and DB
import time
import logging

log = logging.getLogger(__name__)

def validate_config(settings) -> list:
    """Returns list of (level, message). level = 'error' | 'warning'."""
    issues = []

    # Critical
    if not settings.TELEGRAM_BOT_TOKEN:
        issues.append(('error', 'TELEGRAM_BOT_TOKEN is empty'))
    if not settings.TELEGRAM_ADMIN_IDS:
        issues.append(('error', 'TELEGRAM_ADMIN_IDS is empty'))

    # Exchange
    if not settings.EXCHANGE:
        issues.append(('error', 'EXCHANGE is empty'))
    if '/' not in settings.PAIR:
        issues.append(('error', f'PAIR "{settings.PAIR}" invalid format (expected BASE/QUOTE)'))

    # Risk
    if settings.RISK_PER_TRADE <= 0 or settings.RISK_PER_TRADE > 0.2:
        issues.append(('warning', f'RISK_PER_TRADE={settings.RISK_PER_TRADE} outside safe range (0.001-0.20)'))
    if settings.CAPITAL_USD <= 0:
        issues.append(('error', 'CAPITAL_USD must be > 0'))
    if settings.MAX_OPEN_TRADES < 1:
        issues.append(('warning', 'MAX_OPEN_TRADES < 1, no trades will be opened'))

    # AI Fusion
    if settings.AI_FUSION_POLICY not in ('local_only', 'advisory', 'majority', 'strict_consensus'):
        issues.append(('warning', f'AI_FUSION_POLICY "{settings.AI_FUSION_POLICY}" unknown, falling back to local_only'))
    if settings.FEATURE_AI_FUSION and settings.AI_FUSION_POLICY != 'local_only':
        if not settings.CLAUDE_API_KEY and not settings.OPENAI_API_KEY:
            issues.append(('warning', 'AI fusion enabled but no CLAUDE_API_KEY or OPENAI_API_KEY set'))

    # Live mode safety
    if not settings.PAPER_TRADING:
        if not settings.KRAKEN_API_KEY or not settings.KRAKEN_API_SECRET:
            issues.append(('error', 'PAPER_TRADING=false but KRAKEN_API_KEY/SECRET missing'))

    # Timeframes
    valid_tfs = {'1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w','1M'}
    for tf in settings.TIMEFRAMES:
        if tf not in valid_tfs:
            issues.append(('warning', f'Timeframe "{tf}" may not be supported by exchange'))

    return issues


def validate_exchange(settings) -> tuple:
    """Try fetch_ticker for PAIR. Returns (ok, message)."""
    try:
        import ccxt
        ex = getattr(ccxt, settings.EXCHANGE)({'enableRateLimit': True})
        t = ex.fetch_ticker(settings.PAIR)
        price = t.get('last') or t.get('close')
        if price and float(price) > 0:
            return True, f'{settings.PAIR} OK (${float(price):,.2f})'
        return False, f'{settings.PAIR} returned no price'
    except Exception as e:
        return False, f'Exchange check failed: {e}'


def validate_telegram(settings) -> tuple:
    """Check TELEGRAM_BOT_TOKEN is set and reachable."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return False, 'No TELEGRAM_BOT_TOKEN'
    try:
        import urllib.request, json
        url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe'
        r = urllib.request.urlopen(url, timeout=10)
        data = json.loads(r.read())
        if data.get('ok'):
            bot = data['result']
            return True, f'@{bot["username"]} ({bot["first_name"]})'
        return False, 'Telegram returned ok=false'
    except Exception as e:
        return False, f'Telegram check failed: {e}'


def validate_db(settings) -> tuple:
    """Check DB is accessible and tables exist."""
    try:
        from storage import check_db_health
        ok, msg, details = check_db_health()
        return ok, msg
    except Exception as e:
        return False, f'DB check failed: {e}'


def run_all_checks(settings) -> str:
    """Run all validators, return formatted summary string."""
    lines = ['--- Startup Validation ---']
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    lines.append(f'Time: {ts}')
    lines.append(f'Mode: {"PAPER" if settings.PAPER_TRADING else "LIVE"}')
    lines.append(f'Pair: {settings.PAIR} ({settings.PAIR_MODE} mode)')
    lines.append(f'AutoExit: {"ON" if settings.ENABLE_EXIT_AUTOMATION else "OFF"}')
    lines.append(f'Kill Switch: {"ON" if settings.KILL_SWITCH else "OFF"}')
    lines.append(f'AI Policy: {settings.AI_FUSION_POLICY}')
    try:
        from config import aggressive_mode_banner
        banner = aggressive_mode_banner()
        if banner:
            lines.append(f'!!! {banner}')
    except Exception:
        pass
    lines.append('')

    # Config checks
    config_issues = validate_config(settings)
    errors = [m for l, m in config_issues if l == 'error']
    warns = [m for l, m in config_issues if l == 'warning']
    if errors:
        lines.append(f'Config ERRORS ({len(errors)}):')
        for e in errors:
            lines.append(f'  X {e}')
    if warns:
        lines.append(f'Config warnings ({len(warns)}):')
        for w in warns:
            lines.append(f'  ! {w}')
    if not errors and not warns:
        lines.append('Config: OK')

    # DB check
    db_ok, db_msg = validate_db(settings)
    lines.append(f'DB: {"OK" if db_ok else "FAIL"} - {db_msg}')

    # Exchange check
    ex_ok, ex_msg = validate_exchange(settings)
    lines.append(f'Exchange: {"OK" if ex_ok else "FAIL"} - {ex_msg}')

    # Feature flags
    flags = []
    if settings.FEATURE_MULTI_PAIR: flags.append('multi-pair')
    if settings.FEATURE_AI_FUSION: flags.append('AI-fusion')
    if settings.FEATURE_CANDLE_PATTERNS: flags.append('candle-patterns')
    if settings.FEATURE_HIDDEN_DIVERGENCE: flags.append('hidden-div')
    if settings.FEATURE_MARKET_REGIME: flags.append('market-regime')
    lines.append(f'Features: {", ".join(flags) if flags else "all defaults"}')

    # Production hardening info
    lines.append(f'Trailing: {"ATR" if settings.TRAILING_ENABLED else "OFF"}')
    lines.append(f'Correlation Guard: {"ON" if settings.CORRELATION_CHECK_ENABLED else "OFF"}')
    lines.append(f'Drawdown Mgmt: {"ON" if settings.DRAWDOWN_TRACKING_ENABLED else "OFF"}')
    lines.append(f'DB Engine: {settings.DB_ENGINE}')

    # Trade state
    try:
        from trade_executor import get_trade_state_summary
        state = get_trade_state_summary()
        lines.append(f'Trades: open={state.get("open", 0)} pending={state.get("pending", 0)} failed={state.get("failed", 0)}')
    except Exception:
        pass

    lines.append('--- End ---')
    return '\n'.join(lines)
