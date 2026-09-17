"""Public "not right now" notices are auto-deleted; results are kept."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from helpers import fresh_db, FakeInteraction, make_cog

from config import Config
from cogs.economy import Economy
from cogs.games import Games, JackpotView
from utils import clock

TTL = Config.TRANSIENT_MESSAGE_SECONDS


class FakeMessage:
    def __init__(self):
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(SimpleNamespace(**kwargs))


class EconomyNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.cog = make_cog(Economy, self.db)

    async def test_daily_claim_kept_but_not_available_deleted(self):
        with patch.object(clock, "now_ts", return_value=1_700_000_000):
            first, second = FakeInteraction(1), FakeInteraction(1)
            await self.cog.daily.callback(self.cog, first)
            await self.cog.daily.callback(self.cog, second)
        self.assertIsNone(first.response.sent[0].delete_after)
        self.assertEqual(second.last_embed.title, "⏰ Daily Not Available")
        self.assertEqual(second.response.sent[0].delete_after, TTL)

    async def test_work_break_and_daily_limit_deleted(self):
        day_start = 1_700_006_400
        with patch.object(clock, "now_ts", return_value=day_start):
            done, on_break = FakeInteraction(1), FakeInteraction(1)
            await self.cog.work.callback(self.cog, done)
            await self.cog.work.callback(self.cog, on_break)
        self.assertIsNone(done.response.sent[0].delete_after)
        self.assertEqual(on_break.last_embed.title, "⏰ Still On Break")
        self.assertEqual(on_break.response.sent[0].delete_after, TTL)

        self.db.add_daily_counter(1, "work_shifts", clock.utc_day(day_start), Config.WORK_MAX_SHIFTS_PER_DAY)
        capped = FakeInteraction(1)
        with patch.object(clock, "now_ts", return_value=day_start + 7200):
            await self.cog.work.callback(self.cog, capped)
        self.assertEqual(capped.last_embed.title, "😴 Done For The Day")
        self.assertEqual(capped.response.sent[0].delete_after, TTL)


class JackpotPromptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.db.get_or_create_user(1)
        self.cog = make_cog(Games, self.db)

    async def test_canceled_prompt_is_deleted(self):
        view = JackpotView(self.cog, 1, 50)
        inter = FakeInteraction(1)
        await view.cancel.callback(inter)
        self.assertEqual(inter.response.edited[-1].delete_after, TTL)

    async def test_unanswered_prompt_is_deleted_on_timeout(self):
        view = JackpotView(self.cog, 1, 50)
        view.message = FakeMessage()
        await view.on_timeout()
        self.assertEqual(view.message.edits[-1].delete_after, TTL)

    async def test_bought_ticket_result_is_kept(self):
        view = JackpotView(self.cog, 1, 50)
        inter = FakeInteraction(1)
        await view.confirm.callback(inter)
        self.assertTrue(view.resolved)
        self.assertIsNone(inter.response.edited[-1].delete_after)


if __name__ == "__main__":
    unittest.main()
