import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    DATABASE_PATH = "database.db"
    SUGGESTIONS_PATH = "C:/Users/JinMori07/Documents/NPC bot/database/suggestions"
    COMMAND_PREFIX = '$'
    DAILY_REWARD = 250
    JACKPOT_ENTRY_PERCENT = 0.05
    JACKPOT_WIN_CHANCE = 0.15
    STARTING_BALANCE = 100
    MONEY_PER_MESSAGE = 0.50
    OWNER_ID = 719140739384344627
