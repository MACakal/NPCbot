import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from database.manager import DatabaseManager
from config import Config

class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)
        self.roulette_outcomes = ["red"] * 18 + ["black"] * 18 + ["green"] * 3
    
    @app_commands.command(name="coin-flip", description="Double or nothing!")
    @app_commands.describe(amount="Amount to bet")
    async def coin_flip(self, interaction: discord.Interaction, amount: float):
        if amount <= 0:
            embed = discord.Embed(
                title="❌ Invalid Amount",
                description="Amount must be greater than 0",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        user_id = interaction.user.id
        user_data = self.db.get_or_create_user(user_id)
        
        if amount > user_data["money"]:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"You don't have ${amount:.2f} to bet",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        result = random.choice([True, False])
        
        if result:
            self.db.update_user_money(user_id, amount)
            embed = discord.Embed(
                title="🪙 Coin Flip - Win!",
                description=f"You won **${amount:.2f}**",
                color=discord.Color.green()
            )
            embed.set_footer(text="Heads!")
        else:
            self.db.update_user_money(user_id, -amount)
            self.db.update_pool_money(amount)
            embed = discord.Embed(
                title="🪙 Coin Flip - Loss",
                description=f"You lost **${amount:.2f}**",
                color=discord.Color.red()
            )
            embed.set_footer(text="Tails!")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="roulette-color", description="Bet on red, black, or green")
    @app_commands.choices(color=[
        app_commands.Choice(name="Red", value="red"),
        app_commands.Choice(name="Black", value="black"),
        app_commands.Choice(name="Green", value="green")
    ])
    async def roulette_color(
        self,
        interaction: discord.Interaction,
        color: app_commands.Choice[str],
        amount: int
    ):
        if amount <= 0:
            embed = discord.Embed(
                title="❌ Invalid Amount",
                description="Amount must be greater than 0",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        user_id = interaction.user.id
        user_data = self.db.get_or_create_user(user_id)
        
        if amount > user_data["money"]:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"You don't have ${amount} to bet",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        outcome = random.choice(self.roulette_outcomes)
        
        # Get color emoji
        color_emoji = "🔴" if outcome == "red" else "⚫" if outcome == "black" else "🟢"
        
        if outcome == color.value:
            if outcome == "green":
                winnings = amount * 10
                self.db.update_user_money(user_id, winnings)
                embed = discord.Embed(
                    title="🎰 Roulette - Jackpot!",
                    description=f"**{color_emoji} GREEN!**\n\nYou won **${winnings}**",
                    color=discord.Color.green()
                )
            else:
                self.db.update_user_money(user_id, amount)
                embed = discord.Embed(
                    title="🎰 Roulette - Win!",
                    description=f"**{color_emoji} {outcome.upper()}!**\n\nYou won **${amount}**",
                    color=discord.Color.green()
                )
        else:
            self.db.update_user_money(user_id, -amount)
            self.db.update_pool_money(amount)
            embed = discord.Embed(
                title="🎰 Roulette - Loss",
                description=f"**{color_emoji} {outcome.upper()}**\n\nYou lost **${amount}**",
                color=discord.Color.red()
            )
        
        await interaction.response.send_message(embed=embed)
    
    # @app_commands.command(name="jackpot", description="Enter the jackpot")
    # async def jackpot(self, interaction: discord.Interaction):
    #     user_id = interaction.user.id
    #     user_data = self.db.get_or_create_user(user_id)
    #     pool_data = self.db.get_pool()
        
    #     price_entry = pool_data["money"] * Config.JACKPOT_ENTRY_PERCENT
        
    #     if user_data["money"] < price_entry:
    #         embed = discord.Embed(
    #             title="❌ Insufficient Funds",
    #             description=f"Entry costs **${price_entry:.2f}**",
    #             color=discord.Color.red()
    #         )
    #         await interaction.response.send_message(embed=embed)
    #         return
        
    #     embed = discord.Embed(
    #         title="🎰 Jackpot Entry",
    #         description=f"{interaction.user.mention}, confirm your entry:",
    #         color=discord.Color.gold()
    #     )
    #     embed.add_field(name="Entry Cost", value=f"${price_entry:.2f}", inline=True)
    #     embed.add_field(name="Win Chance", value=f"{int(Config.JACKPOT_WIN_CHANCE * 100)}%", inline=True)
    #     embed.set_footer(text="Type 'yes' to confirm or 'no' to cancel (30s timeout)")
        
    #     await interaction.response.send_message(embed=embed)
        
    #     def check(m):
    #         return (m.author.id == user_id and 
    #                 m.channel == interaction.channel and 
    #                 m.content.lower() in ["yes", "no"])
        
    #     try:
    #         reply = await self.bot.wait_for("message", check=check, timeout=30)
    #     except asyncio.TimeoutError:
    #         embed = discord.Embed(
    #             title="⏰ Timeout",
    #             description="Jackpot entry canceled",
    #             color=discord.Color.orange()
    #         )
    #         await interaction.followup.send(embed=embed, ephemeral=True)
    #         return
        
    #     if reply.content.lower() == "no":
    #         embed = discord.Embed(
    #             title="❌ Canceled",
    #             description="Jackpot entry canceled",
    #             color=discord.Color.orange()
    #         )
    #         await interaction.followup.send(embed=embed, ephemeral=True)
    #         return
        
    #     self.db.update_user_money(user_id, -price_entry)
        
    #     if random.random() <= Config.JACKPOT_WIN_CHANCE:
    #         jackpot_amount = pool_data["money"] * Config.JACKPOT_ENTRY_PERCENT
    #         self.db.update_user_money(user_id, jackpot_amount)
    #         self.db.update_pool_money(-jackpot_amount)
            
    #         embed = discord.Embed(
    #             title="🎉 JACKPOT WIN!",
    #             description=f"You won **${jackpot_amount:.2f}**",
    #             color=discord.Color.gold()
    #         )
    #         await interaction.followup.send(embed=embed)
    #     else:
    #         self.db.update_pool_money(price_entry)
            
    #         embed = discord.Embed(
    #             title="💔 Jackpot Loss",
    #             description=f"You lost **${price_entry:.2f}**\nBetter luck next time!",
    #             color=discord.Color.red()
    #         )
    #         await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Games(bot))