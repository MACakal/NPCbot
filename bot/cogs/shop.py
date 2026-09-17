import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock


class Shop(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)

    @app_commands.command(name="shop", description="View items available for purchase")
    async def shop(self, interaction: discord.Interaction):
        items = self.db.get_shop_items()

        embed = discord.Embed(title="🛒 Shop", color=discord.Color.blurple())
        for item in items:
            embed.add_field(
                name=f"{item['name']} — ${item['price']:.2f}",
                value=item["description"],
                inline=False
            )
        embed.set_footer(text="Use /buy <item> to purchase")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy an item from the shop")
    @app_commands.describe(item="Item to purchase")
    async def buy(self, interaction: discord.Interaction, item: str):
        user_id = interaction.user.id
        self.db.get_or_create_user(user_id)

        shop_item = self.db.get_item_by_name(item)
        if shop_item is None:
            embed = discord.Embed(
                title="❌ Item Not Found",
                description=f"No item named **{item}** in the shop. Check `/shop`.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if self.db.purchase_item(user_id, shop_item["id"]):
            embed = discord.Embed(
                title="✅ Purchase Complete",
                description=f"You bought **{shop_item['name']}** for **${shop_item['price']:.2f}**",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            if self.db.unlock_achievement(user_id, "first_shop_purchase"):
                await announce_unlock(interaction, "first_shop_purchase")
        else:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"You don't have **${shop_item['price']:.2f}** for {shop_item['name']}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @buy.autocomplete("item")
    async def buy_autocomplete(self, interaction: discord.Interaction, current: str):
        items = self.db.get_shop_items()
        return [
            app_commands.Choice(name=item["name"], value=item["name"])
            for item in items
            if current.lower() in item["name"].lower()
        ][:25]

    @app_commands.command(name="inventory", description="View your owned items")
    async def inventory(self, interaction: discord.Interaction):
        owned = self.db.get_user_inventory(interaction.user.id)

        if not owned:
            embed = discord.Embed(
                title="🎒 Inventory",
                description="You don't own any items yet. Check `/shop`.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(title="🎒 Inventory", color=discord.Color.blurple())
        for item in owned:
            qty_label = f" x{item['quantity']}" if item["quantity"] > 1 else ""
            embed.add_field(
                name=f"{item['name']}{qty_label}",
                value=item["description"],
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
