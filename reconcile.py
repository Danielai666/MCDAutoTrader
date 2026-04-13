# reconcile.py
# Exchange reconciliation: compare DB state vs actual exchange state
# Used on startup and via /reconcile command

import time
import logging
from typing import List, Dict
from config import SETTINGS
from storage import fetchall, fetchone, execute, upsert_bot_state

log = logging.getLogger(__name__)


def reconcile_positions() -> Dict:
    """
    Compare DB open trades vs exchange open positions.
    Returns reconciliation report.

    Detects:
    - DB says OPEN but exchange has no position (orphaned DB record)
    - Exchange has position but DB doesn't (untracked exposure)
    - Order ID mismatch
    - PENDING/FAILED trades that need cleanup
    """
    report = {
        'ts': int(time.time()),
        'db_open_trades': [],
        'exchange_positions': [],
        'issues': [],
        'actions_taken': [],
        'clean': True,
    }

    # 1. Get all DB open trades
    db_trades = fetchall(
        "SELECT id, pair, side, qty, entry, status, order_id, lifecycle, ts_open "
        "FROM trades WHERE status IN ('OPEN', 'PENDING') ORDER BY id"
    )
    for row in db_trades:
        trade = {
            'id': row[0], 'pair': row[1], 'side': row[2],
            'qty': float(row[3]) if row[3] else 0,
            'entry': float(row[4]) if row[4] else 0,
            'status': row[5], 'order_id': row[6],
            'lifecycle': row[7], 'ts_open': row[8],
        }
        report['db_open_trades'].append(trade)

    # 2. Check for stale PENDING trades (older than 5 minutes)
    for trade in report['db_open_trades']:
        if trade['status'] == 'PENDING':
            age = int(time.time()) - (trade['ts_open'] or 0)
            if age > 300:  # 5 minutes
                report['issues'].append({
                    'type': 'stale_pending',
                    'trade_id': trade['id'],
                    'pair': trade['pair'],
                    'age_seconds': age,
                    'message': f"Trade #{trade['id']} stuck PENDING for {age}s"
                })
                report['clean'] = False

    # 3. Check exchange positions (only for live mode)
    if not SETTINGS.PAPER_TRADING:
        try:
            from exchange import get_client
            ex = get_client()
            balance = ex.fetch_balance()

            # Get non-zero positions
            for currency, amount in balance.get('free', {}).items():
                if amount and float(amount) > 0 and currency not in ('USD', 'USDT', 'USDC', 'EUR'):
                    report['exchange_positions'].append({
                        'currency': currency,
                        'free': float(amount),
                        'total': float(balance.get('total', {}).get(currency, 0)),
                    })

            # Cross-check: DB open trades vs exchange balance
            db_pairs = set()
            for trade in report['db_open_trades']:
                if trade['status'] == 'OPEN':
                    base = trade['pair'].split('/')[0] if '/' in trade['pair'] else trade['pair']
                    db_pairs.add(base)

            exchange_currencies = set(p['currency'] for p in report['exchange_positions'])

            # DB says open but no exchange position
            for base in db_pairs - exchange_currencies:
                matching_trades = [t for t in report['db_open_trades']
                                   if t['status'] == 'OPEN' and t['pair'].startswith(base + '/')]
                for t in matching_trades:
                    report['issues'].append({
                        'type': 'db_orphan',
                        'trade_id': t['id'],
                        'pair': t['pair'],
                        'message': f"Trade #{t['id']} OPEN in DB but no {base} position on exchange"
                    })
                    report['clean'] = False

            # Exchange has position but no DB record
            for curr in exchange_currencies - db_pairs:
                report['issues'].append({
                    'type': 'untracked_position',
                    'currency': curr,
                    'message': f"Exchange has {curr} position but no OPEN trade in DB"
                })
                report['clean'] = False

        except Exception as e:
            report['issues'].append({
                'type': 'exchange_error',
                'message': f"Cannot fetch exchange positions: {e}"
            })
            report['clean'] = False

    elif SETTINGS.PAPER_TRADING:
        # Paper mode: just verify DB consistency
        for trade in report['db_open_trades']:
            if trade['status'] == 'OPEN' and not trade['order_id']:
                report['issues'].append({
                    'type': 'missing_order_id',
                    'trade_id': trade['id'],
                    'pair': trade['pair'],
                    'message': f"Trade #{trade['id']} has no order_id"
                })

    # 4. Check for guard/trail state consistency
    for trade in report['db_open_trades']:
        if trade['status'] != 'OPEN':
            continue
        # Check if ATR trail state exists for active trailing trades
        if trade['lifecycle'] == 'trailing':
            trail_row = fetchone("SELECT value FROM bot_state WHERE key=?",
                                 (f"atr_trail_{trade['id']}",))
            if not trail_row or not trail_row[0]:
                report['issues'].append({
                    'type': 'missing_trail_state',
                    'trade_id': trade['id'],
                    'message': f"Trade #{trade['id']} lifecycle=trailing but no trail state in bot_state"
                })

    # 5. Record reconciliation result
    upsert_bot_state('last_reconcile', str(int(time.time())), int(time.time()))
    upsert_bot_state('reconcile_clean', '1' if report['clean'] else '0', int(time.time()))

    return report


