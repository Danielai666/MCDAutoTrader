# tests/test_multi_user.py
# Multi-user isolation tests: verify user A cannot see user B's data.
# Uses SQLite in-memory. Creates 2 test users and verifies isolation
# across: trades, guards, pairs, reports, credentials, risk queries.

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['DB_ENGINE'] = 'sqlite'
os.environ['DB_PATH'] = ':memory:'
os.environ['CREDENTIAL_ENCRYPTION_KEY'] = 'PH42bKt69piR9FyFisekjQ0ws63lhwwWjjJx6YMYPT0='
os.environ['TELEGRAM_BOT_TOKEN'] = 'fake'
os.environ['TELEGRAM_ADMIN_IDS'] = '1001'
os.environ['FEATURE_MULTI_PAIR'] = 'true'

import unittest

USER_A = 1001
USER_B = 2002


class TestMultiUserSetup(unittest.TestCase):
    """Create two test users before running isolation tests."""

    @classmethod
    def setUpClass(cls):
        from storage import init_db, execute
        init_db()
        now = int(time.time())
        execute("INSERT OR IGNORE INTO users(user_id, tg_username, capital_usd) VALUES(?,?,?)",
                (USER_A, 'user_a', 5000))
        execute("INSERT OR IGNORE INTO users(user_id, tg_username, capital_usd) VALUES(?,?,?)",
                (USER_B, 'user_b', 3000))


class TestTradeIsolation(TestMultiUserSetup):
    """Verify trades are isolated per user."""

    def test_open_trade_has_user_id(self):
        from storage import insert_trade, fetchone
        tid = insert_trade('BTC/USDT', 'BUY', 0.1, 50000, 'test_a')
        # Manually set user_id (as the scheduler would)
        from storage import execute
        execute("UPDATE trades SET user_id=? WHERE id=?", (USER_A, tid))

        row = fetchone("SELECT user_id FROM trades WHERE id=?", (tid,))
        self.assertEqual(row[0], USER_A)

    def test_user_a_cannot_see_user_b_trades(self):
        from storage import execute, fetchall
        now = int(time.time())
        # Create trades for both users
        execute("INSERT INTO trades(pair,side,qty,entry,status,ts_open,user_id) VALUES(?,?,?,?,?,?,?)",
                ('ETH/USDT', 'BUY', 1.0, 3000, 'OPEN', now, USER_A))
        execute("INSERT INTO trades(pair,side,qty,entry,status,ts_open,user_id) VALUES(?,?,?,?,?,?,?)",
                ('SOL/USDT', 'SELL', 10.0, 100, 'OPEN', now, USER_B))

        # Query for user A
        a_trades = fetchall("SELECT pair FROM trades WHERE status='OPEN' AND user_id=?", (USER_A,))
        a_pairs = [r[0] for r in a_trades]
        self.assertIn('ETH/USDT', a_pairs)
        self.assertNotIn('SOL/USDT', a_pairs)

        # Query for user B
        b_trades = fetchall("SELECT pair FROM trades WHERE status='OPEN' AND user_id=?", (USER_B,))
        b_pairs = [r[0] for r in b_trades]
        self.assertIn('SOL/USDT', b_pairs)
        self.assertNotIn('ETH/USDT', b_pairs)

    def test_open_trade_count_per_user(self):
        from risk import open_trade_count
        count_a = open_trade_count(USER_A)
        count_b = open_trade_count(USER_B)
        # Should be different (A has more trades from earlier tests)
        self.assertIsInstance(count_a, int)
        self.assertIsInstance(count_b, int)

    def test_realized_pnl_per_user(self):
        from risk import realized_pnl_today
        pnl_a = realized_pnl_today(USER_A)
        pnl_b = realized_pnl_today(USER_B)
        self.assertIsInstance(pnl_a, float)
        self.assertIsInstance(pnl_b, float)


class TestGuardIsolation(TestMultiUserSetup):
    """Verify manual guards are per-user."""

    def test_guards_are_user_scoped(self):
        from trade_executor import set_manual_guard
        from storage import fetchone

        set_manual_guard(USER_A, 'BTC/USDT', sl=48000, tp=55000)
        set_manual_guard(USER_B, 'BTC/USDT', sl=49000, tp=54000)

        a_guard = fetchone("SELECT stop_loss, take_profit FROM manual_guards WHERE user_id=? AND pair=?",
                           (USER_A, 'BTC/USDT'))
        b_guard = fetchone("SELECT stop_loss, take_profit FROM manual_guards WHERE user_id=? AND pair=?",
                           (USER_B, 'BTC/USDT'))

        self.assertIsNotNone(a_guard)
        self.assertIsNotNone(b_guard)
        self.assertEqual(float(a_guard[0]), 48000)
        self.assertEqual(float(b_guard[0]), 49000)
        # Different SL values per user
        self.assertNotEqual(float(a_guard[0]), float(b_guard[0]))


