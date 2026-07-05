import json
import pandas as pd
from pathlib import Path
from datetime import timedelta
from loguru import logger
from sqlalchemy import text

from shared_utils import load_config, get_db_engine, BASE_DIR, apply_manual_name_mappings, finish_script
from loguru_setup import loguru_setup

SCRIPT_NAME = "4_enrich_roster"

def canonicalize_rsn(name: str) -> str:
    """
    Converts an OSRS name into a canonical format for matching purposes.
    OSRS treats spaces, hyphens, and underscores as identical characters.
    """
    if pd.isna(name) or not name: return ""
    return ' '.join(str(name).lower().replace('-', ' ').replace('_', ' ').split())

def load_roster_data(json_path: Path):
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def build_interval_map(roster_payload, buffer_hours, df_all_events):
    interval_map = {}
    t_max = pd.Timestamp.max.tz_localize('UTC')
    t_min = pd.Timestamp.min.tz_localize('UTC')
    
    # Create a canonicalized series for ultra-fast Pandas masking using mapping
    if not df_all_events.empty:
        unique_all_events_usernames = df_all_events['Username'].dropna().unique()
        canon_all_events_map = {u: canonicalize_rsn(u) for u in unique_all_events_usernames}
        df_all_events['Canon_Username'] = df_all_events['Username'].map(canon_all_events_map)

    for member in roster_payload.get("members", []):
        discord_id = member.get("discord_id")
        discord_name = member.get("discord_name")
        
        # Start by assuming they hold their current names until the end of time
        open_spans = {canonicalize_rsn(rsn): t_max for rsn in member.get("current_rsns", [])}
        
        # Walk backwards through their name change history
        history = sorted(member.get("name_history", []), key=lambda x: x["date"], reverse=True)
        
        for event in history:
            old_name = canonicalize_rsn(event["old_name"])
            new_name = canonicalize_rsn(event["new_name"])
            t_change = pd.to_datetime(event["date"], utc=True)
            
            # Close the interval for the new name (it started when the change happened)
            if new_name in open_spans:
                end_time = open_spans.pop(new_name)
                if buffer_hours > 0:
                    buffer = pd.Timedelta(hours=buffer_hours)
                    window_start = t_change - buffer
                    
                    start_time = t_change
                    if not df_all_events.empty:
                        # Find first appearance of new_name in window
                        mask = (df_all_events['Canon_Username'] == new_name) & \
                               (df_all_events['Timestamp'] >= window_start) & \
                               (df_all_events['Timestamp'] <= t_change)
                        
                        first_seen = df_all_events.loc[mask, 'Timestamp'].min()
                        if pd.notna(first_seen):
                            start_time = first_seen
                else:
                    start_time = t_change
                
                if new_name not in interval_map:
                    interval_map[new_name] = []
                interval_map[new_name].append({
                    'start': start_time, 'end': end_time,
                    'discord_id': discord_id, 'discord_name': discord_name
                })
            
            # Open an interval for the old name (Ends exactly when WOM syncs the new name)
            open_spans[old_name] = start_time
            
        # Close any remaining open spans at the beginning of time
        for rsn, end_time in open_spans.items():
            if rsn not in interval_map:
                interval_map[rsn] = []
            interval_map[rsn].append({
                'start': t_min, 'end': end_time,
                'discord_id': discord_id, 'discord_name': discord_name
            })
            
    return interval_map

