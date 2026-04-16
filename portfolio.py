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
from storage import get_credential, fetchall, fetchone, execute

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
class OpenPosition:
    """Unified open-position record, sourced from either:
      - the bot's trades table (`source='bot'`) — gives us entry price for
        spot exchanges that have no native position concept, OR
      - CCXT fetch_positions (`source='exchange'`) — derivatives venues only.
    """
    symbol: str                # e.g. "BTC/USD" (bot) or "BTC/USD:USD" (derivatives)
    side: str                  # 'BUY' / 'SELL' (bot) or 'long' / 'short' (exchange)
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pct: float
    source: str = "bot"        # 'bot' | 'exchange'


@dataclass
class PortfolioSnapshot:
    # sync_status: 'OK' | 'NO_EXCHANGE' | 'PAPER' | 'ERROR'
    sync_status: str = "OK"
    sync_error: str = ""
    last_sync_ts: int = 0
    exchange_id: str = ""
    total_value: float = 0.0          # cash + positions_value (asset holdings)
    available_cash: float = 0.0       # stablecoin balance
    positions_value: float = 0.0      # non-stablecoin holdings (mark-to-market)
    unrealized_pnl: float = 0.0       # sum of unrealized PnL across open_positions
    true_equity: float = 0.0          # total_value (already mark-to-market) — kept
                                      # for parity with derivatives accounting
    assets: List[Asset] = field(default_factory=list)
    open_positions: List[OpenPosition] = field(default_factory=list)
    reconcile_warning: str = ""       # non-empty when bot/exchange disagree


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

        # --- Open positions + unrealized PnL -----------------------------
        # Primary source: bot trades table (has entry prices). Secondary:
        # fetch_positions() if the exchange supports it (derivatives only;
        # Kraken spot returns []).
        snap.open_positions = _collect_open_positions(uid, client, exchange_id)
        snap.unrealized_pnl = round(
            sum(p.unrealized_pnl for p in snap.open_positions), 2
        )
        # true_equity = mark-to-market of all holdings. On spot, this is
        # already total_value because `assets` is priced at current marks.
        # Kept as a named field for dashboard parity.
        snap.true_equity = snap.total_value

        # --- Reconciliation: bot expected qty vs exchange balance --------
        snap.reconcile_warning = _reconcile_check(uid, balance)

        snap.sync_status = "OK"
    except Exception as e:
        log.warning("portfolio fetch_balance failed for uid=%s: %s", uid, e)
        snap.sync_status = "ERROR"
        snap.sync_error = str(e)[:160]

    return snap


# -------------------------------------------------------------------
# Open positions + unrealized PnL
# -------------------------------------------------------------------
def _base_asset(pair: str) -> str:
    """Return base asset from a pair like 'BTC/USDT' → 'BTC'."""
    return (pair or "").split("/")[0].split(":")[0].upper()


def _collect_open_positions(uid: int, client, exchange_id: str) -> List[OpenPosition]:
    positions: List[OpenPosition] = []

    # 1. Bot-tracked OPEN trades (primary for spot)
    try:
        rows = fetchall(
            "SELECT pair, side, qty, entry FROM trades "
            "WHERE user_id=? AND status='OPEN'",
            (uid,),
        )
    except Exception as e:
        log.debug("portfolio: bot trades query failed: %s", e)
        rows = []

    for row in rows:
        pair, side, qty, entry = row
        try:
            qty_f = float(qty or 0.0)
            entry_f = float(entry or 0.0)
        except (TypeError, ValueError):
            continue
        if qty_f <= 0 or entry_f <= 0:
            continue
        # Get current price via ticker
        try:
            t = client.fetch_ticker(pair)
            cur = float(t.get("last") or t.get("close") or 0.0)
        except Exception:
            cur = 0.0
        if cur <= 0:
            # Fall back to stablecoin valuation through _usd_price
            cur = _usd_price(client, exchange_id, _base_asset(pair))
        if cur <= 0:
            continue
        side_u = (side or "BUY").upper()
        if side_u == "BUY":
            upnl = (cur - entry_f) * qty_f
        else:
            upnl = (entry_f - cur) * qty_f
        upct = ((cur - entry_f) / entry_f * 100.0) if side_u == "BUY" else \
               ((entry_f - cur) / entry_f * 100.0)
        positions.append(OpenPosition(
            symbol=pair, side=side_u, size=qty_f,
            entry_price=round(entry_f, 6), current_price=round(cur, 6),
            unrealized_pnl=round(upnl, 2), unrealized_pct=round(upct, 2),
            source="bot",
        ))

    # 2. Derivatives-style fetch_positions (bonus; harmless on spot)
    try:
        if client.has.get("fetchPositions"):
            exch_positions = client.fetch_positions() or []
            for p in exch_positions:
                try:
                    contracts = float(p.get("contracts") or 0.0)
                    if contracts <= 0:
                        continue
                    entry = float(p.get("entryPrice") or 0.0)
                    mark = float(p.get("markPrice") or p.get("lastPrice") or 0.0)
                    upnl = float(p.get("unrealizedPnl") or 0.0)
                    upct = float(p.get("percentage") or 0.0)
                    positions.append(OpenPosition(
                        symbol=str(p.get("symbol", "?")),
                        side=str(p.get("side", "")).lower(),
                        size=contracts,
                        entry_price=round(entry, 6),
                        current_price=round(mark, 6),
                        unrealized_pnl=round(upnl, 2),
                        unrealized_pct=round(upct, 2),
                        source="exchange",
                    ))
                except Exception:
                    continue
    except Exception:
        # Many spot exchanges raise on fetch_positions. Silent fallback.
        pass

    return positions


