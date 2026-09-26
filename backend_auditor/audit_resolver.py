import os
import time
import sys
from dotenv import load_dotenv
from db_manager import DBManager
import run_auditor as orchestrator
from constants import SystemFlag, SHARED_SECRETS_DIR, SHARED_DATA_DIR
from sqlite_manager import SQLiteManager

# --- ANSI COLORS ---
RESET = "\033[0m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
DARK_GRAY = "\033[90m"
MAGENTA = "\033[95m"
LIGHT_BLUE = "\033[94m"

load_dotenv(SHARED_SECRETS_DIR / ".env")
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

if not SPREADSHEET_ID:
    print(f"{RED}Error: SPREADSHEET_ID not found in environment.{RESET}")
    sys.exit(1)

def modify_flags(current_str, add_flags=None, remove_flags=None):
    flags = [f.strip() for f in current_str.split(',') if f.strip()]
    if add_flags:
        for f in add_flags:
            if f not in flags:
                flags.append(f)
    if remove_flags:
        for f in remove_flags:
            if f in flags:
                flags.remove(f)
    return ", ".join(flags) if flags else ""

def compute_rank_suggestions(member, valid_ranks, discord_req_to_rank, ig_main_to_rank, rank_to_exc_roles, role_map, target_clan_name):
    d_ranks_raw = [r.strip().replace("'", "") for r in str(member.get('Discord Ranks', '')).split(',') if r.strip()]
    
    clans_list = [c.strip() for c in str(member.get('Account Clan', '')).split(',') if c.strip()]
    ranks_list = [rk.strip() for rk in str(member.get('Game Ranks', '')).split(',') if rk.strip()]
    
    target_game_ranks = []
    for idx, clan in enumerate(clans_list):
        if clan.lower() == target_clan_name.lower():
            if idx < len(ranks_list):
                rk = ranks_list[idx]
                if rk and rk != 'Unknown':
                    target_game_ranks.append(rk)
                    
    if not target_game_ranks:
        target_game_ranks = [rk for rk in ranks_list if rk and rk != 'Unknown']

    suggestions = set()
    reasons = {}
    invalid_ranks = set()

    for dr in d_ranks_raw:
        if dr in discord_req_to_rank:
            for cr in discord_req_to_rank[dr]:
                suggestions.add(cr)
                role_name = role_map.get(dr, f"Role ID: {dr}")
                reasons.setdefault(cr, []).append(f"Discord Req '{role_name}'")

        for cr in valid_ranks:
            if dr in rank_to_exc_roles.get(cr, []):
                invalid_ranks.add(cr)

    for ir in target_game_ranks:
        if ir.lower() in ig_main_to_rank:
            for cr in ig_main_to_rank[ir.lower()]:
                suggestions.add(cr)
                reasons.setdefault(cr, []).append(f"Main In-Game '{ir}'")

    suggestions = suggestions - invalid_ranks

    perfect_matches = {
        r for r in suggestions 
        if any("Discord Req" in res for res in reasons.get(r, [])) 
        and any("Main In-Game" in res for res in reasons.get(r, []))
    }
    if perfect_matches:
        suggestions = perfect_matches

    sorted_suggestions = [r for r in valid_ranks if r in suggestions]
    return sorted_suggestions, reasons

def prompt_rank_picker(valid_ranks, suggestions, reasons):
    print(f"\n{CYAN}--- Clan Rank Selector ---{RESET}")
    print(f"  0: ↩️  Cancel / Back")
    choice_map = {}
    current_choice = 1

    # Suggestions first
    for rank in valid_ranks:
        if rank in suggestions:
            reason_str = f" {DARK_GRAY}(Matches: {', '.join(dict.fromkeys(reasons[rank]))}){RESET}"
            print(f"  {current_choice}: {YELLOW}⭐ {rank}{RESET}{reason_str}")
            choice_map[current_choice] = rank
            current_choice += 1

    # Remaining valid ranks
    for rank in valid_ranks:
        if rank not in suggestions:
            print(f"  {current_choice}:    {rank}")
            choice_map[current_choice] = rank
            current_choice += 1

    while True:
        choice = input(f"\nSelect rank [0-{len(valid_ranks)}] or 'c' to cancel: ").strip().lower()
        if choice in ['0', 'c']:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(valid_ranks):
            return choice_map[int(choice)]
        print(f"{RED}Invalid input. Please enter a number between 0 and {len(valid_ranks)}.{RESET}")


