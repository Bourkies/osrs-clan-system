import requests
import pandas as pd
import sys
from datetime import datetime, timedelta, timezone
import json
import time
from sqlalchemy import create_engine, inspect, text
from loguru import logger

from shared_utils import (
    load_config, get_db_engine, PROJECT_ROOT, CACHES_DIR, DATA_DIR, finish_script
)
from loguru_setup import loguru_setup

SCRIPT_NAME = "2_fetch_item_prices"

def get_or_update_item_mapping(config: dict, run_warnings: list, force_update: bool = False) -> dict:
    """
    Fetches the item ID to name mapping from the Wiki API.
    Caches the mapping locally to avoid fetching it on every run.
    An update can be forced if a configured item is not found in the local cache.
    """
    mapping_file = CACHES_DIR / 'item_mapping.json'
    user_agent = config.get('secrets', {}).get('api_settings', {}).get('user_agent')
    
    if not force_update and mapping_file.exists():
        logger.info("Loading cached item mapping from file...")
        try:
            with open(mapping_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            msg = f"Could not read cached item mapping file. Will fetch from API. Error: {e}"
            logger.warning(msg)
            run_warnings.append(msg)

    logger.info(f"{'Forcing update of' if force_update else 'Fetching'} item mapping from Wiki API...")
    url = "https://prices.runescape.wiki/api/v1/osrs/mapping"
    headers = {'User-Agent': user_agent}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        mapping_data = response.json()
        
        # Create a more efficient lookup dictionary: {id: {name: '...', ...}}
        id_to_item_map = {str(item['id']): item for item in mapping_data}
        
        with open(mapping_file, 'w') as f:
            json.dump(id_to_item_map, f, indent=2)
        logger.success(f"--> Successfully saved item mapping with {len(id_to_item_map)} items.")
        return id_to_item_map
    except (requests.RequestException, json.JSONDecodeError) as e:
        logger.critical(f"Failed to fetch or save item mapping: {e}")
        run_warnings.append(f"Failed to fetch or save item mapping: {e}")
        return {}

def get_wiki_timeseries(item_id: str, item_name: str, user_agent: str, run_warnings: list, timestep: str = '24h') -> list:
    """
    Fetches timeseries data for a given item from the OSRS Wiki API.
    Timestep can be '5m', '1h', '6h', or '24h'.
    """
    # A descriptive User-Agent is required by the OSRS Wiki API.
    headers = {'User-Agent': user_agent}
    # The API uses item IDs for timeseries lookups.
    # The 'from' parameter is only valid for 5m and 1h timesteps, so we don't use it here.
    url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep={timestep}&id={item_id}"

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        data = response.json().get('data', [])
        if not data:
            msg = f"No price data returned from API for '{item_name}' (ID: {item_id})"
            logger.warning(msg)
            run_warnings.append(msg)
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            msg = f"Item '{item_name}' (ID: {item_id}) not found on the Wiki API (404)."
            logger.error(msg)
            run_warnings.append(msg)
        else:
            msg = f"HTTP error fetching data for '{item_name}' (ID: {item_id}): {e}"
            logger.error(msg)
            run_warnings.append(msg)
    except requests.exceptions.RequestException as e:
        msg = f"Request failed for '{item_name}' (ID: {item_id}): {e}"
        logger.error(msg)
        run_warnings.append(msg)
    except Exception as e:
        msg = f"An unexpected error occurred while fetching data for '{item_name}' (ID: {item_id}): {e}"
        logger.error(msg, exc_info=True)
        run_warnings.append(msg)
    
    return []

def get_last_timestamp_for_item(engine, item_id: str) -> pd.Timestamp:
    """
    Finds the most recent timestamp for a given item ID in the database.
    Returns a timezone-aware pandas Timestamp or None if not found.
    """
    try:
        with engine.connect() as connection:
            query = text("SELECT MAX(timestamp) FROM item_prices WHERE item_id = :item_id")
            result = connection.execute(query, {"item_id": item_id}).scalar_one_or_none()
            if result:
                # The database stores timestamps as strings, convert back to a pandas Timestamp
                return pd.to_datetime(result, utc=True)
    except Exception as e:
        logger.error(f"Error getting last timestamp for item ID '{item_id}': {e}")
    return None

def main():
    config = load_config()
    loguru_setup(config, PROJECT_ROOT)
    logger.info(f"{f' Starting {SCRIPT_NAME} ':=^80}")

    run_warnings = []
    engine = None
    
    try:
        # --- Configuration ---
        api_settings = config.get('secrets', {}).get('api_settings', {})
        user_agent = api_settings.get('user_agent')
        request_delay = api_settings.get('request_delay_seconds', 1.0)

        if not user_agent or "YOUR_APP_NAME" in user_agent:
            raise ValueError("A valid User-Agent is required for the Wiki API. Please set 'user_agent' in the [api_settings] section of your secrets.toml file.")

        # Get the list of items to track from the item_value_overrides section
        all_item_overrides = config.get('item_value_overrides', {})
        if not all_item_overrides:
            raise ValueError("No items found in [item_value_overrides] section of config.toml. Exiting.")

        # Define the database for item prices
        db_uri = f"sqlite:///{DATA_DIR / 'item_prices.db'}"
        engine = get_db_engine(db_uri)
        if not engine:
            raise ValueError("Failed to create database engine.")

        # Ensure the table exists
        try:
            with engine.connect() as connection:
                with connection.begin():
                    connection.execute(text("""
                        CREATE TABLE IF NOT EXISTS item_prices (
                            item_id TEXT NOT NULL,
                            item_name TEXT NOT NULL,
                            timestamp TEXT NOT NULL,
                            avg_high_price INTEGER,
                            avg_low_price INTEGER,
                            high_price_volume INTEGER,
                            low_price_volume INTEGER,
                            PRIMARY KEY (item_id, timestamp)
                        )
                    """))
                    connection.execute(text("CREATE INDEX IF NOT EXISTS idx_item_name ON item_prices (item_name);"))
            logger.info("Database table 'item_prices' is ready.")
        except Exception as e:
            raise RuntimeError(f"Failed to create or verify database table: {e}") from e

        # --- Item Mapping ---
        # Get the mapping of item IDs to names, updating if necessary
        item_mapping = get_or_update_item_mapping(config, run_warnings)
        if not item_mapping:
            raise RuntimeError("Could not load item mapping. Cannot proceed without it.")

        # --- Main Loop ---
        items_to_fetch = {}
        mapping_is_stale = False
        for item_name, value in all_item_overrides.items():
            if isinstance(value, list) and len(value) == 2:
                item_id = str(value[1]) # Ensure ID is a string
                items_to_fetch[item_name] = item_id
                if item_id not in item_mapping:
                    msg = f"Item '{item_name}' (ID: {item_id}) from config not found in local item mapping. Will force an update."
                    logger.warning(msg)
                    run_warnings.append(msg)
                    mapping_is_stale = True
            else:
                logger.trace(f"Skipping price fetch for '{item_name}': not configured for dynamic pricing.")

        if mapping_is_stale:
            item_mapping = get_or_update_item_mapping(config, run_warnings, force_update=True)

        all_new_records = []
        failed_items = []
        run_start_time = datetime.now(timezone.utc)

        if not items_to_fetch:
            summary = f"**⚠️ {config.get('general', {}).get('project_name', 'Unnamed Project')}: {SCRIPT_NAME} Complete**\n\nNo items are configured for dynamic price fetching. Exiting."
            logger.warning("No items are configured for dynamic price fetching. Exiting.")
            finish_script(SCRIPT_NAME, config, summary, run_warnings)
            return
        
        total_items_to_fetch = len(items_to_fetch)
        logger.info(f"Found {total_items_to_fetch} items configured for dynamic price fetching.")

        for i, (item_name, item_id) in enumerate(items_to_fetch.items(), 1):
            # Log progress every 10 items to show the script is still working
            if i > 1 and i % 10 == 0 and i < total_items_to_fetch:
                logger.info(f"Progress: {i} of {total_items_to_fetch} items processed...")

            wiki_item_details = item_mapping.get(item_id)
            if not wiki_item_details:
                logger.error(f"Skipping '{item_name}' (ID: {item_id}) as it was not found in the updated Wiki item mapping.")
                failed_items.append(f"'{item_name}' (ID: {item_id}) - Not found in Wiki mapping")
                continue

            wiki_name = wiki_item_details.get('name', 'Unknown Wiki Name')
            logger.debug(f"Processing '{item_name}' (ID: {item_id}). Wiki name: '{wiki_name}'")
            last_known_ts = get_last_timestamp_for_item(engine, item_id)
            
            api_data = get_wiki_timeseries(item_id, item_name, user_agent, run_warnings, '24h')
            if not api_data:
                failed_items.append(f"'{item_name}' (ID: {item_id}) - No price data from API")
                time.sleep(request_delay) # Be polite to the API
                continue

            for record in api_data:
                # The API gives timestamps in seconds, convert to datetime.
                # We add a check to ensure we don't re-insert the 'from_time' record itself.
                record_ts = pd.to_datetime(record['timestamp'], unit='s', utc=True)
                if not last_known_ts or record_ts > last_known_ts:
                    all_new_records.append({
                        'item_id': item_id,
                        'item_name': item_name,
                        'timestamp': record_ts.isoformat(), # Store as ISO string
                        'avg_high_price': record.get('avgHighPrice'),
                        'avg_low_price': record.get('avgLowPrice'),
                        'high_price_volume': record.get('highPriceVolume'),
                        'low_price_volume': record.get('lowPriceVolume')
                    })
            
            # Be polite to the API, wait a bit between requests
            time.sleep(request_delay)

        # --- Save to Database ---
        if all_new_records:
            df_new_prices = pd.DataFrame(all_new_records)
            
            min_ts = pd.to_datetime(df_new_prices['timestamp']).min().strftime('%Y-%m-%d')
            max_ts = pd.to_datetime(df_new_prices['timestamp']).max().strftime('%Y-%m-%d')
            
            logger.info(f"Found {len(df_new_prices)} new price records to add across all items.")
            logger.info(f"--> New data ranges from approximately {min_ts} to {max_ts}.")
            
            try:
                df_new_prices.to_sql('item_prices', engine, if_exists='append', index=False)
                logger.success(f"--> Successfully appended new price data. The database will ignore any duplicates.")
            except Exception as e:
                msg = f"Could not append all new price data, some may have been duplicates. Error: {e}"
                logger.warning(msg)
                run_warnings.append(msg)

        else:
            logger.info("No new price records to add. Database is up to date.")

        # --- Summary ---
        failed_items_str = ""
        if failed_items:
            failed_items_str = "\n**⚠️ Failed to fetch data for:**\n- " + "\n- ".join(failed_items)

        summary_lines = [
            f"**Run Time:** `{run_start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}`",
            f"**Items Scanned for Dynamic Pricing:** `{len(items_to_fetch)}`",
            f"**New Price Records Added:** `{len(all_new_records)}`"
        ]
        if failed_items_str:
            summary_lines.append(failed_items_str)
            
        finish_script(SCRIPT_NAME, config, summary_lines, run_warnings)

    except Exception as e:
        finish_script(SCRIPT_NAME, config, exception=e)
    finally:
        if engine: engine.dispose()
        logger.info("Database connection closed.")
        logger.info(f"{f' Finished {SCRIPT_NAME} ':=^80}")

if __name__ == "__main__":
    main()