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

            # Table 4: Issue Tracker (Duration & History Tracking)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS issue_tracker (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    first_seen_at DATETIME NOT NULL,
                    last_seen_at DATETIME NOT NULL,
                    consecutive_runs INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'active',
                    resolved_at DATETIME,
                    UNIQUE(entity_type, entity_id, issue_type, status)
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

    def get_active_issues(self):
        """Returns a dict mapping (entity_type, entity_id, issue_type) to duration info."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT entity_type, entity_id, issue_type, first_seen_at, last_seen_at, consecutive_runs
                FROM issue_tracker
                WHERE status = 'active'
            ''')
            now = datetime.utcnow()
            results = {}
            for row in cursor.fetchall():
                e_type, e_id, i_type, first_seen_str, last_seen_str, runs = row
                try:
                    first_seen_dt = datetime.fromisoformat(first_seen_str)
                    days_active = max(0, (now - first_seen_dt).days)
                except Exception:
                    days_active = 0
                
                tag = "*(NEW)*" if days_active == 0 else f"*({days_active}d)*"
                results[(e_type, str(e_id), i_type)] = {
                    "first_seen_at": first_seen_str,
                    "last_seen_at": last_seen_str,
                    "consecutive_runs": runs,
                    "days_active": days_active,
                    "formatted_tag": tag
                }
            return results

    def sync_active_issues(self, current_active_issues):
        """
        Synchronizes the current run's active issues with the database.
        - Existing active issues are updated (last_seen_at = now, consecutive_runs += 1).
        - New active issues are inserted with first_seen_at = now.
        - Active issues in DB that are missing from current_active_issues are marked 'resolved'.
        """
        now_str = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT entity_type, entity_id, issue_type, consecutive_runs
                FROM issue_tracker
                WHERE status = 'active'
            ''')
            db_active = {(row[0], str(row[1]), row[2]): row[3] for row in cursor.fetchall()}
            current_set = {(item[0], str(item[1]), item[2]) for item in current_active_issues}
            
            # 1. Update existing active issues
            for key in current_set & db_active.keys():
                runs = db_active[key] + 1
                cursor.execute('''
                    UPDATE issue_tracker
                    SET last_seen_at = ?, consecutive_runs = ?
                    WHERE entity_type = ? AND entity_id = ? AND issue_type = ? AND status = 'active'
                ''', (now_str, runs, key[0], key[1], key[2]))
                
            # 2. Insert new active issues
            for key in current_set - db_active.keys():
                cursor.execute('''
                    INSERT INTO issue_tracker (entity_type, entity_id, issue_type, first_seen_at, last_seen_at, consecutive_runs, status)
                    VALUES (?, ?, ?, ?, ?, 1, 'active')
                ''', (key[0], key[1], key[2], now_str, now_str))
                
            # 3. Resolve missing active issues
            for key in db_active.keys() - current_set:
                cursor.execute('''
                    UPDATE issue_tracker
                    SET status = 'resolved', resolved_at = ?
                    WHERE entity_type = ? AND entity_id = ? AND issue_type = ? AND status = 'active'
                ''', (now_str, key[0], key[1], key[2]))
                
            conn.commit()