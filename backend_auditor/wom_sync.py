import os
import json
from datetime import datetime
from urllib.parse import quote
from loguru import logger
from constants import SystemFlag
from sqlite_manager import SQLiteManager

def sync_wom_data(db_manager, wom_client, target_clan_name, audit_logs):
    """Syncs WOM data for all members and returns a list of untracked WOM members."""
    logger.info(f"Starting WOM Sync for Target Clan: '{target_clan_name}'")
    if not target_clan_name or target_clan_name == 'Unknown Clan':
        logger.warning("Target Clan Name is missing or 'Unknown Clan'. Skipping WOM sync.")
        return [], [], {}
        
    try:
        # We pass force_refresh=True to always get fresh data, but we cache it so the CLI tools can reuse it.
        search_res = wom_client.get(f'/groups?name={quote(target_clan_name)}&limit=1', cache_key=f"group_search_{target_clan_name}")
        if not search_res or search_res[0].get('name', '').lower() != target_clan_name.lower():
            logger.error(f"Could not find exact WOM Group matching '{target_clan_name}'")
            return [], [], {}
            
        group_id = search_res[0]['id']
        logger.info(f"Found WOM Group ID: {group_id}")
        
        group_res = wom_client.get(f'/groups/{group_id}', cache_key=f"group_details_{group_id}")
        if not group_res:
            logger.error(f"Failed to fetch details for Group ID {group_id}")
            return [], [], {}
    except Exception as e:
        logger.error(f"WOM API Group Sync Error: {e}")
        return [], [], {}
        
    memberships = group_res.get('memberships', [])
    group_roster = {
        str(m['player']['id']): {
            'rsn': m['player'].get('displayName') or m['player'].get('username') or 'Unknown', 
            'rank': m['role'],
            'status': m['player'].get('status', 'active'),
            'updatedAt': m['player'].get('updatedAt'),
            'lastChangedAt': m['player'].get('lastChangedAt')
        } for m in memberships
    }
    logger.info(f"Loaded {len(group_roster)} members from WOM Group Roster.")
    
    # --- Self-Healing: Force update stale players ---
    outdated_players = []
    failed_updates = {}
    now = datetime.utcnow()
    for wid, data in group_roster.items():
        updated_str = data.get('updatedAt')
        if updated_str and data['status'] == 'active':
            try:
                # Parse standard ISO 8601 string from WOM (e.g. 2026-04-27T02:07:54)
                parsed_date = datetime.strptime(updated_str[:19], "%Y-%m-%dT%H:%M:%S")
                if (now - parsed_date).days >= 7:
                    outdated_players.append((wid, data['rsn'], data.get('lastChangedAt')))
            except Exception:
                continue
                
    if outdated_players:
        logger.info(f"Found {len(outdated_players)} active players not updated in 7+ days. Requesting WOM updates...")
        if hasattr(wom_client, 'post'):
            success_count = 0
            for wid, rsn, last_changed in outdated_players:
                try:
                    if wom_client.post(f"/players/{quote(rsn)}"):
                        success_count += 1
                    else:
                        logger.warning(f"WOM API failed to update player: {rsn}")
                        failed_updates[wid] = {'rsn': rsn, 'last_changed': last_changed}
                except Exception as e:
                    logger.warning(f"Error requesting update for {rsn}: {e}")
            logger.success(f"Successfully queued {success_count}/{len(outdated_players)} players for a WOM update.")
        else:
            logger.warning("wom_client is missing a 'post' method. Unable to push updates.")

    # --- Local DB Name Change History Tracking ---
    all_name_changes = None
    try:
        db_path = os.path.join(os.path.dirname(__file__), '..', 'shared_data', 'databases', 'history.db')
        sqlite_db = SQLiteManager(db_path)
        
        # 1. Save the raw daily JSON snapshot
        today_str = datetime.utcnow().strftime('%Y-%m-%d')
        sqlite_db.save_group_snapshot(today_str, json.dumps(group_res))
        
        # 2. Check for RSN changes to fetch history efficiently
        local_players = sqlite_db.get_all_players()
        
        for wid_str, data in group_roster.items():
            wid = int(wid_str)
            current_rsn = data['rsn']
            
            if wid not in local_players or local_players[wid] != current_rsn:
                logger.info(f"Name change or new player detected for WOM ID {wid} ({current_rsn}). Fetching history...")
                name_history = wom_client.get(f'/players/{quote(current_rsn)}/names', cache_key=f"names_{wid}")
                
                if name_history and isinstance(name_history, list):
                    changes_to_insert = []
                    for change in name_history:
                        old_name = change.get('oldName', 'Unknown')
                        new_name = change.get('newName', 'Unknown')
                        status = str(change.get('status', 'Unknown'))
                        resolved_at = change.get('resolvedAt') or change.get('createdAt')
                        changes_to_insert.append((wid, old_name, new_name, status, resolved_at))
                    
                    if changes_to_insert:
                        sqlite_db.insert_name_changes(changes_to_insert)
                        
                sqlite_db.update_player(wid, current_rsn)
        all_name_changes = sqlite_db.get_all_name_changes_grouped()
    except Exception as e:
        logger.error(f"Local SQLite Name History tracking failed: {e}")
    # ---------------------------------------------

    all_records = db_manager.get_all_records('Database')
    
    tracked_wom_ids = set()
    banned_members = []
    
    for wid, data in group_roster.items():
        if data['status'] == 'banned':
            banned_members.append({'wom_id': wid, 'rsn': data['rsn']})
            
    batch_updates = []
    
    for row in all_records:
        discord_name = row.get('Discord Name', str(row.get('Discord ID', 'Unknown')))
        clean_id = str(row.get('Discord ID', 'Unknown')).replace("'", "")
        sys_flags = str(row.get('System Flags', ''))
        wom_ids_str = str(row.get('WOM IDs', ''))
        
        # If a user is archived, we skip their individual API lookups unless they have reappeared in the clan.
        # This saves a significant number of API calls for long-running clans with many past members.
        if SystemFlag.ARCHIVED.value in sys_flags:
            wids_list = [w.strip() for w in wom_ids_str.split(',') if w.strip()]
            has_rejoined = any(wid in group_roster for wid in wids_list)
            if not has_rejoined:
                logger.trace(f"Skipping archived user: {discord_name}")
                continue

        if not wom_ids_str.strip():
            continue
            
        wids = [w.strip() for w in wom_ids_str.split(',') if w.strip()]
        tracked_wom_ids.update(wids)
        
        new_rsns, new_clans, new_ranks = [], [], []
        needs_update = False
        
        existing_rsns = [x.strip() for x in str(row.get('RSNs', '')).split(',')]
        existing_clans = [x.strip() for x in str(row.get('Account Clan', '')).split(',')]
        existing_ranks = [x.strip() for x in str(row.get('Game Ranks', '')).split(',')]
        
        for idx, wid in enumerate(wids):
            if wid in group_roster:
                # Memory hit (Fast!)
                rsn = group_roster[wid]['rsn']
                new_rsns.append(rsn)
                new_clans.append(target_clan_name)
                new_ranks.append(group_roster[wid]['rank'])
            else:
                # API / Cache hit (Fallback for players not in the clan)
                try:
                    player_data = wom_client.get(f'/players/id/{wid}', cache_key=f"player_{wid}")
                    
                    if player_data:
                        rsn = player_data.get('displayName') or player_data.get('username') or 'Unknown'
                        new_rsns.append(rsn)
                        
                        username = player_data.get('username')
                        if username:
                            groups_res = wom_client.get(f'/players/{quote(username)}/groups', cache_key=f"groups_{wid}")
                            if groups_res:
                                valid_groups = []
                                for g in groups_res:
                                    g_name = g.get('group', {}).get('name', 'Unknown')
                                    g_chat = g.get('group', {}).get('clanChat')
                                    g_role = str(g.get('role', '')).lower()
                                    
                                    # Filter out Events, Bingos, and Skilling lists
                                    if g_chat and g_role != 'member':
                                        valid_groups.append((g_name, g.get('role', 'Unknown')))
                                        
                                if valid_groups:
                                    new_clans.append(valid_groups[0][0])
                                    new_ranks.append(valid_groups[0][1])
                                else:
                                    new_clans.append('None')
                                    new_ranks.append('None')
                            else:
                                new_clans.append('None')
                                new_ranks.append('None')
                        else:
                            new_clans.append('None')
                            new_ranks.append('None')
                    else:
                        new_rsns.append('Unknown')
                        new_clans.append('Unknown')
                        new_ranks.append('Unknown')
                except Exception as e:
                    logger.error(f"Failed to fetch WOM ID {wid}: {e}. Falling back to existing local data.")
                    new_rsns.append(existing_rsns[idx] if idx < len(existing_rsns) and existing_rsns[idx] else 'Unknown')
                    new_clans.append(existing_clans[idx] if idx < len(existing_clans) and existing_clans[idx] else 'Unknown')
                    new_ranks.append(existing_ranks[idx] if idx < len(existing_ranks) and existing_ranks[idx] else 'Unknown')
        
        # Reconstruct and check for changes
        new_rsns_str, new_clans_str, new_ranks_str = ", ".join(new_rsns), ", ".join(new_clans), ", ".join(new_ranks)
        
        if str(row.get('RSNs', '')) != new_rsns_str:
            batch_updates.append({'id': clean_id, 'col_name': 'RSNs', 'value': new_rsns_str})
            needs_update = True
        if str(row.get('Account Clan', '')) != new_clans_str:
            batch_updates.append({'id': clean_id, 'col_name': 'Account Clan', 'value': new_clans_str})
            needs_update = True
        if str(row.get('Game Ranks', '')) != new_ranks_str:
            batch_updates.append({'id': clean_id, 'col_name': 'Game Ranks', 'value': new_ranks_str})
            needs_update = True
            
        if all_name_changes is not None:
            user_history = {}
            for wid in wids:
                if wid in all_name_changes:
                    user_history[wid] = all_name_changes[wid]
            new_history_str = json.dumps(user_history, separators=(',', ':')) if user_history else ""
            
            if str(row.get('Name History', '')).strip() != new_history_str:
                batch_updates.append({'id': clean_id, 'col_name': 'Name History', 'value': new_history_str})
                needs_update = True
            
        if needs_update:
            audit_logs.append(f"Data Update - {discord_name} ({clean_id}): Synced WOM data ({len(wids)} accounts).")

    if batch_updates:
        db_manager.batch_update_by_id('Database', 'Discord ID', batch_updates)
        logger.success(f"Executed {len(batch_updates)} WOM data cell updates.")
    
    untracked_members = []
    for wid, data in group_roster.items():
        if wid not in tracked_wom_ids:
            untracked_members.append({'wom_id': wid, 'rsn': data['rsn'], 'rank': data['rank']})
            
    if untracked_members:
        logger.warning(f"Found {len(untracked_members)} untracked members in WOM group.")
        
    return untracked_members, banned_members, failed_updates