def reconcile_orders() -> Dict:
    """
    Check recently closed trades for order consistency.
    Verifies that FAILED trades are properly recorded.
    """
    report = {
        'ts': int(time.time()),
        'failed_trades': [],
        'issues': [],
    }

    # Get recently failed trades (last 24h)
    start = int(time.time()) - 86400
    failed = fetchall(
        "SELECT id, pair, side, qty, entry, note, ts_open FROM trades "
        "WHERE status='FAILED' AND ts_open>=? ORDER BY id DESC", (start,)
    )
    for row in failed:
        report['failed_trades'].append({
            'id': row[0], 'pair': row[1], 'side': row[2],
            'qty': float(row[3]) if row[3] else 0,
            'note': row[5], 'ts_open': row[6],
        })

    return report


def auto_fix_issues(report: Dict) -> List[str]:
    """
    Attempt to automatically fix reconciliation issues.
    Returns list of actions taken.
    """
    actions = []

    for issue in report.get('issues', []):
        if issue['type'] == 'stale_pending':
            # Mark stale PENDING as FAILED
            execute(
                "UPDATE trades SET status='FAILED', lifecycle='blocked', "
                "note='Auto-recovered: stale PENDING on reconcile' WHERE id=?",
                (issue['trade_id'],)
            )
            actions.append(f"Marked trade #{issue['trade_id']} FAILED (stale PENDING)")
            log.warning("Reconcile: auto-fixed stale PENDING trade %d", issue['trade_id'])

        elif issue['type'] == 'missing_trail_state':
            # Reset lifecycle from trailing to open
            execute("UPDATE trades SET lifecycle='open' WHERE id=?", (issue['trade_id'],))
            actions.append(f"Reset trade #{issue['trade_id']} lifecycle to 'open' (missing trail state)")

    return actions


