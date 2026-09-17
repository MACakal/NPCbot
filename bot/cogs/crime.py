import discord
from discord import app_commands
from discord.ext import commands
import random
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock
from utils import clock


def rob_amounts(target_money: float, robber_money: float, penalty_reduction: float = 0.0):
    """(amount a success steals, fine a failure costs) for a robbery attempt.
    The fine scales with what was attempted, so a broke robber can't rob
    for free."""
    attempted = min(max(target_money, 0) * Config.ROB_STEAL_PERCENT, Config.ROB_MAX_STEAL)
    fine = max(robber_money * Config.ROB_FAIL_PENALTY_PERCENT, attempted * Config.ROB_FAIL_PENALTY_OF_ATTEMPT)
    return round(attempted, 2), round(fine * (1 - penalty_reduction), 2)


class Crime(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)

    async def _reject(self, interaction: discord.Interaction, title: str, description: str, color=None):
        embed = discord.Embed(title=title, description=description, color=color or discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="rob", description="Attempt to rob another user")
    @app_commands.describe(member="User to rob")
    async def rob(self, interaction: discord.Interaction, member: discord.Member):
        robber_id = interaction.user.id
        target_id = member.id

        if member.bot:
            await self._reject(interaction, "❌ Invalid Target", "You can't rob a bot")
            return

        if target_id == robber_id:
            await self._reject(interaction, "❌ Invalid Target", "You can't rob yourself")
            return

        now = clock.now_ts()
        last_attempt = self.db.get_last_rob_attempt(robber_id)

        if last_attempt is not None and now < last_attempt + Config.ROB_COOLDOWN_SECONDS:
            time_left = (last_attempt + Config.ROB_COOLDOWN_SECONDS) - now
            await self._reject(
                interaction, "⏰ Lying Low",
                f"You need to wait **{clock.format_duration(time_left)}** before robbing again",
                discord.Color.orange()
            )
            return

        target_data = self.db.get_or_create_user(target_id)
        robber_data = self.db.get_or_create_user(robber_id)

        if robber_data["money"] < Config.ROB_MIN_ROBBER_BALANCE:
            await self._reject(
                interaction, "❌ Can't Afford The Risk",
                f"You need at least **${Config.ROB_MIN_ROBBER_BALANCE:.2f}** in your wallet to cover a fine"
            )
            return

        if target_data["money"] <= 0:
            await self._reject(interaction, "❌ Nothing To Steal", f"{member.mention} has no money to rob")
            return

        protected_for = self.db.timer_remaining(target_id, "rob_protection", now)
        if protected_for > 0:
            await self._reject(
                interaction, "🛡️ Target Protected",
                f"{member.mention} can't be robbed for another **{clock.format_duration(protected_for)}**",
                discord.Color.orange()
            )
            return

        self.db.set_last_rob_attempt(robber_id, now)

        attacker_bonus = self.db.get_perk_bonus(robber_id, "rob_success_bonus")
        defender_bonus = self.db.get_perk_bonus(target_id, "rob_defense")
        attacker_bonus += self.db.consume_item(robber_id, "rob_success_consumable")
        success_chance = min(max(Config.ROB_SUCCESS_CHANCE + attacker_bonus - defender_bonus, 0.05), 0.95)
        success = random.random() <= success_chance

        penalty_reduction = self.db.get_item_effect_value(robber_id, "rob_penalty_reduction")
        steal_amount, penalty_amount = rob_amounts(target_data["money"], robber_data["money"], penalty_reduction)

        if success:
            actual = self.db.rob_user(robber_id, target_id, True, steal_amount, 0)
            self.db.extend_timer(target_id, "rob_protection", now + Config.ROB_TARGET_PROTECTION_SECONDS)
            embed = discord.Embed(
                title="🕵️ Robbery Successful!",
                description=f"You stole **${actual:.2f}** from {member.mention}",
                color=discord.Color.green()
            )
        else:
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
        embed.set_footer(text=f"Success chance: {success_chance * 100:.0f}%")

        await interaction.response.send_message(embed=embed)
        if success and self.db.unlock_achievement(robber_id, "first_theft"):
            await announce_unlock(interaction, "first_theft")


async def setup(bot: commands.Bot):
    await bot.add_cog(Crime(bot))
