import requests
from datetime import datetime
import time
from loguru import logger
from constants import SystemFlag

DISCORD_API_BASE_URL = 'https://discord.com/api/v10'

def get_discord_roles(bot_token, guild_id):
    """Fetches all roles from the Discord server."""
    headers = {"Authorization": f"Bot {bot_token}"}
    url = f"{DISCORD_API_BASE_URL}/guilds/{guild_id}/roles"
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    return res.json()

def sync_roles(db_manager, bot_token, guild_id, audit_logs):
    """Syncs Discord roles to the Discord_Roles tab."""
    logger.info("Fetching roles from Discord...")
    api_roles = get_discord_roles(bot_token, guild_id)
    
    sheet_data = db_manager.get_all_records('Discord_Roles')
    # Strip visual apostrophes for safe memory comparison
    sheet_roles = {str(row['Role ID']).replace("'", ""): row for row in sheet_data}
    
    # Prepare the new complete data payload
    updated_roles = []
    api_role_ids = set()
    
    for role in api_roles:
        role_id = str(role['id'])
        role_name = role['name']
        api_role_ids.add(role_id)
        # Prepend apostrophe to ID to force string in Google Sheets
        updated_roles.append([f"'{role_id}", role_name, "OK"])
        
        if role_id not in sheet_roles:
            audit_logs.append(f"New Role - System (N/A): Discovered and added Discord Role '{role_name}' ({role_id}).")
        elif sheet_roles[role_id]['Role Name'] != role_name:
            audit_logs.append(f"Role Update - System (N/A): Discord Role Name changed from '{sheet_roles[role_id]['Role Name']}' -> '{role_name}' ({role_id}).")

    # Check for deleted/missing roles that are in the sheet but not in Discord
    for role_id, row in sheet_roles.items():
        if role_id not in api_role_ids:
            if row['Status'] != 'Not Found':
                audit_logs.append(f"Role Missing - System (N/A): Discord Role missing or deleted '{row['Role Name']}' ({role_id}).")
            updated_roles.append([f"'{role_id}", row['Role Name'], "Not Found"])
            
    db_manager.clear_and_rewrite('Discord_Roles', ["Role ID", "Role Name", "Status"], updated_roles)
        
    logger.success(f"Synced {len(updated_roles)} roles to Discord_Roles tab.")
    
    # Return a mapping dictionary for the member sync to use
    return {str(r['id']): r['name'] for r in api_roles}

def get_discord_members(bot_token, guild_id):
    """Fetches all members from the Discord server using pagination."""
    headers = {"Authorization": f"Bot {bot_token}"}
    members = []
    limit = 1000
    after = 0
    
    while True:
        url = f"{DISCORD_API_BASE_URL}/guilds/{guild_id}/members?limit={limit}&after={after}"
        res = requests.get(url, headers=headers)
        if res.status_code == 403:
            logger.error("403 Forbidden: Cannot fetch Discord members. Ensure 'Server Members Intent' is enabled in the Discord Developer Portal!")
            raise Exception("Discord API 403 Forbidden: Missing Server Members Intent.")
        res.raise_for_status()
        batch = res.json()
        members.extend(batch)
        if len(batch) < limit:
            break
        after = batch[-1]['user']['id']
        
    return members

