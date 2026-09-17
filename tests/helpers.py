"""Shared test setup.

Points BOT_DATA_DIR at a throwaway temp folder *before* anything imports
`config`, so tests never touch the real database. Import this module first
in every test file.
"""
import os
import sys
import tempfile
import uuid
import warnings
from pathlib import Path
from types import SimpleNamespace

# Test DBs are throwaway; don't warn about connections left open.
warnings.simplefilter("ignore", ResourceWarning)

TEST_DATA_DIR = tempfile.mkdtemp(prefix="npcbot-tests-")
os.environ["BOT_DATA_DIR"] = TEST_DATA_DIR
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

from database.manager import DatabaseManager  # noqa: E402


def fresh_db() -> DatabaseManager:
    return DatabaseManager(f"test-{uuid.uuid4().hex}.db")


class FakeResponse:
    def __init__(self):
        self.sent = []
        self.edited = []

    async def send_message(self, content=None, *, embed=None, view=None, ephemeral=False, delete_after=None):
        self.sent.append(SimpleNamespace(content=content, embed=embed, view=view, ephemeral=ephemeral,
                                         delete_after=delete_after))

    async def edit_message(self, *, embed=None, view=None, delete_after=None):
        self.edited.append(SimpleNamespace(embed=embed, view=view, delete_after=delete_after))


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, *, embed=None, ephemeral=False):
        self.sent.append(SimpleNamespace(content=content, embed=embed, ephemeral=ephemeral))


class FakeInteraction:
    def __init__(self, user_id: int, channel_id: int = 1):
        self.user = SimpleNamespace(id=user_id, name=f"user{user_id}", mention=f"<@{user_id}>", bot=False)
        self.channel = SimpleNamespace(id=channel_id)
        self.response = FakeResponse()
        self.followup = FakeFollowup()

    async def original_response(self):
        return None

    @property
    def last_embed(self):
        return self.response.sent[-1].embed if self.response.sent else self.response.edited[-1].embed


def fake_member(user_id: int, bot: bool = False):
    return SimpleNamespace(id=user_id, name=f"user{user_id}", mention=f"<@{user_id}>", bot=bot)


def make_cog(cog_cls, db, bot=None):
    """Build a cog without running its __init__ DB setup against the real file."""
    cog = cog_cls.__new__(cog_cls)
    cog.bot = bot
    cog.db = db
    if hasattr(cog_cls, "_init_state"):
        cog._init_state()
    return cog
