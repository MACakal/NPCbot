import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock

class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        
        user_id = message.author.id
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
        
        now = int(datetime.utcnow().timestamp())
        last_daily = user_data["last_daily"]
        
        # Check if 24 hours have passed (86400 seconds = 1 day)
        if last_daily is None or now >= last_daily + 86400:
            bonus = self.db.get_perk_bonus(user_id, "daily_bonus")
            reward = Config.DAILY_REWARD * (1 + bonus)
            self.db.update_user_money(user_id, reward)
            self.db.update_last_daily(user_id, now)

            next_claim = datetime.fromtimestamp(now + 86400).strftime('%Y-%m-%d %H:%M:%S')

            embed = discord.Embed(
                title="✅ Daily Claimed",
                description=f"You received **${reward:.2f}**",
                color=discord.Color.green()
            )
            embed.add_field(name="Next Claim", value=f"{next_claim} UTC", inline=False)
            if bonus > 0:
                embed.set_footer(text=f"+{bonus * 100:.0f}% companion bonus applied")

            await interaction.response.send_message(embed=embed)
            if self.db.unlock_achievement(user_id, "first_daily"):
                await announce_unlock(interaction, "first_daily")
        else:
            next_claim_ts = last_daily + 86400
            next_claim = datetime.fromtimestamp(next_claim_ts).strftime('%Y-%m-%d %H:%M:%S')
            time_left = next_claim_ts - now
            hours = time_left // 3600
            minutes = (time_left % 3600) // 60
            
            embed = discord.Embed(
                title="⏰ Daily Not Available",
                description=f"Come back in **{hours}h {minutes}m**",
                color=discord.Color.orange()
            )
            embed.add_field(name="Available At", value=f"{next_claim} UTC", inline=False)
            
            await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="work", description="Work a quick job for some quick cash")
    async def work(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = self.db.get_or_create_user(user_id)

        now = int(datetime.utcnow().timestamp())
        last_work = user_data["last_work"]

        if last_work is None or now >= last_work + Config.WORK_COOLDOWN_SECONDS:
            bonus = self.db.get_perk_bonus(user_id, "work_bonus")
            reward = Config.WORK_REWARD * (1 + bonus)
            self.db.update_user_money(user_id, reward)
            self.db.update_last_work(user_id, now)

            embed = discord.Embed(
                title="🛠️ Job Done",
                description=f"You worked a shift and earned **${reward:.2f}**",
                color=discord.Color.green()
            )
            if bonus > 0:
                embed.set_footer(text=f"+{bonus * 100:.0f}% companion bonus applied")
            await interaction.response.send_message(embed=embed)
            if self.db.unlock_achievement(user_id, "first_work"):
                await announce_unlock(interaction, "first_work")
        else:
            time_left = (last_work + Config.WORK_COOLDOWN_SECONDS) - now
            minutes = time_left // 60
            seconds = time_left % 60

            embed = discord.Embed(
                title="⏰ Still On Break",
                description=f"You can work again in **{minutes}m {seconds}s**",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="give", description="Give money to another user")
    @app_commands.describe(member="User to give money to", amount="Amount to give")
    async def give(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[float, 0.01, None]):
        amount = round(amount, 2)

        if self.db.transfer_money(interaction.user.id, member.id, amount):
            embed = discord.Embed(
                title="💸 Transfer Complete",
                description=f"Sent **${amount:.2f}** to {member.mention}",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description="You don't have enough money",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
    
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
            leaderboard_text += f"{medal} {username} — ${entry['money']:.2f}\n"
        
        embed = discord.Embed(
            title="🏆 Leaderboard",
            description=leaderboard_text,
            color=discord.Color.gold()
        )
        
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