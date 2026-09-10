import asyncio
import unittest

from main import TradingSignalBot


class MessageFormatTests(unittest.TestCase):
    def test_confidence_colors(self):
        self.assertIn("🔴", TradingSignalBot.confidence_block(0.52))
        self.assertIn("THẤP", TradingSignalBot.confidence_block(0.52))
        self.assertIn("🟡", TradingSignalBot.confidence_block(0.60))
        self.assertIn("TRUNG BÌNH", TradingSignalBot.confidence_block(0.60))
        self.assertIn("🟢", TradingSignalBot.confidence_block(0.70))
        self.assertIn("CAO", TradingSignalBot.confidence_block(0.70))

    def test_result_is_exactly_one_line(self):
        bot = object.__new__(TradingSignalBot)
        for result, expected in (
            ("WIN", "✅ <b>ĐÃ THẮNG</b>"),
            ("LOSS", "❌ <b>ĐÃ THUA</b>"),
            ("TIE", "➖ <b>ĐÃ HÒA</b>"),
        ):
            text = asyncio.run(bot.result_text(None, 0.0, result, 0.0))
            self.assertEqual(text, expected)
            self.assertNotIn("\n", text)


if __name__ == "__main__":
    unittest.main()
