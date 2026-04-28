import pandas as pd
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore
import os
import json
import re
from sqlalchemy import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
import itertools
from loguru import logger

from shared_utils import (
    load_config, get_db_engine, DATA_DIR, SHARED_CONFIG_DIR,
    PROJECT_ROOT, BASE_DIR, get_time_periods,
    validate_mapping_rules, apply_manual_name_mappings, finish_script
)
from loguru_setup import loguru_setup

SCRIPT_NAME = "5_transform_data"

# --- Helper Functions ---

def time_str_to_seconds(time_str):
    """Converts a time string (e.g., '1:23.4' or '1:15:45') to seconds."""
    if not isinstance(time_str, str):
        return float('inf')
    parts = time_str.split(':')
    seconds = 0
    try:
        if len(parts) == 3:  # H:M:S
            seconds += int(parts[0]) * 3600
            seconds += int(parts[1]) * 60
            seconds += float(parts[2])
        elif len(parts) == 2:  # M:S
            seconds += int(parts[0]) * 60
            seconds += float(parts[1])
        elif len(parts) == 1:  # S
            seconds += float(parts[0])
    except (ValueError, IndexError):
        return float('inf')
    return seconds

def calculate_ticks(time_str):
    """
    Converts a time string to OSRS game ticks (0.6s).
    Implements 'Tick Pessimism' for rounded times:
    - If precise (has decimal): round(seconds / 0.6)
    - If rounded (no decimal): assumes the worst-case (slowest) tick that rounds to this second.
    """
    if not isinstance(time_str, str):
        return float('inf')
    
    seconds = time_str_to_seconds(time_str)
    if seconds == float('inf'):
        return float('inf')

    # Check for precision by looking for a decimal point
    if "." in time_str:
        return round(seconds / 0.6)
    else:
        # Pessimistic approach: Find the largest tick count k where round(k * 0.6) == seconds
        # Logic: k * 0.6 < seconds + 0.5  =>  k < (seconds + 0.5) / 0.6
        return int((seconds + 0.5) / 0.6 - 1e-9)

def format_ticks_to_time(ticks):
    """Converts OSRS ticks back to a readable time string (MM:SS.ss)."""
    if ticks == float('inf'):
        return "0:00"
    
    total_seconds = round(ticks * 0.6, 2)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02}:{seconds:05.2f}"
    else:
        return f"{minutes}:{seconds:05.2f}"

def prepare_dataframe(df, use_enriched_db):
    """Prepares DataFrames by establishing the core Entity and Display Names."""
    if df.empty: return df
    
    df['Raw_RSN'] = df['Username']
    
    if use_enriched_db:
        if 'Discord_ID' in df.columns:
            df['Entity_ID'] = df['Discord_ID'].astype(str).replace(['nan', 'None', ''], pd.NA).fillna(df['Username'])
        else:
            df['Entity_ID'] = df['Username']
            
        if 'Discord_Name' in df.columns:
            df['Display_Name'] = df['Discord_Name'].replace(['nan', 'None', ''], pd.NA).fillna(df['Username'])
        else:
            df['Display_Name'] = df['Username']

        if 'Is_Retained' not in df.columns:
            df['Is_Retained'] = True
        else:
            df['Is_Retained'] = df['Is_Retained'].fillna(True).astype(bool)
    else:
        df['Entity_ID'] = df['Username']
        df['Display_Name'] = df['Username']
        df['Is_Retained'] = True
        
    return df

def get_records_for_period(df, start_date=None, end_date=None):
    if df.empty: return pd.DataFrame()
    df_copy = df.copy()
    if 'Timestamp' not in df_copy.columns: return pd.DataFrame()
    df_copy['Timestamp'] = pd.to_datetime(df_copy['Timestamp'], errors='coerce', utc=True)
    df_copy.dropna(subset=['Timestamp'], inplace=True)
    
    if start_date: df_copy = df_copy[df_copy['Timestamp'] >= start_date]
    if end_date: df_copy = df_copy[df_copy['Timestamp'] < end_date]
    return df_copy

def create_metadata_tables(engine, config, periods, run_warnings):
    """Creates tables for run metadata and dashboard config, including dynamic labels."""
    logger.info("Creating/updating metadata tables...")
    run_time_iso = periods['All_Time']['end'].isoformat()
    
    df_meta = pd.DataFrame([{'last_updated_utc': run_time_iso}])
    df_meta.to_sql('run_metadata', engine, if_exists='replace', index=False)
    
    # Load settings and group/item orders from historical files
    pb_historical_file = SHARED_CONFIG_DIR / config.get('historical_data', {}).get('personal_bests_file')
    with open(pb_historical_file, "rb") as f:
        pb_hist_data = tomllib.load(f)
												  
    pb_item_orders = {g.get('title'): [r.get('name') for r in g.get('records', [])] for g in pb_hist_data.get('groups', [])}

    clog_historical_file = SHARED_CONFIG_DIR / config.get('historical_data', {}).get('collection_log_file')
    with open(clog_historical_file, "rb") as f:
        clog_hist_data = tomllib.load(f)
    
    clog_group_order = [g.get('title') for g in clog_hist_data.get('groups', [])]
    clog_item_orders = {g.get('title'): g.get('items', []) for g in clog_hist_data.get('groups', [])}

    df_config = pd.DataFrame([
        {'key': 'custom_lookback_days', 'value': str(config['dashboard_settings'].get('custom_lookback_days', 14))},
        {'key': 'top_drops_limit', 'value': str(config['dashboard_settings'].get('top_drops_limit', 50))},
        {'key': 'label_prev_week', 'value': periods['Prev_Week']['label']},
        {'key': 'label_prev_month', 'value': periods['Prev_Month']['label']},
        {'key': 'label_ytd', 'value': periods['YTD']['label']},
        {'key': 'label_custom_days', 'value': periods['Custom_Days']['label']},
        
        {'key': 'pb_other_group_name', 'value': pb_hist_data.get('other_group_name', 'Miscellaneous PBs')},
        {'key': 'pb_default_group_sort', 'value': pb_hist_data.get('default_group_sort', 'config')},
        {'key': 'pb_default_item_sort', 'value': pb_hist_data.get('default_item_sort', 'alphabetical')},
        {'key': 'pb_group_order', 'value': json.dumps(list(pb_item_orders.keys()))},
        {'key': 'pb_item_orders', 'value': json.dumps(pb_item_orders)},

        {'key': 'clog_other_group_name', 'value': clog_hist_data.get('other_group_name', 'Miscellaneous Drops')},
        {'key': 'clog_default_group_sort', 'value': clog_hist_data.get('default_group_sort', 'config')},
        {'key': 'clog_default_item_sort', 'value': clog_hist_data.get('default_item_sort', 'alphabetical')},
        {'key': 'clog_group_order', 'value': json.dumps(clog_group_order)},
        {'key': 'clog_item_orders', 'value': json.dumps(clog_item_orders)},
    ])
    df_config.to_sql('dashboard_config', engine, if_exists='replace', index=False)
    logger.success("--> Metadata tables updated successfully.")