def _reconcile_check(uid: int, balance: dict) -> str:
    """
    Lightweight per-user reconciliation: for each symbol the bot has OPEN
    trades on, verify the exchange balance is at least the bot-expected qty.
    Returns a warning string or empty.

    On spot, user may hold MORE than bot-tracked (pre-existing balance is
    fine). Flag only under-balance: bot expects 0.01 BTC but exchange
    shows 0.005 BTC → probably a manual close or failed trade.
    """
    try:
        rows = fetchall(
            "SELECT pair, SUM(qty) FROM trades "
            "WHERE user_id=? AND status='OPEN' AND side='BUY' "
            "GROUP BY pair",
            (uid,),
        )
    except Exception:
        return ""

    totals = balance.get("total", {}) or {}
    warnings = []
    for pair, expected_qty in rows:
        try:
            expected = float(expected_qty or 0.0)
        except (TypeError, ValueError):
            continue
        if expected <= 0:
            continue
        asset = _base_asset(pair)
        have = 0.0
        try:
            have = float(totals.get(asset, 0.0) or 0.0)
        except (TypeError, ValueError):
            have = 0.0
        # Tolerate 1% float drift (rounding / fees)
        if have < expected * 0.99:
            warnings.append(f"{asset}: bot expects {expected:.6f}, exchange has {have:.6f}")
    if warnings:
        return "⚠️ Sync mismatch: " + "; ".join(warnings)
    return ""


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
    # Opportunistic snapshot save (throttled internally, only when OK status)
    try:
        save_snapshot(uid, snap)
    except Exception as e:
        log.debug("portfolio.save_snapshot after fetch failed uid=%s: %s", uid, e)
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


def _signed_money(v: float) -> str:
    """Render a signed USD amount with the sign on the OUTSIDE of the $:
    12.3 -> '+$12.30', -5.0 -> '-$5.00', 0 -> '$0.00'."""
    try:
        v = float(v or 0.0)
    except (TypeError, ValueError):
        v = 0.0
    if v > 0:
        return f"+${v:,.2f}"
    if v < 0:
        return f"-${abs(v):,.2f}"
    return f"${v:,.2f}"


def _relative_time(ts: int, uid: Optional[int] = None) -> str:
    """Human-friendly 'N min ago' for UX."""
    if not ts:
        return "—"
    diff = int(time.time()) - int(ts)
    if diff < 60:
        return f"{diff} {_tr(uid, 'portfolio_seconds_ago', 'sec ago')}"
    if diff < 3600:
        return f"{diff // 60} {_tr(uid, 'portfolio_minutes_ago', 'min ago')}"
    if diff < 86400:
        return f"{diff // 3600} {_tr(uid, 'portfolio_hours_ago', 'hr ago')}"
    return f"{diff // 86400} {_tr(uid, 'portfolio_days_ago', 'days ago')}"


