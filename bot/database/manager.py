import sqlite3
from typing import Optional, List, Dict
from config import Config
from datetime import datetime
import math
import threading
from pathlib import Path
import os

class DatabaseManager:
    def __init__(self, db_filename: str = "database.db"):
        """
        Initialize the database manager.

        db_filename: name of the sqlite database file, stored in the top-level database folder.
        """
        # Allow override via environment variable
        data_dir = os.getenv('BOT_DATA_DIR')
        
        if data_dir:
            # Use environment variable if set
            self.BASE_DIR = Path(data_dir)
        else:
            # Check if we're running from a mounted filesystem
            current_path = Path(__file__).resolve()
            current_path_str = str(current_path)
            
            # If running from mounted partition (/mnt/ or /run/media/), use Linux home directory
            if current_path_str.startswith('/mnt/') or current_path_str.startswith('/run/media/'):
                self.BASE_DIR = Path.home() / "discord-bot-data"
            else:
                # Otherwise use the project root as before
                self.BASE_DIR = current_path.parents[2]  # two levels up from bot/database/manager.py
        
        self.DB_DIR = self.BASE_DIR / "database"              # database folder
        self.DB_DIR.mkdir(parents=True, exist_ok=True)        # create folder if missing
        self.db_path = self.DB_DIR / db_filename              # full path to database file

        print(f"DEBUG: Database will be stored at: {self.db_path}")
        print(f"DEBUG: Running from mounted partition: {current_path_str.startswith('/mnt/') or current_path_str.startswith('/run/media/')}")
        print(f"DEBUG: BOT_DATA_DIR env var: {os.getenv('BOT_DATA_DIR')}")

        self._local = threading.local()

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
        r_eff = period_rate * f
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
        period_rate = (1 + daily_rate)**(1/288) - 1
        r_eff = daily_rate * f
        return r_eff

    # ========== Utility ==========
    def close(self):
        """Close database connection."""
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            delattr(self._local, 'conn')