# --- Exclusion Functions ---

def apply_exclusion_filters(df, config, run_warnings):
    """Filters out records based on configured date ranges and types."""
    exclusion_ranges = config.get('exclusion_settings', {}).get('ranges', [])
    if not exclusion_ranges or df.empty:
        return df

    logger.info("Applying exclusion filters (Temporary Game Modes)...")
    initial_count = len(df)
    
    # Create a mask for rows to DROP
    drop_mask = pd.Series(False, index=df.index)

    for rule in exclusion_ranges:
        try:
            start_str = rule.get('start_date')
            end_str = rule.get('end_date')
            exclude_types = rule.get('exclude_types', [])
            
            if not start_str or not end_str or not exclude_types:
                continue

            start_date = pd.to_datetime(start_str, utc=True)
            end_date = pd.to_datetime(end_str, utc=True)

            # Time filter
            time_mask = (df['Timestamp'] >= start_date) & (df['Timestamp'] <= end_date)
            
            if not time_mask.any():
                continue

            # Type filter
            if "All Broadcasts" in exclude_types:
                drop_mask |= time_mask
                logger.info(f"  - Dropping all broadcasts between {start_str} and {end_str} ({time_mask.sum()} rows found in range)")
            elif 'Broadcast_Type' in df.columns:
                type_mask = df['Broadcast_Type'].isin(exclude_types)
                combined_mask = time_mask & type_mask
                drop_mask |= combined_mask
                if combined_mask.any():
                    logger.info(f"  - Dropping specific types {exclude_types} between {start_str} and {end_str} ({combined_mask.sum()} rows)")
                    
        except Exception as e:
            msg = f"Failed to apply exclusion rule {rule}: {e}"
            logger.warning(msg)
            run_warnings.append(msg)

    if drop_mask.any():
        df_filtered = df[~drop_mask].copy()
        logger.success(f"--> Excluded {initial_count - len(df_filtered)} records based on exclusion settings.")
        return df_filtered
    
    return df

# --- Report Generators ---

def generate_leaderboard_reports(df_chat, df_broadcasts, config, periods, run_warnings, entity_to_name=None, global_drop_leavers=False):
    logger.info("Generating all configured leaderboard reports...")
    reports = {}
    report_configs = config['dashboard_settings'].get('leaderboard_reports', [])
    
    for rc in report_configs:
        try:
            name = rc['report_name']
            source_df_name = rc.get('source_table', 'clan_broadcasts')
            df_source = df_chat if source_df_name == 'chat' else df_broadcasts
            
            df_filtered = df_source.copy()

            include_leavers = rc.get('include_leavers', False)
            if not include_leavers and global_drop_leavers and 'Is_Retained' in df_filtered.columns:
                df_filtered = df_filtered[df_filtered['Is_Retained']]

            if 'broadcast_type' in rc:
                broadcast_types = rc['broadcast_type']
                if isinstance(broadcast_types, str):
                    # Handle the original case of a single string for backward compatibility
                    df_filtered = df_filtered[df_filtered['Broadcast_Type'] == broadcast_types]
                elif isinstance(broadcast_types, list):
                    # Handle the new case of a list of strings
                    df_filtered = df_filtered[df_filtered['Broadcast_Type'].isin(broadcast_types)]
            
            if 'item_name_filter' in rc:
                 df_filtered = df_filtered[df_filtered['Item_Name'] == rc['item_name_filter']]

            if 'search_phrases' in rc:
                search_regex = '|'.join(rc['search_phrases'])
                df_filtered = df_filtered[df_filtered['Content'].str.contains(search_regex, case=False, na=False)]
            
            if df_filtered.empty:
                msg = f"Skipping leaderboard report '{name}': No source data after filtering."
                logger.warning(msg)
                run_warnings.append(msg)
                reports[name] = pd.DataFrame()
                continue
            
            use_raw_rsn = rc.get('use_raw_rsn', False)
            group_by_col = rc['group_by_column']
            original_group_by = group_by_col
            
            if group_by_col == 'Username':
                if use_raw_rsn and 'Raw_RSN' in df_filtered.columns:
                    group_by_col = 'Raw_RSN'
                elif 'Entity_ID' in df_filtered.columns:
                    group_by_col = 'Entity_ID'

            aggregations = rc.get('aggregations', {})
            
            agg_spec = {}
            if 'Count' in aggregations:
                agg_spec['Count_All_Time'] = pd.NamedAgg(column=aggregations['Count'], aggfunc='count')
            if 'Value' in aggregations:
                df_filtered[aggregations['Value']] = pd.to_numeric(df_filtered[aggregations['Value']], errors='coerce').fillna(0)
                agg_spec['Value_All_Time'] = pd.NamedAgg(column=aggregations['Value'], aggfunc='sum')

            if not agg_spec:
                msg = f"No aggregations defined for report '{name}'. Skipping."
                logger.warning(msg)
                run_warnings.append(msg)
                continue

            df_summary = df_filtered.groupby(group_by_col).agg(**agg_spec).reset_index()

            for period_key, dates in periods.items():
                if period_key == "All_Time": continue
                df_period = get_records_for_period(df_filtered, start_date=dates['start'], end_date=dates['end'])
                
                period_agg_spec = {}
                if 'Count' in aggregations: period_agg_spec[f'Count_{period_key}'] = pd.NamedAgg(column=aggregations['Count'], aggfunc='count')
                if 'Value' in aggregations: period_agg_spec[f'Value_{period_key}'] = pd.NamedAgg(column=aggregations['Value'], aggfunc='sum')
                
                if not df_period.empty and period_agg_spec:
                    period_agg = df_period.groupby(group_by_col).agg(**period_agg_spec).reset_index()
                    df_summary = pd.merge(df_summary, period_agg, on=group_by_col, how='left')
                else:
                    if 'Count' in aggregations: df_summary[f'Count_{period_key}'] = 0
                    if 'Value' in aggregations: df_summary[f'Value_{period_key}'] = 0

            for col in df_summary.columns:
                if 'Count_' in col or 'Value_' in col:
                    df_summary[col] = df_summary[col].fillna(0).astype(int)
            
            if original_group_by == 'Username':
                if group_by_col == 'Raw_RSN':
                    df_summary['Username'] = df_summary['Raw_RSN']
                    df_summary.drop(columns=['Raw_RSN'], inplace=True)
                elif group_by_col == 'Entity_ID':
                    if entity_to_name:
                        df_summary['Username'] = df_summary['Entity_ID'].map(entity_to_name).fillna(df_summary['Entity_ID'])
                    else:
                        df_summary['Username'] = df_summary['Entity_ID']
                    df_summary.drop(columns=['Entity_ID'], inplace=True)
                    
                if 'Username' in df_summary.columns:
                    cols = ['Username'] + [c for c in df_summary.columns if c != 'Username']
                    df_summary = df_summary[cols]

            reports[name] = df_summary
            logger.info(f"--> Generated leaderboard report '{name}' with {len(df_summary)} entries.")
        except Exception as e:
            msg = f"Failed to generate leaderboard report '{rc.get('report_name', 'Unknown')}': {e}"
            logger.error(msg, exc_info=True)
            run_warnings.append(msg)
            
    return reports

