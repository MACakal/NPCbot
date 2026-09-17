import discord
from discord.ext import commands
from config import Config
import asyncio

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=Config.COMMAND_PREFIX, intents=intents)
    
    async def setup_hook(self):
        """Load all cogs before syncing commands."""
        cogs = ['cogs.admin', 'cogs.economy', 'cogs.games', 'cogs.utilities', 'cogs.crime', 'cogs.npc', 'cogs.shop', 'cogs.achievements', 'cogs.trivia']
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                print(f'Loaded {cog}')
            except Exception as e:
                print(f'Failed to load {cog}: {e}')
        
        try:
            synced = await self.tree.sync()
            print(f'Synced {len(synced)} command(s)')
        except Exception as e:
            print(f'Failed to sync commands: {e}')
    
    async def on_ready(self):
        print(f'Logged in as {self.user}')

async def main():
    bot = MyBot()
    
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError
    ):
        if isinstance(error, discord.app_commands.CommandInvokeError):
            await interaction.response.send_message(
                f"An error occurred: {str(error)}",
                ephemeral=True
            )
            print(f"Error: {error}")
        else:
            await interaction.response.send_message(
                "Something went wrong!",
                ephemeral=True
            )
    
    async with bot:
        await bot.start(Config.TOKEN)

if __name__ == '__main__':
    asyncio.run(main())