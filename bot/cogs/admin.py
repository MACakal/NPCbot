import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from database.manager import DatabaseManager
from config import Config
from discord import User
from utils.helper import Helper

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)
        self.owner_id = Config.OWNER_ID

    @app_commands.command(name="shutdown", description="Shut down the bot")
    @app_commands.default_permissions(administrator=True)
    @Helper.is_owner(Config.OWNER_ID)
    async def shutdown(self, interaction: discord.Interaction):
        await interaction.response.send_message("Shutting down…", ephemeral=True)
        await self.bot.close()

    @app_commands.command(
        name="interest-rate-person", 
        description="See the interest somebody is getting"
    )
    @app_commands.default_permissions(administrator=True)
    @Helper.is_owner(Config.OWNER_ID)
    @app_commands.describe(target="The user whose interest rate you want to check")
    async def interest_rate(self, interaction: discord.Interaction, target: User):
        user_id = target.id
        interest = self.db.return_interest_rate(user_id=user_id)
        await interaction.response.send_message(
            f"{target.mention} currently earns {interest*100:.3f}% interest per day."
            , ephemeral=True
        )
    
async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))