def generate_detailed_reports(df_broadcasts, config, periods, run_warnings, global_drop_leavers=False):
    logger.info("Generating all configured detailed reports...")
    reports = {}
    report_configs = config['dashboard_settings'].get('detailed_reports', [])

    for rc in report_configs:
        try:
            name_prefix = rc['report_name_prefix']
            broadcast_types = rc['broadcast_types']
            
            df_filtered = df_broadcasts[df_broadcasts['Broadcast_Type'].isin(broadcast_types)].copy()
            
            include_leavers = rc.get('include_leavers', False)
            if not include_leavers and global_drop_leavers and 'Is_Retained' in df_filtered.columns:
                df_filtered = df_filtered[df_filtered['Is_Retained']]
                
            use_raw_rsn = rc.get('use_raw_rsn', False)
            if use_raw_rsn and 'Raw_RSN' in df_filtered.columns:
                df_filtered['Username'] = df_filtered['Raw_RSN']
            
            if not df_filtered.empty:
                if 'Item_Value' in df_filtered.columns:
                     df_filtered['Item_Value'] = pd.to_numeric(df_filtered['Item_Value'], errors='coerce').fillna(0)
                df_filtered['Timestamp'] = pd.to_datetime(df_filtered['Timestamp'], utc=True)
                df_filtered = df_filtered.sort_values(by='Timestamp', ascending=False)

            # Export ONE unified master table for dynamic Streamlit filtering
            table_name = f"{name_prefix}_all_time"
            reports[table_name] = df_filtered
            logger.info(f"--> Generated unified detailed report '{table_name}' with {len(df_filtered)} rows.")

        except Exception as e:
            msg = f"Failed to generate detailed report for '{rc.get('report_name_prefix', 'Unknown')}': {e}"
            logger.error(msg, exc_info=True)
            run_warnings.append(msg)
            
    return reports

def generate_timeseries_reports(df_source, config, run_warnings, global_drop_leavers=False):
    logger.info("Generating all configured timeseries reports...")
    reports = {}
    report_configs = config['dashboard_settings'].get('timeseries_reports', [])
    if not report_configs: 
        logger.warning("No timeseries reports configured.")
        return reports

    df_source['Timestamp'] = pd.to_datetime(df_source['Timestamp'], errors='coerce', utc=True)
    df_source.dropna(subset=['Timestamp'], inplace=True)

    for rc in report_configs:
        try:
            name = rc['report_name']
            
            broadcast_types = rc['broadcast_type']
            if isinstance(broadcast_types, str):
                # Handle the original case of a single string for backward compatibility
                df_filtered = df_source[df_source['Broadcast_Type'] == broadcast_types].copy()
            elif isinstance(broadcast_types, list):
                # Handle the new case of a list of strings
                df_filtered = df_source[df_source['Broadcast_Type'].isin(broadcast_types)].copy()
            
            include_leavers = rc.get('include_leavers', False)
            if not include_leavers and global_drop_leavers and 'Is_Retained' in df_filtered.columns:
                df_filtered = df_filtered[df_filtered['Is_Retained']]
                
            use_raw_rsn = rc.get('use_raw_rsn', False)
            if use_raw_rsn and 'Raw_RSN' in df_filtered.columns:
                df_filtered['Username'] = df_filtered['Raw_RSN']
                
            if df_filtered.empty: 
                logger.info(f"--> No data for timeseries report '{name}', creating empty table.")
                reports[name] = pd.DataFrame()
                continue
            
            if 'Item_Value' in df_filtered.columns:
                df_filtered['Item_Value'] = pd.to_numeric(df_filtered['Item_Value'], errors='coerce').fillna(0)
            else: 
                df_filtered['Item_Value'] = 0

            all_resampled = []
            for freq in rc.get('frequencies', ['D']):
                df_resampled = df_filtered.set_index('Timestamp').resample(freq).agg(
                    Count=('Username', 'count'), 
                    Total_Value=('Item_Value', 'sum')
                ).sort_index()
                df_resampled['Cumulative_Count'] = df_resampled['Count'].cumsum()
                df_resampled['Cumulative_Value'] = df_resampled['Total_Value'].cumsum()
                
                df_resampled = df_resampled.reset_index()
                df_resampled['Frequency'] = freq
                all_resampled.append(df_resampled)
            
            if not all_resampled: 
                reports[name] = pd.DataFrame()
                continue

            df_final = pd.concat(all_resampled).rename(columns={'Timestamp': 'Date'})
            reports[name] = df_final
            logger.info(f"--> Generated timeseries report '{name}' for freqs {rc['frequencies']} with {len(df_final)} entries.")
        except Exception as e:
            msg = f"Failed to generate timeseries report '{rc.get('report_name', 'Unknown')}': {e}"
            logger.error(msg, exc_info=True)
            run_warnings.append(msg)
    
    return reports

