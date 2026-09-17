import sqlite3
from typing import Optional, List, Dict
from config import Config
from datetime import datetime
import math
import threading
import random

class DatabaseManager:
    def __init__(self, db_filename: str = "database.db"):
        """
        Initialize the database manager.

        db_filename: name of the sqlite database file, stored in the top-level database folder.
        """
        self.BASE_DIR = Config.BASE_DIR
        self.DB_DIR = self.BASE_DIR / "database"              # database folder
        self.DB_DIR.mkdir(parents=True, exist_ok=True)        # create folder if missing
        self.db_path = self.DB_DIR / db_filename              # full path to database file

        print(f"DEBUG: Database will be stored at: {self.db_path}")

        self._local = threading.local()
        self._ensure_schema_upgrades()

    def _ensure_schema_upgrades(self):
        """
        Defensive, additive-only schema upgrades.

        Safe to run against the existing production database: every
        statement here either creates a brand-new table (CREATE TABLE IF NOT
        EXISTS) or adds a new column to an existing table, guarded against
        the column already existing. Nothing here ever drops, renames, or
        alters the type of an existing column/table, so this is safe to run
        every time a DatabaseManager is constructed.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Base tables. These were never created by any code in the original
        # repo — they only worked on the live DB because they already
        # existed there from before. CREATE TABLE IF NOT EXISTS is a no-op
        # on that live DB and only matters for a brand-new/fresh database.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                money REAL NOT NULL DEFAULT 0,
                last_daily INTEGER,
                last_work INTEGER
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pool (
                id INTEGER PRIMARY KEY,
                money REAL NOT NULL DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Bank (
                id INTEGER PRIMARY KEY,
                money REAL NOT NULL DEFAULT 0,
                last_interest INTEGER,
                total_deposited REAL NOT NULL DEFAULT 0,
                total_withdrawn REAL NOT NULL DEFAULT 0,
                total_interest_earned REAL
            )
            """
        )
        cursor.execute('INSERT OR IGNORE INTO pool (id, money) VALUES (1, 0)')
        conn.commit()

        for statement in (
            "ALTER TABLE users ADD COLUMN last_work INTEGER",
        ):
            try:
                cursor.execute(statement)
            except sqlite3.OperationalError:
                pass  # column already exists on this database

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS rob_cooldowns (
                user_id INTEGER PRIMARY KEY,
                last_attempt INTEGER NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS npc_templates (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                archetype TEXT NOT NULL,
                flavor_text TEXT,
                perk_type TEXT NOT NULL,
                perk_value REAL NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_npcs (
                user_id INTEGER PRIMARY KEY,
                npc_template_id INTEGER NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                xp INTEGER NOT NULL DEFAULT 0,
                acquired_at INTEGER NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                effect_type TEXT NOT NULL,
                effect_value REAL NOT NULL DEFAULT 0
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_inventory (
                user_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (user_id, item_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_achievements (
                user_id INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                unlocked_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, achievement_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trivia_questions (
                id INTEGER PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL
            )
            """
        )
        conn.commit()

        self._seed_npc_templates()
        self._seed_shop_items()
        self._seed_trivia_questions()

    def _seed_npc_templates(self):
        """Seed the fixed NPC roster. INSERT OR IGNORE keyed by id, so this
        is safe to run on every startup — existing rows are never touched,
        new archetypes added here in the future just slot in."""
        templates = [
            (1, "Reggie the Muscle Broker", "merchant",
             "Made his fortune trading discounted tendons. Somehow.",
             "daily_bonus", 0.03),
            (2, "Big Clavicle", "laborer",
             "Built like a doorframe, works like one too.",
             "work_bonus", 0.03),
            (3, "Dr. Ledger", "banker",
             "Compounds interest and questionable diagnoses.",
             "bank_interest_bonus", 0.03),
            (4, "The Sternum", "guard",
             "Stands between you and anyone dumb enough to try something.",
             "rob_defense", 0.05),
            (5, "Slippery Sinew", "gambler",
             "Nobody's caught him lifting a wallet. Yet.",
             "rob_success_bonus", 0.05),
        ]
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT OR IGNORE INTO npc_templates
                (id, name, archetype, flavor_text, perk_type, perk_value)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            templates
        )
        conn.commit()

    def _seed_shop_items(self):
        """Seed the fixed shop catalog. INSERT OR IGNORE keyed by id, so
        this is safe to run on every startup — existing rows (and any
        purchases already made against them) are never touched."""
        items = [
            (1, "Discount Badge", "Reduces NPC recruiting & training costs by 10%.",
             300, "npc_cost_discount", 0.10),
            (2, "Insurance Policy", "Halves the fine you pay when a robbery goes wrong.",
             250, "rob_penalty_reduction", 0.50),
            (3, "Golden Feather", "Purely decorative. Flex on your friends.",
             100, "cosmetic", 0.0),
        ]
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT OR IGNORE INTO shop_items
                (id, name, description, price, effect_type, effect_value)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            items
        )
        conn.commit()

    def _seed_trivia_questions(self):
        """Seed the fixed trivia question bank (with a light physiology
        theme, a nod to the server this bot is named after). Multiple
        acceptable answers are pipe-separated. INSERT OR IGNORE keyed by
        id, safe to run on every startup."""
        questions = [
            (1, "What is the powerhouse of the cell?", "mitochondria"),
            (2, "How many bones are in the adult human body?", "206"),
            (3, "What is the largest organ in the human body?", "skin"),
            (4, "What gas do plants absorb from the atmosphere for photosynthesis?", "carbon dioxide|co2"),
            (5, "What is the hardest substance in the human body?", "enamel|tooth enamel"),
            (6, "Which chamber of the heart pumps oxygenated blood to the body?", "left ventricle"),
            (7, "What is the medical term for the voice box?", "larynx"),
            (8, "How many chromosomes are in a typical human somatic cell?", "46"),
            (9, "What macronutrient is the body's primary source of quick energy?", "carbohydrates|carbs"),
            (10, "What vitamin does sunlight help your skin produce?", "vitamin d|vitamin d3"),
        ]
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.executemany(
            'INSERT OR IGNORE INTO trivia_questions (id, question, answer) VALUES (?, ?, ?)',
            questions
        )
        conn.commit()

    def _get_connection(self):
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row  # Access columns by name
        return self._local.conn

    def _convert_user_row(self, row: sqlite3.Row) -> Dict:
        """Convert database row to dict and handle type conversions."""
        user = dict(row)
        if user.get("last_daily") is not None and isinstance(user["last_daily"], str):
            try:
                user["last_daily"] = int(user["last_daily"])
            except ValueError:
                user["last_daily"] = int(datetime.fromisoformat(user["last_daily"]).timestamp())
        if user.get("last_work") is not None and isinstance(user["last_work"], str):
            try:
                user["last_work"] = int(user["last_work"])
            except ValueError:
                user["last_work"] = int(datetime.fromisoformat(user["last_work"]).timestamp())
        return user

    # ========== User Operations ==========
    def get_user(self, user_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        return self._convert_user_row(row) if row else None

    def create_user(self, user_id: int, starting_balance: float = Config.STARTING_BALANCE) -> Dict:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO users (id, money, last_daily) VALUES (?, ?, NULL)',
            (user_id, starting_balance)
        )
        conn.commit()
        return self.get_user(user_id)

    def get_or_create_user(self, user_id: int) -> Dict:
        user = self.get_user(user_id)
        if user is None:
            return self.create_user(user_id)
        return user

    def update_user_money(self, user_id: int, amount: float) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET money = money + ? WHERE id = ?',
            (amount, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0

    def set_user_money(self, user_id: int, amount: float) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET money = ? WHERE id = ?',
            (amount, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0

    def update_last_daily(self, user_id: int, timestamp: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET last_daily = ? WHERE id = ?',
            (timestamp, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0

    def update_last_work(self, user_id: int, timestamp: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET last_work = ? WHERE id = ?',
            (timestamp, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0

    def transfer_money(self, from_id: int, to_id: int, amount: float) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN')
            cursor.execute(
                'UPDATE users SET money = money - ? WHERE id = ? AND money >= ?',
                (amount, from_id, amount)
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False
            self.get_or_create_user(to_id)
            cursor.execute(
                'UPDATE users SET money = money + ? WHERE id = ?',
                (amount, to_id)
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e

    # ========== Robbery ==========
    def get_last_rob_attempt(self, user_id: int) -> Optional[int]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT last_attempt FROM rob_cooldowns WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def set_last_rob_attempt(self, user_id: int, timestamp: int) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO rob_cooldowns (user_id, last_attempt) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_attempt = excluded.last_attempt
            """,
            (user_id, timestamp)
        )
        conn.commit()

    def rob_user(self, robber_id: int, target_id: int, success: bool, steal_amount: float, penalty_amount: float) -> float:
        """
        Execute a robbery attempt atomically.

        On success, moves up to `steal_amount` from the target to the robber,
        capped by the target's actual balance. On failure, moves up to
        `penalty_amount` from the robber into the shared pool, capped by the
        robber's actual balance. Returns the amount actually moved.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN')
            if success:
                cursor.execute('SELECT money FROM users WHERE id = ?', (target_id,))
                row = cursor.fetchone()
                target_money = row[0] if row else 0
                actual = min(steal_amount, max(target_money, 0))
                if actual > 0:
                    cursor.execute('UPDATE users SET money = money - ? WHERE id = ?', (actual, target_id))
                    cursor.execute('UPDATE users SET money = money + ? WHERE id = ?', (actual, robber_id))
                conn.commit()
                return actual
            else:
                cursor.execute('SELECT money FROM users WHERE id = ?', (robber_id,))
                row = cursor.fetchone()
                robber_money = row[0] if row else 0
                actual = min(penalty_amount, max(robber_money, 0))
                if actual > 0:
                    cursor.execute('UPDATE users SET money = money - ? WHERE id = ?', (actual, robber_id))
                    cursor.execute('UPDATE pool SET money = money + ? WHERE id = 1', (actual,))
                conn.commit()
                return actual
        except Exception as e:
            conn.rollback()
            raise e

    # ========== Pool Operations ==========
    def get_pool(self) -> Dict:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM pool WHERE id = 1')
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_pool_money(self, amount: float) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE pool SET money = money + ? WHERE id = 1',
            (amount,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def set_pool_money(self, amount: float) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE pool SET money = ? WHERE id = 1',
            (amount,)
        )
        conn.commit()
        return cursor.rowcount > 0

    # ========== Leaderboard & Stats ==========
    def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM users ORDER BY money DESC LIMIT ?',
            (limit,)
        )
        return [self._convert_user_row(row) for row in cursor.fetchall()]

    def get_total_users(self) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        return cursor.fetchone()[0]

    def get_total_money_in_circulation(self) -> float:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(money) FROM users")
        users_sum = cursor.fetchone()[0] or 0
        cursor.execute("SELECT SUM(money) FROM bank")
        bank_sum = cursor.fetchone()[0] or 0
        return users_sum + bank_sum

    # ========== Banking ==========
    def update_total_earned_interest(self, user_id: int, amount: float) -> bool:
        bank_account = self.get_bank_account(user_id=user_id)
        if bank_account["total_interest_earned"] is None:
            bank_account["total_interest_earned"] = amount
        else:
            bank_account["total_interest_earned"] += amount

        self.update_bank_balance_and_interest(user_id=user_id,
                                              new_balance=bank_account["money"],
                                              timestamp=int(datetime.utcnow().timestamp()),
                                              earned_interest=amount)
        return True

    def create_bank_account_if_neccesary(self, user_id : int) -> None:
        self.get_or_create_user(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM Bank WHERE id = ? LIMIT 1", (user_id,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO Bank (id, money, last_interest, total_deposited, total_withdrawn) VALUES (?, ?, ?, ?, ?)", (user_id, 0, None, 0, 0))
        conn.commit()

    def deposite_money_to_bank(self, user_id : int, amount : float) -> bool:
        self.create_bank_account_if_neccesary(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Bank SET money = money + ?, total_deposited = total_deposited + ? WHERE id = ?", (amount, amount, user_id))
        conn.commit()
        return cursor.rowcount > 0

    def withdraw_from_bank(self, user_id: int, amount: float) -> bool:
        self.create_bank_account_if_neccesary(user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Bank SET money = money - ?, total_withdrawn = total_withdrawn + ? WHERE id = ? AND money >= ?", (amount, amount, user_id, amount))
        conn.commit()
        return cursor.rowcount > 0

    def get_bank_account(self, user_id : int) -> Optional[Dict]:
        self.create_bank_account_if_neccesary(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM Bank WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_bank_balance_and_interest(self, user_id: int, new_balance: float, timestamp: int, earned_interest: float = 0) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Bank SET money = ?, last_interest = ?, total_interest_earned = COALESCE(total_interest_earned, 0) + ? WHERE id = ?", (new_balance, timestamp, earned_interest, user_id))
        conn.commit()
        return cursor.rowcount > 0

    def get_bank_balance(self, user_id : int) -> float:
        self.create_bank_account_if_neccesary(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT money FROM Bank WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0.0

    def apply_interest(self, user_id: int) -> float:
        bank = self.get_bank_account(user_id)
        now = int(datetime.utcnow().timestamp())
        last_interest = bank['last_interest']
        if not last_interest:
            self.update_bank_balance_and_interest(user_id, bank['money'], now)
            return 0
        periods_passed = (now - last_interest) // 300
        if periods_passed < 1:
            return 0
        total = max(self.get_total_money_in_circulation(), 1)
        p = min(max(bank["money"] / total, 0.0), 1.0)
        f = math.exp(-1.5 * p)
        daily_rate = 0.10
        period_rate = (1 + daily_rate)**(1/288) - 1
        bonus = self.get_perk_bonus(user_id, "bank_interest_bonus")
        r_eff = period_rate * f * (1 + bonus)
        new_balance = bank["money"] * (1 + r_eff)**periods_passed
        interest_earned = new_balance - bank['money']
        self.update_bank_balance_and_interest(user_id, new_balance, now, interest_earned)
        return interest_earned

    def return_interest_rate(self, user_id: int) -> float:
        bank = self.get_bank_account(user_id)
        total = max(self.get_total_money_in_circulation(), 1)
        p = min(max(bank["money"] / total, 0.0), 1.0)
        f = math.exp(-1.5 * p)
        daily_rate = 0.10
        bonus = self.get_perk_bonus(user_id, "bank_interest_bonus")
        r_eff = daily_rate * f * (1 + bonus)
        return r_eff

    # ========== NPC Companions ==========
    def get_npc_templates(self) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM npc_templates')
        return [dict(row) for row in cursor.fetchall()]

    def get_random_npc_template(self) -> Optional[Dict]:
        templates = self.get_npc_templates()
        return random.choice(templates) if templates else None

    def get_user_npc(self, user_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT user_npcs.user_id, user_npcs.npc_template_id, user_npcs.level,
                   user_npcs.xp, user_npcs.acquired_at, npc_templates.name,
                   npc_templates.archetype, npc_templates.flavor_text,
                   npc_templates.perk_type, npc_templates.perk_value
            FROM user_npcs
            JOIN npc_templates ON npc_templates.id = user_npcs.npc_template_id
            WHERE user_npcs.user_id = ?
            """,
            (user_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def recruit_npc(self, user_id: int, npc_template_id: int, timestamp: int) -> bool:
        """Fails (returns False) if the user already has a companion."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO user_npcs (user_id, npc_template_id, level, xp, acquired_at) VALUES (?, ?, 1, 0, ?)',
            (user_id, npc_template_id, timestamp)
        )
        conn.commit()
        return cursor.rowcount > 0

    def release_npc(self, user_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_npcs WHERE user_id = ?', (user_id,))
        conn.commit()
        return cursor.rowcount > 0

    def train_npc(self, user_id: int, xp_gain: int, xp_per_level: int, max_level: int) -> Optional[Dict]:
        """
        Add XP to the user's NPC, leveling up as needed (capped at
        max_level). Returns the updated npc dict (with a 'leveled_up' flag)
        or None if the user has no companion.
        """
        npc = self.get_user_npc(user_id)
        if npc is None:
            return None

        level = npc["level"]
        xp = npc["xp"] + xp_gain
        leveled_up = False
        while level < max_level and xp >= xp_per_level:
            xp -= xp_per_level
            level += 1
            leveled_up = True
        if level >= max_level:
            xp = min(xp, xp_per_level)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE user_npcs SET level = ?, xp = ? WHERE user_id = ?',
            (level, xp, user_id)
        )
        conn.commit()

        npc["level"] = level
        npc["xp"] = xp
        npc["leveled_up"] = leveled_up
        return npc

    def get_perk_bonus(self, user_id: int, perk_type: str) -> float:
        """
        Returns the raw bonus fraction (e.g. 0.09 for +9%) granted by the
        user's companion for the given perk_type, or 0.0 if they have no
        companion or their companion's perk doesn't match. Callers decide
        how to apply it (e.g. reward * (1 + bonus)).
        """
        npc = self.get_user_npc(user_id)
        if npc is None or npc["perk_type"] != perk_type:
            return 0.0
        return npc["perk_value"] * npc["level"]

    # ========== Shop & Inventory ==========
    def get_shop_items(self) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM shop_items ORDER BY id')
        return [dict(row) for row in cursor.fetchall()]

    def get_item(self, item_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM shop_items WHERE id = ?', (item_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_item_by_name(self, name: str) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM shop_items WHERE name = ? COLLATE NOCASE', (name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_inventory(self, user_id: int) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT shop_items.id, shop_items.name, shop_items.description,
                   shop_items.price, shop_items.effect_type, shop_items.effect_value,
                   user_inventory.quantity
            FROM user_inventory
            JOIN shop_items ON shop_items.id = user_inventory.item_id
            WHERE user_inventory.user_id = ? AND user_inventory.quantity > 0
            ORDER BY shop_items.id
            """,
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def purchase_item(self, user_id: int, item_id: int) -> bool:
        item = self.get_item(item_id)
        if item is None:
            return False

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN')
            cursor.execute(
                'UPDATE users SET money = money - ? WHERE id = ? AND money >= ?',
                (item["price"], user_id, item["price"])
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False
            cursor.execute(
                """
                INSERT INTO user_inventory (user_id, item_id, quantity) VALUES (?, ?, 1)
                ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + 1
                """,
                (user_id, item_id)
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e

    def get_item_effect_value(self, user_id: int, effect_type: str) -> float:
        """
        Returns the effect_value of the first owned item matching
        effect_type, or 0.0 if the user owns no such item. Functional
        effects here are non-stacking (owning more than one of an item
        doesn't compound the bonus).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT shop_items.effect_value
            FROM user_inventory
            JOIN shop_items ON shop_items.id = user_inventory.item_id
            WHERE user_inventory.user_id = ? AND shop_items.effect_type = ? AND user_inventory.quantity > 0
            LIMIT 1
            """,
            (user_id, effect_type)
        )
        row = cursor.fetchone()
        return row[0] if row else 0.0

    # ========== Achievements ==========
    def unlock_achievement(self, user_id: int, achievement_id: str) -> bool:
        """Returns True if this was a newly-unlocked achievement, False if
        the user already had it (idempotent via INSERT OR IGNORE)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = int(datetime.utcnow().timestamp())
        cursor.execute(
            'INSERT OR IGNORE INTO user_achievements (user_id, achievement_id, unlocked_at) VALUES (?, ?, ?)',
            (user_id, achievement_id, now)
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_user_achievements(self, user_id: int) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT achievement_id, unlocked_at FROM user_achievements WHERE user_id = ? ORDER BY unlocked_at',
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    # ========== Trivia ==========
    def get_random_trivia_question(self) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM trivia_questions')
        rows = cursor.fetchall()
        return dict(random.choice(rows)) if rows else None

    def award_trivia_prize(self, user_id: int, reward: float) -> float:
        """Pays the reward out of the shared pool, capped to what the pool
        actually has. Returns the amount actually paid."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN')
            cursor.execute('SELECT money FROM pool WHERE id = 1')
            row = cursor.fetchone()
            pool_money = row[0] if row else 0
            actual = min(reward, max(pool_money, 0))
            if actual > 0:
                cursor.execute('UPDATE pool SET money = money - ? WHERE id = 1', (actual,))
                cursor.execute('UPDATE users SET money = money + ? WHERE id = ?', (actual, user_id))
            conn.commit()
            return actual
        except Exception as e:
            conn.rollback()
            raise e

    # ========== Utility ==========
    def close(self):
        """Close database connection."""
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            delattr(self._local, 'conn')
