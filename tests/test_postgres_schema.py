# tests/test_postgres_schema.py
# PostgreSQL schema validation: runs all migrations, inserts test data,
# queries with user_id filters, verifies upsert helpers.
#
# This test can run in two modes:
# 1. SQLite mode (default): validates schema + queries work on SQLite
# 2. PostgreSQL mode: set DB_ENGINE=postgres + connection vars
#
# Run: python -m pytest tests/test_postgres_schema.py -v
# Or: DB_ENGINE=postgres SUPABASE_DB_HOST=... python -m pytest tests/test_postgres_schema.py -v

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Default to SQLite for CI; set DB_ENGINE=postgres for real PG test
if not os.environ.get('DB_ENGINE'):
    os.environ['DB_ENGINE'] = 'sqlite'
    os.environ['DB_PATH'] = ':memory:'
os.environ.setdefault('CREDENTIAL_ENCRYPTION_KEY', 'PH42bKt69piR9FyFisekjQ0ws63lhwwWjjJx6YMYPT0=')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'fake')
os.environ.setdefault('TELEGRAM_ADMIN_IDS', '1001')

import unittest


class TestSchemaCreation(unittest.TestCase):
    """Verify all 14 tables are created successfully."""

    @classmethod
    def setUpClass(cls):
        from storage import init_db
        init_db()

    def _table_exists(self, table_name):
        from storage import fetchone, _USE_POSTGRES
        if _USE_POSTGRES:
            row = fetchone(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=?)",
                (table_name,))
        else:
            row = fetchone(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,))
        return row is not None and row[0]

    def test_users_table(self):
        self.assertTrue(self._table_exists('users'))

    def test_trades_table(self):
        self.assertTrue(self._table_exists('trades'))

    def test_signals_table(self):
        self.assertTrue(self._table_exists('signals'))

    def test_manual_guards_table(self):
        self.assertTrue(self._table_exists('manual_guards'))

    def test_trading_pairs_table(self):
        self.assertTrue(self._table_exists('trading_pairs'))

    def test_ai_decisions_table(self):
        self.assertTrue(self._table_exists('ai_decisions'))

    def test_blocked_trades_table(self):
        self.assertTrue(self._table_exists('blocked_trades'))

    def test_bot_state_table(self):
        self.assertTrue(self._table_exists('bot_state'))

    def test_performance_snapshots_table(self):
        self.assertTrue(self._table_exists('performance_snapshots'))

    def test_credentials_table(self):
        self.assertTrue(self._table_exists('credentials'))

    def test_user_settings_table(self):
        self.assertTrue(self._table_exists('user_settings'))

    def test_operation_log_table(self):
        self.assertTrue(self._table_exists('operation_log'))

    def test_mt5_connections_table(self):
        self.assertTrue(self._table_exists('mt5_connections'))

    def test_mt5_nonces_table(self):
        self.assertTrue(self._table_exists('mt5_nonces'))


