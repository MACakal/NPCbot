import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock
from utils import clock

class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)
        self._init_state()

    def _init_state(self):
        # user_id -> timestamp of the last paid message. In memory only: a
        # restart just lets everyone earn one message early.
        self.last_message_reward = {}

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        if len(message.content.strip()) < Config.MESSAGE_MIN_LENGTH:
            return

        user_id = message.author.id
        now = clock.now_ts()
        last = self.last_message_reward.get(user_id)
        if last is not None and now - last < Config.MESSAGE_REWARD_COOLDOWN_SECONDS:
            return
        self.last_message_reward[user_id] = now

        self.db.get_or_create_user(user_id)
        self.db.update_user_money(user_id, Config.MONEY_PER_MESSAGE)

    @app_commands.command(name="balance", description="Check your balance")
    async def balance(self, interaction: discord.Interaction):
        user_data = self.db.get_or_create_user(interaction.user.id)

        embed = discord.Embed(
            title="💰 Balance",
            description=f"**${user_data['money']:.2f}**",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Requested by {interaction.user.name}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily-claim", description="Claim your daily reward")
    async def daily(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = self.db.get_or_create_user(user_id)

        now = clock.now_ts()
        last_daily = user_data["last_daily"]

        # Check if 24 hours have passed (86400 seconds = 1 day)
        if last_daily is None or now >= last_daily + 86400:
            if last_daily is not None and now - last_daily <= Config.DAILY_STREAK_GRACE_SECONDS:
                streak = self.db.get_daily_streak(user_id) + 1
            else:
                streak = 1
            self.db.set_daily_streak(user_id, streak)
            streak_bonus = min((streak - 1) * Config.DAILY_STREAK_BONUS, Config.DAILY_STREAK_MAX_BONUS)

            bonus = self.db.get_perk_bonus(user_id, "daily_bonus")
            reward = round(Config.DAILY_REWARD * (1 + bonus + streak_bonus), 2)
            self.db.update_user_money(user_id, reward)
            self.db.update_last_daily(user_id, now)

            embed = discord.Embed(
                title="✅ Daily Claimed",
                description=f"You received **${reward:.2f}**",
                color=discord.Color.green()
            )
            days = "day" if streak == 1 else "days"
            embed.add_field(name="Streak", value=f"🔥 {streak} {days} (+{streak_bonus * 100:.0f}%)", inline=True)
            embed.add_field(name="Next Claim", value=f"{clock.format_utc(now + 86400)} UTC", inline=False)
            footer = f"Claim again within {Config.DAILY_STREAK_GRACE_SECONDS // 3600}h to keep your streak"
            if bonus > 0:
                footer += f" • +{bonus * 100:.0f}% companion bonus applied"
            embed.set_footer(text=footer)

            await interaction.response.send_message(embed=embed)
            if self.db.unlock_achievement(user_id, "first_daily"):
                await announce_unlock(interaction, "first_daily")
        else:
            next_claim_ts = last_daily + 86400

            embed = discord.Embed(
                title="⏰ Daily Not Available",
                description=f"Come back in **{clock.format_duration(next_claim_ts - now)}**",
                color=discord.Color.orange()
            )
            embed.add_field(name="Available At", value=f"{clock.format_utc(next_claim_ts)} UTC", inline=False)

            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="work", description="Work a quick job for some quick cash")
    async def work(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = self.db.get_or_create_user(user_id)

        now = clock.now_ts()
        today = clock.utc_day(now)
        last_work = user_data["last_work"]
        shifts_today = self.db.get_daily_counter(user_id, "work_shifts", today)

        if shifts_today >= Config.WORK_MAX_SHIFTS_PER_DAY:
            reset_in = 86400 - now % 86400
            embed = discord.Embed(
                title="😴 Done For The Day",
                description=(
                    f"You've worked all **{Config.WORK_MAX_SHIFTS_PER_DAY}** shifts today. "
                    f"New shifts open in **{clock.format_duration(reset_in)}**"
                ),
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed)
            return

        if not last_work or now >= last_work + Config.WORK_COOLDOWN_SECONDS:
            bonus = self.db.get_perk_bonus(user_id, "work_bonus")
            reward = round(Config.WORK_REWARD * (1 + bonus), 2)
            self.db.update_user_money(user_id, reward)
            self.db.update_last_work(user_id, now)
            shifts_today = self.db.add_daily_counter(user_id, "work_shifts", today, 1)

            embed = discord.Embed(
                title="🛠️ Job Done",
                description=f"You worked a shift and earned **${reward:.2f}**",
                color=discord.Color.green()
            )
            footer = f"Shift {shifts_today:.0f}/{Config.WORK_MAX_SHIFTS_PER_DAY} today"
            if bonus > 0:
                footer += f" • +{bonus * 100:.0f}% companion bonus applied"
            embed.set_footer(text=footer)
            await interaction.response.send_message(embed=embed)
            if self.db.unlock_achievement(user_id, "first_work"):
                await announce_unlock(interaction, "first_work")
        else:
            time_left = (last_work + Config.WORK_COOLDOWN_SECONDS) - now

            embed = discord.Embed(
                title="⏰ Still On Break",
                description=f"You can work again in **{clock.format_duration(time_left)}**",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="give", description="Give money to another user")
    @app_commands.describe(member="User to give money to", amount="Amount to give")
    async def give(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[float, 0.01, None]):
        amount = round(amount, 2)
        sender_id = interaction.user.id
        today = clock.utc_day(clock.now_ts())

        error = None
        if amount <= 0:
            error = ("❌ Invalid Amount", "Amount must be positive")
        elif member.bot or member.id == sender_id:
            error = ("❌ Invalid Recipient", "You can't give money to yourself or to a bot")
        else:
            sent_today = self.db.get_daily_counter(sender_id, "money_given", today)
            if sent_today + amount > Config.GIVE_DAILY_LIMIT:
                left = max(Config.GIVE_DAILY_LIMIT - sent_today, 0)
                error = ("❌ Daily Limit Reached",
                         f"You can send **${left:.2f}** more today (limit ${Config.GIVE_DAILY_LIMIT:,.0f}/day)")
        if error:
            embed = discord.Embed(title=error[0], description=error[1], color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        fee = round(amount * Config.GIVE_TAX_PERCENT, 2)
        if self.db.transfer_money(sender_id, member.id, amount, fee):
            self.db.add_daily_counter(sender_id, "money_given", today, amount)
            embed = discord.Embed(
                title="💸 Transfer Complete",
                description=f"Sent **${amount - fee:.2f}** to {member.mention}",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"${fee:.2f} transfer tax ({Config.GIVE_TAX_PERCENT * 100:.0f}%)")
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description="You don't have enough money",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="leaderboard", description="View the richest users")
    async def leaderboard(self, interaction: discord.Interaction):
        top_users = self.db.get_leaderboard(10)
        
        leaderboard_text = ""
        for i, entry in enumerate(top_users, start=1):
            try:
                user = await self.bot.fetch_user(entry["id"])
                username = user.name
            except:
                username = f"User ID: {entry['id']}"
            
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"**{i}.**"
            leaderboard_text += (
                f"{medal} {username} — **${entry['net_worth']:.2f}** "
                f"(wallet ${entry['wallet']:.2f} · bank ${entry['bank']:.2f})\n"
            )

        embed = discord.Embed(
            title="🏆 Leaderboard",
            description=leaderboard_text,
            color=discord.Color.gold()
        )
        embed.set_footer(text="Ranked by wallet + bank")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="pool", description="View the pool balance")
    async def pool(self, interaction: discord.Interaction):
        pool_data = self.db.get_pool()
        
        embed = discord.Embed(
            title="🏦 Pool Balance",
            description=f"**${pool_data['money']:.2f}**",
            color=discord.Color.blue()
        )
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="bank-balance", description="Shows bank account balance")
    async def bankBalance(self, interaction: discord.Interaction) -> None:
        self.db.apply_interest(user_id=interaction.user.id)
        money = self.db.get_bank_balance(user_id=interaction.user.id)
        
        embed = discord.Embed(
            title="🏦 Bank Balance",
            description=f"**${money:.2f}**",
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Requested by {interaction.user.name}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="deposit", description="Deposit money to your bank account")
    @app_commands.describe(amount="Amount to deposit")
    async def deposit(self, interaction: discord.Interaction, amount: app_commands.Range[float, 0.01, None]) -> None:
        amount = round(amount, 2)
        self.db.apply_interest(user_id=interaction.user.id)

        if self.db.deposit_to_bank(user_id=interaction.user.id, amount=amount):
            embed = discord.Embed(
                title="✅ Deposit Successful",
                description=f"Deposited **${amount:.2f}** to your bank account",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"You don't have ${amount:.2f} to deposit",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="withdraw", description="Withdrawing money from your bank account")
    @app_commands.describe(amount="Amount to withdraw")
    async def withdraw(self, interaction: discord.Interaction, amount: app_commands.Range[float, 0.01, None]) -> None:
        amount = round(amount, 2)
        self.db.apply_interest(user_id=interaction.user.id)

        if self.db.withdraw_from_bank(user_id=interaction.user.id, amount=amount):
            embed = discord.Embed(
                title="✅ Withdrawal Successful",
                description=f"Withdrew **${amount:.2f}** from your bank account",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"You don't have ${amount:.2f} in your bank account",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="bank-stats", description="See your banking stats")
    async def bankStats(self, interaction: discord.Interaction):
        self.db.apply_interest(user_id=interaction.user.id)
        bank_account = self.db.get_bank_account(user_id=interaction.user.id)
        interest = self.db.return_interest_rate(interaction.user.id)
        max_daily = self.db.return_max_daily_interest(interaction.user.id)

        embed = discord.Embed(
            title="📊 Bank Statistics",
            color=discord.Color.blue()
        )
        embed.add_field(name="Balance", value=f"${bank_account['money']:.2f}", inline=True)
        embed.add_field(name="Total Deposited", value=f"${bank_account['total_deposited']:.2f}", inline=True)
        embed.add_field(name="Total Withdrawn", value=f"${bank_account['total_withdrawn']:.2f}", inline=True)
        
        total_interest = bank_account["total_interest_earned"] if bank_account["total_interest_earned"] is not None else 0
        embed.add_field(name="Total Interest Earned", value=f"${total_interest:.2f}", inline=True)
        embed.add_field(name="Current daily rate", value=f"{interest * 100:.3f}%", inline=True)
        embed.add_field(name="Max interest per day", value=f"${max_daily:.2f}", inline=True)
        
        embed.set_footer(text=f"Requested by {interaction.user.name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))