# tests/test_mt5_bridge.py
# Smoke tests for MT5 EA Bridge: HMAC auth, replay protection, symbol mapping,
# lot sizing, session rules. No external dependencies — uses SQLite in-memory.

import os
import sys
import time
import secrets

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force SQLite + test config before any imports
os.environ['DB_ENGINE'] = 'sqlite'
os.environ['DB_PATH'] = ':memory:'
os.environ['CREDENTIAL_ENCRYPTION_KEY'] = 'PH42bKt69piR9FyFisekjQ0ws63lhwwWjjJx6YMYPT0='
os.environ['TELEGRAM_BOT_TOKEN'] = 'fake'
os.environ['TELEGRAM_ADMIN_IDS'] = '111'
os.environ['FEATURE_MT5_BRIDGE'] = 'true'

import unittest


class TestHMACAuth(unittest.TestCase):
    """Test HMAC-SHA256 authentication and replay protection."""

    @classmethod
    def setUpClass(cls):
        from storage import init_db
        init_db()

    def test_compute_hmac_deterministic(self):
        from mt5_bridge import compute_hmac
        sig1 = compute_hmac('secret', 'POST', '/trade/open', '{"a":1}', '1000', 'nonce1')
        sig2 = compute_hmac('secret', 'POST', '/trade/open', '{"a":1}', '1000', 'nonce1')
        self.assertEqual(sig1, sig2)

    def test_compute_hmac_different_inputs(self):
        from mt5_bridge import compute_hmac
        sig1 = compute_hmac('secret', 'POST', '/trade/open', '{}', '1000', 'n1')
        sig2 = compute_hmac('secret', 'POST', '/trade/close', '{}', '1000', 'n1')
        self.assertNotEqual(sig1, sig2)

    def test_compute_hmac_different_secrets(self):
        from mt5_bridge import compute_hmac
        sig1 = compute_hmac('secret_a', 'POST', '/path', '', '1000', 'n1')
        sig2 = compute_hmac('secret_b', 'POST', '/path', '', '1000', 'n1')
        self.assertNotEqual(sig1, sig2)

    def test_generate_bridge_token(self):
        from mt5_bridge import generate_bridge_token
        token_id, secret = generate_bridge_token()
        self.assertTrue(token_id.startswith('mt5_'))
        self.assertEqual(len(secret), 64)  # 32 bytes hex

    def test_verify_hmac_unknown_token(self):
        from mt5_bridge import verify_hmac
        ok, reason = verify_hmac(999, 'fake_token', 'POST', '/path', '', '1000', 'n1', 'sig')
        self.assertFalse(ok)
        self.assertIn('Unknown', reason)

    def test_verify_hmac_full_flow(self):
        from mt5_bridge import create_bridge_connection, compute_hmac, verify_hmac
        from storage import execute

        # Create test user
        execute("INSERT OR IGNORE INTO users(user_id, tg_username) VALUES(?,?)", (100, 'tester'))

        # Create bridge connection
        result = create_bridge_connection(100, 'TestBroker')
        token_id = result['token_id']
        shared_secret = result['secret']

        # Compute valid signature
        ts = str(int(time.time()))
        nonce = secrets.token_hex(16)
        body = '{"symbol":"XAUUSD"}'
        sig = compute_hmac(shared_secret, 'POST', '/trade/open', body, ts, nonce)

        # Verify
        ok, reason = verify_hmac(100, token_id, 'POST', '/trade/open', body, ts, nonce, sig)
        self.assertTrue(ok, f"HMAC verification failed: {reason}")

    def test_replay_protection(self):
        from mt5_bridge import create_bridge_connection, compute_hmac, verify_hmac
        from storage import execute

        execute("INSERT OR IGNORE INTO users(user_id, tg_username) VALUES(?,?)", (101, 'replay'))
        result = create_bridge_connection(101, 'Broker')
        token_id = result['token_id']
        secret = result['secret']

        ts = str(int(time.time()))
        nonce = 'fixed_nonce_123'
        sig = compute_hmac(secret, 'GET', '/signals', '', ts, nonce)

        # First request: should succeed
        ok1, _ = verify_hmac(101, token_id, 'GET', '/signals', '', ts, nonce, sig)
        self.assertTrue(ok1)

        # Replay: same nonce should fail
        ok2, reason = verify_hmac(101, token_id, 'GET', '/signals', '', ts, nonce, sig)
        self.assertFalse(ok2)
        self.assertIn('replay', reason.lower())

    def test_timestamp_outside_window(self):
        from mt5_bridge import create_bridge_connection, compute_hmac, verify_hmac
        from storage import execute

        execute("INSERT OR IGNORE INTO users(user_id, tg_username) VALUES(?,?)", (102, 'old'))
        result = create_bridge_connection(102)
        token_id = result['token_id']
        secret = result['secret']

        # Timestamp 60 seconds ago (outside 30s window)
        old_ts = str(int(time.time()) - 60)
        nonce = secrets.token_hex(16)
        sig = compute_hmac(secret, 'POST', '/heartbeat', '', old_ts, nonce)

        ok, reason = verify_hmac(102, token_id, 'POST', '/heartbeat', '', old_ts, nonce, sig)
        self.assertFalse(ok)
        self.assertIn('replay window', reason.lower())


