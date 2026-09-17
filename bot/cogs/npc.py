import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock

PERK_LABELS = {
    "daily_bonus": "+{pct:.0f}% /daily-claim reward",
    "work_bonus": "+{pct:.0f}% /work reward",
    "bank_interest_bonus": "+{pct:.0f}% bank interest",
    "rob_defense": "-{pct:.0f}% chance of being successfully robbed",
    "rob_success_bonus": "+{pct:.0f}% chance to succeed when robbing",
}


def describe_perk(perk_type: str, perk_value: float, level: int) -> str:
    pct = perk_value * level * 100
    label = PERK_LABELS.get(perk_type, "Unknown perk")
    return label.format(pct=pct)


class Npc(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)

    @app_commands.command(name="npc-recruit", description=f"Recruit a random NPC companion for ${Config.NPC_RECRUIT_COST}")
    async def npc_recruit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = self.db.get_or_create_user(user_id)

        if self.db.get_user_npc(user_id) is not None:
            embed = discord.Embed(
                title="❌ Already Have A Companion",
                description="Use `/npc-release` first if you want to recruit a different one.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        discount = self.db.get_item_effect_value(user_id, "npc_cost_discount")
        recruit_cost = Config.NPC_RECRUIT_COST * (1 - discount)

        if user_data["money"] < recruit_cost:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"Recruiting a companion costs **${recruit_cost:.2f}**",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        template = self.db.get_random_npc_template()
        if template is None:
            embed = discord.Embed(
                title="❌ No Companions Available",
                description="Something went wrong — no NPC templates exist. Contact JinMori07.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not self.db.try_debit_user(user_id, recruit_cost):
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"Recruiting a companion costs **${recruit_cost:.2f}**",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        now = int(datetime.utcnow().timestamp())
        recruited = self.db.recruit_npc(user_id, template["id"], now)
        if not recruited:
            self.db.update_user_money(user_id, recruit_cost)  # refund
            embed = discord.Embed(
                title="❌ Already Have A Companion",
                description="Use `/npc-release` first if you want to recruit a different one.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
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
            embed = discord.Embed(
                title="🫥 No Companion",
                description="You haven't recruited an NPC companion yet. Try `/npc-recruit`.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
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
        else:
            embed.add_field(name="XP", value="MAX LEVEL", inline=True)
        embed.add_field(name="Perk", value=describe_perk(npc["perk_type"], npc["perk_value"], npc["level"]), inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="npc-train", description=f"Train your companion for ${Config.NPC_TRAIN_COST}")
    async def npc_train(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = self.db.get_or_create_user(user_id)

        npc = self.db.get_user_npc(user_id)
        if npc is None:
            embed = discord.Embed(
                title="🫥 No Companion",
                description="You haven't recruited an NPC companion yet. Try `/npc-recruit`.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if npc["level"] >= Config.NPC_MAX_LEVEL:
            embed = discord.Embed(
                title="⭐ Already Max Level",
                description=f"**{npc['name']}** is already at level {Config.NPC_MAX_LEVEL}.",
                color=discord.Color.gold()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        discount = self.db.get_item_effect_value(user_id, "npc_cost_discount")
        train_cost = Config.NPC_TRAIN_COST * (1 - discount)

        if not self.db.try_debit_user(user_id, train_cost):
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"Training costs **${train_cost:.2f}**",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

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
            embed = discord.Embed(
                title="🫥 No Companion",
                description="You don't have an NPC companion to release.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.db.release_npc(user_id)
        embed = discord.Embed(
            title="👋 Companion Released",
            description=f"**{npc['name']}** has gone their own way. No refund for recruiting costs.",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Npc(bot))