def _portfolio_insight(uid: int, snap: PortfolioSnapshot) -> str:
    """Compact two-line insight on portfolio posture. Uses cash %
    (stablecoin + USD) vs positions. Heuristic, honest framing."""
    total = snap.total_value or 0.0
    if total <= 0:
        return ""
    cash_pct = (snap.available_cash / total * 100.0)
    invested_pct = 100.0 - cash_pct

    if cash_pct >= 70:
        bias_key = "portfolio_insight_conservative"
        note_key = "portfolio_insight_conservative_note"
    elif cash_pct >= 40:
        bias_key = "portfolio_insight_balanced"
        note_key = "portfolio_insight_balanced_note"
    else:
        bias_key = "portfolio_insight_aggressive"
        note_key = "portfolio_insight_aggressive_note"

    title = _tr(uid, "portfolio_insight_title", "🧠 Portfolio Insight")
    bias = _tr(uid, bias_key, "Balanced")
    note = _tr(uid, note_key, f"{invested_pct:.0f}% invested, {cash_pct:.0f}% cash")
    return f"*{title}*\n• {bias}\n• {note}"


# Colored-dot markers for Assets Breakdown (cycled by index)
_ASSET_DOTS = ["🟢", "🟡", "🔵", "🟣", "🟠", "⚪", "🔴"]


