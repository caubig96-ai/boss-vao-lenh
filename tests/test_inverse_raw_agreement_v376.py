from __future__ import annotations

import inspect
import unittest

from runtime_v376 import (
    APP_VERSION,
    INVERSE_MAX_RAW_AGREEMENT,
    INVERSE_MIN_EXECUTED_SUPPORT,
    TradingSignalBotV3,
    inverse_entry_allowed,
)


class InverseRawAgreementV376Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.7.6")

    def test_four_of_six_original_support_is_no_buy_when_inverted(self):
        self.assertFalse(inverse_entry_allowed(4, 2))
        self.assertFalse(inverse_entry_allowed(5, 1))
        self.assertFalse(inverse_entry_allowed(6, 0))

    def test_three_of_six_can_buy_only_if_inverse_has_three_supporters(self):
        self.assertEqual(INVERSE_MAX_RAW_AGREEMENT, 3)
        self.assertEqual(INVERSE_MIN_EXECUTED_SUPPORT, 3)
        self.assertTrue(inverse_entry_allowed(3, 3))
        self.assertFalse(inverse_entry_allowed(3, 2))

    def test_inverse_card_preserves_original_agreement_and_explains_inverse_support(self):
        source = inspect.getsource(TradingSignalBotV3.signal_text)
        self.assertIn("Đồng thuận gốc", source)
        self.assertIn("Ủng hộ hướng đảo", source)
        self.assertIn("KHÔNG NÊN VÀO", source)


if __name__ == "__main__":
    unittest.main()
