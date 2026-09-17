import discord
from discord import app_commands
from discord.ext import commands
from database.manager import DatabaseManager, CONSUMABLE_EFFECTS
from config import Config
from utils.achievements import announce_unlock
from utils import clock

# Consumables that are activated with /use (the Lockpick is used
# automatically by /rob instead).
USABLE_EFFECTS = {"rob_protection_consumable", "work_cooldown_reset"}


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
        embed.set_footer(text="Use /buy <item> to purchase and /use <item> to activate consumables")

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

        status = self.db.purchase_item(user_id, shop_item["id"])
        if status == "ok":
            embed = discord.Embed(
                title="✅ Purchase Complete",
                description=f"You bought **{shop_item['name']}** for **${shop_item['price']:.2f}**",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            if self.db.unlock_achievement(user_id, "first_shop_purchase"):
                await announce_unlock(interaction, "first_shop_purchase")
            return

        if status == "already_owned":
            title = "❌ Already Owned"
            description = f"You already have **{shop_item['name']}**. It's permanent and doesn't stack."
        else:
            title = "❌ Insufficient Funds"
            description = f"You don't have **${shop_item['price']:.2f}** for {shop_item['name']}"
        embed = discord.Embed(title=title, description=description, color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @buy.autocomplete("item")
    async def buy_autocomplete(self, interaction: discord.Interaction, current: str):
        items = self.db.get_shop_items()
        return [
            app_commands.Choice(name=item["name"], value=item["name"])
            for item in items
            if current.lower() in item["name"].lower()
        ][:25]

    @app_commands.command(name="use", description="Activate a consumable item you own")
    @app_commands.describe(item="Item to use")
    async def use(self, interaction: discord.Interaction, item: str):
        user_id = interaction.user.id
        shop_item = self.db.get_item_by_name(item)
        owned = {i["id"]: i["quantity"] for i in self.db.get_user_inventory(user_id)}

        if shop_item is None or shop_item["effect_type"] not in USABLE_EFFECTS:
            await self._fail(interaction, "❌ Can't Use That", f"**{item}** isn't an item you can activate.")
            return
        if owned.get(shop_item["id"], 0) <= 0:
            await self._fail(interaction, "❌ Not In Inventory", f"You don't have a **{shop_item['name']}**. Check `/shop`.")
            return

        now = clock.now_ts()
        effect = shop_item["effect_type"]
        if effect == "work_cooldown_reset":
            user_data = self.db.get_or_create_user(user_id)
            last_work = user_data["last_work"]
            if not last_work or now >= last_work + Config.WORK_COOLDOWN_SECONDS:
                await self._fail(interaction, "❌ Not Needed", "You're not on a break — just use `/work`.")
                return
            self.db.consume_item(user_id, effect)
            self.db.update_last_work(user_id, 0)
            message = "Break skipped! You can `/work` right now (the daily shift limit still applies)."
        else:
            self.db.consume_item(user_id, effect)
            until = now + int(shop_item["effect_value"])
            self.db.extend_timer(user_id, "rob_protection", until)
            left = self.db.timer_remaining(user_id, "rob_protection", now)
            message = f"Nobody can rob you for the next **{clock.format_duration(left)}**."

        embed = discord.Embed(
            title=f"✨ Used {shop_item['name']}",
            description=message,
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @use.autocomplete("item")
    async def use_autocomplete(self, interaction: discord.Interaction, current: str):
        owned = self.db.get_user_inventory(interaction.user.id)
        return [
            app_commands.Choice(name=f"{item['name']} (x{item['quantity']})", value=item["name"])
            for item in owned
            if item["effect_type"] in USABLE_EFFECTS and current.lower() in item["name"].lower()
        ][:25]

    async def _fail(self, interaction: discord.Interaction, title: str, description: str):
        embed = discord.Embed(title=title, description=description, color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
            qty_label = f" x{item['quantity']}" if item["quantity"] > 1 or item["effect_type"] in CONSUMABLE_EFFECTS else ""
            embed.add_field(
                name=f"{item['name']}{qty_label}",
                value=item["description"],
                inline=False
            )

        now = clock.now_ts()
        protected = self.db.timer_remaining(interaction.user.id, "rob_protection", now)
        if protected > 0:
            embed.set_footer(text=f"🛡️ Rob protection active for {clock.format_duration(protected)}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