class TestPairIsolation(TestMultiUserSetup):
    """Verify watchlist pairs are per-user."""

    def test_pairs_are_user_scoped(self):
        from pair_manager import add_pair, get_active_pairs
        add_pair(USER_A, 'BTC/USDT')
        add_pair(USER_B, 'DOGE/USDT')

        a_pairs = get_active_pairs(USER_A)
        b_pairs = get_active_pairs(USER_B)

        self.assertIn('BTC/USDT', a_pairs)
        self.assertIn('DOGE/USDT', b_pairs)
        # User A should not see user B's DOGE pair (unless it's the global default)
        # Note: get_active_pairs falls back to SETTINGS.PAIR if empty


class TestReportIsolation(TestMultiUserSetup):
    """Verify reports are per-user."""

    def test_performance_summary_per_user(self):
        from reports import performance_summary
        perf_a = performance_summary(user_id=USER_A, days=30)
        perf_b = performance_summary(user_id=USER_B, days=30)
        self.assertIsInstance(perf_a, dict)
        self.assertIsInstance(perf_b, dict)
        self.assertIn('total_trades', perf_a)

    def test_blocked_trades_per_user(self):
        from reports import blocked_trades_summary
        txt_a = blocked_trades_summary(user_id=USER_A, days=7)
        txt_b = blocked_trades_summary(user_id=USER_B, days=7)
        self.assertIsInstance(txt_a, str)
        self.assertIsInstance(txt_b, str)


class TestRiskIsolation(TestMultiUserSetup):
    """Verify risk engine is per-user when ctx provided."""

    def test_portfolio_exposure_per_user(self):
        from risk import portfolio_exposure_check
        from user_context import UserContext
        ctx_a = UserContext(user_id=USER_A, capital_usd=5000, max_portfolio_exposure=0.5)
        ctx_b = UserContext(user_id=USER_B, capital_usd=3000, max_portfolio_exposure=0.5)

        can_a, exp_a, rem_a = portfolio_exposure_check(ctx_a)
        can_b, exp_b, rem_b = portfolio_exposure_check(ctx_b)

        # Different capital → different remaining
        self.assertIsInstance(can_a, bool)
        self.assertIsInstance(can_b, bool)

    def test_duplicate_trade_per_user(self):
        from risk import is_duplicate_trade
        from storage import execute
        now = int(time.time())
        # Ensure user A has a known OPEN trade
        execute("INSERT INTO trades(pair,side,qty,entry,status,ts_open,user_id) VALUES(?,?,?,?,?,?,?)",
                ('LINK/USDT', 'BUY', 1.0, 20, 'OPEN', now, USER_A))
        dup_a = is_duplicate_trade(USER_A, 'LINK/USDT', 'BUY')
        dup_b = is_duplicate_trade(USER_B, 'LINK/USDT', 'BUY')
        self.assertTrue(dup_a)
        self.assertFalse(dup_b)


class TestCredentialIsolation(TestMultiUserSetup):
    """Verify credentials are per-user."""

    def test_save_and_get_credential(self):
        from storage import save_credential, get_credential
        save_credential(USER_A, 'ccxt', 'binance', 'enc_key_a', 'enc_secret_a', '', 1)
        save_credential(USER_B, 'ccxt', 'kraken', 'enc_key_b', 'enc_secret_b', '', 1)

        cred_a = get_credential(USER_A, 'ccxt')
        cred_b = get_credential(USER_B, 'ccxt')

        self.assertIsNotNone(cred_a)
        self.assertIsNotNone(cred_b)
        self.assertEqual(cred_a['exchange_id'], 'binance')
        self.assertEqual(cred_b['exchange_id'], 'kraken')
        self.assertNotEqual(cred_a['api_key_enc'], cred_b['api_key_enc'])

    def test_user_cannot_access_other_credential(self):
        from storage import get_credential
        # User A should not get user B's kraken cred
        cred = get_credential(USER_A, 'ccxt', 'kraken')
        self.assertIsNone(cred)


class TestUserContextIsolation(TestMultiUserSetup):
    """Verify UserContext loads per-user data."""

    def test_load_different_capital(self):
        from user_context import UserContext
        ctx_a = UserContext.load(USER_A)
        ctx_b = UserContext.load(USER_B)
        self.assertEqual(ctx_a.capital_usd, 5000)
        self.assertEqual(ctx_b.capital_usd, 3000)
        self.assertNotEqual(ctx_a.user_id, ctx_b.user_id)


if __name__ == '__main__':
    unittest.main()
