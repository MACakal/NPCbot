import discord
from discord import app_commands
from discord.ext import commands
import random
from database.manager import DatabaseManager
from config import Config
from utils.achievements import announce_unlock
from utils import clock

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
ROULETTE_OUTCOMES = ["red"] * 18 + ["black"] * 18 + ["green"] * 3


def create_deck():
    deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck


def card_rank(card: str) -> str:
    return card[:-1]


def hand_value(hand) -> int:
    value = 0
    aces = 0
    for card in hand:
        rank = card_rank(card)
        if rank == "A":
            aces += 1
            value += 11
        elif rank in ("J", "Q", "K"):
            value += 10
        else:
            value += int(rank)
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


def format_hand(hand, hide_second: bool = False) -> str:
    if hide_second and len(hand) > 1:
        return " ".join(hand[:1]) + " ❓"
    return " ".join(hand)


class BlackjackView(discord.ui.View):
    def __init__(self, cog, user_id: int, amount: float, deck, player_hand, dealer_hand):
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = user_id
        self.amount = amount
        self.deck = deck
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.message: discord.Message = None
        self.finished = False
        self.profit = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return False
        return True

    def build_embed(self, reveal_dealer: bool = False, result_text: str = None, color=None) -> discord.Embed:
        embed = discord.Embed(title="🃏 Blackjack", color=color or discord.Color.blurple())
        embed.add_field(
            name=f"Your Hand ({hand_value(self.player_hand)})",
            value=format_hand(self.player_hand),
            inline=False
        )
        dealer_label = str(hand_value(self.dealer_hand)) if reveal_dealer else "?"
        embed.add_field(
            name=f"Dealer's Hand ({dealer_label})",
            value=format_hand(self.dealer_hand, hide_second=not reveal_dealer),
            inline=False
        )
        embed.add_field(name="Bet", value=f"${self.amount:.2f}", inline=True)
        if result_text:
            embed.description = result_text
        return embed

    def dealer_play(self):
        while hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())

    def determine_outcome(self) -> str:
        player_value = hand_value(self.player_hand)
        dealer_value = hand_value(self.dealer_hand)
        if player_value > 21:
            return "dealer_win"
        if dealer_value > 21 or player_value > dealer_value:
            return "player_win"
        if player_value < dealer_value:
            return "dealer_win"
        return "push"

    def settle(self, outcome: str) -> discord.Embed:
        """Apply the payout for a finished game and return the result embed."""
        self.finished = True
        for child in self.children:
            child.disabled = True

        db = self.cog.db
        if outcome == "player_blackjack":
            db.update_user_money(self.user_id, self.amount * 2.5)
            self.profit = self.amount * 1.5
            result_text = f"🂡 **Blackjack!** You win **${self.amount * 1.5:.2f}**"
            color = discord.Color.gold()
        elif outcome == "player_win":
            db.update_user_money(self.user_id, self.amount * 2)
            self.profit = self.amount
            result_text = f"🎉 **You win ${self.amount:.2f}!**"
            color = discord.Color.green()
        elif outcome == "push":
            db.update_user_money(self.user_id, self.amount)
            self.profit = 0
            result_text = "🤝 **Push.** Your bet was returned."
            color = discord.Color.light_grey()
        else:
            db.record_gambling_loss(self.amount)
            self.profit = 0
            result_text = f"💔 **You lost ${self.amount:.2f}.**"
            color = discord.Color.red()

        return self.build_embed(reveal_dealer=True, result_text=result_text, color=color)

    async def finish(self, interaction: discord.Interaction, outcome: str):
        embed = self.settle(outcome)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()
        await self.cog.check_gamble_achievements(interaction, self.amount, self.profit)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player_hand.append(self.deck.pop())
        self.double_down.disabled = True
        if hand_value(self.player_hand) > 21:
            await self.finish(interaction, "dealer_win")
            return
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.dealer_play()
        await self.finish(interaction, self.determine_outcome())

    @discord.ui.button(label="Double Down", style=discord.ButtonStyle.success)
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.player_hand) != 2:
            await interaction.response.send_message("You can only double down on your first two cards.", ephemeral=True)
            return
        if not self.cog.db.try_debit_user(self.user_id, self.amount):
            await interaction.response.send_message(
                f"You need another **${self.amount:.2f}** to double down.", ephemeral=True
            )
            return
        self.amount *= 2
        self.player_hand.append(self.deck.pop())
        if hand_value(self.player_hand) <= 21:
            self.dealer_play()
        await self.finish(interaction, self.determine_outcome())

    async def on_timeout(self):
        if self.finished:
            return
        self.dealer_play()
        embed = self.settle(self.determine_outcome())
        embed.description = f"⏰ Timed out and auto-stood.\n{embed.description or ''}"
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass


class JackpotView(discord.ui.View):
    def __init__(self, cog, user_id: int, ticket_price: float):
        super().__init__(timeout=30)
        self.cog = cog
        self.user_id = user_id
        self.ticket_price = ticket_price
        self.message: discord.Message = None
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your jackpot entry!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Buy Ticket", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = self.cog.db
        now = clock.now_ts()

        # Several prompts may be open at once, so the cooldown and the price
        # are both re-checked at purchase time.
        wait = db.timer_remaining(self.user_id, "jackpot_cooldown", now)
        if wait > 0:
            await interaction.response.send_message(
                f"You can buy another ticket in **{clock.format_duration(wait)}**.", ephemeral=True
            )
            return

        self.ticket_price = self.cog.ticket_price_for(self.user_id)
        # Balance is re-checked here, at purchase time, not when the prompt
        # was posted — the wallet may have been spent since.
        if not db.try_debit_user(self.user_id, self.ticket_price):
            await interaction.response.send_message(
                f"You no longer have **${self.ticket_price:.2f}** for a ticket.", ephemeral=True
            )
            return

        self.resolved = True
        for child in self.children:
            child.disabled = True

        db.set_timer(self.user_id, "jackpot_cooldown", now + Config.JACKPOT_COOLDOWN_SECONDS)
        db.update_pool_money(self.ticket_price)

        won = random.random() <= Config.JACKPOT_WIN_CHANCE
        if won:
            self.won_amount = db.pay_jackpot(self.user_id)
            embed = discord.Embed(
                title="🎆 JACKPOT WON!",
                description=(
                    f"You hit the jackpot and won **${self.won_amount:.2f}** "
                    f"({Config.JACKPOT_PAYOUT_PERCENT * 100:.0f}% of the pool)!"
                ),
                color=discord.Color.gold()
            )
        else:
            self.won_amount = 0
            embed = discord.Embed(
                title="💨 No Luck This Time",
                description=f"Your **${self.ticket_price:.2f}** ticket added to the pool. Better luck next time!",
                color=discord.Color.red()
            )
        embed.add_field(name="Pool Now", value=f"${db.get_pool()['money']:.2f}", inline=True)
        embed.add_field(name="Odds", value=f"{Config.JACKPOT_WIN_CHANCE * 100:.0f}%", inline=True)

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

        await self.cog.check_gamble_achievements(interaction, self.ticket_price, self.won_amount - self.ticket_price)
        if won and db.unlock_achievement(self.user_id, "jackpot_winner"):
            await announce_unlock(interaction, "jackpot_winner")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.resolved = True
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="❌ Canceled",
            description="Jackpot entry canceled.",
            color=discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        if self.resolved:
            return
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseManager(Config.DATABASE_PATH)

    def ticket_price_for(self, user_id: int) -> float:
        return self.db.jackpot_ticket_price()

    async def check_gamble_achievements(self, interaction: discord.Interaction, bet: float, profit: float):
        """Shared achievement check for any single gamble action (bet placed / profit won)."""
        to_check = []
        if bet >= Config.HIGH_ROLLER_BET_THRESHOLD:
            to_check.append("high_roller")
        if profit >= Config.BIG_WINNER_WIN_THRESHOLD:
            to_check.append("big_winner")
        for achievement_id in to_check:
            if self.db.unlock_achievement(interaction.user.id, achievement_id):
                await announce_unlock(interaction, achievement_id)

    async def reject_bet(self, interaction: discord.Interaction, amount: float) -> bool:
        """Sends an error and returns True if the bet is out of range or
        unaffordable. Discord enforces the range too, but only once the
        command tree has been re-synced."""
        if amount < 1 or amount > Config.MAX_BET:
            description = f"Bets must be between $1 and ${Config.MAX_BET:,.0f}"
            title = "❌ Invalid Amount"
        elif amount > self.db.get_or_create_user(interaction.user.id)["money"]:
            description = f"You don't have ${amount:.2f} to bet"
            title = "❌ Insufficient Funds"
        else:
            return False
        embed = discord.Embed(title=title, description=description, color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return True

    @app_commands.command(name="coin-flip", description="Double or nothing!")
    @app_commands.describe(amount="Amount to bet")
    async def coin_flip(self, interaction: discord.Interaction, amount: app_commands.Range[float, 1, Config.MAX_BET]):
        amount = round(amount, 2)
        if await self.reject_bet(interaction, amount):
            return

        user_id = interaction.user.id
        result = random.choice([True, False])

        if result:
            profit = round(amount * Config.COIN_FLIP_PAYOUT, 2)
            self.db.update_user_money(user_id, profit)
            embed = discord.Embed(
                title="🪙 Coin Flip - Win!",
                description=f"You won **${profit:.2f}**",
                color=discord.Color.green()
            )
            embed.set_footer(text="Heads!")
        else:
            profit = 0
            self.db.update_user_money(user_id, -amount)
            self.db.record_gambling_loss(amount)
            embed = discord.Embed(
                title="🪙 Coin Flip - Loss",
                description=f"You lost **${amount:.2f}**",
                color=discord.Color.red()
            )
            embed.set_footer(text="Tails!")

        await interaction.response.send_message(embed=embed)
        await self.check_gamble_achievements(interaction, amount, profit)

    @app_commands.command(name="roulette-color", description="Bet on red, black, or green")
    @app_commands.choices(color=[
        app_commands.Choice(name="Red (pays 1x)", value="red"),
        app_commands.Choice(name="Black (pays 1x)", value="black"),
        app_commands.Choice(name=f"Green (pays {Config.ROULETTE_GREEN_PAYOUT}x)", value="green")
    ])
    async def roulette_color(
        self,
        interaction: discord.Interaction,
        color: app_commands.Choice[str],
        amount: app_commands.Range[int, 1, Config.MAX_BET]
    ):
        if await self.reject_bet(interaction, amount):
            return

        user_id = interaction.user.id
        outcome = random.choice(ROULETTE_OUTCOMES)

        # Get color emoji
        color_emoji = "🔴" if outcome == "red" else "⚫" if outcome == "black" else "🟢"

        win_amount = 0
        if outcome == color.value:
            if outcome == "green":
                win_amount = amount * Config.ROULETTE_GREEN_PAYOUT
                self.db.update_user_money(user_id, win_amount)
                embed = discord.Embed(
                    title="🎰 Roulette - Jackpot!",
                    description=f"**{color_emoji} GREEN!**\n\nYou won **${win_amount}**",
                    color=discord.Color.green()
                )
            else:
                win_amount = amount
                self.db.update_user_money(user_id, win_amount)
                embed = discord.Embed(
                    title="🎰 Roulette - Win!",
                    description=f"**{color_emoji} {outcome.upper()}!**\n\nYou won **${amount}**",
                    color=discord.Color.green()
                )
        else:
            self.db.update_user_money(user_id, -amount)
            self.db.record_gambling_loss(amount)
            embed = discord.Embed(
                title="🎰 Roulette - Loss",
                description=f"**{color_emoji} {outcome.upper()}**\n\nYou lost **${amount}**",
                color=discord.Color.red()
            )

        await interaction.response.send_message(embed=embed)
        await self.check_gamble_achievements(interaction, amount, win_amount)

    @app_commands.command(name="blackjack", description="Play a hand of blackjack against the dealer")
    @app_commands.describe(amount="Amount to bet")
    async def blackjack(self, interaction: discord.Interaction, amount: app_commands.Range[float, 1, Config.MAX_BET]):
        amount = round(amount, 2)
        if await self.reject_bet(interaction, amount):
            return

        user_id = interaction.user.id
        if not self.db.try_debit_user(user_id, amount):
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"You don't have ${amount:.2f} to bet",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        deck = create_deck()
        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]
        view = BlackjackView(self, user_id, amount, deck, player_hand, dealer_hand)

        player_blackjack = hand_value(player_hand) == 21
        dealer_blackjack = hand_value(dealer_hand) == 21

        if player_blackjack or dealer_blackjack:
            if player_blackjack and dealer_blackjack:
                outcome = "push"
            elif player_blackjack:
                outcome = "player_blackjack"
            else:
                outcome = "dealer_win"
            embed = view.settle(outcome)
            await interaction.response.send_message(embed=embed)
            await self.check_gamble_achievements(interaction, amount, view.profit)
            return

        await interaction.response.send_message(embed=view.build_embed(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="jackpot", description="Buy a ticket for a chance to win the pool")
    async def jackpot(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = self.db.get_or_create_user(user_id)
        pool_data = self.db.get_pool()
        price = self.ticket_price_for(user_id)

        wait = self.db.timer_remaining(user_id, "jackpot_cooldown", clock.now_ts())
        if wait > 0:
            embed = discord.Embed(
                title="⏰ Ticket Cooldown",
                description=f"You can buy another ticket in **{clock.format_duration(wait)}**",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if user_data["money"] < price:
            embed = discord.Embed(
                title="❌ Insufficient Funds",
                description=f"A ticket costs **${price:.2f}**",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        view = JackpotView(self, user_id, price)
        embed = discord.Embed(
            title="🎰 Jackpot",
            description=(
                f"Buy a **${price:.2f}** ticket for a "
                f"**{Config.JACKPOT_WIN_CHANCE * 100:.0f}%** chance to win "
                f"**{Config.JACKPOT_PAYOUT_PERCENT * 100:.0f}% of the pool**."
            ),
            color=discord.Color.gold()
        )
        embed.add_field(name="Current Pool", value=f"${pool_data['money']:.2f}", inline=True)
        embed.set_footer(text="Ticket price scales with the pool.")
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

async def setup(bot: commands.Bot):
    await bot.add_cog(Games(bot))