class TestSymbolMapping(unittest.TestCase):
    """Test symbol mapping and resolution."""

    def test_default_symbol_no_mapping(self):
        from mt5_bridge import resolve_symbol
        # No user mapping → return canonical as-is
        result = resolve_symbol('XAUUSD', user_id=None)
        self.assertEqual(result, 'XAUUSD')

    def test_canonical_from_broker_no_mapping(self):
        from mt5_bridge import canonical_from_broker
        result = canonical_from_broker('GOLD', user_id=None)
        self.assertEqual(result, 'GOLD')  # No mapping → return as-is


class TestLotSizing(unittest.TestCase):
    """Test MT5 lot sizing calculation."""

    def test_basic_lot_sizing(self):
        from mt5_bridge import compute_mt5_lot_size
        lots = compute_mt5_lot_size(
            capital=10000, risk_pct=0.01, stop_distance_points=2.0,
            tick_value=1.0, tick_size=0.01, contract_size=100)
        self.assertGreater(lots, 0)
        self.assertLessEqual(lots, 100)

    def test_lot_sizing_minimum(self):
        from mt5_bridge import compute_mt5_lot_size
        # Very small capital should hit min_lot
        lots = compute_mt5_lot_size(
            capital=10, risk_pct=0.001, stop_distance_points=100.0,
            tick_value=10.0, tick_size=0.01)
        self.assertEqual(lots, 0.01)  # min_lot

    def test_lot_sizing_zero_stop(self):
        from mt5_bridge import compute_mt5_lot_size
        lots = compute_mt5_lot_size(
            capital=10000, risk_pct=0.01, stop_distance_points=0,
            tick_value=1.0, tick_size=0.01)
        self.assertEqual(lots, 0.01)  # Returns min_lot on zero stop


class TestSessionRules(unittest.TestCase):
    """Test market session and spread guard rules."""

    def test_spread_guard_pass(self):
        from mt5_bridge import check_spread_guard
        ok, msg = check_spread_guard(2.0)
        self.assertTrue(ok)

    def test_spread_guard_fail(self):
        from mt5_bridge import check_spread_guard
        ok, msg = check_spread_guard(10.0)
        self.assertFalse(ok)
        self.assertIn('Spread', msg)

    def test_is_market_open_returns_bool(self):
        from mt5_bridge import is_market_open
        result = is_market_open('XAUUSD')
        self.assertIsInstance(result, bool)

    def test_is_in_rollover_returns_bool(self):
        from mt5_bridge import is_in_rollover_window
        result = is_in_rollover_window()
        self.assertIsInstance(result, bool)


if __name__ == '__main__':
    unittest.main()
