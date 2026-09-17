import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _resolve_base_dir() -> Path:
    """Project root, overridable via BOT_DATA_DIR for server deployments."""
    data_dir = os.getenv('BOT_DATA_DIR')
    if data_dir:
        return Path(data_dir)

    project_root = Path(__file__).resolve().parent.parent
    project_root_str = str(project_root)
    if project_root_str.startswith('/mnt/') or project_root_str.startswith('/run/media/'):
        return Path.home() / "discord-bot-data"
    return project_root

class Config:
    BASE_DIR = _resolve_base_dir()
    TOKEN = os.getenv('DISCORD_TOKEN')
    DATABASE_PATH = "database.db"
    SUGGESTIONS_PATH = str(BASE_DIR / "database" / "suggestions")
    COMMAND_PREFIX = '$'
    DAILY_REWARD = 250
    JACKPOT_TICKET_PRICE = 50
    JACKPOT_WIN_CHANCE = 0.05
    JACKPOT_POOL_SEED = 0
    STARTING_BALANCE = 100
    MONEY_PER_MESSAGE = 0.50
    OWNER_ID = 719140739384344627
    WORK_REWARD = 40
    WORK_COOLDOWN_SECONDS = 1800
    ROB_COOLDOWN_SECONDS = 3600
    ROB_SUCCESS_CHANCE = 0.5
    ROB_STEAL_PERCENT = 0.20
    ROB_FAIL_PENALTY_PERCENT = 0.15
    NPC_RECRUIT_COST = 150
    NPC_TRAIN_COST = 30
    NPC_TRAIN_XP = 25
    NPC_XP_PER_LEVEL = 100
    NPC_MAX_LEVEL = 5
    HIGH_ROLLER_BET_THRESHOLD = 500
    BIG_WINNER_WIN_THRESHOLD = 1000
    TRIVIA_REWARD = 75
    TRIVIA_TIMEOUT_SECONDS = 30

    # Bank interest: each account earns
    #   DAILY_RATE * balance * SOFT_CAP / (SOFT_CAP + balance)
    # per day, accrued once per period. Small balances earn ~DAILY_RATE;
    # large balances approach a ceiling of DAILY_RATE * SOFT_CAP dollars/day,
    # so growth is linear rather than exponential.
    BANK_INTEREST_DAILY_RATE = 0.02
    BANK_INTEREST_SOFT_CAP = 5000
    BANK_INTEREST_PERIOD_SECONDS = 3600
    BANK_INTEREST_MAX_PERIODS = 24 * 365  # accrual stops after a year untouched
