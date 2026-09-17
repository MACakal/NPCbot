import sqlite3
from typing import Optional, List, Dict
from config import Config
from datetime import datetime
from utils import clock
import threading
import random

# Shop effects that are permanent upgrades (owning one is enough).
PERMANENT_EFFECTS = {"npc_cost_discount", "rob_penalty_reduction"}
# Shop effects that are used up one at a time.
CONSUMABLE_EFFECTS = {"rob_success_consumable", "rob_protection_consumable", "work_cooldown_reset"}


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

        # Generic per-user timers: "this action is blocked/active until
        # until_ts". Used for cooldowns and temporary protections.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_timers (
                user_id INTEGER NOT NULL,
                timer TEXT NOT NULL,
                until_ts INTEGER NOT NULL,
                PRIMARY KEY (user_id, timer)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_streaks (
                user_id INTEGER PRIMARY KEY,
                streak INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # Per-user running totals that reset each UTC day (work shifts,
        # trivia wins, money given, ...).
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_counters (
                user_id INTEGER NOT NULL,
                counter TEXT NOT NULL,
                day TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, counter)
            )
            """
        )
        conn.commit()

        self._seed_npc_templates()
        self._seed_shop_items()
        self._seed_trivia_questions()

    def _seed_npc_templates(self):
        """Seed the fixed NPC roster, keyed by id. The roster is owned by
        this code, so existing rows are updated to match it (that's how perk
        rebalances reach the live database); recruited companions only
        reference the id, so they pick up the new values."""
        templates = [
            (1, "Reggie the Muscle Broker", "merchant",
             "Made his fortune trading discounted tendons. Somehow.",
             "daily_bonus", 0.05),
            (2, "Big Clavicle", "laborer",
             "Built like a doorframe, works like one too.",
             "work_bonus", 0.05),
            (3, "Dr. Ledger", "banker",
             "Compounds interest and questionable diagnoses.",
             "bank_interest_bonus", 0.10),
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
            INSERT INTO npc_templates
                (id, name, archetype, flavor_text, perk_type, perk_value)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                archetype = excluded.archetype,
                flavor_text = excluded.flavor_text,
                perk_type = excluded.perk_type,
                perk_value = excluded.perk_value
            """,
            templates
        )
        conn.commit()

    def _seed_shop_items(self):
        """Seed the fixed shop catalog, keyed by id. Like the NPC roster,
        the catalog is owned by this code, so price/effect changes are
        applied to existing rows. Inventories only reference the id, so
        purchases already made are kept."""
        items = [
            (1, "Discount Badge", "Permanent: NPC recruiting & training cost 25% less.",
             100, "npc_cost_discount", 0.25),
            (2, "Insurance Policy", "Permanent: halves the fine you pay when a robbery goes wrong.",
             250, "rob_penalty_reduction", 0.50),
            (3, "Golden Feather", "Purely decorative. Flex on your friends.",
             100, "cosmetic", 0.0),
            (4, "Lockpick", "Consumable: +10% success chance on your next robbery. Used automatically.",
             75, "rob_success_consumable", 0.10),
            (5, "Padlock", "Consumable: nobody can rob you for 24h. Activate with /use.",
             150, "rob_protection_consumable", 86400),
            (6, "Energy Drink", "Consumable: skip your /work break once. Activate with /use.",
             30, "work_cooldown_reset", 0.0),
        ]
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO shop_items
                (id, name, description, price, effect_type, effect_value)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                price = excluded.price,
                effect_type = excluded.effect_type,
                effect_value = excluded.effect_value
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
            (11, "Which blood cells carry oxygen around the body?", "red blood cells|red blood cell|erythrocytes|rbc|rbcs"),
            (12, "What is the longest bone in the human body?", "femur|thigh bone"),
            (13, "What is the smallest bone in the human body?", "stapes|stirrup"),
            (14, "Which organ produces insulin?", "pancreas"),
            (15, "What protein makes up most of your hair and nails?", "keratin"),
            (16, "How many chambers does the human heart have?", "4|four"),
            (17, "What is the largest muscle in the human body?", "gluteus maximus|glutes|glute"),
            (18, "Which molecule is the cell's main energy currency?", "atp|adenosine triphosphate"),
            (19, "What tissue connects muscle to bone?", "tendon|tendons"),
            (20, "What tissue connects bone to bone?", "ligament|ligaments"),
            (21, "Which organ filters blood to produce urine?", "kidney|kidneys"),
            (22, "What is the main mineral stored in bones?", "calcium"),
            (23, "Which part of the brain is mainly responsible for balance and coordination?", "cerebellum"),
            (24, "What pigment gives skin its colour?", "melanin"),
            (25, "How many calories are in one gram of protein?", "4|four"),
            (26, "How many calories are in one gram of fat?", "9|nine"),
            (27, "What is the name of the muscle that separates the chest from the abdomen?", "diaphragm"),
            (28, "Which gas do humans exhale as a waste product?", "carbon dioxide|co2"),
            (29, "What is the name for the tiny air sacs in the lungs?", "alveoli|alveolus"),
            (30, "Which vitamin is essential for blood clotting?", "vitamin k"),
            (31, "What organ stores bile?", "gallbladder|gall bladder"),
            (32, "What is the largest internal organ in the human body?", "liver"),
            (33, "Which hormone is known as the main stress hormone?", "cortisol"),
            (34, "What is the muscle on the front of the upper arm called?", "biceps|bicep|biceps brachii"),
            (35, "What is the muscle on the back of the upper arm called?", "triceps|tricep|triceps brachii"),
            (36, "Which amino acid is best known for triggering muscle protein synthesis?", "leucine"),
            (37, "What does DNA stand for?", "deoxyribonucleic acid"),
            (38, "How many pairs of ribs does a typical human have?", "12|twelve"),
            (39, "Which blood vessels carry blood away from the heart?", "arteries|artery"),
            (40, "Which blood vessels carry blood back to the heart?", "veins|vein"),
            (41, "What is the kneecap's anatomical name?", "patella"),
            (42, "What is the collarbone's anatomical name?", "clavicle"),
            (43, "What is the breastbone's anatomical name?", "sternum"),
            (44, "Which hormone lowers blood sugar?", "insulin"),
            (45, "What is the planet closest to the Sun?", "mercury"),
            (46, "What is the chemical symbol for gold?", "au"),
            (47, "What is the boiling point of water at sea level in Celsius?", "100"),
            (48, "What is the largest planet in our solar system?", "jupiter"),
            (49, "How many continents are there on Earth?", "7|seven"),
            (50, "What is the chemical formula for water?", "h2o"),
            (51, "What is the fastest land animal?", "cheetah"),
            (52, "How many minutes are in a day?", "1440"),
            (53, "What is the square root of 144?", "12|twelve"),
            (54, "Which element has the atomic number 1?", "hydrogen"),
            (55, "What is the most abundant gas in Earth's atmosphere?", "nitrogen|n2"),
            (56, "What type of muscle is the heart made of?", "cardiac|cardiac muscle"),
            (57, "What is the name of the joint between the upper arm and forearm?", "elbow"),
            (58, "What sugar is the body's main fuel, carried in the blood?", "glucose"),
            (59, "What is the stored form of glucose in muscles and liver called?", "glycogen"),
            (60, "How many teeth does a typical adult human have?", "32|thirty-two|thirty two"),
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

    def try_debit_user(self, user_id: int, amount: float) -> bool:
        """Atomically take `amount` from a wallet only if it can cover it.
        Returns False (and changes nothing) otherwise, so wallets never go
        negative."""
        if amount < 0:
            return False
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET money = money - ? WHERE id = ? AND money >= ?',
            (amount, user_id, amount)
        )
        conn.commit()
        return cursor.rowcount > 0

    def transfer_money(self, from_id: int, to_id: int, amount: float, fee: float = 0.0) -> bool:
        """Take `amount` from the sender; the recipient gets `amount - fee`
        and the fee is destroyed."""
        if amount <= 0 or fee < 0 or fee > amount:
            return False
        # Create the recipient before BEGIN: create_user commits, which would
        # otherwise end the transaction between the debit and the credit.
        self.get_or_create_user(to_id)
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
            cursor.execute(
                'UPDATE users SET money = money + ? WHERE id = ?',
                (amount - fee, to_id)
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e

    # ========== Timers & Daily Counters ==========
    def get_timer(self, user_id: int, timer: str) -> Optional[int]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT until_ts FROM user_timers WHERE user_id = ? AND timer = ?', (user_id, timer))
        row = cursor.fetchone()
        return row[0] if row else None

    def timer_remaining(self, user_id: int, timer: str, now: int) -> int:
        """Seconds until the timer expires, or 0 if it isn't running."""
        until = self.get_timer(user_id, timer)
        return max(until - now, 0) if until is not None else 0

    def set_timer(self, user_id: int, timer: str, until_ts: int) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO user_timers (user_id, timer, until_ts) VALUES (?, ?, ?)
            ON CONFLICT(user_id, timer) DO UPDATE SET until_ts = excluded.until_ts
            """,
            (user_id, timer, until_ts)
        )
        conn.commit()

    def extend_timer(self, user_id: int, timer: str, until_ts: int) -> None:
        """Like set_timer, but never shortens a timer that runs longer."""
        current = self.get_timer(user_id, timer)
        if current is None or until_ts > current:
            self.set_timer(user_id, timer, until_ts)

    def get_daily_streak(self, user_id: int) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT streak FROM daily_streaks WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def set_daily_streak(self, user_id: int, streak: int) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO daily_streaks (user_id, streak) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET streak = excluded.streak
            """,
            (user_id, streak)
        )
        conn.commit()

    def get_daily_counter(self, user_id: int, counter: str, day: str) -> float:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT day, amount FROM daily_counters WHERE user_id = ? AND counter = ?', (user_id, counter))
        row = cursor.fetchone()
        return row[1] if row and row[0] == day else 0.0

    def add_daily_counter(self, user_id: int, counter: str, day: str, amount: float) -> float:
        """Add to today's counter (resetting it if it belongs to an earlier
        day) and return the new total."""
        total = self.get_daily_counter(user_id, counter, day) + amount
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO daily_counters (user_id, counter, day, amount) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, counter) DO UPDATE SET day = excluded.day, amount = excluded.amount
            """,
            (user_id, counter, day, total)
        )
        conn.commit()
        return total

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

    def record_gambling_loss(self, amount: float) -> float:
        """A lost bet: part of it is destroyed (a money sink), the rest
        feeds the pool. Returns the amount added to the pool."""
        to_pool = amount * (1 - Config.GAMBLING_LOSS_BURN_PERCENT)
        self.update_pool_money(to_pool)
        return to_pool

    def jackpot_ticket_price(self) -> float:
        """Ticket price scales with the pool so a ticket is never +EV."""
        pool = self.get_pool()["money"]
        return round(max(Config.JACKPOT_TICKET_PRICE, pool * Config.JACKPOT_TICKET_POOL_PERCENT), 2)

    def pay_jackpot(self, user_id: int) -> float:
        """Atomically pay the winner their share of the pool; the rest
        stays as the next pool. Returns the amount paid."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN')
            cursor.execute('SELECT money FROM pool WHERE id = 1')
            row = cursor.fetchone()
            pool_money = max(row[0] if row else 0, 0)
            payout = round(pool_money * Config.JACKPOT_PAYOUT_PERCENT, 2)
            remaining = max(pool_money - payout, Config.JACKPOT_POOL_SEED)
            cursor.execute('UPDATE pool SET money = ? WHERE id = 1', (remaining,))
            cursor.execute('UPDATE users SET money = money + ? WHERE id = ?', (payout, user_id))
            conn.commit()
            return payout
        except Exception as e:
            conn.rollback()
            raise e

    # ========== Leaderboard & Stats ==========
    def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT users.id, users.money AS wallet, COALESCE(Bank.money, 0) AS bank,
                   users.money + COALESCE(Bank.money, 0) AS net_worth
            FROM users
            LEFT JOIN Bank ON Bank.id = users.id
            ORDER BY net_worth DESC
            LIMIT ?
            """,
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

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
                                              timestamp=clock.now_ts(),
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

    def deposit_to_bank(self, user_id: int, amount: float) -> bool:
        """Atomically move `amount` from the wallet into the bank. Returns
        False if the amount isn't positive or the wallet can't cover it."""
        if amount <= 0:
            return False
        self.create_bank_account_if_neccesary(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN')
            cursor.execute(
                'UPDATE users SET money = money - ? WHERE id = ? AND money >= ?',
                (amount, user_id, amount)
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False
            cursor.execute(
                "UPDATE Bank SET money = money + ?, total_deposited = total_deposited + ? WHERE id = ?",
                (amount, amount, user_id)
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e

    def withdraw_from_bank(self, user_id: int, amount: float) -> bool:
        """Atomically move `amount` from the bank into the wallet. Returns
        False if the amount isn't positive or the bank can't cover it."""
        if amount <= 0:
            return False
        self.create_bank_account_if_neccesary(user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN')
            cursor.execute(
                "UPDATE Bank SET money = money - ?, total_withdrawn = total_withdrawn + ? WHERE id = ? AND money >= ?",
                (amount, amount, user_id, amount)
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False
            cursor.execute('UPDATE users SET money = money + ? WHERE id = ?', (amount, user_id))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e

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

    @staticmethod
    def interest_multiplier(balance: float) -> float:
        """Fraction of the base rate a balance earns: ~1 for small balances,
        shrinking so that absolute interest levels off at the soft cap."""
        if balance <= 0:
            return 0.0
        k = Config.BANK_INTEREST_SOFT_CAP
        return k / (k + balance)

    @classmethod
    def accrue_interest(cls, balance: float, periods: int, bonus: float = 0.0) -> float:
        """Balance after `periods` accrual periods. Depends only on the
        balance and the number of periods, so claiming often or rarely
        gives the same result. Negative balances never accrue."""
        periods_per_day = 86400 / Config.BANK_INTEREST_PERIOD_SECONDS
        period_rate = Config.BANK_INTEREST_DAILY_RATE * (1 + bonus) / periods_per_day
        for _ in range(min(periods, Config.BANK_INTEREST_MAX_PERIODS)):
            if balance <= 0:
                break
            balance += balance * period_rate * cls.interest_multiplier(balance)
        return balance

    def apply_interest(self, user_id: int) -> float:
        bank = self.get_bank_account(user_id)
        now = clock.now_ts()
        last_interest = bank['last_interest']
        if not last_interest:
            self.update_bank_balance_and_interest(user_id, bank['money'], now)
            return 0
        period = Config.BANK_INTEREST_PERIOD_SECONDS
        periods_passed = (now - last_interest) // period
        if periods_passed < 1:
            return 0
        bonus = self.get_perk_bonus(user_id, "bank_interest_bonus")
        new_balance = self.accrue_interest(bank["money"], periods_passed, bonus)
        interest_earned = new_balance - bank['money']
        # Advance by whole periods so the partial period isn't thrown away.
        if periods_passed > Config.BANK_INTEREST_MAX_PERIODS:
            new_last = now - (now - last_interest) % period
        else:
            new_last = last_interest + periods_passed * period
        self.update_bank_balance_and_interest(user_id, new_balance, new_last, interest_earned)
        return interest_earned

    def return_interest_rate(self, user_id: int) -> float:
        """Current effective daily rate for this user's bank balance."""
        bank = self.get_bank_account(user_id)
        bonus = self.get_perk_bonus(user_id, "bank_interest_bonus")
        return Config.BANK_INTEREST_DAILY_RATE * (1 + bonus) * self.interest_multiplier(bank["money"])

    def return_max_daily_interest(self, user_id: int) -> float:
        """Ceiling on dollars of interest per day, however large the balance."""
        bonus = self.get_perk_bonus(user_id, "bank_interest_bonus")
        return Config.BANK_INTEREST_DAILY_RATE * (1 + bonus) * Config.BANK_INTEREST_SOFT_CAP

    # ========== NPC Companions ==========
    def get_npc_templates(self) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM npc_templates')
        return [dict(row) for row in cursor.fetchall()]

    def get_random_npc_template(self) -> Optional[Dict]:
        templates = self.get_npc_templates()
        return random.choice(templates) if templates else None

    def get_npc_template_by_archetype(self, archetype: str) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM npc_templates WHERE archetype = ?', (archetype,))
        row = cursor.fetchone()
        return dict(row) if row else None

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

    def purchase_item(self, user_id: int, item_id: int) -> str:
        """Returns "ok", "not_found", "already_owned" (permanent upgrades
        don't stack, so a second copy is refused) or "insufficient_funds"."""
        item = self.get_item(item_id)
        if item is None:
            return "not_found"
        if item["effect_type"] in PERMANENT_EFFECTS and self.get_item_effect_value(user_id, item["effect_type"]) > 0:
            return "already_owned"

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
                return "insufficient_funds"
            cursor.execute(
                """
                INSERT INTO user_inventory (user_id, item_id, quantity) VALUES (?, ?, 1)
                ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + 1
                """,
                (user_id, item_id)
            )
            conn.commit()
            return "ok"
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

    def consume_item(self, user_id: int, effect_type: str) -> float:
        """Use up one owned item with this effect. Returns its effect_value,
        or 0.0 if the user owns none."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT shop_items.id, shop_items.effect_value
            FROM user_inventory
            JOIN shop_items ON shop_items.id = user_inventory.item_id
            WHERE user_inventory.user_id = ? AND shop_items.effect_type = ? AND user_inventory.quantity > 0
            LIMIT 1
            """,
            (user_id, effect_type)
        )
        row = cursor.fetchone()
        if row is None:
            return 0.0
        cursor.execute(
            'UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_id = ? AND quantity > 0',
            (user_id, row[0])
        )
        conn.commit()
        return row[1] if cursor.rowcount > 0 else 0.0

    # ========== Achievements ==========
    def unlock_achievement(self, user_id: int, achievement_id: str) -> bool:
        """Returns True if this was a newly-unlocked achievement, False if
        the user already had it (idempotent via INSERT OR IGNORE)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = clock.now_ts()
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

    # ========== Utility ==========
    def close(self):
        """Close database connection."""
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            delattr(self._local, 'conn')
