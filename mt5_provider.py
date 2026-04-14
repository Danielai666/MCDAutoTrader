# mt5_provider.py
# MT5 trading provider — sends commands to MT5 EA via the bridge REST API.
# The EA executes trades locally on the user's MT5 terminal.
# We never store broker credentials on our server.

import json
import time
import logging
import hashlib
import hmac as hmac_mod
import secrets
from typing import Optional
import pandas as pd

from trading_provider import ITradingProvider, OrderResult, BalanceResult
from mt5_bridge import (resolve_symbol, canonical_from_broker,
                         compute_mt5_lot_size, is_market_open,
                         is_in_rollover_window, check_spread_guard)

log = logging.getLogger(__name__)


class MT5Provider(ITradingProvider):
    """
    MT5 trading provider.
    Commands are queued and picked up by the EA via the bridge API.
    The EA reports results back via /trade/open and /trade/close endpoints.

    This provider doesn't execute trades directly — it publishes intent
    that the EA picks up via /signals endpoint.
    """

    def __init__(self, user_id: int, bridge_token_id: str = '',
                 symbol_map: dict = None):
        self.user_id = user_id
        self.bridge_token_id = bridge_token_id
        self.symbol_map = symbol_map or {}
        self._command_queue = []  # Pending commands for EA

    def validate_credentials(self) -> tuple:
        """Check if bridge connection exists and was recently seen."""
        from mt5_bridge import get_bridge_connection
        conn = get_bridge_connection(self.user_id)
        if not conn:
            return False, "No MT5 bridge connection configured"
        last_seen = conn.get('last_seen')
        if last_seen:
            age = int(time.time()) - last_seen
            if age > 300:  # 5 minutes
                return True, f"Bridge connected but last seen {age}s ago (may be offline)"
            return True, f"Bridge connected, last seen {age}s ago"
        return True, "Bridge configured but EA has not connected yet"

    def fetch_ohlcv(self, pair: str, timeframe: str, limit: int) -> pd.DataFrame:
        """MT5 OHLCV not directly available from server side.
        For analysis, we use CCXT public data as a fallback."""
        from exchange import fetch_ohlcv as ccxt_fetch
        # Map to crypto equivalent if possible, otherwise try directly
        try:
            return ccxt_fetch(pair, timeframe, limit)
        except Exception:
            # Return empty DataFrame for MT5-only symbols
            return pd.DataFrame(columns=['ts', 'open', 'high', 'low', 'close', 'volume'])

    def market_price(self, pair: str) -> float:
        """MT5 price not directly available. Use CCXT as fallback."""
        from exchange import market_price as ccxt_price
        try:
            return ccxt_price(pair)
        except Exception:
            return 0.0

    def place_market_order(self, pair: str, side: str, amount: float) -> OrderResult:
        """Queue a trade command for the EA to pick up.
        The EA will execute it on MT5 and report back via /trade/open.
        """
        # Pre-flight checks
        broker_symbol = resolve_symbol(pair, self.user_id)

        if not is_market_open(pair):
            return OrderResult(order_id='', status='failed', side=side, amount=amount,
                               raw={'error': 'Market closed'})

        if is_in_rollover_window():
            return OrderResult(order_id='', status='failed', side=side, amount=amount,
                               raw={'error': 'Rollover window — no trading'})

        # Queue the command (EA will pick it up via /signals)
        cmd_id = f"mt5cmd_{secrets.token_hex(6)}"
        from storage import upsert_bot_state
        cmd = {
            'cmd_id': cmd_id,
            'action': 'OPEN',
            'symbol': broker_symbol,
            'canonical': pair,
            'side': side.upper(),
            'lots': amount,
            'user_id': self.user_id,
            'ts': int(time.time()),
        }
        # Store as pending command in bot_state
        upsert_bot_state(f"mt5_cmd_{cmd_id}", json.dumps(cmd), int(time.time()))

        log.info("MT5 command queued: %s %s %s lots=%s", cmd_id, side, broker_symbol, amount)
        return OrderResult(order_id=cmd_id, status='pending', side=side, amount=amount, raw=cmd)

    def cancel_order(self, order_id: str, pair: str) -> OrderResult:
        """Remove a pending command."""
        from storage import execute as db_exec
        db_exec("DELETE FROM bot_state WHERE key=?", (f"mt5_cmd_{order_id}",))
        return OrderResult(order_id=order_id, status='cancelled', side='', amount=0)

    def get_balance(self, currency: str = 'USD') -> BalanceResult:
        """Balance not available server-side for MT5. EA should report it."""
        # Check if EA has reported balance
        from storage import fetchone
        row = fetchone("SELECT value FROM bot_state WHERE key=?",
                       (f"mt5_balance_{self.user_id}",))
        if row and row[0]:
            try:
                data = json.loads(row[0])
                return BalanceResult(
                    free=float(data.get('free', 0)),
                    used=float(data.get('used', 0)),
                    total=float(data.get('total', 0)),
                    currency=currency)
            except Exception:
                pass
        return BalanceResult(free=0, used=0, total=0, currency=currency)

    def health_check(self) -> tuple:
        """Check if EA bridge is responsive."""
        ok, msg = self.validate_credentials()
        return ok, msg

    def validate_pair(self, pair: str) -> bool:
        """Check if the pair has a symbol mapping configured."""
        broker_sym = resolve_symbol(pair, self.user_id)
        return broker_sym != pair or pair in ('XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY')
