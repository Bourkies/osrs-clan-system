import os
import sqlite3
import time
from collections import defaultdict
from loguru import logger
from dotenv import load_dotenv
from constants import SHARED_DATA_DIR

# Load environment variables
load_dotenv()

def wait_for_database(db_path, wait_time=30):
    """Checks if DB exists. If not, waits up to wait_time seconds."""
    if os.path.exists(db_path):
        return True
    logger.info(f"Database {db_path} not found. Waiting up to {wait_time} seconds for ETL to generate it...")
    
    start_time = time.time()
    while time.time() - start_time < wait_time:
        if os.path.exists(db_path):
            logger.info("Database appeared!")
            return True
        time.sleep(2)
        
    return False

def generate_activity_report():
    # Updated fallback to match your new ETL naming convention
    db_path = os.getenv("ENRICHED_DB_PATH", SHARED_DATA_DIR / "databases" / "enriched_data.db")
    output_db = SHARED_DATA_DIR / "databases" / "activity.db"
    tmp_db = SHARED_DATA_DIR / "databases" / "activity_tmp.db"

    if not wait_for_database(db_path, wait_time=30):
        logger.warning(f"Enriched database not found at {db_path} after waiting. Skipping activity report update.")
        return

    # Data structure: dict[discord_id] -> dict[date] -> dict of stats
    # Example: { '123': { '2026-03-15': {'name': 'Zezima', 'chats': 10, 'broadcasts': 5, 'ranks': {'Smiley'}} } }
    activity_data = defaultdict(lambda: defaultdict(lambda: {'name': '', 'chats': 0, 'broadcasts': 0, 'ranks': set()}))

    try:
        # timeout=30.0 gracefully handles the scenario where the DB is present but locked by the ETL
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 1. Process Chats Grouped by Day (Length 10 substring: YYYY-MM-DD)
        logger.info("Querying daily chat activity...")
        cursor.execute("""
            SELECT Discord_ID, Discord_Name, substr(Timestamp, 1, 10) as Date, Rank, COUNT(*) as count
            FROM chat
            WHERE Discord_ID IS NOT NULL AND Timestamp IS NOT NULL
            GROUP BY Discord_ID, Discord_Name, Date, Rank
        """)
        for row in cursor.fetchall():
            d_id = row['Discord_ID']
            date = row['Date']
            activity_data[d_id][date]['name'] = row['Discord_Name']
            activity_data[d_id][date]['chats'] += row['count']
            if row['Rank']:
                activity_data[d_id][date]['ranks'].add(row['Rank'])

        # 2. Process Broadcasts Grouped by Day
        logger.info("Querying daily broadcast activity...")
        cursor.execute("""
            SELECT Discord_ID, Discord_Name, substr(Timestamp, 1, 10) as Date, COUNT(*) as count
            FROM clan_broadcasts
            WHERE Discord_ID IS NOT NULL AND Timestamp IS NOT NULL
            GROUP BY Discord_ID, Discord_Name, Date
        """)
        for row in cursor.fetchall():
            d_id = row['Discord_ID']
            date = row['Date']
            # Ensure name is captured even if they have 0 chats this day
            if not activity_data[d_id][date]['name']:
                activity_data[d_id][date]['name'] = row['Discord_Name']
            activity_data[d_id][date]['broadcasts'] += row['count']

        conn.close()
    except sqlite3.OperationalError as e:
        logger.warning(f"Database locked or inaccessible ({db_path}): {e}. Skipping activity report update.")
        return
    except sqlite3.Error as e:
        logger.error(f"Database error while reading {db_path}: {e}")
        return

    # 3. Create Atomic SQLite Output
    logger.info("Compiling high-resolution SQLite report...")
    os.makedirs(os.path.dirname(output_db), exist_ok=True)
    
    # Clean up any failed tmp files from previous runs
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
        
    try:
        out_conn = sqlite3.connect(tmp_db)
        out_cursor = out_conn.cursor()
        
        out_cursor.execute('''
            CREATE TABLE daily_activity (
                Discord_ID TEXT,
                Discord_Name TEXT,
                Date TEXT,
                Chats INTEGER,
                Broadcasts INTEGER,
                Total_Activity INTEGER,
                Seen_Ranks TEXT,
                PRIMARY KEY (Discord_ID, Date)
            )
        ''')
        
        insert_data = []
        for d_id, dates in activity_data.items():
            for date, stats in sorted(dates.items()):
                total = stats['chats'] + stats['broadcasts']
                ranks_str = ", ".join(sorted(stats['ranks'])) if stats['ranks'] else "None"
                
                insert_data.append((
                    str(d_id),
                    stats['name'],
                    date,
                    stats['chats'],
                    stats['broadcasts'],
                    total,
                    ranks_str
                ))
                
        out_cursor.executemany('''
            INSERT INTO daily_activity 
            (Discord_ID, Discord_Name, Date, Chats, Broadcasts, Total_Activity, Seen_Ranks)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', insert_data)
        
        # Create indexes for lightning-fast queries in our downstream scripts
        out_cursor.execute('CREATE INDEX idx_discord_id ON daily_activity(Discord_ID)')
        out_cursor.execute('CREATE INDEX idx_date ON daily_activity(Date)')
        
        out_conn.commit()
        out_conn.close()
        
        # 4. Atomic File Swap
        os.replace(tmp_db, output_db)
        logger.success(f"Granular Activity Database successfully generated and swapped at {output_db}")
        
    except Exception as e:
        logger.error(f"Failed to compile output database {tmp_db}: {e}")
        if os.path.exists(tmp_db):
            os.remove(tmp_db)
                

if __name__ == '__main__':
    generate_activity_report()