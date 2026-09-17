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
    # Public "not right now" notices are removed after this many seconds so
    # they don't clutter the channel.
    TRANSIENT_MESSAGE_SECONDS = 15
    DAILY_REWARD = 250
    JACKPOT_TICKET_PRICE = 50           # minimum ticket price
    JACKPOT_TICKET_POOL_PERCENT = 0.03  # price = max(minimum, 3% of pool)
    JACKPOT_WIN_CHANCE = 0.05
    JACKPOT_PAYOUT_PERCENT = 0.50       # winner takes half; the rest seeds the next pool
    JACKPOT_POOL_SEED = 0               # floor for the pool after a win
    JACKPOT_COOLDOWN_SECONDS = 300
    MAX_BET = 1000
    COIN_FLIP_PAYOUT = 0.95             # profit per $1 bet on a win
    ROULETTE_GREEN_PAYOUT = 11          # profit multiplier; 3/39 slots are green
    GAMBLING_LOSS_BURN_PERCENT = 0.25   # share of every lost bet that is destroyed
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
    NPC_TRAIN_COOLDOWN_SECONDS = 1800
    NPC_RELEASE_REFUND_PERCENT = 0.25    # of training costs paid
    HIGH_ROLLER_BET_THRESHOLD = 500
    BIG_WINNER_WIN_THRESHOLD = 1000
    TRIVIA_REWARD = 25
    TRIVIA_TIMEOUT_SECONDS = 30
    TRIVIA_CHANNEL_COOLDOWN_SECONDS = 300
    TRIVIA_MAX_WINS_PER_DAY = 5

    # Chat rewards: at most one payout per user per cooldown window.
    MESSAGE_REWARD_COOLDOWN_SECONDS = 60
    MESSAGE_MIN_LENGTH = 3

    WORK_MAX_SHIFTS_PER_DAY = 8          # per UTC day

    # Consecutive /daily-claim streak: +10% per day, up to +50%. Missing
    # the claim for more than the grace window resets the streak.
    DAILY_STREAK_BONUS = 0.10
    DAILY_STREAK_MAX_BONUS = 0.50
    DAILY_STREAK_GRACE_SECONDS = 48 * 3600

    GIVE_TAX_PERCENT = 0.05              # destroyed, not paid to anyone
    GIVE_DAILY_LIMIT = 5000              # max sent per UTC day

    ROB_MIN_ROBBER_BALANCE = 100
    ROB_MAX_STEAL = 500
    ROB_FAIL_PENALTY_OF_ATTEMPT = 0.50   # fine is at least half of what you tried to steal
    ROB_TARGET_PROTECTION_SECONDS = 7200 # a robbed user can't be robbed again for 2h

    # Bank interest: each account earns
    #   DAILY_RATE * balance * SOFT_CAP / (SOFT_CAP + balance)
    # per day, accrued once per period. Small balances earn ~DAILY_RATE;
    # large balances approach a ceiling of DAILY_RATE * SOFT_CAP dollars/day,
    # so growth is linear rather than exponential.
    BANK_INTEREST_DAILY_RATE = 0.02
    BANK_INTEREST_SOFT_CAP = 5000
    BANK_INTEREST_PERIOD_SECONDS = 3600
    BANK_INTEREST_MAX_PERIODS = 24 * 365  # accrual stops after a year untouched
