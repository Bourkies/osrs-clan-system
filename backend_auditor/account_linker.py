import os
import time
import difflib
from urllib.parse import quote
from dotenv import load_dotenv
from db_manager import DBManager
from wom_client import WomClient
import run_auditor as orchestrator

# --- ANSI COLORS ---
RESET = "\033[0m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
DARK_GRAY = "\033[90m"

load_dotenv()
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

def main():
    print(f"{CYAN}Initializing Account Linker...{RESET}")
    db = DBManager(SPREADSHEET_ID)
    
    print(f"\n{YELLOW}Data might be stale. Do you want to run a silent database sync before linking?{RESET}")
    print(f"  {DARK_GRAY}(This updates Discord names, WOM clans, and API caches without firing the webhook){RESET}")
    while True:
        sync_choice = input("Select [y/n]: ").strip().lower()
        if sync_choice in ['y', 'n']:
            break
            
    if sync_choice == 'y':
        print(f"\n{CYAN}Running silent sync... Please wait.{RESET}")
        orchestrator.run_orchestrator(force_wom=False, skip_webhook=True, sync_only=True)
        print(f"{GREEN}Sync complete!{RESET}\n")

    print("Fetching live WOM Roster...")
    wom = WomClient()
    config_records = db.get_all_records('System_Config')
    system_config = {str(row.get('Setting Name', '')).strip(): str(row.get('Value', '')).strip() for row in config_records}
    target_clan_name = system_config.get('Target Clan Name', 'Unknown Clan')
    
    search_res = wom.get(f'/groups?name={quote(target_clan_name)}&limit=1', cache_key=f"group_search_{target_clan_name}")
    if not search_res or search_res[0].get('name', '').lower() != target_clan_name.lower():
        print(f"{RED}Could not find exact WOM Group matching '{target_clan_name}'{RESET}")
        return
        
    group_id = search_res[0]['id']
    group_res = wom.get(f'/groups/{group_id}', cache_key=f"group_details_{group_id}")
    if not group_res:
        print(f"{RED}Failed to fetch details for Group ID {group_id}{RESET}")
        return
        
    wom_roster = group_res.get('memberships', [])

    print("Loading Reference Data mapping...")
    ref_records = db.get_all_records('Reference_Data')
    managed_roles = set()
    for row in ref_records:
        clan_rank = str(row.get('Clan Rank', '')).strip()
        if not clan_rank:
            continue
        req_roles = [r.strip() for r in str(row.get('Required Discord Roles', '')).split(',') if r.strip()]
        all_roles = [r.strip() for r in str(row.get('Allowed Discord Roles', '')).split(',') if r.strip()]
        exc_roles = [r.strip() for r in str(row.get('Excluded Discord Roles', '')).split(',') if r.strip()]
        
        managed_roles.update(req_roles + all_roles + exc_roles)

    print("Loading Discord Roles mapping...")
    roles_records = db.get_all_records('Discord_Roles')
    role_map = {str(row.get('Role ID', '')).replace("'", ""): str(row.get('Role Name', '')) for row in roles_records}

    print("Loading current Database...")
    db_records = db.get_all_records('Database')
    
    tracked_wom_ids = {}
    members_data = []
    for row in db_records:
        d_id = str(row.get('Discord ID', '')).replace("'", "")
        d_name = str(row.get('Discord Name', ''))
        u_notes = str(row.get('User Notes', ''))
        wom_raw = str(row.get('WOM IDs', ''))
        
        members_data.append({
            'discord_id': d_id,
            'discord_name': d_name,
            'user_notes': u_notes,
            'wom_ids_raw': wom_raw,
            'clan_rank': str(row.get('Clan Rank', '')).strip(),
            'discord_ranks': str(row.get('Discord Ranks', '')).replace("'", "").strip(),
            'rsns': str(row.get('RSNs', '')).strip(),
            'game_ranks': str(row.get('Game Ranks', '')).strip(),
            'account_clans': str(row.get('Account Clan', '')).strip()
        })
        
        wids = [w.strip() for w in wom_raw.split(',') if w.strip()]
        for w in wids:
            tracked_wom_ids[w] = d_id
            
    unlinked_accounts = []
    for m in wom_roster:
        player = m.get('player', {})
        wom_id = str(player.get('id', ''))
        rsn = player.get('displayName') or player.get('username') or 'Unknown'
        if wom_id and wom_id not in tracked_wom_ids:
            unlinked_accounts.append({'WOM ID': wom_id, 'RSN': rsn, 'Rank': m.get('role', 'Unknown')})
                
    if not unlinked_accounts:
        print(f"{GREEN}✅ All accounts in the WOM roster are already linked to Discord members!{RESET}")
        return
        
    print(f"Found {len(unlinked_accounts)} unlinked WOM accounts.")
    print("-" * 50)
    
    linked_count = 0
    quit_linker = False

    for idx, acc in enumerate(unlinked_accounts, 1):
        wom_id = acc['WOM ID']
        rsn = acc['RSN']
        ig_rank = acc['Rank']
        
        print(f"\n{CYAN}👤 Unlinked Account: {GREEN}{rsn}{CYAN} {DARK_GRAY}[WOM ID: {wom_id}] (In-Game Rank: {ig_rank}){RESET} | Progress: {idx}/{len(unlinked_accounts)}")
        
        # Fuzzy match scoring based on Discord Name and User Notes
        scored_members = []
        for m in members_data:
            target_rsn = rsn.lower()
            d_name_lower = m['discord_name'].lower()
            notes_lower = m['user_notes'].lower()
            linked_rsns_lower = [r.strip().lower() for r in m['rsns'].split(',') if r.strip()]
            
            score_a = difflib.SequenceMatcher(None, target_rsn, d_name_lower).ratio()
            score_b = difflib.SequenceMatcher(None, target_rsn, notes_lower).ratio() if notes_lower else 0
            score_c = max([difflib.SequenceMatcher(None, target_rsn, r).ratio() for r in linked_rsns_lower] + [0])
            
            score = max(score_a, score_b, score_c)
            
            if target_rsn in d_name_lower or any(target_rsn in r for r in linked_rsns_lower):
                score = 1.0
            elif target_rsn in notes_lower:
                score = max(score, 0.85)
                
            scored_members.append((score, m))
            
        scored_members.sort(key=lambda x: x[0], reverse=True)
        top_matches = scored_members[:5]
        
        print("  Top Matches:")
        for i, (score, m) in enumerate(top_matches, 1):
            _print_member_match(i, m, role_map, managed_roles, score)
            
        print("\n  0: ⏭️  Skip")
        print("  s: 🔍 Search manually by Discord Name")
        
        while True:
            choice = input(f"Select [0-5, s] or 'q' to quit: ").strip().lower()
            
            if choice == 'q':
                print(f"{YELLOW}Ending linking session...{RESET}")
                quit_linker = True
                break
            elif choice == '0':
                print(f"{YELLOW}Skipped.{RESET}")
                break
            elif choice == 's':
                search_term = input("Enter Discord Name to search: ").strip().lower()
                # Allow searching by Discord Name, Notes, or Linked RSNs
                results = [m for m in members_data if search_term in m['discord_name'].lower() or search_term in m['user_notes'].lower() or search_term in m['rsns'].lower()]
                if not results:
                    print(f"{RED}No members found matching '{search_term}'.{RESET}")
                else:
                    print("Search Results:")
                    for r_idx, r_m in enumerate(results[:5], 1):
                        _print_member_match(r_idx, r_m, role_map, managed_roles)
                    r_choice = input(f"Select a result [1-{min(5, len(results))}] or press Enter to cancel: ").strip()
                    if r_choice.isdigit() and 1 <= int(r_choice) <= min(5, len(results)):
                        selected_member = results[int(r_choice) - 1]
                        _link_account(db, selected_member, wom_id, rsn)
                        _update_local(members_data, selected_member['discord_id'], wom_id)
                        linked_count += 1
                        break
            elif choice.isdigit() and 1 <= int(choice) <= 5:
                selected_member = top_matches[int(choice) - 1][1]
                _link_account(db, selected_member, wom_id, rsn)
                _update_local(members_data, selected_member['discord_id'], wom_id)
                linked_count += 1
                break
            else:
                print("Invalid input.")
                
        if quit_linker:
            break
            
    if linked_count > 0:
        print(f"\n{YELLOW}You linked {linked_count} accounts during this session.{RESET}")
        print(f"Would you like to run a silent database sync to fetch their game ranks and update the sheet? {DARK_GRAY}(Recommended before running Rank Matcher){RESET}")
        while True:
            sync_after = input("Select [y/n]: ").strip().lower()
            if sync_after in ['y', 'n']:
                break
                
        if sync_after == 'y':
            print(f"\n{CYAN}Running silent sync... Please wait.{RESET}")
            orchestrator.run_orchestrator(force_wom=False, skip_webhook=True, sync_only=True)
            print(f"{GREEN}Sync complete!{RESET}\n")

