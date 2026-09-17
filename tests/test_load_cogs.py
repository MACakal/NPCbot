"""Smoke test: every cog loads and registers its slash commands."""
import unittest

import helpers  # noqa: F401  (sets up the temp data dir and sys.path)

import discord
from discord.ext import commands

COGS = ['cogs.admin', 'cogs.economy', 'cogs.games', 'cogs.utilities', 'cogs.crime',
        'cogs.npc', 'cogs.shop', 'cogs.achievements', 'cogs.trivia']


class LoadCogsTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_cogs_load(self):
        bot = commands.Bot(command_prefix='$', intents=discord.Intents.default())
        for cog in COGS:
            await bot.load_extension(cog)
        names = {c.name for c in bot.tree.get_commands()}
        for expected in ("deposit", "withdraw", "coin-flip", "jackpot", "rob", "npc-recruit", "shop", "trivia"):
            self.assertIn(expected, names)
        # Serialising every command exercises choices/ranges/describe metadata.
        for command in bot.tree.get_commands():
            command.to_dict(bot.tree)
        await bot.close()


if __name__ == "__main__":
    unittest.main()