class TestInsertAndQuery(unittest.TestCase):
    """Verify inserts and user-scoped queries work on all tables."""

    @classmethod
    def setUpClass(cls):
        from storage import init_db, execute
        init_db()
        execute("INSERT OR IGNORE INTO users(user_id, tg_username, capital_usd) VALUES(?,?,?)",
                (5001, 'schema_test', 1000))

    def test_insert_trade(self):
        from storage import insert_trade, fetchone
        tid = insert_trade('BTC/USDT', 'BUY', 0.5, 50000, 'schema_test')
        self.assertGreater(tid, 0)
        row = fetchone("SELECT pair, side FROM trades WHERE id=?", (tid,))
        self.assertEqual(row[0], 'BTC/USDT')
        self.assertEqual(row[1], 'BUY')

    def test_upsert_bot_state(self):
        from storage import upsert_bot_state, fetchone
        upsert_bot_state('test_key', 'test_value', int(time.time()))
        row = fetchone("SELECT value FROM bot_state WHERE key=?", ('test_key',))
        self.assertEqual(row[0], 'test_value')

        # Update same key
        upsert_bot_state('test_key', 'updated_value', int(time.time()))
        row = fetchone("SELECT value FROM bot_state WHERE key=?", ('test_key',))
        self.assertEqual(row[0], 'updated_value')

    def test_upsert_user_settings(self):
        from storage import upsert_user_settings, get_user_settings
        upsert_user_settings(5001, mode='paper', ai_mode='manual_confirm', timezone='US/Pacific')
        settings = get_user_settings(5001)
        self.assertIsNotNone(settings)
        self.assertEqual(settings['mode'], 'paper')
        self.assertEqual(settings['ai_mode'], 'manual_confirm')
        self.assertEqual(settings['timezone'], 'US/Pacific')

    def test_save_and_get_credential(self):
        from storage import save_credential, get_credential
        save_credential(5001, 'ccxt', 'binance', 'enc_k', 'enc_s', 'enc_dk', 2)
        cred = get_credential(5001, 'ccxt', 'binance')
        self.assertIsNotNone(cred)
        self.assertEqual(cred['exchange_id'], 'binance')
        self.assertEqual(cred['encryption_version'], 2)

    def test_operation_log(self):
        from storage import record_operation, check_operation_id
        record_operation('op_123', 5001, 'TRADE', 'BTC/USDT', 'BUY', '{"success":true}')
        existing = check_operation_id('op_123')
        self.assertIsNotNone(existing)
        self.assertEqual(existing['user_id'], 5001)

        # Duplicate should return same record
        existing2 = check_operation_id('op_123')
        self.assertIsNotNone(existing2)

    def test_append_trade_note(self):
        from storage import insert_trade, append_trade_note, fetchone
        tid = insert_trade('ETH/USDT', 'SELL', 1.0, 3000, 'note_test')
        append_trade_note(tid, ' | guard triggered')
        row = fetchone("SELECT note FROM trades WHERE id=?", (tid,))
        self.assertIn('guard triggered', row[0])

    def test_db_health_check(self):
        from storage import check_db_health
        ok, msg, details = check_db_health()
        self.assertTrue(ok)
        self.assertIn('engine', details)
        self.assertGreater(details['users'], 0)


class TestMultiTenantMigration(unittest.TestCase):
    """Verify multi-tenant migration columns exist."""

    @classmethod
    def setUpClass(cls):
        from storage import init_db
        init_db()

    def test_trades_has_user_id(self):
        from storage import fetchone
        # Insert a trade and check user_id column exists
        from storage import execute
        execute("INSERT INTO trades(pair,side,qty,entry,status,ts_open,user_id) VALUES(?,?,?,?,?,?,?)",
                ('TEST/USD', 'BUY', 1, 100, 'OPEN', int(time.time()), 9999))
        row = fetchone("SELECT user_id FROM trades WHERE pair='TEST/USD'")
        self.assertEqual(row[0], 9999)

    def test_signals_has_user_id(self):
        from storage import execute, fetchone
        execute("INSERT INTO signals(ts,pair,tf,direction,reason,user_id) VALUES(?,?,?,?,?,?)",
                (int(time.time()), 'TEST/USD', '1h', 'BUY', 'test', 9999))
        row = fetchone("SELECT user_id FROM signals WHERE pair='TEST/USD'")
        self.assertEqual(row[0], 9999)

    def test_bot_state_has_user_id(self):
        from storage import upsert_bot_state, fetchone
        # bot_state user_id is nullable (global state has NULL)
        upsert_bot_state('global_key', 'global_val', int(time.time()))
        row = fetchone("SELECT user_id FROM bot_state WHERE key='global_key'")
        # user_id should be NULL for global keys
        self.assertIsNone(row[0])

    def test_users_has_new_columns(self):
        from storage import fetchone
        row = fetchone("SELECT capital_usd, risk_per_trade, paper_trading FROM users WHERE user_id=5001")
        self.assertIsNotNone(row)
        self.assertEqual(float(row[0]), 1000)


if __name__ == '__main__':
    unittest.main()