def sync_members(db_manager, bot_token, guild_id, role_map, audit_logs):
    """Discovers new members and updates existing members' volatile Discord data."""
    logger.info("Fetching members from Discord...")
    api_members = get_discord_members(bot_token, guild_id)
    
    headers = db_manager.get_headers('Database')
    all_records = db_manager.get_all_records('Database')
    # Strip visual apostrophes for safe memory comparison
    sheet_members = {str(row['Discord ID']).replace("'", ""): {'row_num': idx + 2, 'data': row} for idx, row in enumerate(all_records)}
    
    new_rows = []
    # To avoid concurrency conflicts, we only want to update specific cells for existing members
    batch_updates = [] 
    
    api_member_ids = set()
    today = datetime.utcnow().strftime('%Y-%m-%d')

    for member in api_members:
        user_id = str(member['user']['id'])
        api_member_ids.add(user_id)
        
        # Use display_name (nickname) if set, otherwise global username
        display_name = member.get('nick') or member.get('user', {}).get('global_name') or member.get('user', {}).get('username')
        
        # Map role IDs to human-readable names
        role_ids = [str(r_id) for r_id in member.get('roles', [])]
        roles_str_db = ", ".join(role_ids) # Store pure IDs in the DB
        
        member_role_names = [role_map.get(r_id, f"Unknown Role ({r_id})") for r_id in role_ids]
        roles_str_log = ", ".join(member_role_names) # Use names for human readable Audit Logs
        
        join_date = member.get('joined_at', '').split('T')[0] if member.get('joined_at') else today
        
        if user_id not in sheet_members:
            # Member is completely new! Append them.
            new_row = [''] * len(headers)
            new_row[headers.index('Discord ID')] = f"'{user_id}"
            new_row[headers.index('Discord Name')] = display_name
            new_row[headers.index('Discord Ranks')] = roles_str_db
            new_row[headers.index('Join Date')] = join_date
            new_row[headers.index('System Flags')] = SystemFlag.OK.value
            new_rows.append(new_row)
            logger.info(f"Discovered new member: {display_name} ({user_id})")
            audit_logs.append(f"New Member - {display_name} ({user_id}): Discovered and appended to database.")
        else:
            # Member exists! Check if we need to update their volatile data
            existing = sheet_members[user_id]['data']
            row_num = sheet_members[user_id]['row_num']
            
            if str(existing.get('Discord Name', '')) != display_name:
                batch_updates.append({'id': user_id, 'col_name': 'Discord Name', 'value': display_name})
                audit_logs.append(f"Data Update - {display_name} ({user_id}): Discord Name changed from '{existing.get('Discord Name')}'.")
                
            # Compare against DB string (IDs)
            if str(existing.get('Discord Ranks', '')).replace("'", "") != roles_str_db:
                batch_updates.append({'id': user_id, 'col_name': 'Discord Ranks', 'value': roles_str_db})
                audit_logs.append(f"Data Update - {display_name} ({user_id}): Discord Roles updated to '{roles_str_log}'.")
                
            # Clear 'Not in Discord' flag if it was previously set
            sys_flags = str(existing.get('System Flags', ''))
            if SystemFlag.NOT_IN_DISCORD.value in sys_flags:
                new_flags = db_manager.update_flags(sys_flags, remove_flags=[SystemFlag.NOT_IN_DISCORD.value])
                batch_updates.append({'id': user_id, 'col_name': 'System Flags', 'value': new_flags})
                audit_logs.append(f"Flag Removed - {display_name} ({user_id}): Cleared 'Not in Discord' flag.")

    # Check for missing users to flag 'Not in Discord'
    for user_id, info in sheet_members.items():
        if user_id not in api_member_ids:
            existing = info['data']
            row_num = info['row_num']
            sys_flags = str(existing.get('System Flags', ''))
            admin_flags = str(existing.get('Admin Flags', ''))
            discord_ranks = str(existing.get('Discord Ranks', '')).replace("'", "")
            
            # If they aren't already flagged, and the Admin hasn't acknowledged it
            if SystemFlag.NOT_IN_DISCORD.value not in sys_flags and SystemFlag.NOT_IN_DISCORD.value not in admin_flags:
                new_flags = db_manager.update_flags(sys_flags, add_flags=[SystemFlag.NOT_IN_DISCORD.value])
                batch_updates.append({'id': user_id, 'col_name': 'System Flags', 'value': new_flags})
                audit_logs.append(f"Flag Added - {existing.get('Discord Name', user_id)} ({user_id}): Flagged as 'Not in Discord'.")

            # Clear Discord Ranks if they are not already empty
            if discord_ranks:
                batch_updates.append({'id': user_id, 'col_name': 'Discord Ranks', 'value': ''})
                audit_logs.append(f"Data Update - {existing.get('Discord Name', user_id)} ({user_id}): Cleared Discord Ranks (User left Discord).")

    if new_rows:
        db_manager.append_rows('Database', new_rows)
        logger.success(f"Appended {len(new_rows)} new members to the database.")
    
    if batch_updates:
        db_manager.batch_update_by_id('Database', 'Discord ID', batch_updates)
        logger.success(f"Updated {len(batch_updates)} cells for existing members.")