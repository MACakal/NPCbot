"""Phase 5: NPC balance, shop items, leaderboard (audit H5, L1, L2, M6, L4)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from helpers import fresh_db, FakeInteraction, fake_member, make_cog

from config import Config
from cogs import crime
from cogs.crime import Crime
from cogs.economy import Economy
from cogs.npc import Npc, training_sessions_done
from cogs.shop import Shop
from utils import clock


def choice(value):
    return SimpleNamespace(name=value, value=value)


class NpcTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.db.get_or_create_user(1)
        self.db.set_user_money(1, 10_000)
        self.cog = make_cog(Npc, self.db)

    async def test_recruit_chosen_archetype(self):
        await self.cog.npc_recruit.callback(self.cog, FakeInteraction(1), choice("banker"))
        self.assertEqual(self.db.get_user_npc(1)["archetype"], "banker")
        self.assertAlmostEqual(self.db.get_user(1)["money"], 10_000 - Config.NPC_RECRUIT_COST)

    async def test_training_has_cooldown(self):
        await self.cog.npc_recruit.callback(self.cog, FakeInteraction(1), choice("laborer"))
        with patch.object(clock, "now_ts", return_value=5_000_000):
            await self.cog.npc_train.callback(self.cog, FakeInteraction(1))
            inter = FakeInteraction(1)
            await self.cog.npc_train.callback(self.cog, inter)
        self.assertEqual(inter.last_embed.title, "😮‍💨 Still Recovering")
        self.assertEqual(self.db.get_user_npc(1)["xp"], Config.NPC_TRAIN_XP)
        with patch.object(clock, "now_ts", return_value=5_000_000 + Config.NPC_TRAIN_COOLDOWN_SECONDS):
            await self.cog.npc_train.callback(self.cog, FakeInteraction(1))
        self.assertEqual(self.db.get_user_npc(1)["xp"], 2 * Config.NPC_TRAIN_XP)

    async def test_release_refunds_part_of_training(self):
        await self.cog.npc_recruit.callback(self.cog, FakeInteraction(1), choice("guard"))
        for i in range(8):
            with patch.object(clock, "now_ts", return_value=5_000_000 + i * Config.NPC_TRAIN_COOLDOWN_SECONDS):
                await self.cog.npc_train.callback(self.cog, FakeInteraction(1))
        self.assertEqual(training_sessions_done(**{k: self.db.get_user_npc(1)[k] for k in ("level", "xp")}), 8)
        before = self.db.get_user(1)["money"]
        await self.cog.npc_release.callback(self.cog, FakeInteraction(1))
        self.assertIsNone(self.db.get_user_npc(1))
        refund = 8 * Config.NPC_TRAIN_COST * Config.NPC_RELEASE_REFUND_PERCENT
        self.assertAlmostEqual(self.db.get_user(1)["money"] - before, refund)

    def test_max_level_perks_are_comparable(self):
        """Daily value of each economic perk at max level stays in a narrow band."""
        perks = {t["perk_type"]: t["perk_value"] for t in self.db.get_npc_templates()}
        lvl = Config.NPC_MAX_LEVEL
        daily = Config.DAILY_REWARD * perks["daily_bonus"] * lvl
        work = Config.WORK_REWARD * Config.WORK_MAX_SHIFTS_PER_DAY * perks["work_bonus"] * lvl
        bank_cap = Config.BANK_INTEREST_DAILY_RATE * Config.BANK_INTEREST_SOFT_CAP * perks["bank_interest_bonus"] * lvl
        values = [daily, work, bank_cap]
        self.assertLessEqual(max(values) / min(values), 2.0, values)

    def test_seed_updates_existing_rows(self):
        conn = self.db._get_connection()
        conn.execute("UPDATE npc_templates SET perk_value = 0.99 WHERE id = 3")
        conn.execute("UPDATE shop_items SET price = 1 WHERE id = 1")
        conn.commit()
        self.db._seed_npc_templates()
        self.db._seed_shop_items()
        self.assertEqual(self.db.get_npc_template_by_archetype("banker")["perk_value"], 0.10)
        self.assertEqual(self.db.get_item(1)["price"], 100)


class ShopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = fresh_db()
        self.db.get_or_create_user(1)
        self.db.set_user_money(1, 10_000)
        self.cog = make_cog(Shop, self.db)

    async def test_permanent_items_do_not_stack(self):
        await self.cog.buy.callback(self.cog, FakeInteraction(1), "Discount Badge")
        inter = FakeInteraction(1)
        await self.cog.buy.callback(self.cog, inter, "discount badge")
        self.assertEqual(inter.last_embed.title, "❌ Already Owned")
        self.assertAlmostEqual(self.db.get_user(1)["money"], 10_000 - 100)

    async def test_consumables_stack(self):
        for _ in range(3):
            await self.cog.buy.callback(self.cog, FakeInteraction(1), "Lockpick")
        owned = {i["name"]: i["quantity"] for i in self.db.get_user_inventory(1)}
        self.assertEqual(owned["Lockpick"], 3)

    async def test_padlock_blocks_robbery(self):
        await self.cog.buy.callback(self.cog, FakeInteraction(1), "Padlock")
        await self.cog.use.callback(self.cog, FakeInteraction(1), "Padlock")
        self.assertEqual(self.db.get_user_inventory(1), [])  # used up

        self.db.get_or_create_user(2)
        self.db.set_user_money(2, 1000)
        robber = make_cog(Crime, self.db)
        inter = FakeInteraction(2)
        await robber.rob.callback(robber, inter, fake_member(1))
        self.assertEqual(inter.last_embed.title, "🛡️ Target Protected")

    async def test_energy_drink_skips_break_only_when_on_break(self):
        await self.cog.buy.callback(self.cog, FakeInteraction(1), "Energy Drink")
        inter = FakeInteraction(1)
        await self.cog.use.callback(self.cog, inter, "Energy Drink")
        self.assertEqual(inter.last_embed.title, "❌ Not Needed")

        econ = make_cog(Economy, self.db)
        await econ.work.callback(econ, FakeInteraction(1))
        before = self.db.get_user(1)["money"]
        await self.cog.use.callback(self.cog, FakeInteraction(1), "Energy Drink")
        await econ.work.callback(econ, FakeInteraction(1))
        self.assertAlmostEqual(self.db.get_user(1)["money"] - before, Config.WORK_REWARD)
        self.assertEqual(self.db.get_user_inventory(1), [])  # used up

    async def test_lockpick_is_consumed_by_rob(self):
        await self.cog.buy.callback(self.cog, FakeInteraction(1), "Lockpick")
        self.db.get_or_create_user(2)
        self.db.set_user_money(2, 1000)
        robber = make_cog(Crime, self.db)
        with patch.object(crime.random, "random", return_value=0.55):  # fails at 50%, succeeds at 60%
            await robber.rob.callback(robber, FakeInteraction(1), fake_member(2))
        self.assertAlmostEqual(self.db.get_user(2)["money"], 800)
        self.assertEqual(self.db.get_user_inventory(1), [])


class LeaderboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_ranks_by_wallet_plus_bank(self):
        db = fresh_db()
        for uid, wallet in ((1, 3000), (2, 5000)):
            db.get_or_create_user(uid)
            db.set_user_money(uid, wallet)
        db.deposit_to_bank(2, 4900)  # user 2: wallet 100 + bank 4900 beats user 1's 3000 wallet
        rows = db.get_leaderboard(10)
        self.assertEqual([r["id"] for r in rows], [2, 1])
        self.assertAlmostEqual(rows[0]["net_worth"], 5000)


if __name__ == "__main__":
    unittest.main()