def format_portfolio(uid: int, snap: PortfolioSnapshot, max_assets: int = 10) -> str:
    """Professional, visual portfolio dashboard (§18.27).
    Presentation-only rewrite — no data model changes."""
    title = _tr(uid, "portfolio_overview_title", "💼 Portfolio Overview")

    if snap.sync_status == "NO_EXCHANGE":
        return (
            f"*{title}*\n\n"
            f"🔌 {_tr(uid, 'portfolio_no_exchange', 'No exchange connected.')}\n"
            f"_{_tr(uid, 'portfolio_connect_hint', 'Use the Connect button to link your exchange.')}_"
        )

    if snap.sync_status == "ERROR":
        return (
            f"*{title}*\n\n"
            f"⚠️ {_tr(uid, 'portfolio_sync', 'Exchange Sync')}: `ERROR`\n"
            f"_{snap.sync_error or '—'}_"
        )

    # OK path — clean, scannable layout
    total = snap.total_value or 0.0
    cash = snap.available_cash or 0.0
    invested = snap.positions_value or 0.0
    upnl = snap.unrealized_pnl or 0.0
    cash_pct = (cash / total * 100.0) if total > 0 else 0.0
    invested_pct = (invested / total * 100.0) if total > 0 else 0.0
    upnl_pct = (upnl / (total - upnl) * 100.0) if (total - upnl) != 0 else 0.0

    rel_sync = _relative_time(snap.last_sync_ts, uid)

    lines = [
        f"*{title}*",
        "",
        f"💰 {_tr(uid, 'portfolio_total', 'Total Value')}: `${total:,.2f}`",
        f"💵 {_tr(uid, 'portfolio_cash', 'Cash')}: `${cash:,.2f}` _({cash_pct:.1f}%)_",
        f"📊 {_tr(uid, 'portfolio_invested', 'Invested')}: `${invested:,.2f}` _({invested_pct:.1f}%)_",
        "",
        f"📈 {_tr(uid, 'portfolio_unrealized', 'Unrealized PnL')}: `{_signed_money(upnl)}` _({upnl_pct:+.2f}%)_",
        f"🔄 {_tr(uid, 'portfolio_last_sync', 'Last Sync')}: _{rel_sync}_",
        f"🔗 {_tr(uid, 'portfolio_exchange', 'Exchange')}: `{_tr(uid, 'account_connected', 'Connected')}` _({snap.exchange_id.upper()})_",
    ]

    # Reconcile warning (kept) — subtle
    if snap.reconcile_warning:
        lines.append("")
        lines.append(snap.reconcile_warning)

    # Assets Breakdown — clean separator, colored dots, allocation %
    if snap.assets:
        lines.append("")
        lines.append(f"*{_tr(uid, 'portfolio_assets_breakdown', 'Assets Breakdown')}*")
        for i, a in enumerate(snap.assets[:max_assets]):
            dot = _ASSET_DOTS[i % len(_ASSET_DOTS)]
            pct = (a.value_usd / total * 100.0) if total > 0 else 0.0
            # Below-1% assets get a compact line
            if pct < 1.0:
                lines.append(f"{dot} `{a.symbol}` — `${a.value_usd:,.2f}`")
            else:
                lines.append(f"{dot} `{a.symbol}` — `${a.value_usd:,.2f}` _({pct:.1f}%)_")
        if len(snap.assets) > max_assets:
            lines.append(f"_… +{len(snap.assets) - max_assets} more_")

    # Open positions (bot-tracked) — kept after assets
    if snap.open_positions:
        lines.append("")
        lines.append(f"*{_tr(uid, 'portfolio_open_positions', 'Open Positions')}*")
        for p in snap.open_positions[:max_assets]:
            src = "🤖" if p.source == "bot" else "📊"
            lines.append(
                f"{src} `{p.symbol}` {p.side}  {p.size:.6f}  "
                f"@ `${p.entry_price:,.2f}` → `${p.current_price:,.2f}`  "
                f"{_signed_money(p.unrealized_pnl)} _({p.unrealized_pct:+.2f}%)_"
            )

    # Portfolio Insight (heuristic bias) — compact visual footer
    insight = _portfolio_insight(uid, snap)
    if insight:
        lines.append("")
        lines.append(insight)

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
    """Multi-line summary for the control panel header.
    Reads ONLY from cache to avoid blocking the panel render or adding
    API load on every auto-refresh tick. Returns empty string if there's
    nothing to show."""
    if not is_enabled():
        return ""
    snap = _cached_snapshot(uid)
    if not snap:
        return ""  # panel stays clean until the user hits /portfolio once
    if snap.sync_status in ("NO_EXCHANGE", "ERROR"):
        return ""
    pnl_label = _tr(uid, "portfolio_pnl_short", "PnL")
    port_label = _tr(uid, "portfolio_short", "Portfolio")
    upnl_label = _tr(uid, "portfolio_unrealized_short", "Unrealized")
    # 1-day realized PnL quickly from trades table (cheap, local)
    try:
        report = compute_report(uid, window_days=1)
        pnl_pct = f"{report.roi_pct:+.2f}%"
    except Exception:
        pnl_pct = "—"
    upnl = snap.unrealized_pnl or 0.0
    total = snap.total_value or 0.0
    invested = snap.positions_value or 0.0
    exposure_pct = (invested / total * 100.0) if total > 0 else 0.0
    cash_label = _tr(uid, "portfolio_cash_short", "Cash")
    exposure_label = _tr(uid, "portfolio_exposure_short", "Exposure")
    line1 = f"{port_label}: `${total:,.2f}`   {cash_label}: `${snap.available_cash:,.2f}`"
    line2 = f"{pnl_label}: `{pnl_pct}` _(1d)_   {upnl_label}: `{_signed_money(upnl)}`"
    line3 = f"{exposure_label}: `{exposure_pct:.0f}%`"
    return f"{line1}\n{line2}\n{line3}"


# -------------------------------------------------------------------
# Real trade-history report (/portfolio report real)
# Uses CCXT fetch_my_trades if supported. Computes simple buy-cost vs
# sell-proceeds aggregation per symbol within a time window. NOT FIFO-
# accurate — clearly labeled in UI as "approximate".
# -------------------------------------------------------------------
# uid -> (ts, PerformanceReport)  — small cache to protect API quotas
_real_report_cache: dict = {}
REAL_REPORT_TTL = 300  # 5 minutes


