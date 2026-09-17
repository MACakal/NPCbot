import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock
from utils import clock

PERK_LABELS = {
    "daily_bonus": "+{pct:.0f}% /daily-claim reward",
    "work_bonus": "+{pct:.0f}% /work reward",
    "bank_interest_bonus": "+{pct:.0f}% bank interest",
    "rob_defense": "-{pct:.0f}% chance of being successfully robbed",
    "rob_success_bonus": "+{pct:.0f}% chance to succeed when robbing",
}

ARCHETYPE_CHOICES = [
    app_commands.Choice(name="Merchant — bigger /daily-claim", value="merchant"),
    app_commands.Choice(name="Laborer — bigger /work pay", value="laborer"),
    app_commands.Choice(name="Banker — more bank interest", value="banker"),
    app_commands.Choice(name="Guard — harder to rob you", value="guard"),
    app_commands.Choice(name="Gambler — better robbery odds", value="gambler"),
]


def describe_perk(perk_type: str, perk_value: float, level: int) -> str:
    pct = perk_value * level * 100
    label = PERK_LABELS.get(perk_type, "Unknown perk")
    return label.format(pct=pct)


def training_sessions_done(level: int, xp: int) -> int:
    if level >= Config.NPC_MAX_LEVEL:
        total_xp = (Config.NPC_MAX_LEVEL - 1) * Config.NPC_XP_PER_LEVEL
    else:
        total_xp = (level - 1) * Config.NPC_XP_PER_LEVEL + xp
    return total_xp // Config.NPC_TRAIN_XP


