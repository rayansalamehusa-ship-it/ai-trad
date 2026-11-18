import os
import unittest
from unittest.mock import patch
import telegram_bot

class TelegramBotTests(unittest.TestCase):
    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "12345"}, clear=False)
    def test_private_chat_authorization(self):
        good = {"chat": {"id": 12345, "type": "private"}, "from": {"id": 12345}}
        bad_user = {"chat": {"id": 12345, "type": "private"}, "from": {"id": 999}}
        group = {"chat": {"id": 12345, "type": "group"}, "from": {"id": 12345}}
        self.assertTrue(telegram_bot._authorized(good))
        self.assertFalse(telegram_bot._authorized(bad_user))
        self.assertFalse(telegram_bot._authorized(group))

    @patch("telegram_bot.send")
    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "12345"}, clear=False)
    def test_help_command(self, send_mock):
        telegram_bot._handle("12345", "/help")
        self.assertTrue(send_mock.called)
        self.assertIn("PAPER", send_mock.call_args.args[1])

    @patch("telegram_bot.set_key")
    @patch("telegram_bot.send")
    @patch.dict(os.environ, {}, clear=False)
    def test_auto_on_accepts_keyboard_and_arabic_activation(self, send_mock, set_key_mock):
        for command in ("▶️ تفعيل المسح", "تفعيل المسح", "تفعيل", "/auto_on تفعيل"):
            with self.subTest(command=command):
                telegram_bot._handle("12345", command)
                self.assertEqual(os.environ.get("AUTO_SCAN_MIN"), "15")
                self.assertIn("15 دقيقة", send_mock.call_args.args[1])

    @patch("telegram_bot.set_key")
    @patch("telegram_bot.send")
    @patch.dict(os.environ, {}, clear=False)
    def test_auto_on_accepts_custom_minutes(self, send_mock, set_key_mock):
        telegram_bot._handle("12345", "/auto_on 30")
        self.assertEqual(os.environ.get("AUTO_SCAN_MIN"), "30")
        self.assertIn("30 دقيقة", send_mock.call_args.args[1])

    @patch("telegram_bot.set_key")
    @patch("telegram_bot.send")
    def test_auto_on_rejects_non_numeric_argument_without_crashing(self, send_mock, set_key_mock):
        telegram_bot._handle("12345", "/auto_on abc")
        self.assertIn("صيغة غير صحيحة", send_mock.call_args.args[1])
        set_key_mock.assert_not_called()

if __name__ == "__main__":
    unittest.main()