def _compute_real_report_sync(uid: int, window_days: int) -> PerformanceReport:
    report = PerformanceReport(window_days=window_days)
    cred = get_credential(uid, "ccxt")
    if not cred:
        return report
    try:
        from crypto_utils import decrypt_exchange_keys
        api_key, api_secret = decrypt_exchange_keys(
            cred["api_key_enc"], cred["api_secret_enc"],
            cred.get("data_key_enc", ""),
            int(cred.get("encryption_version", 1)),
        )
    except Exception:
        return report

    exchange_id = cred["exchange_id"]
    try:
        from ccxt_provider import CCXTProvider
        client = CCXTProvider(exchange_id, api_key, api_secret)._client
        if not client.has.get("fetchMyTrades"):
            return report
        since_ms = int((time.time() - window_days * 86400) * 1000)
        trades = client.fetch_my_trades(since=since_ms, limit=500) or []
    except Exception as e:
        log.warning("portfolio real report fetch failed: %s", e)
        return report

    # Per-symbol buy-cost vs sell-proceeds aggregation (approximate)
    by_sym: dict = {}
    for tr in trades:
        sym = tr.get("symbol")
        side = (tr.get("side") or "").lower()
        price = float(tr.get("price") or 0)
        amount = float(tr.get("amount") or 0)
        cost = float(tr.get("cost") or price * amount)
        fee = 0.0
        f = tr.get("fee") or {}
        if f and isinstance(f, dict):
            fee = float(f.get("cost") or 0)
        if not sym or amount <= 0 or cost <= 0:
            continue
        s = by_sym.setdefault(sym, {"buy_cost": 0.0, "sell_proceeds": 0.0,
                                     "buy_qty": 0.0, "sell_qty": 0.0,
                                     "fees": 0.0, "fills": 0})
        if side == "buy":
            s["buy_cost"] += cost
            s["buy_qty"] += amount
        elif side == "sell":
            s["sell_proceeds"] += cost
            s["sell_qty"] += amount
        s["fees"] += fee
        s["fills"] += 1

    realized = 0.0
    wins = losses = 0
    total_fills = 0
    best = 0.0
    worst = 0.0
    for sym, s in by_sym.items():
        # Approximation: realized PnL per symbol = min(buy_qty, sell_qty)
        # worth of sells minus the proportional buy cost.
        qty_realized = min(s["buy_qty"], s["sell_qty"])
        if qty_realized <= 0:
            continue
        avg_buy = s["buy_cost"] / s["buy_qty"] if s["buy_qty"] else 0.0
        avg_sell = s["sell_proceeds"] / s["sell_qty"] if s["sell_qty"] else 0.0
        pnl = (avg_sell - avg_buy) * qty_realized - s["fees"]
        realized += pnl
        total_fills += s["fills"]
        if pnl > 0:
            wins += 1
            if pnl > best:
                best = pnl
        elif pnl < 0:
            losses += 1
            if pnl < worst:
                worst = pnl

    report.trades = total_fills
    report.wins = wins
    report.losses = losses
    report.realized_pnl = round(realized, 2)
    report.best_trade = round(best, 2)
    report.worst_trade = round(worst, 2)
    try:
        from storage import fetchone
        row = fetchone("SELECT capital_usd FROM users WHERE user_id=?", (uid,))
        capital = float(row[0]) if row and row[0] else 0.0
        if capital > 0:
            report.roi_pct = round((realized / capital) * 100.0, 2)
    except Exception:
        pass
    return report


async def compute_report_real(uid: int, window_days: int = 7) -> PerformanceReport:
    """Async wrapper with short cache — hits exchange fetch_my_trades."""
    if not is_enabled():
        return PerformanceReport(window_days=window_days)
    cached = _real_report_cache.get(uid)
    if cached and (time.time() - cached[0]) < REAL_REPORT_TTL \
            and cached[1].window_days == window_days:
        return cached[1]
    loop = asyncio.get_event_loop()
    report = await loop.run_in_executor(None, _compute_real_report_sync, uid, window_days)
    _real_report_cache[uid] = (time.time(), report)
    return report


# -------------------------------------------------------------------
# Portfolio snapshots (historical reporting — §18.26)
# Lightweight per-user persistence so /portfolio history can report
# real portfolio value change over time. Honest design:
#   - Save snapshot only on successful live fetch_portfolio() calls
#   - Throttle to at most once per hour per user (prevent row spam)
#   - Only saves real exchange data (sync_status='OK'); NO_EXCHANGE /
#     ERROR snapshots are NOT persisted
#   - Historical data builds up from the moment a user first runs
#     /portfolio — no faked historical values
# -------------------------------------------------------------------
SNAPSHOT_MIN_INTERVAL = 3600  # seconds — 1h min between saves per user