class Npc(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)

    def cost_multiplier(self, user_id: int) -> float:
        return 1 - self.db.get_item_effect_value(user_id, "npc_cost_discount")

    async def _reply(self, interaction: discord.Interaction, title: str, description: str, color):
        embed = discord.Embed(title=title, description=description, color=color)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="npc-recruit", description=f"Recruit an NPC companion for ${Config.NPC_RECRUIT_COST}")
    @app_commands.describe(archetype="Which kind of companion to recruit (random if left empty)")
    @app_commands.choices(archetype=ARCHETYPE_CHOICES)
    async def npc_recruit(self, interaction: discord.Interaction, archetype: Optional[app_commands.Choice[str]] = None):
        user_id = interaction.user.id
        user_data = self.db.get_or_create_user(user_id)

        if self.db.get_user_npc(user_id) is not None:
            await self._reply(
                interaction, "❌ Already Have A Companion",
                "Use `/npc-release` first if you want to recruit a different one.", discord.Color.red()
            )
            return

        recruit_cost = round(Config.NPC_RECRUIT_COST * self.cost_multiplier(user_id), 2)

        if user_data["money"] < recruit_cost:
            await self._reply(
                interaction, "❌ Insufficient Funds",
                f"Recruiting a companion costs **${recruit_cost:.2f}**", discord.Color.red()
            )
            return

        if archetype is not None:
            template = self.db.get_npc_template_by_archetype(archetype.value)
        else:
            template = self.db.get_random_npc_template()
        if template is None:
            await self._reply(
                interaction, "❌ No Companions Available",
                "Something went wrong — no NPC templates exist. Contact JinMori07.", discord.Color.red()
            )
            return

        if not self.db.try_debit_user(user_id, recruit_cost):
            await self._reply(
                interaction, "❌ Insufficient Funds",
                f"Recruiting a companion costs **${recruit_cost:.2f}**", discord.Color.red()
            )
            return

        recruited = self.db.recruit_npc(user_id, template["id"], clock.now_ts())
        if not recruited:
            self.db.update_user_money(user_id, recruit_cost)  # refund
            await self._reply(
                interaction, "❌ Already Have A Companion",
                "Use `/npc-release` first if you want to recruit a different one.", discord.Color.red()
            )
            return

        embed = discord.Embed(
            title="🤝 Companion Recruited!",
            description=f"**{template['name']}** ({template['archetype']}) has joined you.\n*{template['flavor_text']}*",
            color=discord.Color.green()
        )
        embed.add_field(name="Perk", value=describe_perk(template["perk_type"], template["perk_value"], 1), inline=False)
        embed.set_footer(text=f"Cost: ${recruit_cost:.2f}")
        await interaction.response.send_message(embed=embed)
        if self.db.unlock_achievement(user_id, "first_npc"):
            await announce_unlock(interaction, "first_npc")

    @app_commands.command(name="npc-info", description="View your NPC companion")
    async def npc_info(self, interaction: discord.Interaction):
        npc = self.db.get_user_npc(interaction.user.id)

        if npc is None:
            await self._reply(
                interaction, "🫥 No Companion",
                "You haven't recruited an NPC companion yet. Try `/npc-recruit`.", discord.Color.orange()
            )
            return

        embed = discord.Embed(
            title=f"🧑 {npc['name']}",
            description=f"*{npc['flavor_text']}*",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Archetype", value=npc["archetype"].title(), inline=True)
        embed.add_field(name="Level", value=f"{npc['level']} / {Config.NPC_MAX_LEVEL}", inline=True)
        if npc["level"] < Config.NPC_MAX_LEVEL:
            embed.add_field(name="XP", value=f"{npc['xp']} / {Config.NPC_XP_PER_LEVEL}", inline=True)
            wait = self.db.timer_remaining(interaction.user.id, "npc_train", clock.now_ts())
            ready = "Ready now" if wait == 0 else f"in {clock.format_duration(wait)}"
            embed.add_field(name="Next Training", value=ready, inline=True)
        else:
            embed.add_field(name="XP", value="MAX LEVEL", inline=True)
        embed.add_field(name="Perk", value=describe_perk(npc["perk_type"], npc["perk_value"], npc["level"]), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="npc-train", description=f"Train your companion for ${Config.NPC_TRAIN_COST}")
    async def npc_train(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        self.db.get_or_create_user(user_id)

        npc = self.db.get_user_npc(user_id)
        if npc is None:
            await self._reply(
                interaction, "🫥 No Companion",
                "You haven't recruited an NPC companion yet. Try `/npc-recruit`.", discord.Color.orange()
            )
            return

        if npc["level"] >= Config.NPC_MAX_LEVEL:
            await self._reply(
                interaction, "⭐ Already Max Level",
                f"**{npc['name']}** is already at level {Config.NPC_MAX_LEVEL}.", discord.Color.gold()
            )
            return

        now = clock.now_ts()
        wait = self.db.timer_remaining(user_id, "npc_train", now)
        if wait > 0:
            await self._reply(
                interaction, "😮‍💨 Still Recovering",
                f"**{npc['name']}** can train again in **{clock.format_duration(wait)}**", discord.Color.orange()
            )
            return

        train_cost = round(Config.NPC_TRAIN_COST * self.cost_multiplier(user_id), 2)
        if not self.db.try_debit_user(user_id, train_cost):
            await self._reply(
                interaction, "❌ Insufficient Funds",
                f"Training costs **${train_cost:.2f}**", discord.Color.red()
            )
            return

        self.db.set_timer(user_id, "npc_train", now + Config.NPC_TRAIN_COOLDOWN_SECONDS)
        updated = self.db.train_npc(user_id, Config.NPC_TRAIN_XP, Config.NPC_XP_PER_LEVEL, Config.NPC_MAX_LEVEL)

        if updated["leveled_up"]:
            embed = discord.Embed(
                title="📈 Level Up!",
                description=f"**{updated['name']}** is now level **{updated['level']}**!",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="🏋️ Training Complete",
                description=f"**{updated['name']}** gained **{Config.NPC_TRAIN_XP} XP**",
                color=discord.Color.blurple()
            )
        embed.add_field(name="Perk", value=describe_perk(updated["perk_type"], updated["perk_value"], updated["level"]), inline=False)
        await interaction.response.send_message(embed=embed)
        if updated["level"] >= Config.NPC_MAX_LEVEL and self.db.unlock_achievement(user_id, "npc_max_level"):
            await announce_unlock(interaction, "npc_max_level")

    @app_commands.command(name="npc-release", description="Release your current NPC companion")
    async def npc_release(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        npc = self.db.get_user_npc(user_id)

        if npc is None:
            await self._reply(
                interaction, "🫥 No Companion",
                "You don't have an NPC companion to release.", discord.Color.orange()
            )
            return

        sessions = training_sessions_done(npc["level"], npc["xp"])
        refund = round(
            sessions * Config.NPC_TRAIN_COST * self.cost_multiplier(user_id) * Config.NPC_RELEASE_REFUND_PERCENT, 2
        )

        if not self.db.release_npc(user_id):
            return
        if refund > 0:
            self.db.update_user_money(user_id, refund)

        description = f"**{npc['name']}** has gone their own way."
        if refund > 0:
            description += (
                f" You got **${refund:.2f}** back "
                f"({Config.NPC_RELEASE_REFUND_PERCENT * 100:.0f}% of training costs)."
            )
        else:
            description += " No refund for recruiting costs."
        embed = discord.Embed(title="👋 Companion Released", description=description, color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Npc(bot))
