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
    JACKPOT_ENTRY_PERCENT = 0.05
    JACKPOT_WIN_CHANCE = 0.15
    STARTING_BALANCE = 100
    MONEY_PER_MESSAGE = 0.50
    OWNER_ID = 719140739384344627