def _print_member_match(index, m, role_map, managed_roles, score=None):
    """Helper to print a cleanly formatted multi-line block for a member."""
    if score is not None:
        pct = int(score * 100)
        if pct >= 80: color = GREEN
        elif pct >= 50: color = YELLOW
        else: color = RED
        prefix = f"{color}[{pct:3d}%]{RESET} "
    else:
        prefix = ""
        
    raw_roles = [r.strip() for r in m['discord_ranks'].split(',') if r.strip()]
    relevant_roles = [r for r in raw_roles if r in managed_roles]
    role_names = [role_map.get(r, f"Unknown ({r})") for r in relevant_roles]
    roles_disp = ", ".join(role_names) if role_names else "None"
    
    clan_rank_disp = m['clan_rank'] if m['clan_rank'] else "None"
    
    rsns_list = [r.strip() for r in m['rsns'].split(',') if r.strip()]
    clans_list = [c.strip() for c in m['account_clans'].split(',') if c.strip()]
    ranks_list = [rk.strip() for rk in m['game_ranks'].split(',') if rk.strip()]
    wids_list = [w.strip() for w in m['wom_ids_raw'].split(',') if w.strip()]
    
    linked_displays = []
    for idx_r, r_name in enumerate(rsns_list):
        c_name = clans_list[idx_r] if idx_r < len(clans_list) else "Unknown"
        rk_name = ranks_list[idx_r] if idx_r < len(ranks_list) else "Unknown"
        wid_name = wids_list[idx_r] if idx_r < len(wids_list) else "Unknown"
        linked_displays.append(f"{r_name} {DARK_GRAY}[ID: {wid_name}][{c_name}:{rk_name}]{RESET}")
        
    if len(linked_displays) > 2:
        linked_str = ", ".join(linked_displays[:2]) + f" {DARK_GRAY}... (+{len(linked_displays) - 2} more){RESET}"
    else:
        linked_str = ", ".join(linked_displays) if linked_displays else "None"
        
    print(f"    {index}: {prefix}{YELLOW}{m['discord_name']}{RESET} {DARK_GRAY}[ID: {m['discord_id']}]{RESET}")
    if m['user_notes']:
        print(f"       {DARK_GRAY}↳ Notes: {RESET}{m['user_notes']}")
    print(f"       {DARK_GRAY}↳ Rank: {RESET}{clan_rank_disp} {DARK_GRAY}| Discord Ranks: {RESET}{roles_disp}")
    print(f"       {DARK_GRAY}↳ Linked RSNs: {RESET}{linked_str}\n")

def _update_local(members_data, d_id, wom_id):
    """Updates the in-memory array so newly linked accounts are omitted on subsequent loops."""
    for m in members_data:
        if m['discord_id'] == d_id:
            wids = [w.strip() for w in m['wom_ids_raw'].split(',') if w.strip()]
            wids.append(str(wom_id).strip())
            m['wom_ids_raw'] = ", ".join(wids)

def _link_account(db, member, wom_id, rsn):
    """Uses Smart Just-In-Time (JIT) Indexing to safely link the WOM ID."""
    print(f"Linking '{rsn}' to {member['discord_name']}...")
        
    wids = [w.strip() for w in member['wom_ids_raw'].split(',') if w.strip()]
    wids.append(str(wom_id).strip())
    new_wom_ids = ", ".join(wids)
    
    db.batch_update_by_id('Database', 'Discord ID', [{'id': member['discord_id'], 'col_name': 'WOM IDs', 'value': new_wom_ids}])
    db.append_audit_logs([f"Manual Update - {member['discord_name']} ({member['discord_id']}): Linked WOM account '{rsn}' (ID: {wom_id})."])
    print(f"{GREEN}✅ Successfully linked!{RESET}")

if __name__ == '__main__':
    main()