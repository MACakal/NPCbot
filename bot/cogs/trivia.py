import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock


class Trivia(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)

    @app_commands.command(name="trivia", description="Answer a trivia question for a shot at the pool")
    async def trivia(self, interaction: discord.Interaction):
        question = self.db.get_random_trivia_question()
        if question is None:
            embed = discord.Embed(
                title="❌ No Questions Available",
                description="Something went wrong — no trivia questions exist. Contact JinMori07.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🧠 Trivia Time!",
            description=question["question"],
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"First correct answer wins ${Config.TRIVIA_REWARD:.2f} from the pool! {Config.TRIVIA_TIMEOUT_SECONDS}s to answer.")
        await interaction.response.send_message(embed=embed)

        accepted_answers = {a.strip().lower() for a in question["answer"].split("|")}

        def check(message: discord.Message) -> bool:
            return (
                not message.author.bot
                and message.channel == interaction.channel
                and message.content.strip().lower() in accepted_answers
            )

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=Config.TRIVIA_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="⏰ Time's Up",
                description=f"Nobody got it. The answer was **{question['answer'].split('|')[0]}**.",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed)
            return

        winner_id = reply.author.id
        self.db.get_or_create_user(winner_id)
        reward = self.db.award_trivia_prize(winner_id, Config.TRIVIA_REWARD)

        embed = discord.Embed(
            title="🎉 Correct!",
            description=f"{reply.author.mention} got it first and won **${reward:.2f}** from the pool!",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed)

        if self.db.unlock_achievement(winner_id, "first_trivia_win"):
            await announce_unlock(interaction, "first_trivia_win")


async def setup(bot: commands.Bot):
    await bot.add_cog(Trivia(bot))
