import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import random
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock


class Crime(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)

    @app_commands.command(name="rob", description="Attempt to rob another user")
    @app_commands.describe(member="User to rob")
    async def rob(self, interaction: discord.Interaction, member: discord.Member):
        robber_id = interaction.user.id
        target_id = member.id

        if member.bot:
            embed = discord.Embed(
                title="❌ Invalid Target",
                description="You can't rob a bot",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if target_id == robber_id:
            embed = discord.Embed(
                title="❌ Invalid Target",
                description="You can't rob yourself",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        now = int(datetime.utcnow().timestamp())
        last_attempt = self.db.get_last_rob_attempt(robber_id)

        if last_attempt is not None and now < last_attempt + Config.ROB_COOLDOWN_SECONDS:
            time_left = (last_attempt + Config.ROB_COOLDOWN_SECONDS) - now
            minutes = time_left // 60
            seconds = time_left % 60
            embed = discord.Embed(
                title="⏰ Lying Low",
                description=f"You need to wait **{minutes}m {seconds}s** before robbing again",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        target_data = self.db.get_or_create_user(target_id)
        robber_data = self.db.get_or_create_user(robber_id)

        if target_data["money"] <= 0:
            embed = discord.Embed(
                title="❌ Nothing To Steal",
                description=f"{member.mention} has no money to rob",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.db.set_last_rob_attempt(robber_id, now)

        attacker_bonus = self.db.get_perk_bonus(robber_id, "rob_success_bonus")
        defender_bonus = self.db.get_perk_bonus(target_id, "rob_defense")
        success_chance = min(max(Config.ROB_SUCCESS_CHANCE + attacker_bonus - defender_bonus, 0.05), 0.95)
        success = random.random() <= success_chance

        if success:
            steal_amount = target_data["money"] * Config.ROB_STEAL_PERCENT
            actual = self.db.rob_user(robber_id, target_id, True, steal_amount, 0)
            embed = discord.Embed(
                title="🕵️ Robbery Successful!",
                description=f"You stole **${actual:.2f}** from {member.mention}",
                color=discord.Color.green()
            )
        else:
            penalty_reduction = self.db.get_item_effect_value(robber_id, "rob_penalty_reduction")
            penalty_amount = robber_data["money"] * Config.ROB_FAIL_PENALTY_PERCENT * (1 - penalty_reduction)
            actual = self.db.rob_user(robber_id, target_id, False, 0, penalty_amount)
            if actual > 0:
                description = f"You got caught and paid **${actual:.2f}** into the pool as a fine"
            else:
                description = "You got caught, but had nothing to pay as a fine"
            embed = discord.Embed(
                title="🚨 Robbery Failed!",
                description=description,
                color=discord.Color.red()
            )

        await interaction.response.send_message(embed=embed)
        if success and self.db.unlock_achievement(robber_id, "first_theft"):
            await announce_unlock(interaction, "first_theft")


async def setup(bot: commands.Bot):
    await bot.add_cog(Crime(bot))
