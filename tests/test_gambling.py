"""Phase 3: gambling balance (audit H3, H4, M1, M2, L3)."""
import unittest
from unittest.mock import patch

from helpers import fresh_db, FakeInteraction, make_cog

from config import Config
from cogs import games
from cogs.games import Games, BlackjackView, JackpotView
from discord import app_commands


class CoinFlipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.db.get_or_create_user(1)
        self.db.set_user_money(1, 1000)
        self.cog = make_cog(Games, self.db)

    async def test_win_pays_less_than_even_money(self):
        with patch.object(games.random, "choice", return_value=True):
            await self.cog.coin_flip.callback(self.cog, FakeInteraction(1), 100)
        self.assertAlmostEqual(self.db.get_user(1)["money"], 1000 + 100 * Config.COIN_FLIP_PAYOUT)

    async def test_loss_burns_part_of_the_bet(self):
        with patch.object(games.random, "choice", return_value=False):
            await self.cog.coin_flip.callback(self.cog, FakeInteraction(1), 100)
        self.assertAlmostEqual(self.db.get_user(1)["money"], 900)
        self.assertAlmostEqual(self.db.get_pool()["money"], 100 * (1 - Config.GAMBLING_LOSS_BURN_PERCENT))

    async def test_bet_above_max_is_rejected(self):
        self.db.set_user_money(1, 1_000_000)
        inter = FakeInteraction(1)
        await self.cog.coin_flip.callback(self.cog, inter, Config.MAX_BET + 1)
        self.assertEqual(inter.last_embed.title, "❌ Invalid Amount")
        self.assertAlmostEqual(self.db.get_user(1)["money"], 1_000_000)


class RouletteTests(unittest.IsolatedAsyncioTestCase):
    async def test_green_payout_and_expected_value(self):
        db = fresh_db()
        db.get_or_create_user(1)
        db.set_user_money(1, 1000)
        cog = make_cog(Games, db)
        green = app_commands.Choice(name="Green", value="green")
        with patch.object(games.random, "choice", return_value="green"):
            await cog.roulette_color.callback(cog, FakeInteraction(1), green, 10)
        self.assertAlmostEqual(db.get_user(1)["money"], 1000 + 10 * Config.ROULETTE_GREEN_PAYOUT)

        slots = len(games.ROULETTE_OUTCOMES)
        greens = games.ROULETTE_OUTCOMES.count("green")
        reds = games.ROULETTE_OUTCOMES.count("red")
        ev_green = (greens * Config.ROULETTE_GREEN_PAYOUT - (slots - greens)) / slots
        ev_red = (reds - (slots - reds)) / slots
        self.assertAlmostEqual(ev_green, ev_red)
        self.assertLess(ev_green, 0)


class BlackjackDoubleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.db.get_or_create_user(1)
        self.db.set_user_money(1, 100)
        self.cog = make_cog(Games, self.db)

    def _view(self, bet, deck, player, dealer):
        self.db.try_debit_user(1, bet)
        return BlackjackView(self.cog, 1, bet, deck, player, dealer)

    async def test_double_down_win_pays_double(self):
        # Player 5+6=11, draws 10 -> 21. Dealer 10+7=17 stands.
        view = self._view(40, ["2♠", "10♠"], ["5♠", "6♠"], ["10♥", "7♥"])
        await view.double_down.callback(FakeInteraction(1))
        self.assertTrue(view.finished)
        self.assertAlmostEqual(view.amount, 80)
        self.assertAlmostEqual(self.db.get_user(1)["money"], 100 - 80 + 160)

    async def test_double_down_needs_funds(self):
        view = self._view(80, ["10♠"], ["5♠", "6♠"], ["10♥", "7♥"])
        inter = FakeInteraction(1)
        await view.double_down.callback(inter)
        self.assertFalse(view.finished)
        self.assertTrue(inter.response.sent[-1].ephemeral)
        self.assertAlmostEqual(self.db.get_user(1)["money"], 20)

    async def test_double_down_disabled_after_hit(self):
        view = self._view(10, ["2♠", "3♠"], ["5♠", "6♠"], ["10♥", "7♥"])
        await view.hit.callback(FakeInteraction(1))
        self.assertTrue(view.double_down.disabled)
        inter = FakeInteraction(1)
        await view.double_down.callback(inter)
        self.assertTrue(inter.response.sent[-1].ephemeral)

    async def test_loss_burns_part_of_bet(self):
        view = self._view(40, [], ["10♠", "7♠"], ["10♥", "9♥"])
        await view.stand.callback(FakeInteraction(1))
        self.assertAlmostEqual(self.db.get_user(1)["money"], 60)
        self.assertAlmostEqual(self.db.get_pool()["money"], 40 * (1 - Config.GAMBLING_LOSS_BURN_PERCENT))


class JackpotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.db.get_or_create_user(1)
        self.db.set_user_money(1, 10_000)
        self.cog = make_cog(Games, self.db)

    def test_ticket_is_never_positive_ev(self):
        for pool in (0, 500, 950, 1666, 1667, 2000, 10_000, 1_000_000):
            self.db.set_pool_money(pool)
            price = self.db.jackpot_ticket_price()
            ev = Config.JACKPOT_WIN_CHANCE * Config.JACKPOT_PAYOUT_PERCENT * (pool + price) - price
            self.assertLess(ev, 0, f"pool={pool}")

    async def test_win_pays_share_and_keeps_rest(self):
        self.db.set_pool_money(1000)
        view = JackpotView(self.cog, 1, 50)
        with patch.object(games.random, "random", return_value=0.0):
            await view.confirm.callback(FakeInteraction(1))
        # Ticket (price 50) goes in first -> pool 1050, winner takes half.
        self.assertAlmostEqual(self.db.get_user(1)["money"], 10_000 - 50 + 525)
        self.assertAlmostEqual(self.db.get_pool()["money"], 525)

    async def test_cooldown_blocks_second_ticket(self):
        with patch.object(games.random, "random", return_value=0.99):
            await JackpotView(self.cog, 1, 50).confirm.callback(FakeInteraction(1))
            second = JackpotView(self.cog, 1, 50)
            inter = FakeInteraction(1)
            await second.confirm.callback(inter)
        self.assertFalse(second.resolved)
        self.assertIn("another ticket", inter.response.sent[-1].content)
        self.assertAlmostEqual(self.db.get_user(1)["money"], 10_000 - 50)

        inter = FakeInteraction(1)
        await self.cog.jackpot.callback(self.cog, inter)
        self.assertEqual(inter.last_embed.title, "⏰ Ticket Cooldown")


if __name__ == "__main__":
    unittest.main()
