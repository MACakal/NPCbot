import discord

ACHIEVEMENTS = {
    "first_daily": {
        "emoji": "🎉",
        "name": "First Paycheck",
        "description": "Claim your first daily reward.",
    },
    "first_work": {
        "emoji": "🛠️",
        "name": "Nine to Five",
        "description": "Complete your first /work shift.",
    },
    "first_npc": {
        "emoji": "🤝",
        "name": "Not Alone Anymore",
        "description": "Recruit your first NPC companion.",
    },
    "npc_max_level": {
        "emoji": "⭐",
        "name": "Max Potential",
        "description": "Train an NPC companion to max level.",
    },
    "first_theft": {
        "emoji": "🕵️",
        "name": "Sticky Fingers",
        "description": "Successfully rob another user.",
    },
    "first_shop_purchase": {
        "emoji": "🛍️",
        "name": "Retail Therapy",
        "description": "Buy your first item from the shop.",
    },
    "high_roller": {
        "emoji": "🎲",
        "name": "High Roller",
        "description": "Bet $500 or more in a single gamble.",
    },
    "big_winner": {
        "emoji": "💰",
        "name": "Jackpot Energy",
        "description": "Win $1,000 or more in a single gamble.",
    },
    "jackpot_winner": {
        "emoji": "🎆",
        "name": "Break The Bank",
        "description": "Win the shared pool jackpot.",
    },
    "first_trivia_win": {
        "emoji": "🧠",
        "name": "Big Brain",
        "description": "Win a /trivia round.",
    },
}


async def announce_unlock(interaction: discord.Interaction, achievement_id: str):
    """Send a follow-up message announcing a newly unlocked achievement.
    Must be called after the interaction has already been responded to
    (via response.send_message or response.edit_message)."""
    info = ACHIEVEMENTS[achievement_id]
    embed = discord.Embed(
        title="🏆 Achievement Unlocked!",
        description=f"{info['emoji']} **{info['name']}**\n{info['description']}",
        color=discord.Color.gold()
    )
    await interaction.followup.send(embed=embed)