def apply_mapping(df, interval_map, sync_config):
    if df.empty:
        df['Discord_ID'] = None
        df['Discord_Name'] = None
        return df
        
    df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce', utc=True, format='mixed')
    
    # 1. Pre-canonicalize usernames using a lookup dict to avoid redundant string work
    unique_usernames = df['Username'].dropna().unique()
    canon_user_map = {u: canonicalize_rsn(u) for u in unique_usernames}
    
    # 2. Separate usernames in interval_map into single-interval and multi-interval
    single_interval_map = {}
    multi_interval_map = {}
    for username, ivs in interval_map.items():
        if len(ivs) == 1:
            single_interval_map[username] = ivs[0]
        else:
            multi_interval_map[username] = ivs

    discord_ids = []
    discord_names = []
    t_min = pd.Timestamp.min.tz_localize('UTC')
    t_max = pd.Timestamp.max.tz_localize('UTC')
    
    tolerance_days = sync_config.get("wom_sync_delay_tolerance_days", 35)
    tolerance_delta = pd.Timedelta(days=tolerance_days)
    
    # 3. Iterate over zipped lists directly to avoid Pandas iterrows Series overhead
    usernames = df['Username'].tolist()
    timestamps = df['Timestamp'].tolist()
    
    for username_raw, timestamp in zip(usernames, timestamps):
        username = canon_user_map.get(username_raw, "")
        if not username:
            discord_ids.append(None)
            discord_names.append(None)
            continue
            
        match = None
        
        # Check single-interval map first (almost all cases)
        if username in single_interval_map:
            iv = single_interval_map[username]
            if pd.notna(timestamp) and iv['start'] <= timestamp <= iv['end']:
                match = iv
            elif pd.notna(timestamp):
                # Fallback within tolerance. Ignore infinite bounds to prevent OutOfBoundsDatetime
                is_within_tolerance = False
                if iv['start'] != t_min and abs(timestamp - iv['start']) <= tolerance_delta:
                    is_within_tolerance = True
                if iv['end'] != t_max and abs(timestamp - iv['end']) <= tolerance_delta:
                    is_within_tolerance = True
                if is_within_tolerance:
                    match = iv
            else:
                # Missing timestamp fallback
                if iv['end'] == t_max:
                    match = iv
        elif username in multi_interval_map:
            ivs = multi_interval_map[username]
            if pd.notna(timestamp):
                valid_ivs = [iv for iv in ivs if iv['start'] <= timestamp <= iv['end']]
                if valid_ivs:
                    match = valid_ivs[0]
                else:
                    unique_owners = {iv['discord_id'] for iv in ivs}
                    if len(unique_owners) == 1:
                        min_dist = None
                        for iv in ivs:
                            if iv['start'] != t_min:
                                dist = abs(timestamp - iv['start'])
                                if min_dist is None or dist < min_dist:
                                    min_dist = dist
                            if iv['end'] != t_max:
                                dist = abs(timestamp - iv['end'])
                                if min_dist is None or dist < min_dist:
                                    min_dist = dist
                        if min_dist is not None and min_dist <= tolerance_delta:
                            match = ivs[0]
            else:
                current_ivs = [iv for iv in ivs if iv['end'] == t_max]
                if current_ivs:
                    match = current_ivs[0]
                    
        if match:
            discord_ids.append(match['discord_id'])
            discord_names.append(match['discord_name'])
        else:
            discord_ids.append(None)
            discord_names.append(None)
            
    df['Discord_ID'] = discord_ids
    df['Discord_Name'] = discord_names
    return df

def assign_retention_flags(df, last_activity, roster_dict, sync_config):
    if df.empty:
        df['Is_Retained'] = False
        return df

    current_time = pd.Timestamp.now(tz='UTC')
    leaver_grace_period_days = sync_config.get("leaver_grace_period_days", 30)
    exclude_instantly = sync_config.get("exclude_discord_leavers_instantly", False)
    grace_delta = pd.Timedelta(days=leaver_grace_period_days)
    
    # Pre-calculate retention flags at the player entity level to avoid iterrows loop overhead
    unique_pairs = df[['Discord_ID', 'Username']].drop_duplicates()
    
    retention_map = {}
    for _, row in unique_pairs.iterrows():
        discord_id = row['Discord_ID']
        username_raw = row['Username']
        username = canonicalize_rsn(username_raw)
        entity_id = discord_id if pd.notna(discord_id) and discord_id else username
        
        last_active = last_activity.get(entity_id, pd.Timestamp('1970-01-01', tz='UTC'))
        
        if pd.notna(discord_id) and discord_id in roster_dict:
            member = roster_dict[discord_id]
            sys_flags = member.get('system_flags', [])
            
            if "Archived" in sys_flags:
                is_retained = False
            elif exclude_instantly and "Not in Discord" in sys_flags:
                is_retained = False
            elif "Not in WOM Clan" in sys_flags or "Not in Discord" in sys_flags:
                is_retained = (current_time - last_active) <= grace_delta
            elif "OK" in sys_flags:
                is_retained = True
            else:
                is_retained = True
        else:
            is_retained = False
            
        retention_map[(discord_id, username_raw)] = is_retained
        
    df['Is_Retained'] = [retention_map.get((d, u), False) for d, u in zip(df['Discord_ID'].tolist(), df['Username'].tolist())]
    return df

