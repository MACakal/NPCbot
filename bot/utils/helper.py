import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from database.manager import DatabaseManager
from config import Config

class Helper:

    @staticmethod
    def is_owner(owner_id: int):
        async def predicate(interaction: discord.Interaction):
            return interaction.user.id == owner_id
        return app_commands.check(predicate)