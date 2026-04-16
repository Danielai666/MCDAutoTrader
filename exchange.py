# exchange.py
# Exchange abstraction layer — split into public (shared) and authenticated (per-user) paths.
#
# Ownership model (enforced — see §18.25):
#   • Public (read-only) functions use an unauthenticated shared CCXT client.
#   • Authenticated functions (orders, balance, cancels) MUST use per-user
#     credentials from UserContext. There is NO silent fallback to the
#     platform owner's SETTINGS.KRAKEN_* keys for regular users.
#   • The legacy ctx=None branch (which used global keys) is explicitly
#     guarded by REQUIRE_PER_USER_CREDS — it raises NoCredentialsError
#     unless the caller opts in via allow_global=True (admin-only).
import logging
import ccxt
import pandas as pd
from config import SETTINGS

log = logging.getLogger(__name__)


class NoCredentialsError(Exception):
    """Raised when an authenticated exchange call is attempted without
    per-user credentials. Callers should convert this into a user-friendly
    'Live trading requires your own exchange connection' message."""
    pass


def _has_per_user_creds(ctx) -> bool:
    """Belt-and-braces check: has_exchange_keys property + direct string test."""
    if ctx is None:
        return False
    try:
        if hasattr(ctx, "has_exchange_keys"):
            return bool(ctx.has_exchange_keys)
    except Exception:
        pass
    return bool(getattr(ctx, "exchange_key", None)) and bool(getattr(ctx, "exchange_secret", None))

_public_client = None


def get_public_client():
    """Unauthenticated client for public data (OHLCV, tickers). Cached."""
    global _public_client
    if _public_client is None:
        _public_client = getattr(ccxt, SETTINGS.EXCHANGE)({'enableRateLimit': True})
    return _public_client


def get_user_client(ctx):
    """Authenticated client for a specific user's exchange credentials.
    ctx: UserContext with exchange_name, exchange_key, exchange_secret."""
    ex_name = getattr(ctx, 'exchange_name', None) or SETTINGS.EXCHANGE
    return getattr(ccxt, ex_name)({
        'enableRateLimit': True,
        'apiKey': ctx.exchange_key or None,
        'secret': ctx.exchange_secret or None,
    })


def get_client():
    """Backward-compat alias. Returns public client for read-only operations."""
    return get_public_client()


# -------------------------------------------------------------------
# Public data functions (no user auth needed)
# -------------------------------------------------------------------
def fetch_ohlcv(pair, timeframe, limit):
    ex = get_public_client()
    data = ex.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    return df


def market_price(pair):
    ex = get_public_client()
    t = ex.fetch_ticker(pair)
    return float(t['last'])


def health_check():
    """Check exchange connectivity. Returns (ok, message)."""
    try:
        ex = get_public_client()
        ex.fetch_time()
        return True, f'{SETTINGS.EXCHANGE} OK'
    except Exception as e:
        return False, f'{SETTINGS.EXCHANGE} error: {e}'


def validate_pair_on_exchange(pair):
    """Check if pair exists on exchange."""
    try:
        ex = get_public_client()
        ex.load_markets()
        return pair in ex.markets
    except Exception:
        return False


# -------------------------------------------------------------------
# Authenticated functions (need UserContext or fallback to SETTINGS)
# -------------------------------------------------------------------
def place_market_order(pair, side, amount, ctx=None, allow_global=False):
    """Place market order.

    Ownership enforcement (§18.25):
      - `ctx.paper_trading=True`: mock-fill returned, no exchange touched.
      - `ctx` with per-user creds: routes via user's CCXT client.
      - `ctx` without per-user creds (live): raises NoCredentialsError.
      - `ctx=None, PAPER_TRADING=True` (global paper): mock-fill.
      - `ctx=None, PAPER_TRADING=False, allow_global=False`: refused.
        Only admin-level callers may opt into global-key trading by
        passing `allow_global=True`.
    """
    if ctx:
        if ctx.paper_trading:
            return {'id': f'paper-{pair}-{side}', 'status': 'filled', 'side': side, 'amount': amount}
        if not _has_per_user_creds(ctx):
            raise NoCredentialsError(
                f"Live trade blocked: user {getattr(ctx, 'user_id', '?')} has no exchange credentials."
            )
        ex = get_user_client(ctx)
    elif SETTINGS.PAPER_TRADING:
        return {'id': f'paper-{pair}-{side}', 'status': 'filled', 'side': side, 'amount': amount}
    else:
        if not allow_global:
            raise NoCredentialsError(
                "Live trade blocked: no user context and allow_global=False. "
                "Regular users must use their own exchange credentials."
            )
        ex = getattr(ccxt, SETTINGS.EXCHANGE)({
            'enableRateLimit': True,
            'apiKey': SETTINGS.KRAKEN_API_KEY or None,
            'secret': SETTINGS.KRAKEN_API_SECRET or None,
        })
    return ex.create_order(symbol=pair, type='market', side=side.lower(), amount=amount)


def cancel_order(order_id, pair, ctx=None, allow_global=False):
    if ctx:
        if ctx.paper_trading:
            return {'id': order_id, 'status': 'cancelled'}
        if not _has_per_user_creds(ctx):
            raise NoCredentialsError(
                f"Cancel blocked: user {getattr(ctx, 'user_id', '?')} has no exchange credentials."
            )
        ex = get_user_client(ctx)
    elif SETTINGS.PAPER_TRADING:
        return {'id': order_id, 'status': 'cancelled'}
    else:
        if not allow_global:
            raise NoCredentialsError(
                "Cancel blocked: no user context and allow_global=False."
            )
        ex = getattr(ccxt, SETTINGS.EXCHANGE)({
            'enableRateLimit': True,
            'apiKey': SETTINGS.KRAKEN_API_KEY or None,
            'secret': SETTINGS.KRAKEN_API_SECRET or None,
        })
    return ex.cancel_order(order_id, symbol=pair)


def get_balance(currency='USDC', ctx=None, allow_global=False):
    if ctx:
        if ctx.paper_trading:
            return ctx.capital_usd
        if not _has_per_user_creds(ctx):
            raise NoCredentialsError(
                f"Balance blocked: user {getattr(ctx, 'user_id', '?')} has no exchange credentials."
            )
        ex = get_user_client(ctx)
    elif SETTINGS.PAPER_TRADING:
        return SETTINGS.CAPITAL_USD
    else:
        if not allow_global:
            raise NoCredentialsError(
                "Balance blocked: no user context and allow_global=False."
            )
        ex = getattr(ccxt, SETTINGS.EXCHANGE)({
            'enableRateLimit': True,
            'apiKey': SETTINGS.KRAKEN_API_KEY or None,
            'secret': SETTINGS.KRAKEN_API_SECRET or None,
        })
    try:
        bal = ex.fetch_balance()
        return float(bal.get('free', {}).get(currency, 0.0))
    except Exception:
        return 0.0