def print_member_details(member, role_map, managed_roles, active_issues=None):
    d_name = str(member.get('Discord Name', '')).strip()
    d_id = str(member.get('Discord ID', '')).replace("'", "").strip()
    notes = str(member.get('User Notes', '')).strip()
    sheet_rank = str(member.get('Clan Rank', '')).strip() or "None"
    sys_flags = str(member.get('System Flags', '')).strip() or "None"
    admin_flags = str(member.get('Admin Flags', '')).strip() or "None"
    
    duration_str = ""
    if active_issues:
        matched = [info['formatted_tag'] for k, info in active_issues.items() if k[0] == 'member' and str(k[1]) == d_id]
        if matched:
            duration_str = f" {matched[0]}"
            
    discord_ranks_raw = [r.strip().replace("'", "") for r in str(member.get('Discord Ranks', '')).split(',') if r.strip()]
    relevant_d_ranks = [r for r in discord_ranks_raw if r in managed_roles]
    readable_roles = [role_map.get(r, f"Unknown ({r})") for r in relevant_d_ranks]
    roles_disp = ", ".join(readable_roles) if readable_roles else "None"
    
    rsns_list = [r.strip() for r in str(member.get('RSNs', '')).split(',') if r.strip()]
    woms_list = [w.strip() for w in str(member.get('WOM IDs', '')).split(',') if w.strip()]
    clans_list = [c.strip() for c in str(member.get('Account Clan', '')).split(',') if c.strip()]
    ranks_list = [rk.strip() for rk in str(member.get('Game Ranks', '')).split(',') if rk.strip()]
    
    print(f"\n--------------------------------------------------")
    print(f"👤 Member: {GREEN}{d_name}{RESET}{MAGENTA}{duration_str}{RESET} {DARK_GRAY}[Discord ID: {d_id}]{RESET}")
    if notes:
        print(f"   {DARK_GRAY}↳ Notes:{RESET} {notes}")
    print(f"   {DARK_GRAY}↳ Sheet Rank:{RESET} {YELLOW}{sheet_rank}{RESET} {DARK_GRAY}| Discord Roles:{RESET} {roles_disp}")
    print(f"   {DARK_GRAY}↳ System Flags:{RESET} {sys_flags}")
    print(f"   {DARK_GRAY}↳ Admin Flags:{RESET} {admin_flags}")
    print(f"   {DARK_GRAY}↳ Linked RSNs:{RESET}")
    
    if not rsns_list:
        print(f"     {DARK_GRAY}- None{RESET}")
    else:
        for idx, rsn in enumerate(rsns_list):
            wid = woms_list[idx] if idx < len(woms_list) else "Unknown"
            clan = clans_list[idx] if idx < len(clans_list) else "Unknown"
            rank = ranks_list[idx] if idx < len(ranks_list) else "Unknown"
            print(f"     - {GREEN}{rsn}{RESET} {DARK_GRAY}[WOM ID: {wid}] [{clan} : {rank}]{RESET}")