def generate_collection_log_report(df_broadcasts, config, periods, run_warnings, use_enriched_db=False, global_drop_leavers=False):
    """
    Generates the collection log summary. An item can appear in multiple groups,
    and item names with quantities (e.g., '72 x Onyx bolts') are parsed.
    """
    logger.info("Generating collection log report...")
    clog_config = config.get('dashboard_settings', {}).get('collection_log', {})
    include_leavers = clog_config.get('include_leavers', False)
    use_raw_rsn = clog_config.get('use_raw_rsn', False)
    
    historical_file = SHARED_CONFIG_DIR / config.get('historical_data', {}).get('collection_log_file')
    if not historical_file.exists():
        msg = f"Historical collection log file not found at {historical_file}"
        logger.error(msg)
        run_warnings.append(msg)
        return pd.DataFrame()
        
    with open(historical_file, "rb") as f:
        hist_data = tomllib.load(f)
        
    exclude_rules = hist_data.get('exclude_rules', [])
    other_group_name = hist_data.get('other_group_name', 'Miscellaneous Drops')
    historical_counts = {item['name']: item['count'] for item in hist_data.get('initial_counts', [])}

    # 1. Filter and process broadcast data
    source_types = clog_config.get('source_types', [])
    df_clog_source = df_broadcasts[df_broadcasts['Broadcast_Type'].isin(source_types)].copy()
    
    if not include_leavers and global_drop_leavers and 'Is_Retained' in df_clog_source.columns:
        df_clog_source = df_clog_source[df_clog_source['Is_Retained']]
        
    if use_raw_rsn and 'Raw_RSN' in df_clog_source.columns:
        df_clog_source['Username'] = df_clog_source['Raw_RSN']
    
    if exclude_rules:
        flat_exclude_list = [item for sublist in exclude_rules for item in sublist]
        logger.info(f"Applying {len(flat_exclude_list)} exclusion rules to collection log items...")
        initial_rows = len(df_clog_source)
        exclude_mask = df_clog_source['Item_Name'].isin(flat_exclude_list)
        df_clog_source = df_clog_source[~exclude_mask]
        logger.info(f"--> Excluded {initial_rows - len(df_clog_source)} CLog items.")

    dedup_type = clog_config.get('deduplication_type')
    if dedup_type:
        df_to_dedup = df_clog_source[df_clog_source['Broadcast_Type'] == dedup_type]
        df_others = df_clog_source[df_clog_source['Broadcast_Type'] != dedup_type]
        
        if use_raw_rsn:
            dedup_subset = ['Username', 'Item_Name']
        else:
            dedup_subset = ['Entity_ID', 'Item_Name'] if (use_enriched_db and 'Entity_ID' in df_to_dedup.columns) else ['Username', 'Item_Name']
            
        df_deduped = df_to_dedup.drop_duplicates(subset=dedup_subset)
        df_clog_source = pd.concat([df_deduped, df_others])
        logger.info(f"Deduplicated {len(df_to_dedup) - len(df_deduped)} rows for broadcast type '{dedup_type}'.")

    # 2. Parse item name and quantity
    def parse_item_and_quantity(item_name_str):
        if not isinstance(item_name_str, str):
            return ('', 1)
        
														   
        match = re.match(r"([\d,]+)\s*x\s*(.+)", item_name_str.strip())
        if match:
													
            quantity = int(match.group(1).replace(',', ''))
            name = match.group(2).strip()
            return (name, quantity)
        else:
            return (item_name_str.strip(), 1)

    if not df_clog_source.empty:
        parsed_data = df_clog_source['Item_Name'].apply(parse_item_and_quantity)
        df_clog_source[['Parsed_Item_Name', 'Item_Quantity']] = pd.DataFrame(parsed_data.tolist(), index=df_clog_source.index)
    else:
        df_clog_source['Parsed_Item_Name'] = None
        df_clog_source['Item_Quantity'] = 1

    # 3. Calculate total counts for every unique item across all periods
    all_db_items = df_clog_source['Parsed_Item_Name'].dropna().unique()
    all_known_items = sorted(list(set(all_db_items) | set(historical_counts.keys())))
    
    df_item_counts = pd.DataFrame({'Item_Name': all_known_items})
    
    for period_key, dates in periods.items():
        df_period = get_records_for_period(df_clog_source, start_date=dates['start'], end_date=dates['end'])
        
        col_name = f'{period_key}_Count'
        if df_period.empty:
            df_item_counts[col_name] = 0
        else:
            period_counts = df_period.groupby('Parsed_Item_Name')['Item_Quantity'].sum().reset_index()
            period_counts.rename(columns={'Parsed_Item_Name': 'Item_Name', 'Item_Quantity': col_name}, inplace=True)
            df_item_counts = pd.merge(df_item_counts, period_counts, on='Item_Name', how='left')

    df_item_counts['Historical_Count'] = df_item_counts['Item_Name'].map(historical_counts).fillna(0)

    df_item_counts['All_Time_Count'] = df_item_counts.get('All_Time_Count', 0).fillna(0) + df_item_counts['Historical_Count']
    
    df_item_counts.drop(columns=['Historical_Count'], inplace=True)
    df_item_counts = df_item_counts.fillna(0).astype({col: int for col in df_item_counts.columns if '_Count' in col})

    # 4. Build the final report by mapping items to their groups
    item_group_pairs = []
    grouped_item_set = set()
    for group in hist_data.get('groups', []):
        group_title = group.get('title')
        for item_name in group.get('items', []):
            item_group_pairs.append({'Group': group_title, 'Item_Name': item_name})
            grouped_item_set.add(item_name)
    
    df_grouped_items = pd.DataFrame(item_group_pairs)

    # 5. Handle ungrouped items
    items_with_drops = set(df_item_counts[df_item_counts['All_Time_Count'] > 0]['Item_Name'])
    ungrouped_items = items_with_drops - grouped_item_set
    
    strict_clog_items_only = clog_config.get('strict_clog_items_only', True)
    
    if ungrouped_items:
        if strict_clog_items_only:
            logger.info(f"Ignored {len(ungrouped_items)} items not found in config groups (strict_clog_items_only is True).")
            df_final_structure = df_grouped_items
        else:
            logger.info(f"Found {len(ungrouped_items)} items with drops that are not in any group. Assigning to '{other_group_name}'.")
            df_ungrouped = pd.DataFrame({
                'Group': other_group_name,
                'Item_Name': list(ungrouped_items)
            })
            df_final_structure = pd.concat([df_grouped_items, df_ungrouped], ignore_index=True)
    else:
        df_final_structure = df_grouped_items

    # 6. Merge the structure with the counts
    df_summary = pd.merge(df_final_structure, df_item_counts, on='Item_Name', how='left')
    df_summary.fillna(0, inplace=True)
    

    for col in df_summary.columns:
        if '_Count' in col:
            df_summary[col] = df_summary[col].astype(int)

    logger.info(f"--> Generated collection log report with {len(df_summary)} total entries (items duplicated across groups).")
    return df_summary

