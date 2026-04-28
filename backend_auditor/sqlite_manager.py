import sqlite3
import os
from datetime import datetime
from loguru import logger

class SQLiteManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self._setup_database()

    def _get_connection(self):
        # Ensure the data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _setup_database(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Table 1: Raw Daily Group Snapshots
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS group_snapshots (
                    snapshot_date DATE PRIMARY KEY,
                    raw_json TEXT
                )
            ''')
            
            # Table 2: The Player Roster State
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS players (
                    wom_id INTEGER PRIMARY KEY,
                    current_rsn TEXT NOT NULL,
                    last_name_check_at DATETIME
                )
            ''')
            
            # Table 3: Normalized Name Change History
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS name_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wom_id INTEGER NOT NULL,
                    old_name TEXT NOT NULL,
                    new_name TEXT NOT NULL,
                    status TEXT,
                    resolved_at DATETIME,
                    FOREIGN KEY(wom_id) REFERENCES players(wom_id),
                    UNIQUE(wom_id, old_name, new_name, resolved_at)
                )
            ''')
            conn.commit()

    def save_group_snapshot(self, snapshot_date, raw_json):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO group_snapshots (snapshot_date, raw_json)
                VALUES (?, ?)
            ''', (snapshot_date, raw_json))
            conn.commit()

    def get_all_players(self):
        """Returns a dictionary mapping wom_id to their current_rsn."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT wom_id, current_rsn FROM players')
            return {row[0]: row[1] for row in cursor.fetchall()}

    def update_player(self, wom_id, current_rsn):
        now = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO players (wom_id, current_rsn, last_name_check_at)
                VALUES (?, ?, ?)
            ''', (wom_id, current_rsn, now))
            conn.commit()

    def insert_name_changes(self, changes):
        """Bulk inserts changes using INSERT OR IGNORE to automatically bypass duplicates."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT OR IGNORE INTO name_changes (wom_id, old_name, new_name, status, resolved_at)
                VALUES (?, ?, ?, ?, ?)
            ''', changes)
            conn.commit()

    def get_all_name_changes_grouped(self):
        """Returns a nested dictionary mapping wom_id (str) to a list of their name changes."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT wom_id, old_name, new_name, resolved_at 
                FROM name_changes 
                ORDER BY resolved_at DESC
            ''')
            results = {}
            for row in cursor.fetchall():
                wid = str(row[0])
                if wid not in results:
                    results[wid] = []
                date_str = row[3][:10] if row[3] else "Unknown" # Format as YYYY-MM-DD
                results[wid].append({"old": row[1], "new": row[2], "date": date_str})
            return results