"""Phase 2: bounded, path-independent bank interest (audit H1, H2)."""
import unittest
from unittest.mock import patch

from helpers import fresh_db

from config import Config
from database.manager import DatabaseManager
from utils import clock

PERIOD = Config.BANK_INTEREST_PERIOD_SECONDS
PER_DAY = 86400 // PERIOD


class InterestFormulaTests(unittest.TestCase):
    def test_small_balance_earns_about_base_rate(self):
        after = DatabaseManager.accrue_interest(100, PER_DAY)
        self.assertAlmostEqual(after / 100 - 1, Config.BANK_INTEREST_DAILY_RATE, delta=0.001)

    def test_daily_interest_never_exceeds_cap(self):
        cap = Config.BANK_INTEREST_DAILY_RATE * Config.BANK_INTEREST_SOFT_CAP
        for balance in (1_000, 10_000, 1_000_000, 1e12):
            gained = DatabaseManager.accrue_interest(balance, PER_DAY) - balance
            self.assertLessEqual(gained, cap + 1e-6)

    def test_growth_is_linear_not_exponential(self):
        cap = Config.BANK_INTEREST_DAILY_RATE * Config.BANK_INTEREST_SOFT_CAP
        year = DatabaseManager.accrue_interest(1_000, PER_DAY * 365)
        self.assertLess(year, 1_000 + cap * 365)
        # Old system turned $1,000 into ~$8.3M in a year.
        self.assertLess(year, 40_000)

    def test_negative_balance_does_not_accrue(self):
        self.assertEqual(DatabaseManager.accrue_interest(-500, PER_DAY * 30), -500)

    def test_bonus_scales_rate_but_stays_bounded(self):
        plain = DatabaseManager.accrue_interest(1e9, PER_DAY) - 1e9
        boosted = DatabaseManager.accrue_interest(1e9, PER_DAY, bonus=0.5) - 1e9
        self.assertAlmostEqual(boosted / plain, 1.5, delta=0.01)


class ApplyInterestTests(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db()
        self.db.get_or_create_user(1)
        self.db.update_user_money(1, 9_900)
        self.db.deposit_to_bank(1, 10_000)
        self.start = 1_700_000_000
        self.db.update_bank_balance_and_interest(1, 10_000, self.start)

    def _claim_at(self, ts):
        with patch.object(clock, "now_ts", return_value=ts):
            self.db.apply_interest(1)

    def test_claim_frequency_does_not_matter(self):
        days = 30
        # Claim once at the end.
        self._claim_at(self.start + days * 86400)
        once = self.db.get_bank_balance(1)

        other = fresh_db()
        other.get_or_create_user(1)
        other.update_user_money(1, 9_900)
        other.deposit_to_bank(1, 10_000)
        other.update_bank_balance_and_interest(1, 10_000, self.start)
        self.db = other
        # Claim every 90 minutes (1.5 periods) — partial periods must carry over.
        t = self.start
        while t < self.start + days * 86400:
            t = min(t + 5400, self.start + days * 86400)
            self._claim_at(t)
        often = self.db.get_bank_balance(1)

        self.assertAlmostEqual(once, often, delta=0.01)
        self.assertAlmostEqual(once, DatabaseManager.accrue_interest(10_000, days * PER_DAY), delta=0.01)

    def test_total_interest_is_recorded(self):
        self._claim_at(self.start + 86400)
        acct = self.db.get_bank_account(1)
        self.assertAlmostEqual(acct["total_interest_earned"], acct["money"] - 10_000, delta=1e-6)
        self.assertEqual(acct["last_interest"], self.start + 86400)


if __name__ == "__main__":
    unittest.main()