def generate_personal_bests_report(df_broadcasts, config, run_warnings, use_enriched_db=False, drop_leavers=False, full_roster=None, df_broadcasts_unfiltered=None):
    """
    Generates the personal bests summary table with logic for grouping team records.
    """
    logger.info("Generating personal bests report...")
    pb_config = config.get('dashboard_settings', {}).get('personal_bests', {})
    include_leavers = pb_config.get('include_leavers', False)
    use_raw_rsn = pb_config.get('use_raw_rsn', False)
    
    if include_leavers:
        drop_leavers = False
        
    grouping_window = timedelta(seconds=pb_config.get('pb_grouping_window_seconds', 5))
    allow_multiple_holders = pb_config.get('allow_multiple_holders_on_match', True)

    historical_file = SHARED_CONFIG_DIR / config.get('historical_data', {}).get('personal_bests_file')
    if not historical_file.exists():
        msg = f"Historical personal bests file not found at {historical_file}"
        logger.error(msg)
        run_warnings.append(msg)
        return pd.DataFrame()
    
    with open(historical_file, "rb") as f:
        hist_data = tomllib.load(f)
        
    exclude_rules = hist_data.get('exclude_rules', [])
    blacklist_rules = hist_data.get('blacklist', [])
    other_group_name = hist_data.get('other_group_name', 'Miscellaneous PBs')
    
    all_pbs = []
    task_to_group_map = {}
    all_historical_tasks = set()
    canonical_task_names = {}
    task_config_map = {}

    def is_retained(did):
        if df_broadcasts_unfiltered is not None and not df_broadcasts_unfiltered.empty:
            if 'Discord_ID' in df_broadcasts_unfiltered.columns and 'Is_Retained' in df_broadcasts_unfiltered.columns:
                matches = df_broadcasts_unfiltered[df_broadcasts_unfiltered['Discord_ID'] == did]
                if not matches.empty:
                    return bool(matches['Is_Retained'].iloc[0])
        if full_roster and did in full_roster:
            user = full_roster[did]
            if user.get('is_archived'): return False
            if user.get('is_ok'): return True
        return False
    
    for group in hist_data.get('groups', []):
        group_title = group.get('title')
        for record in group.get('records', []):
            task_name = record.get('name')
            if task_name:
                canonical_task_names[task_name.lower()] = task_name
                all_historical_tasks.add(task_name)
                task_to_group_map[task_name] = group_title
                
                task_config_map[task_name] = {
                    'metric': record.get('metric', 'time'),
                    'label': record.get('label', 'Time'),
                    'display_name': record.get('display_name', task_name)
                }
                
                holders_raw = record.get('holder', [])
                
                if isinstance(holders_raw, str) or isinstance(holders_raw, dict):
                    holders_raw = [holders_raw]
                elif not holders_raw:
                    holders_raw = []
                    
                holders = []
                for h in holders_raw:
                    if isinstance(h, dict):
                        h_id = str(h.get('id', ''))
                        h_rsn = h.get('rsn', '')
                        if use_enriched_db:
                            if drop_leavers:
                                if h_id and is_retained(h_id):
                                    d_name = full_roster.get(h_id, {}).get('name') if full_roster else None
                                    holders.append(h_rsn if use_raw_rsn else (d_name or h_rsn))
                            else:
                                if h_id:
                                    d_name = full_roster.get(h_id, {}).get('name') if full_roster else None
                                    holders.append(h_rsn if use_raw_rsn else (d_name or h_rsn))
                                elif h_rsn:
                                    holders.append(h_rsn)
                        else:
                            if h_rsn: holders.append(h_rsn)
                    elif isinstance(h, str) and h:
                        if use_enriched_db and drop_leavers:
                            msg = f"Dropping plain text PB holder '{h}' for '{task_name}' (drop_leavers_from_data=True requires 'id')."
                            logger.warning(msg)
                            run_warnings.append(msg)
                        else:
                            holders.append(h)
                
                # Check for manual date override
                manual_date = record.get('date')
                timestamp = pd.Timestamp.min.replace(tzinfo=timezone.utc)
                if manual_date:
                    timestamp = pd.to_datetime(manual_date, errors='coerce', utc=True)
                    if pd.isna(timestamp):
                        timestamp = pd.Timestamp.min.replace(tzinfo=timezone.utc)

                all_pbs.append({
                    'Task_Name': task_name,
                    'PB_Time': record.get('time'),
                    'Username': holders[0] if holders else "", 
                    'All_Holders': holders,
                    'Timestamp': timestamp,
                    'is_historical': True,
                    'manual_date': manual_date
                })

    source_type = pb_config.get('broadcast_type')
    df_pbs_source = df_broadcasts[df_broadcasts['Broadcast_Type'] == source_type].copy()
    
    if drop_leavers and 'Is_Retained' in df_pbs_source.columns:
        df_pbs_source = df_pbs_source[df_pbs_source['Is_Retained']]
        
    if use_raw_rsn and 'Raw_RSN' in df_pbs_source.columns:
        df_pbs_source['Username'] = df_pbs_source['Raw_RSN']
        
    df_pbs_source['is_historical'] = False
    
    if not df_pbs_source.empty:
        all_pbs.extend(df_pbs_source.to_dict('records'))

    if not all_pbs:
        logger.warning("No historical or new personal bests found.")
        return pd.DataFrame()

    df_all_pbs = pd.DataFrame(all_pbs)

    # Normalize Task Names to handle capitalization changes (e.g. "shellbane" vs "Shellbane")
    if 'Task_Name' in df_all_pbs.columns:
        for task in df_all_pbs['Task_Name'].dropna().unique():
            if isinstance(task, str) and task.lower() not in canonical_task_names:
                canonical_task_names[task.lower()] = task
        
        df_all_pbs['Task_Name'] = df_all_pbs['Task_Name'].apply(
            lambda x: canonical_task_names.get(x.lower(), x) if isinstance(x, str) else x
        )
    
    # Apply blacklist rules before any other processing
    if blacklist_rules:
        logger.info(f"Applying {len(blacklist_rules)} PB blacklist rules...")
        
        globally_blacklisted_users = set()
        
        for rule in blacklist_rules:
            if 'task_name' not in rule and ('username' in rule or 'rsn' in rule or 'id' in rule):
                user_legacy = rule.get('username')
                r_id = str(rule.get('id', ''))
                r_rsn = rule.get('rsn', '')
                if use_enriched_db and r_id:
                    t_user = full_roster.get(r_id, {}).get('name') if full_roster else None
                    target_user = t_user or r_rsn or user_legacy
                elif r_rsn:
                    target_user = r_rsn
                else:
                    target_user = user_legacy
                if target_user: globally_blacklisted_users.add(target_user)

        if globally_blacklisted_users:
            logger.info(f"  - Global blacklist for users: {', '.join(globally_blacklisted_users)}")
            # First, remove them from any group records																					
            df_all_pbs['All_Holders'] = df_all_pbs['All_Holders'].apply(
                lambda holders: [h for h in holders if h not in globally_blacklisted_users] if isinstance(holders, list) else holders
            )

        keep_mask = pd.Series(True, index=df_all_pbs.index)
        for rule in blacklist_rules:
            user_legacy = rule.get('username')
            r_id = str(rule.get('id', ''))
            r_rsn = rule.get('rsn', '')
            target_user = None
            if use_enriched_db and r_id:
                t_user = full_roster.get(r_id, {}).get('name') if full_roster else None
                target_user = t_user or r_rsn or user_legacy
            elif r_rsn:
                target_user = r_rsn
            else:
                target_user = user_legacy
                
            if not target_user:
                logger.warning(f"Skipping invalid blacklist rule (missing username or rsn/id): {rule}")
                continue
            user = target_user

            task = rule.get('task_name')
            max_time_str = rule.get('max_time')

            if not task and not max_time_str:  # Global user blacklist
                user_mask = (df_all_pbs['Username'] == user)
                keep_mask &= ~user_mask
            elif task and not max_time_str:  # Specific task blacklist (any time)
                rule_mask = (df_all_pbs['Username'] == user) & (df_all_pbs['Task_Name'] == task)
                keep_mask &= ~rule_mask
            elif task and max_time_str:  # Specific task/time blacklist
                max_time_seconds = time_str_to_seconds(max_time_str)
                rule_mask = (df_all_pbs['Username'] == user) & (df_all_pbs['Task_Name'] == task)
                if rule_mask.any():
                    pb_times_seconds = df_all_pbs.loc[rule_mask, 'PB_Time'].apply(time_str_to_seconds)
                    blacklisted_times_mask = pb_times_seconds < max_time_seconds
                    indices_to_blacklist = df_all_pbs.loc[rule_mask][blacklisted_times_mask].index
                    keep_mask.loc[indices_to_blacklist] = False
            else:
                msg = f"Skipping invalid blacklist rule. A rule must be global (user only), task-specific (user and task), or task-and-time-specific (user, task, and max_time). Rule: {rule}"
                logger.warning(msg)
                run_warnings.append(msg)

        initial_rows = len(df_all_pbs)
        df_all_pbs = df_all_pbs[keep_mask].reset_index(drop=True)
        logger.info(f"--> Removed a total of {initial_rows - len(df_all_pbs)} blacklisted PB records.")

    if exclude_rules:
        logger.info(f"Applying {len(exclude_rules)} exclusion rules to personal bests...")
        initial_rows = len(df_all_pbs)
        exclude_mask = pd.Series(False, index=df_all_pbs.index)
        for rule_set in exclude_rules:
            current_rule_mask = pd.Series(True, index=df_all_pbs.index)
            for required_string in rule_set:
                current_rule_mask &= df_all_pbs['Task_Name'].str.contains(required_string, na=False, regex=False)
            exclude_mask |= current_rule_mask
        df_all_pbs = df_all_pbs[~exclude_mask]
        logger.info(f"--> Excluded {initial_rows - len(df_all_pbs)} PB records.")

    df_all_pbs['Timestamp'] = pd.to_datetime(df_all_pbs['Timestamp'], errors='coerce', utc=True)
    
    # Calculate sort value based on metric (Ticks for Time, Float/Int for Score)
    def get_sort_value(row):
        task = row.get('Task_Name', '')
        metric = task_config_map.get(task, {}).get('metric', 'time')
        val_str = str(row.get('PB_Time', ''))
        
        is_historical = row.get('is_historical', False)
        holders = row.get('All_Holders')
        is_empty_historical = is_historical and (val_str == "0:00" or not holders)
        
        if metric == 'score':
            if is_empty_historical:
                return float('-inf')
            nums = re.findall(r'[-+]?(?:\d*\.\d+|\d+)', val_str)
            return float(nums[0]) if nums else 0.0
        else:
            return float('inf') if is_empty_historical else calculate_ticks(val_str)

    df_all_pbs['sort_value'] = df_all_pbs.apply(get_sort_value, axis=1)
    df_all_pbs.dropna(subset=['Task_Name', 'sort_value'], inplace=True)

    final_records = {}
    for task_name, task_group_df in df_all_pbs.groupby('Task_Name'):
        metric = task_config_map.get(task_name, {}).get('metric', 'time')
        
        if metric == 'score':
            best_val = task_group_df['sort_value'].max()
            best_time_df = task_group_df[task_group_df['sort_value'] == best_val].copy()
            if pd.isna(best_val) or best_val == float('-inf'):
                formatted_val = "0"
            else:
                formatted_val = str(int(best_val)) if best_val == int(best_val) else str(best_val)
        else:
            best_val = task_group_df['sort_value'].min()
            best_time_df = task_group_df.copy() if best_val == float('inf') else task_group_df[task_group_df['sort_value'] == best_val].copy()
            formatted_val = format_ticks_to_time(best_val)
        
        best_time_df = best_time_df.sort_values(by='Timestamp', ascending=True)
        if best_time_df.empty: continue

        first_record_timestamp = best_time_df.iloc[0]['Timestamp']
        group_cutoff_time = first_record_timestamp + grouping_window
        first_achievers_df = best_time_df[best_time_df['Timestamp'] <= group_cutoff_time]

        all_holders = []
        historical_record = first_achievers_df[first_achievers_df['is_historical']]
        if not historical_record.empty:
             all_holders.extend(historical_record.iloc[0].get('All_Holders') or [])

        db_record_holders = first_achievers_df[~first_achievers_df['is_historical']]['Username'].tolist()
        all_holders.extend(db_record_holders)

        if allow_multiple_holders:
            later_achievers_df = best_time_df[best_time_df['Timestamp'] > group_cutoff_time]
            all_holders.extend(later_achievers_df['Username'].tolist())

        unique_holders = sorted(list(set(filter(None, all_holders))))
        
        # The definitive record is the first one in the sorted list (earliest timestamp).
        definitive_record = best_time_df.iloc[0]
        
        # A date is only set if this definitive record is from the DB (not historical).
        record_date = None
        if not definitive_record['is_historical']:
            record_date = definitive_record['Timestamp'].strftime('%Y-%m-%d')
        elif pd.notna(definitive_record.get('manual_date')) and definitive_record.get('manual_date'):
            record_date = str(definitive_record.get('manual_date'))

        final_records[task_name] = {
            'Task': task_name,
            'Display_Name': task_config_map.get(task_name, {}).get('display_name', task_name),
            'Holder': ', '.join(unique_holders),
            'Time': formatted_val,
            'Date': record_date,
            'Group': task_to_group_map.get(task_name, other_group_name),
            'Label': task_config_map.get(task_name, {}).get('label', 'Time')
        }

    df_summary = pd.DataFrame.from_dict(final_records, orient='index')
    
    # Ensure all historical tasks are present in the final report
    processed_tasks = set(df_summary['Task']) if not df_summary.empty else set()
    missing_tasks = all_historical_tasks - processed_tasks
    if missing_tasks:
        missing_records = []
        for task in missing_tasks:
            metric = task_config_map.get(task, {}).get('metric', 'time')
            missing_records.append({
                'Task': task,
                'Display_Name': task_config_map.get(task, {}).get('display_name', task),
                'Holder': '',
                'Time': '0' if metric == 'score' else '0:00',
                'Date': None,
                'Group': task_to_group_map.get(task, other_group_name),
                'Label': task_config_map.get(task, {}).get('label', 'Time')
            })
        df_missing = pd.DataFrame(missing_records)
        df_summary = pd.concat([df_summary, df_missing], ignore_index=True)
        logger.info(f"--> Added back {len(missing_tasks)} tasks that had no valid record holders after blacklisting.")

    logger.info(f"--> Generated personal bests report with {len(df_summary)} unique items.")
    return df_summary