def format_reconcile_report(report: Dict) -> str:
    """Format reconciliation report for Telegram."""
    lines = ["=== Reconciliation Report ==="]
    lines.append(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Mode: {'PAPER' if SETTINGS.PAPER_TRADING else 'LIVE'}")
    lines.append(f"DB open trades: {len(report['db_open_trades'])}")

    if report['exchange_positions']:
        lines.append(f"Exchange positions: {len(report['exchange_positions'])}")
        for p in report['exchange_positions']:
            lines.append(f"  {p['currency']}: {p['free']:.6f}")

    if report['issues']:
        lines.append(f"\nIssues found: {len(report['issues'])}")
        for issue in report['issues']:
            lines.append(f"  [{issue['type']}] {issue['message']}")
    else:
        lines.append("\nNo issues found.")

    if report.get('actions_taken'):
        lines.append(f"\nAuto-fixes applied: {len(report['actions_taken'])}")
        for a in report['actions_taken']:
            lines.append(f"  {a}")

    status = "CLEAN" if report['clean'] else "ISSUES DETECTED"
    lines.append(f"\nStatus: {status}")
    return "\n".join(lines)


# -------------------------------------------------------------------
# Live-readiness check
# -------------------------------------------------------------------
def check_live_readiness() -> Dict:
    """
    Comprehensive check for live trading readiness.
    Returns {ready: bool, status: str, checks: list}
    """
    checks = []
    all_ok = True
    warnings = []

    # 1. DB health
    try:
        from storage import check_db_health
        db_ok, db_msg, db_details = check_db_health()
        checks.append({'name': 'Database', 'ok': db_ok, 'message': db_msg})
        if not db_ok:
            all_ok = False
    except Exception as e:
        checks.append({'name': 'Database', 'ok': False, 'message': str(e)})
        all_ok = False

    # 2. Exchange health
    try:
        from exchange import health_check as ex_health
        ex_ok, ex_msg = ex_health()
        checks.append({'name': 'Exchange', 'ok': ex_ok, 'message': ex_msg})
        if not ex_ok:
            all_ok = False
    except Exception as e:
        checks.append({'name': 'Exchange', 'ok': False, 'message': str(e)})
        all_ok = False

    # 3. Telegram (already working if we're responding)
    checks.append({'name': 'Telegram', 'ok': True, 'message': 'Connected (responding)'})

    # 4. Scheduler health
    try:
        last_health = fetchone("SELECT value FROM bot_state WHERE key='last_health_check'")
        if last_health and last_health[0]:
            age = int(time.time()) - int(last_health[0])
            sched_ok = age < SETTINGS.HEALTH_CHECK_INTERVAL_SECONDS * 3
            checks.append({'name': 'Scheduler', 'ok': sched_ok,
                          'message': f'Last health check {age}s ago' if sched_ok else f'Stale: {age}s ago'})
            if not sched_ok:
                warnings.append("Scheduler may be stuck")
        else:
            checks.append({'name': 'Scheduler', 'ok': True, 'message': 'No health check yet (new startup)'})
    except Exception as e:
        checks.append({'name': 'Scheduler', 'ok': False, 'message': str(e)})

    # 5. Open trade state
    try:
        from trade_executor import get_trade_state_summary
        state = get_trade_state_summary()
        pending = state.get('pending', 0)
        failed = state.get('failed', 0)
        trade_ok = pending == 0
        msg = f"Open: {state.get('open', 0)}, Pending: {pending}, Failed: {failed}"
        checks.append({'name': 'Trade State', 'ok': trade_ok, 'message': msg})
        if pending > 0:
            all_ok = False
        if failed > 0:
            warnings.append(f"{failed} failed trades in history")
    except Exception as e:
        checks.append({'name': 'Trade State', 'ok': False, 'message': str(e)})

    # 6. Reconciliation
    try:
        recon = reconcile_positions()
        recon_ok = recon['clean']
        issue_count = len(recon['issues'])
        checks.append({'name': 'Reconciliation', 'ok': recon_ok,
                       'message': 'Clean' if recon_ok else f'{issue_count} issue(s)'})
        if not recon_ok:
            for issue in recon['issues']:
                warnings.append(issue['message'])
    except Exception as e:
        checks.append({'name': 'Reconciliation', 'ok': False, 'message': str(e)})

    # 7. Watchlist
    try:
        from pair_manager import get_active_pairs
        pairs = get_active_pairs()
        checks.append({'name': 'Watchlist', 'ok': len(pairs) > 0,
                       'message': f'{len(pairs)} active pair(s)'})
    except Exception as e:
        checks.append({'name': 'Watchlist', 'ok': False, 'message': str(e)})

    # 8. AI providers (if enabled)
    if SETTINGS.FEATURE_AI_FUSION and SETTINGS.AI_FUSION_POLICY != 'local_only':
        claude_ok = bool(SETTINGS.CLAUDE_API_KEY)
        openai_ok = bool(SETTINGS.OPENAI_API_KEY)
        ai_ok = claude_ok or openai_ok
        ai_msg = f"Claude: {'OK' if claude_ok else 'no key'}, OpenAI: {'OK' if openai_ok else 'no key'}"
        checks.append({'name': 'AI Providers', 'ok': ai_ok, 'message': ai_msg})
        if not ai_ok:
            warnings.append("AI fusion enabled but no API keys configured")
    else:
        checks.append({'name': 'AI Providers', 'ok': True, 'message': 'Local-only mode'})

    # 9. API keys for live mode
    if not SETTINGS.PAPER_TRADING:
        has_keys = bool(SETTINGS.KRAKEN_API_KEY and SETTINGS.KRAKEN_API_SECRET)
        checks.append({'name': 'Exchange Keys', 'ok': has_keys,
                       'message': 'Present' if has_keys else 'MISSING — cannot trade live'})
        if not has_keys:
            all_ok = False
    else:
        checks.append({'name': 'Exchange Keys', 'ok': True, 'message': 'Paper mode (not required)'})

    # 10. Risk configuration sanity
    risk_ok = True
    risk_msgs = []
    if SETTINGS.RISK_PER_TRADE > 0.05:
        risk_msgs.append(f"RISK_PER_TRADE={SETTINGS.RISK_PER_TRADE:.0%} (>5%)")
        risk_ok = False
    if SETTINGS.DAILY_LOSS_LIMIT_USD <= 0:
        risk_msgs.append("DAILY_LOSS_LIMIT_USD <= 0")
        risk_ok = False
    if SETTINGS.CAPITAL_USD <= 0:
        risk_msgs.append("CAPITAL_USD <= 0")
        risk_ok = False
    checks.append({'name': 'Risk Config', 'ok': risk_ok,
                   'message': 'OK' if risk_ok else '; '.join(risk_msgs)})
    if not risk_ok:
        all_ok = False

    # Determine overall status
    has_warnings = len(warnings) > 0
    if all_ok and not has_warnings:
        status = "READY"
    elif all_ok and has_warnings:
        status = "READY WITH WARNINGS"
    else:
        status = "NOT READY"

    return {
        'ready': all_ok,
        'status': status,
        'checks': checks,
        'warnings': warnings,
    }


def format_readiness_report(result: Dict) -> str:
    """Format live-readiness report for Telegram."""
    lines = [f"=== Live Readiness: {result['status']} ==="]
    lines.append(f"Mode: {'PAPER' if SETTINGS.PAPER_TRADING else 'LIVE'}")
    lines.append("")

    for check in result['checks']:
        icon = "OK" if check['ok'] else "FAIL"
        lines.append(f"[{icon}] {check['name']}: {check['message']}")

    if result['warnings']:
        lines.append(f"\nWarnings ({len(result['warnings'])}):")
        for w in result['warnings']:
            lines.append(f"  - {w}")

    lines.append(f"\nVerdict: {result['status']}")
    if result['status'] == 'READY':
        if SETTINGS.PAPER_TRADING:
            lines.append("Paper mode active — safe for testing.")
        else:
            lines.append("Live mode — all checks passed.")
    elif result['status'] == 'NOT READY':
        lines.append("Fix the FAIL items above before live trading.")

    return "\n".join(lines)
