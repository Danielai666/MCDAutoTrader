# tests/test_screenshots.py
# Smoke tests for screenshot analysis session lifecycle.
# No AI calls — tests session management, file handling, result formatting.

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['DB_ENGINE'] = 'sqlite'
os.environ['DB_PATH'] = ':memory:'
os.environ['CREDENTIAL_ENCRYPTION_KEY'] = 'PH42bKt69piR9FyFisekjQ0ws63lhwwWjjJx6YMYPT0='
os.environ['TELEGRAM_BOT_TOKEN'] = 'fake'
os.environ['TELEGRAM_ADMIN_IDS'] = '111'
os.environ['FEATURE_SCREENSHOTS'] = 'true'

import unittest


class TestScreenshotSession(unittest.TestCase):
    """Test screenshot session lifecycle."""

    def test_start_session(self):
        from screenshot_analyzer import start_session, get_session
        session = start_session(200, 200)
        self.assertEqual(session.user_id, 200)
        self.assertEqual(session.image_count, 0)
        self.assertFalse(session.is_full)
        self.assertFalse(session.is_expired)
        self.assertTrue(os.path.isdir(session.temp_dir))

        # Verify retrievable
        s2 = get_session(200)
        self.assertIsNotNone(s2)
        self.assertEqual(s2.user_id, 200)

    def test_add_image(self):
        from screenshot_analyzer import start_session, add_image, get_session
        session = start_session(201, 201)

        # Create a temp file to simulate a downloaded image
        img_path = os.path.join(session.temp_dir, 'test.jpg')
        with open(img_path, 'wb') as f:
            f.write(b'\xff\xd8\xff\xe0' + b'\x00' * 100)  # Minimal JPEG header

        ok = add_image(201, img_path)
        self.assertTrue(ok)
        self.assertEqual(get_session(201).image_count, 1)

    def test_session_full(self):
        from screenshot_analyzer import start_session, add_image, get_session
        from config import SETTINGS
        session = start_session(202, 202)

        for i in range(SETTINGS.SCREENSHOT_MAX_IMAGES):
            path = os.path.join(session.temp_dir, f'img_{i}.jpg')
            with open(path, 'wb') as f:
                f.write(b'\x00' * 10)
            add_image(202, path)

        self.assertTrue(get_session(202).is_full)

        # Adding one more should fail
        extra_path = os.path.join(session.temp_dir, 'extra.jpg')
        with open(extra_path, 'wb') as f:
            f.write(b'\x00' * 10)
        ok = add_image(202, extra_path)
        self.assertFalse(ok)

    def test_end_session_cleanup(self):
        from screenshot_analyzer import start_session, end_session, get_session
        session = start_session(203, 203)
        temp_dir = session.temp_dir
        self.assertTrue(os.path.isdir(temp_dir))

        end_session(203)
        self.assertFalse(os.path.exists(temp_dir))
        self.assertIsNone(get_session(203))

    def test_no_session_returns_none(self):
        from screenshot_analyzer import get_session
        self.assertIsNone(get_session(999))

    def test_add_image_no_session(self):
        from screenshot_analyzer import add_image
        self.assertFalse(add_image(998, '/fake/path.jpg'))

    def test_expired_session(self):
        from screenshot_analyzer import start_session, get_session
        session = start_session(204, 204)
        session.started_ts = 0  # Force expiry
        self.assertIsNone(get_session(204))


class TestAnalysisFormatting(unittest.TestCase):
    """Test result formatting without AI calls."""

    def test_format_error(self):
        from screenshot_analyzer import format_analysis_result
        result = format_analysis_result({'error': 'No images'})
        self.assertIn('No images', result)

    def test_format_raw_analysis(self):
        from screenshot_analyzer import format_analysis_result
        result = format_analysis_result({'raw_analysis': 'Some long text', 'charts': []})
        self.assertIn('Some long text', result)

    def test_format_structured(self):
        from screenshot_analyzer import format_analysis_result
        result = format_analysis_result({
            'charts': [{
                'symbol': 'BTCUSD',
                'timeframe': '4h',
                'trend': 'bullish',
                'trend_strength': 'strong',
                'divergence': {'type': 'none'},
                'plan': {'bias': 'BUY', 'entry': '65000', 'stop_loss': '63000',
                         'tp1': '68000', 'tp2': '70000'},
                'confidence': 'HIGH',
                'reasoning': 'Strong uptrend',
            }],
            'overall_summary': 'Bullish setup'
        })
        self.assertIn('BTCUSD', result)
        self.assertIn('BUY', result)
        self.assertIn('HIGH', result)

    def test_format_empty_charts(self):
        from screenshot_analyzer import format_analysis_result
        result = format_analysis_result({'charts': []})
        self.assertIn('No analysis', result)


if __name__ == '__main__':
    unittest.main()