def main():
    print(f"{CYAN}Initializing Audit Resolver...{RESET}")
    db = DBManager(SPREADSHEET_ID)
    
    print(f"\n{YELLOW}Data might be stale. Do you want to run a silent database audit before resolving?{RESET}")
    print(f"  {DARK_GRAY}(This updates Discord names, WOM clans, and recalculates system flags without sending pings){RESET}")
    while True:
        sync_choice = input("Select [y/n]: ").strip().lower()
        if sync_choice in ['y', 'n']:
            break
            
    if sync_choice == 'y':
        print(f"\n{CYAN}Running silent audit... Please wait.{RESET}")
        orchestrator.run_orchestrator(force_wom=False, skip_webhook=True, sync_only=False)
        print(f"{GREEN}Audit complete!{RESET}\n")

    print("Loading Reference Data mapping...")
    ref_records = db.get_all_records('Reference_Data')
    valid_ranks = []
    discord_req_to_rank = {}
    ig_main_to_rank = {}
    rank_to_exc_roles = {}
    managed_roles = set()
    all_req_roles = set()
    for row in ref_records:
        clan_rank = str(row.get('Clan Rank', '')).strip()
        if not clan_rank:
            continue
        valid_ranks.append(clan_rank)
        req_roles = [r.strip() for r in str(row.get('Required Discord Roles', '')).split(',') if r.strip()]
        all_req_roles.update(req_roles)
        all_roles = [r.strip() for r in str(row.get('Allowed Discord Roles', '')).split(',') if r.strip()]
        exc_roles = [r.strip() for r in str(row.get('Excluded Discord Roles', '')).split(',') if r.strip()]
        main_rank = str(row.get('Main In-Game Rank', '')).strip()

        for dr in req_roles:
            discord_req_to_rank.setdefault(dr, []).append(clan_rank)

        if main_rank:
            ig_main_to_rank.setdefault(main_rank.lower(), []).append(clan_rank)

        rank_to_exc_roles[clan_rank] = exc_roles
        managed_roles.update(req_roles + all_roles + exc_roles)

    print("Loading Discord Roles mapping...")
    roles_records = db.get_all_records('Discord_Roles')
    role_map = {str(row.get('Role ID', '')).replace("'", ""): str(row.get('Role Name', '')) for row in roles_records}

    print("Loading System Config...")
    config_records = db.get_all_records('System_Config')
    system_config = {str(row.get('Setting Name', '')).strip(): str(row.get('Value', '')).strip() for row in config_records}
    target_clan_name = system_config.get('Target Clan Name', 'Unknown Clan')

    print("Loading current Database...")
    db_records = db.get_all_records('Database')
    
    sqlite_mgr = SQLiteManager(SHARED_DATA_DIR / "databases" / "history.db")
    active_issues = sqlite_mgr.get_active_issues()

    categories = {
        1: {
            'name': "🚪 Missing from In-Game Clan",
            'description': "Has a clan rank or Discord role, but none are in the WOM clan.",
            'members': [],
            'actions': [
                {"label": "Add 'On Leave' (Hiatus)", "add": ["On Leave"]},
                {"label": "Add 'Ignore Error: Clan Departure' (Keep sheet rank/discord, ignore departure)", "add": ["Ignore Error: Clan Departure"]}
            ]
        },
        2: {
            'name': "👋 Returning Members Detected",
            'description': "Active in the clan but marked as departed or on leave.",
            'members': [],
            'actions': [
                {"label": "Remove departure admin flag(s) (Clears 'On Leave' and 'Ignore Error: Clan Departure')", "remove": ["On Leave", "Ignore Error: Clan Departure"]}
            ]
        },
        3: {
            'name': "🏃 Left Discord but still in Clan",
            'description': "Left the Discord server but still has active accounts in the WOM clan.",
            'members': [],
            'actions': [
                {"label": "Add 'Ignore Error: Not in Discord'", "add": ["Ignore Error: Not in Discord"]}
            ]
        },
        4: {
            'name': "⚔️ Multiple Clans Detected",
            'description': "Member has accounts in other clans.",
            'members': [],
            'actions': [
                {"label": "Add 'Ignore Error: Multiple Clans'", "add": ["Ignore Error: Multiple Clans"]}
            ]
        },
        5: {
            'name': "⚖️ Rank & Role Mismatches",
            'description': "Discrepancy between Google Sheet, Discord roles, and in-game ranks.",
            'members': [],
            'actions': [
                {"label": "Add 'Ignore Error: Rank Mismatch'", "add": ["Ignore Error: Rank Mismatch"]},
                {"label": "Add 'On Leave'", "add": ["On Leave"]}
            ]
        },
        6: {
            'name': "⚠️ Ranked Members Missing RSNs",
            'description': "Has clan rank or Discord role but no OSRS accounts linked.",
            'members': [],
            'actions': [
                {"label": "Add 'Ignore Error: Missing RSNs'", "add": ["Ignore Error: Missing RSNs"]}
            ]
        }
    }

    batch_updates = []
    audit_logs = []
    
    while True:
        # Re-categorize members based on current db_records state
        for cat_id in categories:
            categories[cat_id]['members'] = []
            
        for row in db_records:
            sys_flags_str = str(row.get('System Flags', ''))
            sys_flags = {f.strip() for f in sys_flags_str.split(',') if f.strip()}
            
            admin_flags_str = str(row.get('Admin Flags', ''))
            admin_flags = {f.strip() for f in admin_flags_str.split(',') if f.strip()}
            
            account_clan_str = str(row.get('Account Clan', ''))
            account_clans = [c.strip().lower() for c in account_clan_str.split(',') if c.strip()]
            
            # Category conditions matching audit logic
            clan_rank = str(row.get('Clan Rank', '')).strip()
            discord_ranks = str(row.get('Discord Ranks', '')).strip()
            user_roles = [r.strip().replace("'", "") for r in discord_ranks.split(',') if r.strip()]
            has_req_discord_role = any(r in all_req_roles for r in user_roles)
            wom_ids_str = str(row.get('WOM IDs', '')).strip()
            has_wom_ids = bool([w for w in wom_ids_str.split(',') if w.strip()])
            
            # 1. Missing from In-Game Clan
            if (clan_rank or has_req_discord_role) and has_wom_ids:
                if "Not in WOM Clan" in sys_flags:
                    if not ("Ignore Error: Clan Departure" in admin_flags or "On Leave" in admin_flags):
                        categories[1]['members'].append(row)
                        
            # 2. Returning Members Detected
            departure_flags = [f for f in admin_flags if f in ["Ignore Error: Clan Departure", "On Leave"]]
            active_in_target = any(c == target_clan_name.lower() for c in account_clans)
            if departure_flags and active_in_target:
                categories[2]['members'].append(row)
                
            # 3. Left Discord
            if "Not in Discord" in sys_flags:
                if "Ignore Error: Not in Discord" not in admin_flags:
                    categories[3]['members'].append(row)
                    
            # 4. Multiple Clans
            if "Multiple Clans" in sys_flags:
                if "Ignore Error: Multiple Clans" not in admin_flags:
                    categories[4]['members'].append(row)
                    
            # 5. Rank Mismatch
            if "Rank Mismatch" in sys_flags:
                if not ("Ignore Error: Rank Mismatch" in admin_flags or "On Leave" in admin_flags):
                    categories[5]['members'].append(row)
                    
            # 6. Missing RSNs
            if "Missing RSNs" in sys_flags:
                if "Ignore Error: Missing RSNs" not in admin_flags:
                    categories[6]['members'].append(row)

        print(f"\n==================================================")
        print(f"              {CYAN}AUDIT RESOLUTION MENU{RESET}")
        print(f"==================================================")
        for cat_id, cat in categories.items():
            print(f"  {cat_id}: {cat['name']} ({len(cat['members'])} issues)")
        print(f"==================================================")
        print(f"Enter section [1-6] to resolve issues,")
        print(f"  's' to save queued updates and run a silent audit (refreshes menu),")
        print(f"  'q' to save queued updates and quit resolver,")
        print(f"  'x' to cancel all unsaved queued changes and exit.")
        
        while True:
            menu_choice = input(f"Select option: ").strip().lower()
            if menu_choice in ['1', '2', '3', '4', '5', '6', 's', 'q', 'x']:
                break
            print(f"{RED}Invalid menu choice.{RESET}")
            
        if menu_choice == 'x':
            print(f"{YELLOW}Exiting. All queued changes canceled.{RESET}")
            break
            
        elif menu_choice == 'q':
            if batch_updates:
                print(f"\n{CYAN}Applying {len(batch_updates)} updates to the database...{RESET}")
                db.batch_update_by_id('Database', 'Discord ID', batch_updates)
                db.append_audit_logs(audit_logs)
                print(f"{GREEN}✅ Successfully updated the database!{RESET}")
            else:
                print(f"{YELLOW}No updates to apply.{RESET}")
            break
            
        elif menu_choice == 's':
            if batch_updates:
                print(f"\n{CYAN}Applying {len(batch_updates)} updates to the database...{RESET}")
                db.batch_update_by_id('Database', 'Discord ID', batch_updates)
                db.append_audit_logs(audit_logs)
                print(f"{GREEN}✅ Successfully updated the database!{RESET}")
                batch_updates = []
                audit_logs = []
            else:
                print(f"{YELLOW}No pending updates to apply.{RESET}")
                
            print(f"\n{CYAN}Running silent database audit/sync... Please wait.{RESET}")
            orchestrator.run_orchestrator(force_wom=False, skip_webhook=True, sync_only=False)
            print(f"{GREEN}Sync and audit complete!{RESET}\n")
            
            # Reload fresh database records so we have the newly calculated flags
            print("Reloading database...")
            db_records = db.get_all_records('Database')
            continue
            
        else:
            cat_id = int(menu_choice)
            cat = categories[cat_id]
            members_list = cat['members']
            if not members_list:
                print(f"{YELLOW}No issues in section {cat_id}.{RESET}")
                continue
                
            print(f"\n{CYAN}Category {cat_id}: {cat['name']} ({len(members_list)} issues){RESET}")
            print(f"{DARK_GRAY}{cat['description']}{RESET}")
            
            for idx, member in enumerate(members_list, 1):
                print_member_details(member, role_map, managed_roles, active_issues)
                
                # Check dynamic actions for this member
                member_actions = cat['actions'].copy()
                sys_flags_str = str(member.get('System Flags', ''))
                sys_flags = {f.strip() for f in sys_flags_str.split(',') if f.strip()}
                discord_ranks = str(member.get('Discord Ranks', '')).strip()
                
                is_not_in_discord = ("Not in Discord" in sys_flags) or (not discord_ranks or discord_ranks == "None" or discord_ranks == "''")
                
                if cat_id == 1 and is_not_in_discord:
                    member_actions.append({
                        "label": "Clear Sheet Rank (Archives member on next run)",
                        "clear_sheet_rank": True
                    })

                if cat_id == 5:
                    suggestions, reasons = compute_rank_suggestions(
                        member, valid_ranks, discord_req_to_rank, ig_main_to_rank,
                        rank_to_exc_roles, role_map, target_clan_name
                    )
                    rank_actions = []
                    for rank in suggestions[:2]:
                        reason_summary = ", ".join(dict.fromkeys(reasons.get(rank, [])))
                        rank_actions.append({
                            "label": f"🎯 Update Sheet Rank to '{rank}' ⭐ {DARK_GRAY}(Matches: {reason_summary}){RESET}",
                            "set_sheet_rank": rank
                        })
                    rank_actions.append({
                        "label": "📝 Choose a different Sheet Rank (Rank Picker)..." if suggestions else "📝 Update Sheet Rank (Rank Picker)...",
                        "pick_rank": True,
                        "suggestions": suggestions,
                        "reasons": reasons
                    })
                    member_actions = rank_actions + member_actions

                quit_category = False
                while True:
                    print(f"\nSelect action for {GREEN}{member.get('Discord Name')}{RESET} (Progress: {idx}/{len(members_list)}):")
                    action_map = {}
                    for act_idx, action in enumerate(member_actions, 1):
                        print(f"  {act_idx}: {action['label']}")
                        action_map[act_idx] = action
                    print(f"  0: ⏭️  Skip / No Action")
                    
                    while True:
                        act_choice = input(f"Select [0-{len(member_actions)}] or 'q' to return to menu: ").strip().lower()
                        if act_choice == 'q':
                            quit_category = True
                            break
                        if act_choice.isdigit() and 0 <= int(act_choice) <= len(member_actions):
                            act_choice = int(act_choice)
                            break
                        print(f"{RED}Invalid input.{RESET}")
                        
                    if quit_category:
                        print(f"{YELLOW}Returning to main menu...{RESET}")
                        break
                        
                    if act_choice == 0:
                        print(f"{YELLOW}Skipped member.{RESET}")
                        break
                        
                    selected_action = action_map[act_choice]
                    
                    if selected_action.get('pick_rank'):
                        picked = prompt_rank_picker(valid_ranks, selected_action['suggestions'], selected_action['reasons'])
                        if not picked:
                            print(f"{YELLOW}Rank selection canceled.{RESET}")
                            continue
                        selected_action = {'set_sheet_rank': picked}
                        
                    current_admin_flags = str(member.get('Admin Flags', ''))
                    d_id = str(member.get('Discord ID', '')).replace("'", "").strip()
                    d_name = str(member.get('Discord Name', '')).strip()
                    
                    updates_for_member = []
                    action_desc_parts = []
                    
                    if selected_action.get('set_sheet_rank'):
                        new_rank = selected_action['set_sheet_rank']
                        old_rank = str(member.get('Clan Rank', '')).strip()
                        updates_for_member.append({'id': d_id, 'col_name': 'Clan Rank', 'value': new_rank})
                        member['Clan Rank'] = new_rank
                        if old_rank and old_rank != 'None':
                            action_desc_parts.append(f"Updated Clan Rank from '{old_rank}' to '{new_rank}'")
                        else:
                            action_desc_parts.append(f"Assigned Clan Rank '{new_rank}'")
                    
                    if selected_action.get('clear_sheet_rank'):
                        updates_for_member.append({'id': d_id, 'col_name': 'Clan Rank', 'value': ''})
                        member['Clan Rank'] = ''
                        action_desc_parts.append("Cleared Clan Rank")
                    
                    if selected_action.get('add') or selected_action.get('remove'):
                        new_admin_flags = modify_flags(current_admin_flags, add_flags=selected_action.get('add'), remove_flags=selected_action.get('remove'))
                        updates_for_member.append({'id': d_id, 'col_name': 'Admin Flags', 'value': new_admin_flags})
                        member['Admin Flags'] = new_admin_flags
                        
                        if selected_action.get('add'):
                            action_desc_parts.append(f"Added Admin Flag(s): {', '.join(selected_action.get('add'))}")
                        if selected_action.get('remove'):
                            action_desc_parts.append(f"Removed Admin Flag(s): {', '.join(selected_action.get('remove'))}")
                            
                    for u in updates_for_member:
                        batch_updates.append(u)
                        
                    action_desc = " and ".join(action_desc_parts)
                    msg = f"Manual Update - {d_name} ({d_id}): {action_desc}."
                    audit_logs.append(msg)
                    print(f"{GREEN}Queued: {action_desc}{RESET}")
                    break

                if quit_category:
                    break

if __name__ == '__main__':
    main()