def save_snapshot(uid: int, snap: PortfolioSnapshot) -> bool:
    """Persist a snapshot. Returns True if saved, False if skipped
    (throttled or non-OK state). Safe to call on every fetch; handles
    throttling internally."""
    if not is_enabled() or snap.sync_status != "OK":
        return False
    try:
        # Throttle: skip if we already saved within last SNAPSHOT_MIN_INTERVAL
        latest = fetchone(
            "SELECT ts FROM portfolio_snapshots WHERE user_id=? ORDER BY ts DESC LIMIT 1",
            (uid,),
        )
        if latest and latest[0] is not None:
            if (int(time.time()) - int(latest[0])) < SNAPSHOT_MIN_INTERVAL:
                return False
        import json as _json
        asset_summary = _json.dumps([
            {"symbol": a.symbol, "amount": a.amount,
             "price_usd": a.price_usd, "value_usd": a.value_usd}
            for a in (snap.assets or [])
        ])
        execute(
            "INSERT INTO portfolio_snapshots"
            "(user_id, ts, total_value, cash_value, positions_value, "
            " unrealized_pnl, asset_summary_json, exchange_id) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uid, int(time.time()),
             float(snap.total_value or 0), float(snap.available_cash or 0),
             float(snap.positions_value or 0), float(snap.unrealized_pnl or 0),
             asset_summary, snap.exchange_id or ""),
        )
        return True
    except Exception as e:
        log.debug("portfolio.save_snapshot failed uid=%s: %s", uid, e)
        return False


def get_oldest_snapshot_in_window(uid: int, days: int):
    """Return (ts, total_value, cash_value) tuple for the oldest snapshot
    within the lookback window, or None if no snapshot exists."""
    try:
        since = int(time.time()) - max(1, int(days)) * 86400
        row = fetchone(
            "SELECT ts, total_value, cash_value FROM portfolio_snapshots "
            "WHERE user_id=? AND ts >= ? ORDER BY ts ASC LIMIT 1",
            (uid, since),
        )
        return row if row else None
    except Exception as e:
        log.debug("portfolio.get_oldest_snapshot_in_window failed: %s", e)
        return None


def get_latest_snapshot(uid: int):
    """Return (ts, total_value, cash_value) tuple for the most recent snapshot."""
    try:
        row = fetchone(
            "SELECT ts, total_value, cash_value FROM portfolio_snapshots "
            "WHERE user_id=? ORDER BY ts DESC LIMIT 1",
            (uid,),
        )
        return row if row else None
    except Exception as e:
        log.debug("portfolio.get_latest_snapshot failed: %s", e)
        return None


def get_snapshot_count(uid: int) -> int:
    try:
        row = fetchone("SELECT COUNT(*) FROM portfolio_snapshots WHERE user_id=?", (uid,))
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


