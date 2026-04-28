
# src/1_fetch_data.py

import discord
import pandas as pd
import re
import asyncio
from sqlalchemy import text, inspect, exc
from datetime import datetime, timedelta, timezone
from loguru import logger

from shared_utils import (
    load_config, get_db_engine, PROJECT_ROOT, finish_script
)
from loguru_setup import loguru_setup

SCRIPT_NAME = "1_fetch_data"

def clean_discord_escapes(text: str) -> str:
    """Removes Discord's escape backslashes before punctuation."""
    return re.sub(r'\\([^\w\s])', r'\1', text)

def get_date_range(config: dict, engine, run_warnings: list) -> tuple[datetime, datetime]:
    """Determines the start and end dates for the data fetch."""
    logger.info("Determining date range for data fetch...")
    time_settings = config.get('time_settings', {})
    mode = time_settings.get('mode', 'automatic')
    now = datetime.now(timezone.utc)

    if mode == 'custom':
        custom_range = config.get('custom_time_range', {})
        start_str = custom_range.get('custom_start_date')
        end_str = custom_range.get('custom_end_date')
        if not start_str or not end_str:
            raise ValueError("Custom date range mode selected but dates are missing in config.")
        start_date = datetime.strptime(start_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(end_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        logger.info(f"--> Using CUSTOM date range: {start_date.strftime('%Y-%m-%d %H:%M')} to {end_date.strftime('%Y-%m-%d %H:%M')} UTC")
        return start_date, end_date
    
    # Automatic mode
    end_time_offset = time_settings.get('end_time_offset_minutes', 0)
    end_date = now - timedelta(minutes=end_time_offset)
    
    try:
        with engine.connect() as connection:
            query = text("SELECT MAX(timestamp) FROM raw_logs")
            last_timestamp_str = connection.execute(query).scalar_one_or_none()
    except Exception as e:
        msg = f"Could not query for last timestamp, maybe table doesn't exist? Error: {e}"
        logger.warning(msg)
        run_warnings.append(msg)
        last_timestamp_str = None

    if last_timestamp_str:
        last_run_date = datetime.fromisoformat(last_timestamp_str)
        if last_run_date.tzinfo is None:
            last_run_date = last_run_date.replace(tzinfo=timezone.utc)
        overlap = time_settings.get('start_time_overlap_minutes', 60)
        start_date = last_run_date - timedelta(minutes=overlap)
        logger.info(f"--> Last message in DB is from {last_run_date.strftime('%Y-%m-%d %H:%M')}. Fetching data since {start_date.strftime('%Y-%m-%d %H:%M')} UTC.")
    else:
        lookback = time_settings.get('max_lookback_days', 30)
        start_date = now - timedelta(days=lookback)
        logger.info(f"--> No previous data found. Fetching data for the last {lookback} days.")
        
    return start_date, end_date

def create_raw_table(engine):
    """Ensures the raw_logs table exists."""
    inspector = inspect(engine)
    if not inspector.has_table("raw_logs"):
        logger.info("Table 'raw_logs' not found. Creating it...")
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("""
                    CREATE TABLE raw_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        raw_content TEXT NOT NULL,
                        UNIQUE(timestamp, raw_content)
                    )
                """))
                connection.execute(text("CREATE INDEX IF NOT EXISTS idx_timestamp ON raw_logs (timestamp);"))
            logger.success("--> Table 'raw_logs' created successfully with a timestamp index and UNIQUE constraint.")
    else:
        logger.info("--> Table 'raw_logs' already exists.")

class DiscordFetchBot(discord.Client):
    """The bot class responsible for fetching messages."""
    def __init__(self, config, start_date, end_date, engine, run_warnings: list):
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.start_date = start_date
        self.end_date = end_date
        self.engine = engine
        self.summary = {}
        self.summary_message = ""
        self.run_warnings = run_warnings

    async def on_ready(self):
        """Called when the bot successfully logs in."""
        logger.info(f'--> Logged in as {self.user} to fetch data.')
        try:
            await self.fetch_and_store_data()
            start_str = self.start_date.strftime('%Y-%m-%d %H:%M')
            end_str = self.end_date.strftime('%Y-%m-%d %H:%M')
            
            summary_lines = [
                f"**Data Source:** `{self.summary.get('guild_name', 'N/A')}` / `#{self.summary.get('data_channel_name', 'N/A')}`",
                f"**Time Period Processed:** `{start_str}` to `{end_str}` (UTC)\n",
                f"**Fetch Results:**",
                f"- Messages Found: `{self.summary.get('messages_found', 0)}`",
                f"- New Messages Added to DB: `{self.summary.get('messages_added', 0)}`"
            ]
            finish_script(SCRIPT_NAME, self.config, summary_lines, self.run_warnings)
        except Exception as e:
            finish_script(SCRIPT_NAME, self.config, exception=e)
        finally:
            logger.info("Operation complete. Logging out from Discord.")
            await self.close()

    async def fetch_and_store_data(self):
        """Fetches messages and stores them in the raw SQLite database, gracefully skipping duplicates."""
        data_channel_id = self.config.get('secrets', {}).get('discord_data_channel_id')
        if not data_channel_id or "YOUR_DATA_CHANNEL_ID_HERE" in str(data_channel_id):
            raise ValueError("discord_data_channel_id is missing or not set in secrets.toml")
            
        try:
            channel_id_int = int(data_channel_id)
        except ValueError:
            raise ValueError(f"discord_data_channel_id '{data_channel_id}' is not a valid integer.")
            
        channel = self.get_channel(channel_id_int)
        if not channel:
            raise Exception(f"Could not find data channel with ID {data_channel_id}. Ensure the bot has access.")

        self.summary['guild_name'] = channel.guild.name if hasattr(channel, 'guild') else 'Direct Message'
        self.summary['data_channel_name'] = channel.name
        logger.info(f"Fetching messages from server: '{self.summary['guild_name']}', channel: #{channel.name}")

        messages_to_process = []
        fetch_counter = 0
        async for message in channel.history(limit=None, after=self.start_date, before=self.end_date, oldest_first=True):
            fetch_counter += 1
            if message.content:
                messages_to_process.append({
                    "timestamp": message.created_at.isoformat(),
                    "raw_content": clean_discord_escapes(message.content)
                })
            if fetch_counter % 500 == 0:
                logger.info(f"  - Discovered {fetch_counter} messages...")
        
        logger.info(f"--> Found {len(messages_to_process)} total messages with content.")
        self.summary['messages_found'] = len(messages_to_process)

        if not messages_to_process:
            logger.info("No new messages to add.")
            self.summary['messages_added'] = 0
            return

        df_new = pd.DataFrame(messages_to_process)
        
        # Insert rows one-by-one to gracefully handle duplicates
        rows_added = 0
        with self.engine.connect() as connection:
            with connection.begin():
                for _, row in df_new.iterrows():
                    try:
                        # Use INSERT OR IGNORE for SQLite to skip duplicates without erroring
                        insert_stmt = text("""
                            INSERT INTO raw_logs (timestamp, raw_content) 
                            VALUES (:timestamp, :raw_content)
                        """)
                        if self.engine.dialect.name == 'sqlite':
                             insert_stmt = text("""
                                INSERT OR IGNORE INTO raw_logs (timestamp, raw_content) 
                                VALUES (:timestamp, :raw_content)
                            """)
                        
                        result = connection.execute(insert_stmt, row.to_dict())
                        if result.rowcount > 0:
                            rows_added += 1
                    except exc.IntegrityError:
                        # This is a fallback for other DBs if they don't support INSERT OR IGNORE
                        # and ensures the script doesn't crash.
                        logger.trace(f"Skipping duplicate row: {row['timestamp']}")
                        continue

        self.summary['messages_added'] = rows_added
        logger.success(f"--> Successfully added {rows_added} new messages to the database. Skipped {len(df_new) - rows_added} duplicates.")

def main():
    """Main execution function for the fetch data script."""
    config = load_config()
    loguru_setup(config, PROJECT_ROOT)
    logger.info(f"{f' Starting {SCRIPT_NAME} ':=^80}")
    
    raw_db_uri = config.get('databases', {}).get('raw_db_uri')
    engine = get_db_engine(raw_db_uri) if raw_db_uri else None
    if not engine:
        finish_script(SCRIPT_NAME, config, exception=ValueError("Missing 'raw_db_uri' in config.toml or failed to connect."))
        return
        
    create_raw_table(engine)
    run_warnings = []
    start_date, end_date = get_date_range(config, engine, run_warnings)
    
    bot = DiscordFetchBot(config, start_date, end_date, engine, run_warnings)

    try:
        token = config.get('secrets', {}).get('discord_bot_token')
        if not token or "YOUR_DISCORD_BOT_TOKEN_HERE" in token:
            raise ValueError("Discord bot token is missing or has not been set in src/secrets.toml")
        
        logger.info("Starting Discord bot to fetch data...")
        bot.run(token)
        
    except Exception as e:
        if isinstance(e, discord.errors.LoginFailure):
            e = ValueError("Login failed: Improper token provided. Check your discord_bot_token in src/secrets.toml")
        finish_script(SCRIPT_NAME, config, exception=e)
    finally:
        if engine:
            engine.dispose()
            logger.info("Database connection closed.")
        logger.info(f"{f' Finished {SCRIPT_NAME} ':=^80}")

if __name__ == "__main__":
    main()