def generate_recent_achievements_report(df_broadcasts, config, run_warnings, global_drop_leavers=False):
    """Generates a table of recent achievements, creating special categories for maxed skills."""
    logger.info("Generating recent achievements report...")
    ra_config = config.get('dashboard_settings', {}).get('recent_achievements', {})
    
    source_types = ra_config.get('source_types', [])
    limit_per_type = ra_config.get('limit_per_type', 15)
    
    df_source = df_broadcasts[df_broadcasts['Broadcast_Type'].isin(source_types)].copy()
    
    include_leavers = ra_config.get('include_leavers', False)
    if not include_leavers and global_drop_leavers and 'Is_Retained' in df_source.columns:
        df_source = df_source[df_source['Is_Retained']]
        
    use_raw_rsn = ra_config.get('use_raw_rsn', False)
    if use_raw_rsn and 'Raw_RSN' in df_source.columns:
        df_source['Username'] = df_source['Raw_RSN']
    
    if df_source.empty:
        logger.info("No broadcasts found for recent achievements report.")
        return pd.DataFrame()

    df_levelups = df_source[df_source['Broadcast_Type'] == 'Level Up'].copy()
    df_levelups['New_Level'] = pd.to_numeric(df_levelups['New_Level'], errors='coerce').fillna(0).astype(int)

    df_maxed_99 = df_levelups[(df_levelups['New_Level'] == 99) & (df_levelups['Skill'] != 'Combat')].copy()
    df_maxed_99['Broadcast_Type'] = 'Maxed Skill (99)'
    
    df_maxed_combat = df_levelups[(df_levelups['New_Level'] == 126) & (df_levelups['Skill'] == 'Combat')].copy()
    df_maxed_combat['Broadcast_Type'] = 'Maxed Combat'

    df_combined = pd.concat([df_source, df_maxed_99, df_maxed_combat])
    df_combined.sort_values(by='Timestamp', ascending=False, inplace=True)
    df_recent = df_combined.groupby('Broadcast_Type').head(limit_per_type)
    
    logger.info(f"--> Generated recent achievements report with {len(df_recent)} entries.")
    return df_recent


