import discord
from discord import app_commands
from discord.ext import commands
import os
from config import Config

class Utilities(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="convert-weight", description="Convert kg to lb and vice versa")
    @app_commands.describe(number="The number to convert", unit="Unit to convert from")
    @app_commands.choices(unit=[
        app_commands.Choice(name="Kilograms (kg)", value="kg"),
        app_commands.Choice(name="Pounds (lb)", value="lb")
    ])
    async def convert_weight(
        self,
        interaction: discord.Interaction,
        number: float,
        unit: str
    ):
        if unit.lower() == "lb":
            result = number * 0.453592
            embed = discord.Embed(
                title="⚖️ Weight Conversion",
                description=f"**{number} lb** = **{result:.2f} kg**",
                color=discord.Color.blue()
            )
        elif unit.lower() == "kg":
            result = number / 0.453592
            embed = discord.Embed(
                title="⚖️ Weight Conversion",
                description=f"**{number} kg** = **{result:.2f} lb**",
                color=discord.Color.blue()
            )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="convert-height", description="Convert ft to m and vice versa")
    @app_commands.describe(number="The length to convert", unit="Unit to convert from")
    @app_commands.choices(unit=[
        app_commands.Choice(name="Feet (ft)", value="ft"),
        app_commands.Choice(name="Meter (m)", value="m")
    ])
    async def convert_height(
        self,
        interaction: discord.Interaction,
        unit: str,
        number: str
    ):
        embed = discord.Embed(
            title="📏 Height Conversion",
            color=discord.Color.blue()
        )
        
        if unit == "m":
            meters = float(number)
            total_feet = meters * 3.28084
            feet = int(total_feet)
            inches = (total_feet - feet) * 12
            
            embed.description = f"**{number} m**"
            embed.add_field(name="Decimal Feet", value=f"{total_feet:.2f} ft", inline=False)
            embed.add_field(name="Feet & Inches", value=f"{feet}' {inches:.2f}\"", inline=False)
        elif unit == "ft":
            parts = number.replace("'", " ").replace('"', '').split()
            ft = int(parts[0])
            inch = int(parts[1]) if len(parts) > 1 else 0
            
            total_feet = ft + (inch / 12)
            meters = total_feet * 0.3048
            
            embed.description = f"**{ft}' {inch}\"**"
            embed.add_field(name="Meters", value=f"{meters:.2f} m", inline=False)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="1rm-calculator", description="Calculate your 1 rep max")
    @app_commands.describe(weight="The weight lifted", reps="Number of reps")
    async def one_rm(self, interaction: discord.Interaction, weight: float, reps: int):
        one_rep_max = weight * (1 + 0.0333 * reps)
        
        embed = discord.Embed(
            title="💪 1RM Calculator",
            color=discord.Color.green()
        )
        embed.add_field(name="Weight Lifted", value=f"{weight} kg/lb", inline=True)
        embed.add_field(name="Reps", value=f"{reps}", inline=True)
        embed.add_field(name="Estimated 1RM", value=f"**{one_rep_max:.2f} kg/lb**", inline=False)
        embed.set_footer(text="Using Epley Formula")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="suggestion", description="Submit a suggestion")
    @app_commands.describe(suggestion_text="Your suggestion")
    async def suggestion(self, interaction: discord.Interaction, suggestion_text: str):
        os.makedirs(Config.SUGGESTIONS_PATH, exist_ok=True)
        filepath = f"{Config.SUGGESTIONS_PATH}/{interaction.user.name}.txt"
        
        with open(filepath, "a") as f:
            f.write(f"{suggestion_text}\n\n")
        
        embed = discord.Embed(
            title="✅ Suggestion Submitted",
            description="Thank you for your feedback!",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Utilities(bot))