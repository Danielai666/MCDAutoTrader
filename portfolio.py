# portfolio.py
# Read-only portfolio reporting for connected user accounts.
#
# CRITICAL — this module is READ-ONLY:
#   - Calls only fetch_balance / fetch_ticker on the user's exchange.
#   - Never places, cancels, or modifies orders.
#   - Never writes to the trades table.
#
# Integration:
#   - Credentials decrypted via crypto_utils.decrypt_exchange_keys (existing).
#   - Price valuation via CCXT fetch_ticker with in-memory TTL cache.
#   - Per-user snapshot cache (60s TTL) so panel auto-refresh (45s) doesn't
#     hammer the exchange API.
#   - Uses asyncio.run_in_executor for synchronous CCXT calls so the event
#     loop never blocks.
#
# Feature flag: FEATURE_PORTFOLIO (default true). When false, is_enabled()
# returns False and all public functions short-circuit.

import logging
import time
import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from config import SETTINGS
from storage import get_credential, fetchall

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
SNAPSHOT_TTL = 60          # seconds — per-user portfolio snapshot
TICKER_TTL = 30            # seconds — price cache per symbol
STABLECOINS = {"USD", "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "FDUSD"}
MIN_DUST_USD = 0.01         # assets below this value are hidden


def is_enabled() -> bool:
    return bool(getattr(SETTINGS, "FEATURE_PORTFOLIO", True))


# -------------------------------------------------------------------
# Data classes
# -------------------------------------------------------------------
@dataclass
class Asset:
    symbol: str
    amount: float
    price_usd: float
    value_usd: float


@dataclass
class PortfolioSnapshot:
    # sync_status: 'OK' | 'NO_EXCHANGE' | 'PAPER' | 'ERROR'
    sync_status: str = "OK"
    sync_error: str = ""
    last_sync_ts: int = 0
    exchange_id: str = ""
    total_value: float = 0.0
    available_cash: float = 0.0      # stablecoin balance
    positions_value: float = 0.0     # non-stablecoin holdings
    assets: List[Asset] = field(default_factory=list)


@dataclass
class PerformanceReport:
    window_days: int = 7
    realized_pnl: float = 0.0
    roi_pct: float = 0.0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    best_trade: float = 0.0
    worst_trade: float = 0.0

    @property
    def win_rate(self) -> float:
        closed = self.wins + self.losses
        return (self.wins / closed * 100.0) if closed else 0.0


# -------------------------------------------------------------------
# Caches (in memory)
# -------------------------------------------------------------------
# uid -> (ts, PortfolioSnapshot)
_snapshot_cache: dict = {}

# (exchange_id, "BTC/USDT") -> (ts, price_float)
_ticker_cache: dict = {}


def _cached_snapshot(uid: int) -> Optional[PortfolioSnapshot]:
    entry = _snapshot_cache.get(uid)
    if not entry:
        return None
    ts, snap = entry
    if time.time() - ts > SNAPSHOT_TTL:
        return None
    return snap


def invalidate(uid: int) -> None:
    """Force next fetch_portfolio to hit the exchange (e.g. after a trade)."""
    _snapshot_cache.pop(uid, None)


# -------------------------------------------------------------------
# Price valuation
# -------------------------------------------------------------------
def _usd_price(client, exchange_id: str, asset: str) -> float:
    """Look up USD price for `asset` using CCXT tickers. Cached TTL_TICKER."""
    asset = asset.upper()
    if asset in STABLECOINS:
        return 1.0

    for quote in ("USDT", "USD", "USDC"):
        pair = f"{asset}/{quote}"
        key = (exchange_id, pair)
        entry = _ticker_cache.get(key)
        if entry and (time.time() - entry[0]) < TICKER_TTL:
            return entry[1]
        try:
            t = client.fetch_ticker(pair)
            price = float(t.get("last") or t.get("close") or 0.0)
            if price > 0:
                _ticker_cache[key] = (time.time(), price)
                return price
        except Exception:
            # Pair not listed on this exchange — try next quote
            continue
    return 0.0


# -------------------------------------------------------------------
# Snapshot fetch (async-safe wrapper around CCXT sync calls)
# -------------------------------------------------------------------
def _build_snapshot_sync(uid: int) -> PortfolioSnapshot:
    """Synchronous portion — runs inside the executor."""
    snap = PortfolioSnapshot(last_sync_ts=int(time.time()))

    if not is_enabled():
        snap.sync_status = "ERROR"
        snap.sync_error = "FEATURE_PORTFOLIO disabled"
        return snap

    cred = get_credential(uid, "ccxt")
    if not cred:
        # Paper-only user or no exchange connected
        snap.sync_status = "NO_EXCHANGE"
        return snap

    # Decrypt
    try:
        from crypto_utils import decrypt_exchange_keys
        api_key, api_secret = decrypt_exchange_keys(
            cred["api_key_enc"], cred["api_secret_enc"],
            cred.get("data_key_enc", ""),
            int(cred.get("encryption_version", 1)),
        )
    except Exception as e:
        snap.sync_status = "ERROR"
        snap.sync_error = f"decrypt: {e}"
        return snap

    exchange_id = cred["exchange_id"]
    snap.exchange_id = exchange_id

    try:
        from ccxt_provider import CCXTProvider
        provider = CCXTProvider(exchange_id, api_key, api_secret)
        client = provider._client  # read-only usage

        balance = client.fetch_balance()
        totals = balance.get("total", {}) or {}

        assets = []
        for asset, amount in totals.items():
            try:
                amt = float(amount or 0.0)
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            price = _usd_price(client, exchange_id, asset)
            value = amt * price
            if value < MIN_DUST_USD:
                continue
            assets.append(Asset(
                symbol=asset.upper(),
                amount=amt,
                price_usd=round(price, 6),
                value_usd=round(value, 2),
            ))

        # Sort by value desc
        assets.sort(key=lambda a: a.value_usd, reverse=True)
        snap.assets = assets

        # Split available cash (stablecoin) vs positions value
        cash = sum(a.value_usd for a in assets if a.symbol in STABLECOINS)
        positions = sum(a.value_usd for a in assets if a.symbol not in STABLECOINS)
        snap.available_cash = round(cash, 2)
        snap.positions_value = round(positions, 2)
        snap.total_value = round(cash + positions, 2)
        snap.sync_status = "OK"
    except Exception as e:
        log.warning("portfolio fetch_balance failed for uid=%s: %s", uid, e)
        snap.sync_status = "ERROR"
        snap.sync_error = str(e)[:160]

    return snap


async def fetch_portfolio(uid: int, force: bool = False) -> PortfolioSnapshot:
    """Public entry — async-safe. Returns cached snapshot if fresh."""
    if not is_enabled():
        snap = PortfolioSnapshot(sync_status="ERROR", sync_error="disabled")
        return snap

    if not force:
        cached = _cached_snapshot(uid)
        if cached:
            return cached

    loop = asyncio.get_event_loop()
    snap = await loop.run_in_executor(None, _build_snapshot_sync, uid)
    _snapshot_cache[uid] = (time.time(), snap)
    return snap


# -------------------------------------------------------------------
# Performance report (from local trades table)
# -------------------------------------------------------------------
def compute_report(uid: int, window_days: int = 7) -> PerformanceReport:
    report = PerformanceReport(window_days=window_days)
    if not is_enabled():
        return report
    try:
        window_seconds = int(max(1, window_days)) * 86400
        since = int(time.time()) - window_seconds
        rows = fetchall(
            "SELECT pnl FROM trades WHERE user_id=? AND status='CLOSED' "
            "AND ts_close >= ?",
            (uid, since),
        )
    except Exception as e:
        log.warning("portfolio.compute_report failed for uid=%s: %s", uid, e)
        return report

    realized = 0.0
    wins = losses = 0
    best = 0.0
    worst = 0.0
    for r in rows:
        pnl = float(r[0] or 0.0)
        realized += pnl
        if pnl > 0:
            wins += 1
            if pnl > best:
                best = pnl
        elif pnl < 0:
            losses += 1
            if pnl < worst:
                worst = pnl

    report.trades = len(rows)
    report.wins = wins
    report.losses = losses
    report.realized_pnl = round(realized, 2)
    report.best_trade = round(best, 2)
    report.worst_trade = round(worst, 2)

    # ROI relative to user's capital_usd (best-effort)
    try:
        from storage import fetchone
        row = fetchone("SELECT capital_usd FROM users WHERE user_id=?", (uid,))
        capital = float(row[0]) if row and row[0] else 0.0
        if capital > 0:
            report.roi_pct = round((realized / capital) * 100.0, 2)
    except Exception:
        pass

    return report


# -------------------------------------------------------------------
# Bilingual rendering
# -------------------------------------------------------------------
def _tr(uid: Optional[int], key: str, fallback: str) -> str:
    try:
        from i18n import t as _t
        return _t(uid, key) or fallback
    except Exception:
        return fallback


def format_portfolio(uid: int, snap: PortfolioSnapshot, max_assets: int = 10) -> str:
    title = _tr(uid, "portfolio_title", "💼 Portfolio")

    if snap.sync_status == "NO_EXCHANGE":
        return (
            f"*{title}*\n"
            f"{_tr(uid, 'portfolio_no_exchange', 'No exchange connected.')}\n"
            f"{_tr(uid, 'portfolio_connect_hint', 'Use the Connect button to link your exchange.')}"
        )

    if snap.sync_status == "ERROR":
        return (
            f"*{title}*\n"
            f"{_tr(uid, 'portfolio_sync', 'Exchange Sync')}: `ERROR`\n"
            f"{snap.sync_error or '—'}"
        )

    # OK path
    when = time.strftime("%H:%M:%S", time.localtime(snap.last_sync_ts)) if snap.last_sync_ts else "—"
    lines = [
        f"*{title}*",
        f"{_tr(uid, 'portfolio_exchange', 'Exchange')}: `{snap.exchange_id.upper()}`",
        f"{_tr(uid, 'portfolio_sync', 'Exchange Sync')}: `OK`   _({when})_",
        "",
        f"{_tr(uid, 'portfolio_total', 'Total value')}: `${snap.total_value:,.2f}`",
        f"{_tr(uid, 'portfolio_cash', 'Available cash')}: `${snap.available_cash:,.2f}`",
        f"{_tr(uid, 'portfolio_positions_value', 'In positions')}: `${snap.positions_value:,.2f}`",
    ]

    if snap.assets:
        lines.append("")
        lines.append(f"_{_tr(uid, 'portfolio_assets', 'Assets')}:_")
        for a in snap.assets[:max_assets]:
            lines.append(
                f"• `{a.symbol}`  {a.amount:.6f}  @ `${a.price_usd:,.4f}`  = `${a.value_usd:,.2f}`"
            )
        if len(snap.assets) > max_assets:
            lines.append(f"_... +{len(snap.assets) - max_assets} more_")

    return "\n".join(lines)


def format_report(uid: int, report: PerformanceReport) -> str:
    title = _tr(uid, "portfolio_report_title", "📉 Performance Report")
    lines = [
        f"*{title}*  ({report.window_days}d)",
        f"{_tr(uid, 'portfolio_pnl', 'Realized PnL')}: `${report.realized_pnl:,.2f}`",
        f"{_tr(uid, 'portfolio_roi', 'ROI')}: `{report.roi_pct:+.2f}%`",
        f"{_tr(uid, 'portfolio_trades', 'Trades')}: `{report.trades}`  ({report.wins}W / {report.losses}L)",
        f"{_tr(uid, 'portfolio_win_rate', 'Win rate')}: `{report.win_rate:.1f}%`",
    ]
    if report.best_trade or report.worst_trade:
        lines.append(f"{_tr(uid, 'portfolio_best', 'Best trade')}: `${report.best_trade:,.2f}`")
        lines.append(f"{_tr(uid, 'portfolio_worst', 'Worst trade')}: `${report.worst_trade:,.2f}`")
    return "\n".join(lines)


# -------------------------------------------------------------------
# Panel header summary (cache-only — never triggers a fresh fetch)
# -------------------------------------------------------------------
def panel_summary(uid: int) -> str:
    """Short one-line summary for the control panel header.
    Reads ONLY from cache to avoid blocking the panel render or adding
    API load on every auto-refresh tick. Returns empty string if there's
    nothing to show."""
    if not is_enabled():
        return ""
    snap = _cached_snapshot(uid)
    if not snap:
        return ""  # panel stays clean until the user hits /portfolio once
    if snap.sync_status in ("NO_EXCHANGE", "ERROR"):
        return ""  # keep panel clean for paper/error users
    pnl_label = _tr(uid, "portfolio_pnl_short", "PnL")
    port_label = _tr(uid, "portfolio_short", "Portfolio")
    # Fetch 1-day PnL quickly from trades table (cheap, local)
    try:
        report = compute_report(uid, window_days=1)
        pnl_pct = f"{report.roi_pct:+.2f}%"
    except Exception:
        pnl_pct = "—"
    return f"{port_label}: `${snap.total_value:,.2f}`   {pnl_label}: `{pnl_pct}` _(1d)_"
