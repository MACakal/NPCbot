import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from database.manager import DatabaseManager
from config import Config
from utils.achievements import ACHIEVEMENTS


class Achievements(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)

    @app_commands.command(name="achievements", description="View your unlocked achievements")
    async def achievements(self, interaction: discord.Interaction):
        unlocked = {row["achievement_id"]: row["unlocked_at"] for row in self.db.get_user_achievements(interaction.user.id)}

        embed = discord.Embed(
            title="🏆 Achievements",
            description=f"**{len(unlocked)} / {len(ACHIEVEMENTS)}** unlocked",
            color=discord.Color.gold()
        )

        for achievement_id, info in ACHIEVEMENTS.items():
            if achievement_id in unlocked:
                when = datetime.fromtimestamp(unlocked[achievement_id]).strftime('%Y-%m-%d')
                name = f"{info['emoji']} {info['name']}"
                value = f"{info['description']}\n*Unlocked {when}*"
            else:
                name = f"🔒 {info['name']}"
                value = info["description"]
            embed.add_field(name=name, value=value, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Achievements(bot))
