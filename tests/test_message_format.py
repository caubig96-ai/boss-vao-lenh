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


if __name__ == "__main__":
    unittest.main()
