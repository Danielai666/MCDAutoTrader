# trading_provider.py
# Abstract trading provider interface.
# Concrete implementations: CCXTProvider (crypto), MT5Provider (future).
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class OrderResult:
    order_id: str
    status: str       # 'filled', 'partial', 'failed', 'cancelled'
    side: str
    amount: float
    filled_price: Optional[float] = None
    raw: Optional[dict] = None


@dataclass
class BalanceResult:
    free: float
    used: float
    total: float
    currency: str


class ITradingProvider(ABC):
    """Abstract interface for any trading provider."""

    @abstractmethod
    def validate_credentials(self) -> tuple:
        """Test credentials. Returns (ok: bool, message: str)."""
        ...

    @abstractmethod
    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Fetch OHLCV candle data. Returns DataFrame [ts, open, high, low, close, volume]."""
        ...

    @abstractmethod
    def market_price(self, pair: str) -> float:
        """Get current market price for a pair."""
        ...

    @abstractmethod
    def place_market_order(self, pair: str, side: str, amount: float) -> OrderResult:
        """Place a market order."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str, pair: str) -> OrderResult:
        """Cancel an existing order."""
        ...

    @abstractmethod
    def get_balance(self, currency: str = 'USDC') -> BalanceResult:
        """Get balance for a currency."""
        ...

    @abstractmethod
    def health_check(self) -> tuple:
        """Check provider connectivity. Returns (ok: bool, message: str)."""
        ...

    @abstractmethod
    def validate_pair(self, pair: str) -> bool:
        """Check if a trading pair is valid on this provider."""
        ...
