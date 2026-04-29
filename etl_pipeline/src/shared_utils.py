# src/shared_utils.py

import sys
try:
    import tomllib # For Python 3.11+
except ImportError:
    import tomli as tomllib # type: ignore # Fallback for older Python
from pathlib import Path
from sqlalchemy import create_engine
from datetime import datetime, timedelta, timezone
import os
import requests
import json
import pandas as pd
import itertools

from loguru import logger

# --- Constants & Paths ---
# Monorepo centralized paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SHARED_CONFIG_DIR = Path(os.getenv("SHARED_CONFIG_DIR", BASE_DIR / "shared_config"))
SHARED_SECRETS_DIR = Path(os.getenv("SHARED_SECRETS_DIR", BASE_DIR / "shared_secrets"))
SHARED_DATA_DIR = Path(os.getenv("SHARED_DATA_DIR", BASE_DIR / "shared_data"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / 'src'
DATA_DIR = SHARED_DATA_DIR / 'databases'
EXPORTS_DIR = SHARED_DATA_DIR / 'exports'
STATES_DIR = SHARED_DATA_DIR / 'states'
CACHES_DIR = SHARED_DATA_DIR / 'caches'
LOGS_DIR = SHARED_DATA_DIR / 'logs' / 'etl'
SUMMARIES_DIR = SHARED_DATA_DIR / 'reports'
CONFIG_PATH = SHARED_CONFIG_DIR / 'config.toml'
SECRETS_PATH = SHARED_SECRETS_DIR / 'secrets.toml'

# --- Ensure Directories Exist ---
DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
STATES_DIR.mkdir(parents=True, exist_ok=True)
CACHES_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

def write_summary_file(script_name: str, summary_content: str):
    """Writes a summary file for the script run."""
    run_timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')
    summary_file_name = f"{script_name}_summary_{run_timestamp}.txt"
    summary_file_path = SUMMARIES_DIR / summary_file_name
    try:
        with open(summary_file_path, 'w', encoding='utf-8') as f:
            f.write(summary_content)
        logger.info(f"Summary written to {summary_file_path}")
    except Exception as e:
        logger.error(f"Failed to write summary file: {e}")

def load_config():
    """Loads configuration from config.toml and secrets.toml."""
    # Note: We can't use the configured logger here because the config isn't loaded yet.
    # Loguru's default logger will print to stderr, which is acceptable for this step.
    logger.info("Loading configuration files...")
    try:
        with open(CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        logger.success("--> config.toml loaded successfully.")

        with open(SECRETS_PATH, "rb") as f:
            secrets = tomllib.load(f)
        config['secrets'] = secrets
        logger.success("--> secrets.toml loaded successfully.")

        return config
    except FileNotFoundError as e:
        logger.critical(f"FATAL: Configuration file not found: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"FATAL: Failed to parse a config file: {e}")
        sys.exit(1)

def get_db_engine(db_uri: str):
    """Creates a SQLAlchemy engine for a given database URI."""
    try:
        if db_uri.startswith('sqlite'):
            relative_path = db_uri.split('///')[1]
            # Map any data/xxx.db strings straight into the shared database volume
            db_file_path = DATA_DIR / Path(relative_path).name
            db_file_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{db_file_path}")
            logger.info(f"SQLite database engine created for: {db_file_path}")
        else:
            engine = create_engine(db_uri)
            logger.info("Remote PostgreSQL database engine configured.")
        return engine
    except Exception as e:
        logger.error(f"Failed to create database engine for URI {db_uri}: {e}", exc_info=True)
        return None

def get_time_periods(config, run_time=None):
    """
    Calculates all dynamic time period start and end dates.
    If run_time is provided, calculations are based on that fixed point in time.
    Otherwise, it uses the current time.
    """
    if run_time is None:
        run_time = datetime.now(timezone.utc)
        
    start_of_today = run_time.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_7_days = (run_time - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_30_days = (run_time - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_year = run_time.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    all_time_start = datetime.min.replace(tzinfo=timezone.utc)

    periods = {
        "All_Time": {"start": all_time_start, "end": run_time, "label": "All Time"},
        "This_Year": {"start": start_of_year, "end": run_time, "label": f"This Year ({run_time.year})"},
        "Last_30_Days": {"start": start_of_30_days, "end": run_time, "label": "Last 30 Days"},
        "Last_7_Days": {"start": start_of_7_days, "end": run_time, "label": "Last 7 Days"},
        "Today": {"start": start_of_today, "end": run_time, "label": "Today"}
    }
    return periods

def post_to_discord_webhook(webhook_url: str, message: str, color: int = None):
    """Posts a message to a Discord channel using a webhook."""
    if not webhook_url or "YOUR_WEBHOOK_URL_HERE" in webhook_url:
        logger.warning("Discord webhook URL is not configured. Skipping summary post.")
        return

    # Determine embed color based on message content or override
    if "❌" in message or "FAILED" in message:
        final_color = 15158332  # Red
    elif "⚠️" in message and color is None:
        final_color = 15844367  # Yellow/Orange
    elif color is not None:
        final_color = color
    else:
        final_color = 3066993   # Green

    # Discord embed description limit is 4096 characters
    if len(message) > 4096:
        message = message[:4090] + '...'

    embed = {
        "description": message,
        "color": final_color,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    headers = {"Content-Type": "application/json"}
    payload = json.dumps({"embeds": [embed]})

    try:
        response = requests.post(webhook_url, data=payload, headers=headers, timeout=10)
        if response.status_code in [200, 204]:
            logger.info("--> Summary posted to Discord via webhook.")
        else:
            logger.error(f"Failed to post to Discord webhook. Status: {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred while sending request to Discord webhook: {e}", exc_info=True)

def finish_script(script_name: str, config: dict, summary_data=None, run_warnings: list=None, exception: Exception=None):
    """
    Standardized completion handler for ETL scripts.
    Formats the output, logs errors, and dispatches the Discord Webhook & local text summary.
    """
    project_name = config.get('general', {}).get('project_name', 'Unnamed Project')
    webhook_url = config.get('secrets', {}).get('discord_webhook_url')
    
    if exception:
        logger.critical(f"An unexpected error occurred in {script_name}: {exception}", exc_info=True)
        summary = f"**❌ {project_name}: {script_name} FAILED**\n**Error:**\n```\n{exception}\n```"
    else:
        # Allow passing pre-formatted strings directly (e.g. Skipped or manually formatted errors)
        if isinstance(summary_data, str) and any(x in summary_data for x in ["**✅", "**❌", "**⚠️"]):
            summary = summary_data
            if run_warnings:
                summary += "\n\n**⚠️ Warnings & Errors Encountered:**\n" + "\n".join(f"- {w}" for w in run_warnings)
        else:
            lines = [f"**✅ {project_name}: {script_name} Complete**\n"]
            if summary_data:
                lines.extend(summary_data if isinstance(summary_data, list) else [str(summary_data)])
            
            if run_warnings:
                lines.append("\n**⚠️ Warnings & Errors Encountered:**")
                for w in run_warnings:
                    lines.append(f"- {w}")
            summary = "\n".join(lines)

    if summary:
        write_summary_file(script_name, summary)
        if webhook_url:
            post_to_discord_webhook(webhook_url, summary)

def validate_mapping_rules(rules):
    """Checks for overlapping time ranges for the same source username and logs a warning."""
    logger.info("Validating username mapping rules for conflicts...")
    def parse_date(date_str, default):
        if not date_str: return default
        return pd.to_datetime(date_str, errors='coerce', utc=True)

    processed_rules = []
    for i, rule in enumerate(rules):
        start = parse_date(rule.get('start_date'), pd.Timestamp.min.replace(tzinfo=timezone.utc))
        end = parse_date(rule.get('end_date'), pd.Timestamp.max.replace(tzinfo=timezone.utc))
        if pd.isna(start) or pd.isna(end):
            logger.warning(f"Skipping rule {i+1} due to invalid date format: {rule}")
            continue
        processed_rules.append({
            'sources': set(rule.get('source_usernames', [])),
            'start': start,
            'end': end,
            'rule_index': i + 1
        })

    for (r1, r2) in itertools.combinations(processed_rules, 2):
        common_sources = r1['sources'].intersection(r2['sources'])
        if not common_sources:
            continue

        if r1['start'] < r2['end'] and r2['start'] < r1['end']:
            logger.warning(
                f"Conflict detected in username mapping! "
                f"Rule #{r1['rule_index']} and Rule #{r2['rule_index']} both apply to "
                f"'{', '.join(common_sources)}' during an overlapping time period. "
                f"The rule that appears later in the config will take precedence."
            )
    logger.info("--> Validation of mapping rules complete.")

def apply_manual_name_mappings(df, rules, username_columns):
    """Applies manual username mapping rules to the specified columns in a DataFrame."""
    if not rules or df.empty:
        return df

    df_copy = df.copy()
    if 'Timestamp' in df_copy.columns:
        df_copy['Timestamp'] = pd.to_datetime(df_copy['Timestamp'], errors='coerce', utc=True)
    
    for i, rule in reversed(list(enumerate(rules))):
        target_name = rule.get('target_username')
        source_names = rule.get('source_usernames', [])
        if not target_name or not source_names:
            continue

        start_date = pd.to_datetime(rule.get('start_date'), errors='coerce', utc=True)
        end_date = pd.to_datetime(rule.get('end_date'), errors='coerce', utc=True)

        time_mask = pd.Series(True, index=df_copy.index)
        if 'Timestamp' in df_copy.columns:
            if pd.notna(start_date):
                time_mask &= (df_copy['Timestamp'] >= start_date)
            if pd.notna(end_date):
                time_mask &= (df_copy['Timestamp'] < end_date)

        for col in username_columns:
            if col in df_copy.columns:
                name_mask = df_copy[col].isin(source_names)
                combined_mask = time_mask & name_mask
                if combined_mask.any():
                    df_copy.loc[combined_mask, col] = target_name
    
    return df_copy