def main():
    config = load_config()
    loguru_setup(config, BASE_DIR)
    logger.info(f"{f' Starting {SCRIPT_NAME} ':=^80}")
    
    run_warnings = []
    parsed_engine = None
    enriched_engine = None

    try:
        sync_config = config.get("roster_sync", {})
        if not sync_config.get("enable_sync", False):
            logger.info("Roster sync is disabled in config.toml. Exiting.")
            finish_script(SCRIPT_NAME, config, ["Roster sync is disabled in config.toml. Exiting."], run_warnings)
            return
            
        json_path_str = sync_config.get("export_json_path", "shared_data/exports/roster_export.json")
        json_path = BASE_DIR / json_path_str
        
        if not json_path.exists():
            msg = f"Roster export JSON not found at {json_path}. Please ensure The Auditor has generated it."
            logger.error(msg)
            run_warnings.append(msg)
            finish_script(SCRIPT_NAME, config, ["Failed to enrich roster due to missing JSON file."], run_warnings)
            return
            
        buffer_hours = sync_config.get("name_change_buffer_hours", 24)
        
        roster_payload = load_roster_data(json_path)
        
        # Sanitize discord IDs to remove any Google Sheets artifact prefixes (like ')
        for m in roster_payload.get('members', []):
            if m.get('discord_id'):
                m['discord_id'] = str(m['discord_id']).replace("'", "")
                
        roster_dict = {m['discord_id']: m for m in roster_payload.get('members', [])}
        logger.info(f"Loaded {len(roster_dict)} members from JSON.")
        
        parsed_db_uri = config['databases']['parsed_db_uri']
        enriched_db_uri = config['databases'].get('enriched_db_uri', 'sqlite:///shared_data/databases/enriched_data.db')
        
        parsed_engine = get_db_engine(parsed_db_uri)
        enriched_engine = get_db_engine(enriched_db_uri)
        
        if not parsed_engine or not enriched_engine:
            raise ValueError("Failed to create database engines.")
            
        # Read Tables
        df_chat = pd.read_sql_table('chat', parsed_engine)
        df_broadcasts = pd.read_sql_table('clan_broadcasts', parsed_engine)
        
        # Phase 4: First, run apply_manual_name_mappings on the raw tables to fix typos/legacy names.
        mapping_rules = config.get('username_mapping', {}).get('rules', [])
        if mapping_rules:
            logger.info("Applying manual username mappings before JSON enrichment...")
            df_broadcasts = apply_manual_name_mappings(df_broadcasts, mapping_rules, ['Username', 'Action_By', 'Opponent'])
            df_chat = apply_manual_name_mappings(df_chat, mapping_rules, ['Username'])
            
        # Phase 4: Smart Name Change Buffer - requires df_all_events
        df_chat_sub = df_chat[['Username', 'Timestamp']].copy()
        df_bc_sub = df_broadcasts[['Username', 'Timestamp']].copy()
        df_bc_act = df_broadcasts[['Action_By', 'Timestamp']].rename(columns={'Action_By': 'Username'}).dropna(subset=['Username'])
        df_bc_opp = df_broadcasts[['Opponent', 'Timestamp']].rename(columns={'Opponent': 'Username'}).dropna(subset=['Username'])
        df_all_events = pd.concat([df_chat_sub, df_bc_sub, df_bc_act, df_bc_opp]).dropna(subset=['Timestamp'])
        df_all_events['Timestamp'] = pd.to_datetime(df_all_events['Timestamp'], errors='coerce', utc=True, format='mixed')
        
        interval_map = build_interval_map(roster_payload, buffer_hours, df_all_events)
        
        # Phase 4: Apply the Auditor JSON name_history to map the resolved RSNs
        df_chat_mapped = apply_mapping(df_chat, interval_map, sync_config)
        df_broadcasts_mapped = apply_mapping(df_broadcasts, interval_map, sync_config)
        
        # Phase 4: In-Memory Calculation for Last_Activity_Date
        logger.info("Calculating retention eligibility...")
        
        # We only care about Activity from Username for retention
        df_combined = pd.concat([
            df_chat_mapped[['Username', 'Discord_ID', 'Timestamp']],
            df_broadcasts_mapped[['Username', 'Discord_ID', 'Timestamp']]
        ]).dropna(subset=['Timestamp'])
        
        unique_combined_names = df_combined['Username'].dropna().unique()
        canon_combined_map = {n: canonicalize_rsn(n) for n in unique_combined_names}
        df_combined['Entity_ID'] = df_combined['Discord_ID'].fillna(
            df_combined['Username'].map(canon_combined_map)
        )
        last_activity = df_combined.groupby('Entity_ID')['Timestamp'].max()
        
        # Assign Retention Flags
        df_chat_mapped = assign_retention_flags(df_chat_mapped, last_activity, roster_dict, sync_config)
        df_broadcasts_mapped = assign_retention_flags(df_broadcasts_mapped, last_activity, roster_dict, sync_config)
        
        # Save to Enriched DB (Replacing entirely to ensure pure idempotency)
        logger.info("Saving enriched data to database...")
        df_chat_mapped.to_sql('chat', enriched_engine, if_exists='replace', index=False)
        df_broadcasts_mapped.to_sql('clan_broadcasts', enriched_engine, if_exists='replace', index=False)
        
        retained_chat = df_chat_mapped['Is_Retained'].sum()
        retained_bc = df_broadcasts_mapped['Is_Retained'].sum()
        
        summary_lines = [
            f"**Enrichment Results:**",
            f"- Members Loaded: `{len(roster_dict)}`",
            f"- Chat Messages: `{len(df_chat_mapped)}` total (`{retained_chat}` retained)",
            f"- Broadcasts: `{len(df_broadcasts_mapped)}` total (`{retained_bc}` retained)"
        ]
        
        finish_script(SCRIPT_NAME, config, summary_lines, run_warnings)
        logger.success("--> Roster enrichment complete.")

    except Exception as e:
        finish_script(SCRIPT_NAME, config, exception=e)
    finally:
        if parsed_engine: parsed_engine.dispose()
        if enriched_engine: enriched_engine.dispose()
        logger.info(f"{f' Finished {SCRIPT_NAME} ':=^80}")

if __name__ == '__main__':
    main()