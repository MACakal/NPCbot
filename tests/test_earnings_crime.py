"""Phase 4: earning caps, robbery, trivia and transfers (audit H6, H7, M3, M4, M5)."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from helpers import fresh_db, FakeInteraction, fake_member, make_cog

from config import Config
from cogs import crime
from cogs.crime import Crime, rob_amounts
from cogs.economy import Economy
from cogs.trivia import Trivia
from utils import clock


def fake_message(user_id, content="hello there", guild=True, bot=False, channel_id=1):
    replies = []

    async def reply(text, **kwargs):
        replies.append(text)

    return SimpleNamespace(
        author=SimpleNamespace(id=user_id, bot=bot, mention=f"<@{user_id}>"),
        guild=object() if guild else None,
        content=content,
        channel=SimpleNamespace(id=channel_id),
        reply=reply,
        replies=replies,
    )


class MessageRewardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.cog = make_cog(Economy, self.db)

    async def test_spam_pays_once_per_cooldown(self):
        with patch.object(clock, "now_ts", return_value=1000):
            for _ in range(50):
                await self.cog.on_message(fake_message(1))
        self.assertAlmostEqual(self.db.get_user(1)["money"], Config.STARTING_BALANCE + Config.MONEY_PER_MESSAGE)
        with patch.object(clock, "now_ts", return_value=1000 + Config.MESSAGE_REWARD_COOLDOWN_SECONDS):
            await self.cog.on_message(fake_message(1))
        self.assertAlmostEqual(self.db.get_user(1)["money"], Config.STARTING_BALANCE + 2 * Config.MONEY_PER_MESSAGE)

    async def test_dms_and_short_messages_pay_nothing(self):
        await self.cog.on_message(fake_message(1, guild=False))
        await self.cog.on_message(fake_message(2, content="k"))
        self.assertIsNone(self.db.get_user(1))
        self.assertIsNone(self.db.get_user(2))


class WorkAndDailyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.cog = make_cog(Economy, self.db)

    async def test_work_caps_shifts_per_day(self):
        day_start = 1_700_006_400  # a UTC midnight
        self.assertEqual(day_start % 86400, 0)
        for i in range(Config.WORK_MAX_SHIFTS_PER_DAY + 3):
            with patch.object(clock, "now_ts", return_value=day_start + i * Config.WORK_COOLDOWN_SECONDS):
                await self.cog.work.callback(self.cog, FakeInteraction(1))
        expected = Config.STARTING_BALANCE + Config.WORK_MAX_SHIFTS_PER_DAY * Config.WORK_REWARD
        self.assertAlmostEqual(self.db.get_user(1)["money"], expected)

        # A new UTC day resets the count.
        with patch.object(clock, "now_ts", return_value=day_start + 86400):
            await self.cog.work.callback(self.cog, FakeInteraction(1))
        self.assertAlmostEqual(self.db.get_user(1)["money"], expected + Config.WORK_REWARD)

    async def test_daily_streak_grows_caps_and_resets(self):
        t = 1_700_000_000
        rewards = []
        for day in range(8):
            before = self.db.get_or_create_user(1)["money"]
            with patch.object(clock, "now_ts", return_value=t + day * 86400):
                await self.cog.daily.callback(self.cog, FakeInteraction(1))
            rewards.append(round(self.db.get_user(1)["money"] - before, 2))
        base = Config.DAILY_REWARD
        self.assertEqual(rewards[0], base)
        self.assertEqual(rewards[1], round(base * 1.1, 2))
        self.assertEqual(rewards[-1], round(base * (1 + Config.DAILY_STREAK_MAX_BONUS), 2))

        # Miss the grace window -> back to the base reward.
        before = self.db.get_user(1)["money"]
        with patch.object(clock, "now_ts", return_value=t + 7 * 86400 + Config.DAILY_STREAK_GRACE_SECONDS + 1):
            await self.cog.daily.callback(self.cog, FakeInteraction(1))
        self.assertAlmostEqual(self.db.get_user(1)["money"] - before, base)


class GiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.db.get_or_create_user(1)
        self.db.set_user_money(1, 20_000)
        self.cog = make_cog(Economy, self.db)

    async def test_tax_is_destroyed(self):
        await self.cog.give.callback(self.cog, FakeInteraction(1), fake_member(2), 1000)
        self.assertAlmostEqual(self.db.get_user(1)["money"], 19_000)
        self.assertAlmostEqual(self.db.get_user(2)["money"], Config.STARTING_BALANCE + 1000 * (1 - Config.GIVE_TAX_PERCENT))
        self.assertAlmostEqual(self.db.get_pool()["money"], 0)

    async def test_daily_limit(self):
        await self.cog.give.callback(self.cog, FakeInteraction(1), fake_member(2), Config.GIVE_DAILY_LIMIT)
        inter = FakeInteraction(1)
        await self.cog.give.callback(self.cog, inter, fake_member(2), 1)
        self.assertEqual(inter.last_embed.title, "❌ Daily Limit Reached")

    async def test_cannot_give_to_self_or_bot(self):
        for member in (fake_member(1), fake_member(3, bot=True)):
            inter = FakeInteraction(1)
            await self.cog.give.callback(self.cog, inter, member, 10)
            self.assertEqual(inter.last_embed.title, "❌ Invalid Recipient")
        self.assertAlmostEqual(self.db.get_user(1)["money"], 20_000)


class RobberyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        for uid, money in ((1, 1000), (2, 10_000), (3, 0)):
            self.db.get_or_create_user(uid)
            self.db.set_user_money(uid, money)
        self.cog = make_cog(Crime, self.db)

    def test_fine_scales_with_attempt(self):
        steal, fine = rob_amounts(target_money=10_000, robber_money=100)
        self.assertEqual(steal, Config.ROB_MAX_STEAL)
        self.assertEqual(fine, Config.ROB_MAX_STEAL * Config.ROB_FAIL_PENALTY_OF_ATTEMPT)
        # A robber with an empty wallet still faces a real fine.
        _, broke_fine = rob_amounts(target_money=10_000, robber_money=0)
        self.assertGreater(broke_fine, 0)
        _, insured_fine = rob_amounts(target_money=10_000, robber_money=0, penalty_reduction=0.5)
        self.assertAlmostEqual(insured_fine, broke_fine / 2)

    async def test_broke_robber_is_rejected(self):
        inter = FakeInteraction(3)
        await self.cog.rob.callback(self.cog, inter, fake_member(2))
        self.assertEqual(inter.last_embed.title, "❌ Can't Afford The Risk")
        self.assertIsNone(self.db.get_last_rob_attempt(3))

    async def test_success_is_capped_and_protects_target(self):
        with patch.object(crime.random, "random", return_value=0.0):
            await self.cog.rob.callback(self.cog, FakeInteraction(1), fake_member(2))
        self.assertAlmostEqual(self.db.get_user(2)["money"], 10_000 - Config.ROB_MAX_STEAL)

        # Another robber can't hit the same target during the protection window.
        self.db.get_or_create_user(4)
        self.db.set_user_money(4, 1000)
        inter = FakeInteraction(4)
        await self.cog.rob.callback(self.cog, inter, fake_member(2))
        self.assertEqual(inter.last_embed.title, "🛡️ Target Protected")
        self.assertAlmostEqual(self.db.get_user(2)["money"], 10_000 - Config.ROB_MAX_STEAL)

    async def test_failure_fine_goes_to_pool(self):
        with patch.object(crime.random, "random", return_value=0.99):
            await self.cog.rob.callback(self.cog, FakeInteraction(1), fake_member(2))
        # fine = max(15% of 1000, 50% of 500) = 250
        self.assertAlmostEqual(self.db.get_user(1)["money"], 750)
        self.assertAlmostEqual(self.db.get_pool()["money"], 250)


class FakeBot:
    def __init__(self, messages):
        self.messages = messages

    async def wait_for(self, event, check, timeout):
        for message in self.messages:
            if check(message):
                return message
        raise asyncio.TimeoutError


class TriviaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()

    def _cog(self, messages):
        return make_cog(Trivia, self.db, bot=FakeBot(messages))

    async def test_starter_can_win_and_reward_is_minted(self):
        question = {"id": 1, "question": "Q?", "answer": "glucose"}
        cog = self._cog([fake_message(1, "Glucose"), fake_message(2, "glucose")])
        with patch.object(self.db, "get_random_trivia_question", return_value=question):
            await cog.trivia.callback(cog, FakeInteraction(1))
        self.assertAlmostEqual(self.db.get_user(1)["money"], Config.STARTING_BALANCE + Config.TRIVIA_REWARD)
        self.assertIsNone(self.db.get_user(2))
        self.assertAlmostEqual(self.db.get_pool()["money"], 0)

    async def test_capped_winner_gets_notice_once(self):
        today = clock.utc_day(clock.now_ts())
        self.db.add_daily_counter(1, "trivia_wins", today, Config.TRIVIA_MAX_WINS_PER_DAY)
        question = {"id": 1, "question": "Q?", "answer": "glucose"}
        first, second = fake_message(1, "glucose"), fake_message(1, "Glucose")
        cog = self._cog([first, second])
        inter = FakeInteraction(1)
        with patch.object(self.db, "get_random_trivia_question", return_value=question):
            await cog.trivia.callback(cog, inter)
        await asyncio.sleep(0)  # let the notice task run
        self.assertEqual(len(first.replies), 1)
        self.assertIn("Come back tomorrow", first.replies[0])
        self.assertEqual(second.replies, [])
        self.assertTrue(inter.followup.sent[-1].embed.description.startswith("Nobody else got it"))

    async def test_channel_cooldown(self):
        cog = self._cog([])
        await cog.trivia.callback(cog, FakeInteraction(1))
        inter = FakeInteraction(2)
        await cog.trivia.callback(cog, inter)
        self.assertEqual(inter.last_embed.title, "⏰ Trivia Cooldown")
        # A different channel is unaffected.
        inter = FakeInteraction(2, channel_id=99)
        await cog.trivia.callback(cog, inter)
        self.assertEqual(inter.last_embed.title, "🧠 Trivia Time!")

    async def test_daily_win_cap(self):
        question = {"id": 1, "question": "Q?", "answer": "yes"}
        # Someone starting and answering their own rounds is still capped.
        cog = self._cog([fake_message(1, "yes")])
        with patch.object(self.db, "get_random_trivia_question", return_value=question):
            for i in range(Config.TRIVIA_MAX_WINS_PER_DAY + 2):
                cog.channel_next_round.clear()
                await cog.trivia.callback(cog, FakeInteraction(1))
        expected = Config.STARTING_BALANCE + Config.TRIVIA_MAX_WINS_PER_DAY * Config.TRIVIA_REWARD
        self.assertAlmostEqual(self.db.get_user(1)["money"], expected)

    def test_question_bank_is_large(self):
        conn = self.db._get_connection()
        count = conn.execute("SELECT COUNT(*) FROM trivia_questions").fetchone()[0]
        self.assertGreaterEqual(count, 50)


if __name__ == "__main__":
    unittest.main()
