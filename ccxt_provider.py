# ccxt_provider.py
# CCXT-based trading provider. Supports any exchange via CCXT library.
import logging
import ccxt
import pandas as pd
from trading_provider import ITradingProvider, OrderResult, BalanceResult

log = logging.getLogger(__name__)

# Exchanges that require a passphrase in addition to key+secret
PASSPHRASE_EXCHANGES = {'kucoin', 'coinbasepro', 'okx'}

# Popular exchanges for the Telegram connect flow
SUPPORTED_EXCHANGES = [
    'kraken', 'binance', 'bybit', 'coinbasepro', 'kucoin',
    'okx', 'bitfinex', 'gate', 'mexc', 'htx',
]


class CCXTProvider(ITradingProvider):
    """CCXT-based trading provider for any supported exchange."""

    def __init__(self, exchange_id: str, api_key: str = '', api_secret: str = '',
                 passphrase: str = ''):
        self.exchange_id = exchange_id.lower()
        self._client = getattr(ccxt, self.exchange_id)({
            'enableRateLimit': True,
            'apiKey': api_key or None,
            'secret': api_secret or None,
            **(({'password': passphrase} if passphrase else {})),
        })

    def validate_credentials(self) -> tuple:
        try:
            self._client.fetch_balance()
            return True, f'{self.exchange_id} credentials valid'
        except ccxt.AuthenticationError as e:
            return False, f'Authentication failed: {e}'
        except Exception as e:
            return False, f'Validation error: {e}'

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int) -> pd.DataFrame:
        data = self._client.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(data, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df

    def market_price(self, pair: str) -> float:
        t = self._client.fetch_ticker(pair)
        return float(t['last'])

    def place_market_order(self, pair: str, side: str, amount: float) -> OrderResult:
        result = self._client.create_order(
            symbol=pair, type='market', side=side.lower(), amount=amount)
        return OrderResult(
            order_id=str(result.get('id', '')),
            status=result.get('status', 'filled'),
            side=side,
            amount=amount,
            filled_price=result.get('average') or result.get('price'),
            raw=result,
        )

    def cancel_order(self, order_id: str, pair: str) -> OrderResult:
        result = self._client.cancel_order(order_id, symbol=pair)
        return OrderResult(
            order_id=str(result.get('id', order_id)),
            status='cancelled',
            side='',
            amount=0,
            raw=result,
        )

    def get_balance(self, currency: str = 'USDC') -> BalanceResult:
        bal = self._client.fetch_balance()
        free = float(bal.get('free', {}).get(currency, 0.0))
        used = float(bal.get('used', {}).get(currency, 0.0))
        total = float(bal.get('total', {}).get(currency, 0.0))
        return BalanceResult(free=free, used=used, total=total, currency=currency)

    def health_check(self) -> tuple:
        try:
            self._client.fetch_time()
            return True, f'{self.exchange_id} OK'
        except Exception as e:
            return False, f'{self.exchange_id} error: {e}'

    def validate_pair(self, pair: str) -> bool:
        try:
            self._client.load_markets()
            return pair in self._client.markets
        except Exception:
            return False


class PaperProvider(ITradingProvider):
    """Wraps any provider but intercepts orders for paper trading."""

    def __init__(self, real_provider: ITradingProvider, capital: float = 1000.0):
        self._real = real_provider
        self._capital = capital

    def validate_credentials(self) -> tuple:
        return True, 'Paper mode (no credentials needed)'

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int) -> pd.DataFrame:
        return self._real.fetch_ohlcv(pair, timeframe, limit)

    def market_price(self, pair: str) -> float:
        return self._real.market_price(pair)

    def place_market_order(self, pair: str, side: str, amount: float) -> OrderResult:
        return OrderResult(
            order_id=f'paper-{pair}-{side}',
            status='filled',
            side=side,
            amount=amount,
            filled_price=None,
        )

    def cancel_order(self, order_id: str, pair: str) -> OrderResult:
        return OrderResult(order_id=order_id, status='cancelled', side='', amount=0)

    def get_balance(self, currency: str = 'USDC') -> BalanceResult:
        return BalanceResult(free=self._capital, used=0, total=self._capital, currency=currency)

    def health_check(self) -> tuple:
        return self._real.health_check()

    def validate_pair(self, pair: str) -> bool:
        return self._real.validate_pair(pair)


# -------------------------------------------------------------------
# Factory
# -------------------------------------------------------------------
def create_provider(exchange_id: str, api_key: str = '', api_secret: str = '',
                    passphrase: str = '', paper: bool = True,
                    capital: float = 1000.0) -> ITradingProvider:
    """Factory: create the appropriate provider for an exchange."""
    real = CCXTProvider(exchange_id, api_key, api_secret, passphrase)
    if paper:
        return PaperProvider(real, capital)
    return real


def get_public_provider(exchange_id: str = 'kraken') -> CCXTProvider:
    """Unauthenticated provider for public data only."""
    return CCXTProvider(exchange_id)