def main():
    config = load_config()
    loguru_setup(config, PROJECT_ROOT)
    logger.info(f"{f' Starting {SCRIPT_NAME} ':=^80}")
    run_warnings = []
    
    # --- Blue/Green Database Selection ---
    primary_db_uri = config['databases']['optimised_db_uri']
    target_db_uri = primary_db_uri
    target_db_path_for_summary = "Remote DB"
    
    use_enriched_db = config.get('roster_sync', {}).get('use_enriched_db_for_dashboard', False)
    drop_leavers = config.get('roster_sync', {}).get('drop_leavers_from_data', False)

    if primary_db_uri.startswith('sqlite'):
        primary_db_path_str = primary_db_uri.split('///')[1]
        primary_db_path = DATA_DIR / Path(primary_db_path_str).name
        
        # Define the alternate DB path. E.g., 'data/optimised_data.db' -> 'data/optimised_data_alt.db'
        alt_db_path = primary_db_path.with_stem(f"{primary_db_path.stem}_alt")

        primary_mtime = primary_db_path.stat().st_mtime if primary_db_path.exists() else 0
        alt_mtime = alt_db_path.stat().st_mtime if alt_db_path.exists() else 0

        logger.info("Determining which optimised database to update (blue/green strategy)...")
        logger.info(f"  - Primary DB ({primary_db_path.name}) last modified: {datetime.fromtimestamp(primary_mtime).strftime('%Y-%m-%d %H:%M:%S') if primary_mtime else 'N/A'}")
        logger.info(f"  - Alternate DB ({alt_db_path.name}) last modified: {datetime.fromtimestamp(alt_mtime).strftime('%Y-%m-%d %H:%M:%S') if alt_mtime else 'N/A'}")

        if primary_mtime <= alt_mtime:
            target_db_path = primary_db_path
            logger.info(f"--> Target for this run is the PRIMARY database: {target_db_path.name}")
        else:
            target_db_path = alt_db_path
            logger.info(f"--> Target for this run is the ALTERNATE database: {target_db_path.name}")

        target_db_uri = f"sqlite:///{target_db_path}"
        target_db_path_for_summary = str(target_db_path.relative_to(BASE_DIR))

    parsed_db_uri = config['databases']['parsed_db_uri']
    if use_enriched_db:
        if parsed_db_uri.startswith('sqlite'):
            parsed_db_path_str = parsed_db_uri.split('///')[1]
            parsed_db_path = DATA_DIR / Path(parsed_db_path_str).name
            enriched_db_path = parsed_db_path.with_name('enriched_data.db')
            parsed_db_uri = f"sqlite:///{enriched_db_path}"
            logger.info(f"Config set to use enriched DB. Reading from {enriched_db_path.name} instead of parsed DB.")

    parsed_engine = get_db_engine(parsed_db_uri)
    optimised_engine = get_db_engine(target_db_uri)
    
    summary_stats = {}
    try:
        if not parsed_engine or not optimised_engine: 
            raise ValueError("Failed to create database engines.")
            
        logger.info("Reading data from parsed database...")
        df_broadcasts = pd.read_sql_table('clan_broadcasts', parsed_engine, coerce_float=False)
        if 'New_Level' in df_broadcasts.columns:
            df_broadcasts['New_Level'] = pd.to_numeric(df_broadcasts['New_Level'], errors='coerce').astype('Int64')

        df_chat = pd.read_sql_table('chat', parsed_engine, coerce_float=False)
        
        run_time = datetime.now(timezone.utc)
        periods = get_time_periods(config, run_time=run_time)

        df_broadcasts['Timestamp'] = pd.to_datetime(df_broadcasts['Timestamp'], errors='coerce', utc=True)
        df_chat['Timestamp'] = pd.to_datetime(df_chat['Timestamp'], errors='coerce', utc=True)
        
        df_broadcasts_unfiltered = df_broadcasts.copy()
        
        # --- Apply Exclusion Filters ---
        df_broadcasts = apply_exclusion_filters(df_broadcasts, config, run_warnings)

        # --- Apply Username Mapping ---														   
        mapping_rules = config.get('username_mapping', {}).get('rules', [])
        if not use_enriched_db and mapping_rules:
            logger.info("Username mapping rules found. Applying them now...")
            validate_mapping_rules(mapping_rules)
            
            broadcast_user_cols = ['Username', 'Action_By', 'Opponent']
            df_broadcasts = apply_manual_name_mappings(df_broadcasts, mapping_rules, broadcast_user_cols)
            
            chat_user_cols = ['Username']
            df_chat = apply_manual_name_mappings(df_chat, mapping_rules, chat_user_cols)
            
            logger.success("--> Username mapping applied successfully.")
        elif use_enriched_db and mapping_rules:
            logger.info("Using enriched database. Skipping manual name mapping (already applied).")
        else:
            logger.info("No username mapping rules found in config. Skipping.")

        full_roster = {}
        if use_enriched_db:
            roster_file = DATA_DIR.parent / 'exports' / 'roster_export.json'
            if roster_file.exists():
                try:
                    with open(roster_file, 'r', encoding='utf-8') as f:
                        r_payload = json.load(f)
                        for user in r_payload.get('members', []):
                            did = str(user.get('discord_id', '')).replace("'", "")
                            sys_flags = user.get('system_flags', [])
                            is_ok = 'OK' in sys_flags or not sys_flags
                            is_archived = 'Archived' in sys_flags
                            full_roster[did] = {
                                'name': user.get('discord_name', ''),
                                'is_ok': is_ok,
                                'is_archived': is_archived
                            }
                except Exception as e:
                    logger.warning(f"Could not load roster_export.json for PB enrichment: {e}")

        df_broadcasts = prepare_dataframe(df_broadcasts, use_enriched_db)
        df_chat = prepare_dataframe(df_chat, use_enriched_db)

        entity_to_name = {}
        for df in [df_broadcasts, df_chat]:
            if not df.empty and 'Entity_ID' in df.columns and 'Display_Name' in df.columns:
                valid_df = df.dropna(subset=['Entity_ID', 'Display_Name'])
                entity_to_name.update(dict(zip(valid_df['Entity_ID'], valid_df['Display_Name'])))
                
        # Overwrite standard 'Username' column so downstream views pick up Display_Name effortlessly
        if 'Display_Name' in df_broadcasts.columns: df_broadcasts['Username'] = df_broadcasts['Display_Name']
        if 'Display_Name' in df_chat.columns: df_chat['Username'] = df_chat['Display_Name']

        all_reports = {}
        create_metadata_tables(optimised_engine, config, periods, run_warnings)
        
        leaderboard_reports = generate_leaderboard_reports(df_chat, df_broadcasts, config, periods, run_warnings, entity_to_name, drop_leavers)
        all_reports.update(leaderboard_reports)
        
        detailed_reports = generate_detailed_reports(df_broadcasts, config, periods, run_warnings, drop_leavers)
        all_reports.update(detailed_reports)

        timeseries_reports = generate_timeseries_reports(df_broadcasts, config, run_warnings, drop_leavers)
        all_reports.update(timeseries_reports)

        clog_report = generate_collection_log_report(df_broadcasts, config, periods, run_warnings, use_enriched_db, drop_leavers)
        all_reports['collection_log_summary'] = clog_report

        pb_report = generate_personal_bests_report(df_broadcasts, config, run_warnings, use_enriched_db, drop_leavers, full_roster, df_broadcasts_unfiltered)
        all_reports['personal_bests_summary'] = pb_report

        recent_achievements_report = generate_recent_achievements_report(df_broadcasts, config, run_warnings, drop_leavers)
        all_reports['recent_achievements'] = recent_achievements_report


        logger.info("Saving all transformed tables to the optimised database...")
        for name, df_report in all_reports.items():
            if df_report is not None:
                if isinstance(df_report.index, pd.CategoricalIndex):
                    df_report = df_report.reset_index()
                if 'Group' in df_report.columns and isinstance(df_report['Group'].dtype, pd.CategoricalDtype):
                    df_report['Group'] = df_report['Group'].astype(str)

                df_report.to_sql(name, optimised_engine, if_exists='replace', index=False)
                summary_stats[name] = len(df_report)
        
        table_counts_str = ""
        if config.get('transform_data', {}).get('post_detailed_table', False):
            table_counts_list_str = "\n".join([f"- `{name}`: `{count}` rows" for name, count in sorted(summary_stats.items())])
            if table_counts_list_str:
                table_counts_str = f"\n**Created Table Row Counts:**\n{table_counts_list_str}"

        summary_lines = [
            f"**Run Time:** `{run_time.strftime('%Y-%m-%d %H:%M:%S UTC')}`\n",
            f"**Transformation Results:**",
            f"- Broadcasts Processed: `{len(df_broadcasts)}`",
            f"- Chat Messages Processed: `{len(df_chat)}`",
            f"- Optimised Tables Created: `{len(summary_stats)}`",
            f"- **Updated Database:** `{target_db_path_for_summary}`",
        ]
        if table_counts_str:
            summary_lines.append(table_counts_str)
        finish_script(SCRIPT_NAME, config, summary_lines, run_warnings)
        
    except Exception as e:
        finish_script(SCRIPT_NAME, config, exception=e)
    finally:
        if parsed_engine: parsed_engine.dispose()
        if optimised_engine: optimised_engine.dispose()
        logger.info("Database connections closed.")
        logger.info(f"{f' Finished {SCRIPT_NAME} ':=^80}")

if __name__ == "__main__":
    main()
