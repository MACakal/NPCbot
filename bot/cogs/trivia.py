import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock
from utils import clock


class Trivia(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)
        self._init_state()

    def _init_state(self):
        # channel_id -> timestamp when the next round may start
        self.channel_next_round = {}

    def can_win(self, user_id: int, today: str) -> bool:
        return self.db.get_daily_counter(user_id, "trivia_wins", today) < Config.TRIVIA_MAX_WINS_PER_DAY

    @app_commands.command(name="trivia", description="Answer a trivia question for a cash prize")
    async def trivia(self, interaction: discord.Interaction):
        now = clock.now_ts()
        channel_id = interaction.channel.id
        next_round = self.channel_next_round.get(channel_id, 0)
        if now < next_round:
            embed = discord.Embed(
                title="⏰ Trivia Cooldown",
                description=f"The next round in this channel can start in **{clock.format_duration(next_round - now)}**",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        question = self.db.get_random_trivia_question()
        if question is None:
            embed = discord.Embed(
                title="❌ No Questions Available",
                description="Something went wrong — no trivia questions exist. Contact JinMori07.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.channel_next_round[channel_id] = now + Config.TRIVIA_CHANNEL_COOLDOWN_SECONDS

        embed = discord.Embed(
            title="🧠 Trivia Time!",
            description=question["question"],
            color=discord.Color.blurple()
        )
        footer = f"First correct answer wins ${Config.TRIVIA_REWARD:.2f}! {Config.TRIVIA_TIMEOUT_SECONDS}s to answer."
        if not Config.TRIVIA_STARTER_CAN_ANSWER:
            footer += " The person who started the round can't answer."
        embed.set_footer(text=footer)
        await interaction.response.send_message(embed=embed)

        accepted_answers = {a.strip().lower() for a in question["answer"].split("|")}
        starter_id = interaction.user.id
        today = clock.utc_day(now)

        # Correct answers that don't count still get a short explanation
        # (once per user per round) instead of being silently ignored.
        blocked_correct = set()

        def notify_blocked(message: discord.Message, reason: str):
            if message.author.id in blocked_correct:
                return
            blocked_correct.add(message.author.id)
            asyncio.create_task(self._send_notice(message, reason))

        def check(message: discord.Message) -> bool:
            if (
                message.author.bot
                or message.channel.id != channel_id
                or message.content.strip().lower() not in accepted_answers
            ):
                return False
            if message.author.id == starter_id and not Config.TRIVIA_STARTER_CAN_ANSWER:
                notify_blocked(message, "You started this round, so you can't win it. Let someone else answer!")
                return False
            if not self.can_win(message.author.id, today):
                notify_blocked(
                    message, f"You've already won {Config.TRIVIA_MAX_WINS_PER_DAY} trivia rounds today. Come back tomorrow!"
                )
                return False
            return True

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=Config.TRIVIA_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="⏰ Time's Up",
                description=(
                    f"{'Nobody else' if blocked_correct else 'Nobody'} got it. "
                    f"The answer was **{question['answer'].split('|')[0]}**."
                ),
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed)
            return

        winner_id = reply.author.id
        self.db.get_or_create_user(winner_id)
        self.db.update_user_money(winner_id, Config.TRIVIA_REWARD)
        wins = self.db.add_daily_counter(winner_id, "trivia_wins", today, 1)

        embed = discord.Embed(
            title="🎉 Correct!",
            description=f"{reply.author.mention} got it first and won **${Config.TRIVIA_REWARD:.2f}**!",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Trivia wins today: {wins:.0f}/{Config.TRIVIA_MAX_WINS_PER_DAY}")
        await interaction.followup.send(embed=embed)

        if self.db.unlock_achievement(winner_id, "first_trivia_win"):
            await announce_unlock(interaction, "first_trivia_win")


    @staticmethod
    async def _send_notice(message: discord.Message, text: str):
        try:
            await message.reply(text, mention_author=False, delete_after=15)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Trivia(bot))