# -------------------------------------------------------------------
# /portfolio history render
# -------------------------------------------------------------------
def format_history(uid: int, days: int = 7) -> str:
    """Render a portfolio history report for the lookback window.
    Honest behaviour: if insufficient history, tell the user clearly —
    never fabricate historical values."""
    if not is_enabled():
        return _tr(uid, "portfolio_no_exchange", "No exchange connected.")

    title = _tr(uid, "portfolio_history_title", "📈 Portfolio History")
    current = get_latest_snapshot(uid)
    if not current:
        return (
            f"*{title}*  ({days}d)\n\n"
            f"{_tr(uid, 'portfolio_history_empty', 'Portfolio history not available yet. Run /portfolio to record your first snapshot.')}"
        )
    oldest = get_oldest_snapshot_in_window(uid, days)
    # If no snapshot in window, use earliest overall
    if not oldest:
        try:
            row = fetchone(
                "SELECT ts, total_value, cash_value FROM portfolio_snapshots "
                "WHERE user_id=? ORDER BY ts ASC LIMIT 1",
                (uid,),
            )
            oldest = row if row else None
        except Exception:
            oldest = None
    cur_ts, cur_val, cur_cash = int(current[0]), float(current[1] or 0), float(current[2] or 0)

    if not oldest or oldest[0] == current[0]:
        # Only one snapshot exists — report just the current value
        n_snaps = get_snapshot_count(uid)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(cur_ts))
        return (
            f"*{title}*  ({days}d)\n\n"
            f"{_tr(uid, 'portfolio_history_first', 'First snapshot recorded')} _({when})_\n"
            f"{_tr(uid, 'portfolio_total', 'Total value')}: `${cur_val:,.2f}`\n"
            f"{_tr(uid, 'portfolio_cash', 'Available cash')}: `${cur_cash:,.2f}`\n"
            f"_{_tr(uid, 'portfolio_history_insufficient', 'Not enough history for change calc. Check back later.')}_\n"
            f"_{_tr(uid, 'portfolio_snapshot_count', 'Snapshots stored')}: {n_snaps}_"
        )

    old_ts, old_val, old_cash = int(oldest[0]), float(oldest[1] or 0), float(oldest[2] or 0)
    delta = cur_val - old_val
    roi = (delta / old_val * 100.0) if old_val > 0 else 0.0
    span_hours = (cur_ts - old_ts) / 3600.0
    span_days = span_hours / 24.0

    old_when = time.strftime("%Y-%m-%d %H:%M", time.localtime(old_ts))
    cur_when = time.strftime("%Y-%m-%d %H:%M", time.localtime(cur_ts))
    n_snaps = get_snapshot_count(uid)

    lines = [
        f"*{title}*  ({days}d)",
        "",
        f"{_tr(uid, 'portfolio_history_from', 'From')}: `{old_when}`",
        f"{_tr(uid, 'portfolio_history_to', 'To')}: `{cur_when}`",
        f"{_tr(uid, 'portfolio_history_span', 'Span')}: `{span_days:.1f}d`",
        "",
        f"{_tr(uid, 'portfolio_history_start_value', 'Start value')}: `${old_val:,.2f}`",
        f"{_tr(uid, 'portfolio_history_end_value', 'End value')}: `${cur_val:,.2f}`",
        f"{_tr(uid, 'portfolio_history_change', 'Change')}: `{_signed_money(delta)}` ({roi:+.2f}%)",
        "",
        f"_{_tr(uid, 'portfolio_snapshot_count', 'Snapshots stored')}: {n_snaps}_",
    ]
    return "\n".join(lines)


# -------------------------------------------------------------------
# /portfolio asset <symbol> render
# -------------------------------------------------------------------
def format_asset_detail(uid: int, symbol: str, snap: Optional[PortfolioSnapshot] = None) -> str:
    """Render detail for a single asset from the latest cached snapshot,
    or from a provided snapshot. Read-only, no exchange call inside."""
    if not is_enabled():
        return _tr(uid, "portfolio_no_exchange", "No exchange connected.")

    if snap is None:
        snap = _cached_snapshot(uid)
    if not snap or snap.sync_status != "OK":
        return _tr(uid, "portfolio_asset_need_sync", "Run /portfolio first to load wallet data.")

    sym = (symbol or "").upper().strip()
    match = None
    for a in snap.assets or []:
        if a.symbol.upper() == sym:
            match = a
            break

    title = f"*{_tr(uid, 'portfolio_asset_title', '💎 Asset Detail')}: `{sym}`*"
    if not match:
        return f"{title}\n\n_{_tr(uid, 'portfolio_asset_not_found', 'Asset not in your wallet.')}_"

    total = snap.total_value or 1.0
    pct = (match.value_usd / total * 100.0) if total > 0 else 0.0

    lines = [
        title,
        "",
        f"{_tr(uid, 'portfolio_asset_amount', 'Amount')}: `{match.amount:.8f}`",
        f"{_tr(uid, 'portfolio_asset_price', 'Price (USD)')}: `${match.price_usd:,.4f}`",
        f"{_tr(uid, 'portfolio_asset_value', 'Value (USD)')}: `${match.value_usd:,.2f}`",
        f"{_tr(uid, 'portfolio_asset_alloc', 'Allocation')}: `{pct:.2f}%`",
    ]
    # Include any open positions on this symbol (bot-tracked)
    own_positions = [p for p in (snap.open_positions or [])
                     if _base_asset(p.symbol) == sym]
    if own_positions:
        lines.append("")
        lines.append(f"_{_tr(uid, 'portfolio_asset_positions', 'Open positions')}:_")
        for p in own_positions:
            lines.append(
                f"• `{p.symbol}` {p.side}  {p.size:.6f}  "
                f"@ `${p.entry_price:,.2f}` → `${p.current_price:,.2f}`  "
                f"{_signed_money(p.unrealized_pnl)} ({p.unrealized_pct:+.2f}%)"
            )
    return "\n".join(lines)
