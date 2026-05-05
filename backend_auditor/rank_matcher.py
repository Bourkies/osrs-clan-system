import os
import re
import time
from dotenv import load_dotenv
from db_manager import DBManager
import run_auditor as orchestrator

# --- ANSI COLORS ---
RESET = "\033[0m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
DARK_GRAY = "\033[90m"
MAGENTA = "\033[95m"
LIGHT_BLUE = "\033[94m"

# --- CONFIGURATION ---
load_dotenv()

SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

def main():
    print("Initializing Google Sheets connection...")
    db = DBManager(SPREADSHEET_ID)

    # 1. Load Reference Data for matching logic
    print("Loading Reference Data mapping...")
    ref_records = db.get_all_records('Reference_Data')
    
    valid_ranks = []
    discord_req_to_rank = {}
    ig_main_to_rank = {}
    rank_to_exc_roles = {}
    managed_roles = set()
    rank_rules = {}
    
    for row in ref_records:
        clan_rank = str(row.get('Clan Rank', '')).strip()
        if not clan_rank:
            continue
        valid_ranks.append(clan_rank)
        
        req_roles = [r.strip() for r in str(row.get('Required Discord Roles', '')).split(',') if r.strip()]
        all_roles = [r.strip() for r in str(row.get('Allowed Discord Roles', '')).split(',') if r.strip()]
        exc_roles = [r.strip() for r in str(row.get('Excluded Discord Roles', '')).split(',') if r.strip()]
        main_rank = str(row.get('Main In-Game Rank', '')).strip()
        
        rank_rules[clan_rank] = {
            'req_roles': req_roles,
            'main_rank': main_rank
        }
        
        for dr in req_roles:
            discord_req_to_rank.setdefault(dr, []).append(clan_rank)
            
        if main_rank:
            ig_main_to_rank.setdefault(main_rank.lower(), []).append(clan_rank)
            
        rank_to_exc_roles[clan_rank] = exc_roles
        managed_roles.update(req_roles + all_roles + exc_roles)
            
    # 1.5 Load Discord Roles for human-readable output
    print("Loading Discord Roles mapping...")
    roles_records = db.get_all_records('Discord_Roles')
    role_id_to_name = {str(row.get('Role ID', '')).replace("'", ""): str(row.get('Role Name', '')) for row in roles_records}

    # 1.8 Load System Config for Target Clan Name
    print("Loading System Config...")
    config_records = db.get_all_records('System_Config')
    system_config = {str(row.get('Setting Name', '')).strip(): str(row.get('Value', '')).strip() for row in config_records}
    target_clan_name = system_config.get('Target Clan Name', 'Unknown Clan')

    # 2. Load Database
    print("Loading current Database...")
    db_records = db.get_all_records('Database')

    # 3. Choose Tool Mode
    print("\nSelect filter mode:")
    print("  1: All unranked members")
    print("  2: Only unranked members with known RSNs / WOM IDs")
    print("  3: Only actionable unranked members (Have clan Discord roles OR active in-game)")
    print("  4: Sync Promoted Members (Updates Sheet Rank for members already promoted 1-3 tiers higher in Discord/Game)")
    print("  5: Verify from Text (Paste Discord announcement blocks to verify/apply a specific rank)")
    
    while True:
        mode_choice = input("Select [1-5]: ").strip()
        if mode_choice in ['1', '2', '3', '4', '5']:
            break
        print("Invalid choice. Please enter 1, 2, 3, 4, or 5.")
        
    target_accounts = []
    
    if mode_choice in ['1', '2', '3']:
        for row in db_records:
            if not str(row.get('Clan Rank', '')).strip():
                target_accounts.append({'data': row})
                
        print(f"Found {len(target_accounts)} members missing a Clan Rank.")
        
        if mode_choice == '2':
            print("\nOnly show members currently active in the in-game clan?")
            print(f"  {DARK_GRAY}(Filters out old members who have left the clan){RESET}")
            while True:
                in_clan_choice = input("Select [y/n]: ").strip().lower()
                if in_clan_choice in ['y', 'n']:
                    break
                print("Invalid choice. Please enter 'y' or 'n'.")
                
            filtered = []
            for acc in target_accounts:
                has_wom = str(acc['data'].get('WOM IDs', '')).strip() or str(acc['data'].get('RSNs', '')).strip()
                if not has_wom:
                    continue
                    
                if in_clan_choice == 'y':
                    clans = [c.strip().lower() for c in str(acc['data'].get('Account Clan', '')).split(',')]
                    if target_clan_name.lower() not in clans:
                        continue
                        
                filtered.append(acc)
                
            target_accounts = filtered
            print(f"Filtered down to {len(target_accounts)} members.")
        elif mode_choice == '3':
            filtered = []
            for acc in target_accounts:
                # Check for managed discord roles
                d_ranks_raw = [r.strip() for r in str(acc['data'].get('Discord Ranks', '')).replace("'", "").split(',') if r.strip()]
                has_managed_role = any(dr in managed_roles for dr in d_ranks_raw)
                
                # Check for active clan membership
                clans = [c.strip().lower() for c in str(acc['data'].get('Account Clan', '')).split(',')]
                in_clan = target_clan_name.lower() in clans
                
                if has_managed_role or in_clan:
                    filtered.append(acc)
                    
            target_accounts = filtered
            print(f"Filtered down to {len(target_accounts)} actionable members.")
            
    elif mode_choice == '4':
        for row in db_records:
            if str(row.get('Clan Rank', '')).strip():
                target_accounts.append({'data': row})
        print(f"Analyzing {len(target_accounts)} ranked members for pending sheet updates...")
        
    elif mode_choice == '5':
        total_applied_mode_5 = 0
        while True:
            print(f"\n{CYAN}--- Mode 5: Verify Promotions from Text ---{RESET}")
            print("Paste your Discord announcement block below.")
            print("When finished, press Enter on a new empty line, type 'DONE', and press Enter. (Or type 'EXIT' to quit)")
            pasted_lines = []
            exit_requested = False
            while True:
                try:
                    line = input()
                    if line.strip().upper() == 'EXIT':
                        exit_requested = True
                        break
                    if line.strip().upper() == 'DONE':
                        break
                    pasted_lines.append(line)
                except EOFError:
                    break
                    
            if exit_requested:
                break
                
            full_text = "\n".join(pasted_lines)
            extracted_ids = list(set(re.findall(r'<@!?(\d+)>', full_text)))
            
            if not extracted_ids:
                print(f"{RED}No Discord IDs found in the pasted text.{RESET}")
            else:
                block_accounts = []
                missing_ids = []
                
                for eid in extracted_ids:
                    found = False
                    for row in db_records:
                        if str(row.get('Discord ID', '')).replace("'", "").strip() == eid:
                            block_accounts.append({'data': row})
                            found = True
                            break
                    if not found:
                        missing_ids.append(eid)
                        
                print(f"\nFound {len(block_accounts)} valid members from the pasted text.")
                if missing_ids:
                    print(f"{YELLOW}Warning: {len(missing_ids)} IDs were not found in the Database!{RESET}")
                    
                if block_accounts:
                    print(f"\n{CYAN}--- Members in this block ---{RESET}")
                    current_sheet_ranks = set()
                    color_map = {}
                    palette = [MAGENTA, LIGHT_BLUE, CYAN, GREEN, YELLOW]
                    
                    def get_c(val):
                        if val in ["None", "Unknown", ""]: return DARK_GRAY
                        if val not in color_map:
                            color_map[val] = palette[len(color_map) % len(palette)]
                        return color_map[val]
                        
                    for acc in block_accounts:
                        row = acc['data']
                        d_name = str(row.get('Discord Name', '')).strip() or "Unknown"
                        d_id = str(row.get('Discord ID', '')).replace("'", "").strip() or "Unknown"
                        rsns = str(row.get('RSNs', '')).strip() or "None"
                        c_rank = str(row.get('Clan Rank', '')).strip() or "None"
                        g_ranks = str(row.get('Game Ranks', '')).strip() or "None"
                        
                        d_ranks_raw = [r.strip() for r in str(row.get('Discord Ranks', '')).replace("'", "").split(',') if r.strip()]
                        d_ranks_names = [role_id_to_name.get(r, r) for r in d_ranks_raw if r in managed_roles]
                        d_ranks_str = ", ".join(d_ranks_names) if d_ranks_names else "None"
                        
                        if c_rank != "None":
                            current_sheet_ranks.add(c_rank)
                            
                        c_rank_disp = f"{get_c(c_rank)}{c_rank}{RESET}"
                        d_ranks_disp = f"{get_c(d_ranks_str)}{d_ranks_str}{RESET}"
                        g_ranks_disp = f"{get_c(g_ranks)}{g_ranks}{RESET}"
                            
                        print(f"👤 {GREEN}{d_name}{RESET} {DARK_GRAY}[ID: {d_id}]{RESET} | RSNs: {rsns}")
                        print(f"   ├─ Sheet Rank: {c_rank_disp}")
                        print(f"   ├─ Discord: {d_ranks_disp}")
                        print(f"   └─ Game: {g_ranks_disp}")
                        
                    if len(current_sheet_ranks) > 1:
                        print(f"\n{YELLOW}⚠️ WARNING: The users in this block currently have different Sheet ranks: {', '.join(current_sheet_ranks)}{RESET}")
                    
                    cancel_block = False
                    while True:
                        print("\nWhat rank should this block be promoted to?")
                        for i, r in enumerate(valid_ranks, 1):
                            print(f"  {i}: {r}")
                        print("  0: ❌ Cancel / Retry (Paste a new block)")
                            
                        while True:
                            choice = input(f"Select a rank [1-{len(valid_ranks)}] or '0' to cancel: ").strip()
                            if choice == '0':
                                cancel_block = True
                                break
                            if choice.isdigit() and 1 <= int(choice) <= len(valid_ranks):
                                target_rank = valid_ranks[int(choice)-1]
                                break
                            print("Invalid input.")
                            
                        if cancel_block:
                            break
                            
                        confirm = input(f"\nYou selected {YELLOW}'{target_rank}'{RESET}. Is this correct? [y/n]: ").strip().lower()
                        if confirm == 'y':
                            break
                        print(f"{RED}Selection cancelled. Let's try again.{RESET}")
                        
                    if cancel_block:
                        continue
                        
                    target_rule = rank_rules[target_rank]
                    
                    perfect_sync = []
                    ready_for_sheet = []
                    needs_manual_fix = []
                    
                    for acc in block_accounts:
                        row = acc['data']
                        d_name = str(row.get('Discord Name', '')).strip()
                        d_id = str(row.get('Discord ID', '')).replace("'", "").strip()
                        current_rank = str(row.get('Clan Rank', '')).strip()
                        
                        d_ranks_raw = [r.strip() for r in str(row.get('Discord Ranks', '')).replace("'", "").split(',') if r.strip()]
                        game_ranks_raw = [r.strip() for r in str(row.get('Game Ranks', '')).split(',') if r.strip() and r.strip() != 'Unknown']
                        
                        missing_discord = [r for r in target_rule['req_roles'] if r not in d_ranks_raw]
                        has_game = target_rule['main_rank'].lower() in [r.lower() for r in game_ranks_raw] if target_rule['main_rank'] else True
                        
                        sheet_match = (current_rank == target_rank)
                        discord_match = (len(missing_discord) == 0)
                        game_match = has_game
                        
                        if sheet_match and discord_match and game_match:
                            perfect_sync.append(d_name)
                        elif discord_match and game_match and not sheet_match:
                            ready_for_sheet.append((d_name, d_id, current_rank))
                        else:
                            issues = []
                            if not sheet_match: issues.append(f"Sheet='{current_rank}'")
                            if not discord_match:
                                missing_names = [role_id_to_name.get(r, r) for r in missing_discord]
                                issues.append(f"Missing Discord Role(s): {', '.join(missing_names)}")
                            if not game_match: 
                                issues.append(f"Missing Game Rank '{target_rule['main_rank']}'")
                            needs_manual_fix.append((d_name, d_id, current_rank, issues))
                            
                    print(f"\n{CYAN}--- Verification Report for '{target_rank}' ---{RESET}")
                    print(f"{GREEN}✅ Perfectly Synced:{RESET} {len(perfect_sync)}")
                    
                    print(f"\n{YELLOW}📝 Ready for Sheet Update (Only Sheet is missing/wrong):{RESET} {len(ready_for_sheet)}")
                    if ready_for_sheet:
                        for name, _, cr in ready_for_sheet[:5]:
                            print(f"  - {name} (Current: {cr})")
                        if len(ready_for_sheet) > 5:
                            print(f"  ...and {len(ready_for_sheet) - 5} more.")
                            
                    print(f"\n{RED}❌ Action Required (Discord/Game mismatch):{RESET} {len(needs_manual_fix)}")
                    if needs_manual_fix:
                        for name, did, cr, issues in needs_manual_fix:
                            print(f"  - {name}: {', '.join(issues)}")
                            
                    if ready_for_sheet:
                        print(f"\nWould you like to automatically update the Sheet Rank to '{target_rank}' for the {len(ready_for_sheet)} ready members?")
                        while True:
                            apply_choice = input("Select [y/n]: ").strip().lower()
                            if apply_choice in ['y', 'n']:
                                break
                                
                        if apply_choice == 'y':
                            batch_updates = []
                            audit_rows = []
                            timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                            
                            for name, did, cr in ready_for_sheet:
                                batch_updates.append({'id': did, 'col_name': 'Clan Rank', 'value': target_rank})
                                if cr:
                                    msg = f"Manual Update - {name} ({did}): Updated Clan Rank from '{cr}' to '{target_rank}'."
                                else:
                                    msg = f"Manual Update - {name} ({did}): Assigned Clan Rank '{target_rank}'."
                                audit_rows.append([timestamp, 'CLI Setup Tool', 'Admin', msg])
                                
                            print(f"{CYAN}Applying updates to database...{RESET}")
                            db.batch_update_by_id('Database', 'Discord ID', batch_updates)
                            db.append_audit_logs([row[3] for row in audit_rows])
                            print(f"{GREEN}✅ Successfully updated {len(ready_for_sheet)} members!{RESET}")
                            total_applied_mode_5 += len(ready_for_sheet)
                            
                    if needs_manual_fix:
                        print(f"\nWould you like to FORCE update the Sheet Rank to '{target_rank}' for the {len(needs_manual_fix)} mismatched members anyway?")
                        while True:
                            force_choice = input("Select [y/n]: ").strip().lower()
                            if force_choice in ['y', 'n']:
                                break
                                
                        if force_choice == 'y':
                            batch_updates = []
                            audit_rows = []
                            timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                            
                            for name, did, cr, issues in needs_manual_fix:
                                batch_updates.append({'id': did, 'col_name': 'Clan Rank', 'value': target_rank})
                                if cr:
                                    msg = f"Manual Update (Forced) - {name} ({did}): Updated Clan Rank from '{cr}' to '{target_rank}'."
                                else:
                                    msg = f"Manual Update (Forced) - {name} ({did}): Assigned Clan Rank '{target_rank}'."
                                audit_rows.append([timestamp, 'CLI Setup Tool', 'Admin', msg])
                                
                            print(f"{CYAN}Applying forced updates to database...{RESET}")
                            db.batch_update_by_id('Database', 'Discord ID', batch_updates)
                            db.append_audit_logs([row[3] for row in audit_rows])
                            print(f"{GREEN}✅ Successfully force-updated {len(needs_manual_fix)} members!{RESET}")
                            total_applied_mode_5 += len(needs_manual_fix)
            
            print("\nWould you like to process another block?")
            if input("Select [y/n]: ").strip().lower() != 'y':
                break
                
        if total_applied_mode_5 > 0:
            print(f"\nWould you like to run a silent audit to update system flags? {DARK_GRAY}(This will clear 'Rank Mismatch' flags){RESET}")
            while True:
                sync_after = input("Select [y/n]: ").strip().lower()
                if sync_after in ['y', 'n']:
                    break
                    
            if sync_after == 'y':
                print(f"\n{CYAN}Running silent audit... Please wait.{RESET}")
                orchestrator.run_orchestrator(force_wom=False, skip_webhook=True, sync_only=False)
                print(f"{GREEN}Audit complete!{RESET}\n")
        return

    auto_apply = False
    if mode_choice in ['1', '2', '3']:
        print("\nEnable Auto-Apply for perfect matches?")
        print(f"  {DARK_GRAY}(Auto-applies if their Discord and Game ranks all point to exactly ONE rank){RESET}")
        while True:
            auto_apply_choice = input("Select [y/n]: ").strip().lower()
            if auto_apply_choice in ['y', 'n']:
                auto_apply = (auto_apply_choice == 'y')
                break
            print("Invalid choice. Please enter 'y' or 'n'.")

    skipped_count = 0
    applied_count = 0
    
    # 4. Pre-process logic and build suggestions
    processed_accounts = []
    for account in target_accounts:
        row_data = account['data']
        current_rank = str(row_data.get('Clan Rank', '')).strip()
        
        d_ranks_raw = [r.strip() for r in str(row_data.get('Discord Ranks', '')).replace("'", "").split(',') if r.strip()]
        game_ranks_raw = [r.strip() for r in str(row_data.get('Game Ranks', '')).split(',') if r.strip() and r.strip() != 'Unknown']
        
        # Analyze suggestions
        suggestions = set()
        reasons = {}
        invalid_ranks = set()
        
        for dr in d_ranks_raw:
            if dr in discord_req_to_rank:
                for cr in discord_req_to_rank[dr]:
                    suggestions.add(cr)
                    role_name = role_id_to_name.get(dr, f"Role ID: {dr}")
                    reasons[cr] = reasons.get(cr, []) + [f"Discord Req: '{role_name}'"]
                    
            for cr in valid_ranks:
                if dr in rank_to_exc_roles.get(cr, []):
                    invalid_ranks.add(cr)
                
        for ir in game_ranks_raw:
            if ir.lower() in ig_main_to_rank:
                for cr in ig_main_to_rank[ir.lower()]:
                    suggestions.add(cr)
                    reasons[cr] = reasons.get(cr, []) + [f"Main In-Game: '{ir}'"]
                    
        suggestions = suggestions - invalid_ranks

        # Filter out partial matches if a perfect match (both Discord and Game) exists
        perfect_matches = {r for r in suggestions if any("Discord Req" in res for res in reasons.get(r, [])) and any("Main In-Game" in res for res in reasons.get(r, []))}
        if perfect_matches:
            suggestions = perfect_matches

        account['suggestions'] = suggestions
        account['reasons'] = reasons
        account['d_ranks_raw'] = d_ranks_raw
        account['game_ranks_raw'] = game_ranks_raw
        
        if mode_choice == '4':
            if suggestions and current_rank in valid_ranks:
                # Prioritize Discord roles to prevent overlapping in-game ranks from causing false positives
                discord_suggestions = {r for r in suggestions if any("Discord Req" in reason for reason in reasons.get(r, []))}
                eval_suggestions = discord_suggestions if discord_suggestions else suggestions
                
                best_suggested_idx = min(valid_ranks.index(r) for r in eval_suggestions if r in valid_ranks)
                current_idx = valid_ranks.index(current_rank)
                tier_diff = current_idx - best_suggested_idx
                if 1 <= tier_diff <= 3:
                    processed_accounts.append(account)
        else:
            processed_accounts.append(account)
            
    if mode_choice == '4':
        print(f"Found {len(processed_accounts)} members needing a 1-3 tier Sheet Rank update.")

    manual_accounts = []
    if auto_apply:
        auto_accounts = []
        for acc in processed_accounts:
            if len(acc['suggestions']) == 1:
                auto_accounts.append(acc)
            else:
                manual_accounts.append(acc)
                
        if auto_accounts:
            print(f"\n{CYAN}Phase 1: Auto-applying {len(auto_accounts)} perfect matches...{RESET}")
            batch_updates = []
            audit_rows = []
            timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            
            for acc in auto_accounts:
                selected_rank = list(acc['suggestions'])[0]
                d_name = str(acc['data'].get('Discord Name', '')).strip()
                d_id = str(acc['data'].get('Discord ID', '')).replace("'", "").strip()
                
                batch_updates.append({'id': d_id, 'col_name': 'Clan Rank', 'value': selected_rank})
                
                audit_log_msg = f"Auto Update - {d_name} ({d_id}): Assigned Clan Rank '{selected_rank}'."
                audit_rows.append([timestamp, 'CLI Setup Tool', 'Admin', audit_log_msg])
                
            db.batch_update_by_id('Database', 'Discord ID', batch_updates)
            db.append_audit_logs([msg[3] for msg in audit_rows])
            print(f"{GREEN}✅ Successfully auto-applied {len(auto_accounts)} members!{RESET}")
            applied_count += len(auto_accounts)
    else:
        manual_accounts = processed_accounts

    print(f"\n{CYAN}Phase 2: Manual Review ({len(manual_accounts)} members require review){RESET}")
    print("-" * 50)

    # 5. Interactive Matching Loop
    total_manual = len(manual_accounts)
    quit_matcher = False
    for idx, account in enumerate(manual_accounts, 1):
        row_data = account['data']
        
        d_name = str(row_data.get('Discord Name', '')).strip()
        d_id = str(row_data.get('Discord ID', '')).strip()
        current_rank = str(row_data.get('Clan Rank', '')).strip()
        rsns = str(row_data.get('RSNs', '')).strip() or "None"
        wom_ids = str(row_data.get('WOM IDs', '')).strip() or "None"
        account_clans = str(row_data.get('Account Clan', '')).strip() or "None"
        
        suggestions = account['suggestions']
        reasons = account['reasons']
        game_ranks_raw = account['game_ranks_raw']
        d_ranks_raw = account['d_ranks_raw']

        # Print UI
        print(f"\n{CYAN}👤 Member: {GREEN}{d_name}{CYAN} {DARK_GRAY}[Discord ID: {d_id}] [WOM IDs: {wom_ids}]{RESET} | Progress: {idx}/{total_manual} ({skipped_count} skipped, {applied_count} applied)")
        if current_rank:
            print(f"  {CYAN}Current Rank:{RESET} {YELLOW}{current_rank}{RESET}")
        print(f"  {CYAN}Known RSNs:{RESET} {rsns}")
        print(f"  {CYAN}Account Clans:{RESET} {account_clans}")
        if game_ranks_raw:
            print(f"  {CYAN}Game Ranks:{RESET} {', '.join(game_ranks_raw)}")
        relevant_d_ranks = [dr for dr in d_ranks_raw if dr in managed_roles]
        readable_roles = [role_id_to_name.get(dr, f"Unknown ({dr})") for dr in relevant_d_ranks]
        if readable_roles:
            print(f"  {CYAN}Discord Roles:{RESET} {', '.join(readable_roles)}")
        
        print("\n  0: ⏭️  Skip (Do not assign rank)")
        choice_map = {}
        current_choice = 1
        
        # 1. Print suggestions first
        for rank in valid_ranks:
            if rank in suggestions:
                reason_str = f" {DARK_GRAY}(Matches: {', '.join(set(reasons[rank]))}){RESET}"
                print(f"  {current_choice}: {YELLOW}⭐ {rank}{RESET}{reason_str}")
                choice_map[current_choice] = rank
                current_choice += 1
                
        # 2. Print remaining ranks
        for rank in valid_ranks:
            if rank not in suggestions:
                print(f"  {current_choice}:    {rank}")
                choice_map[current_choice] = rank
                current_choice += 1
                
        while True:
            choice = input(f"\nSelect a rank [0-{len(valid_ranks)}] or 'q' to quit: ").strip().lower()
            
            if choice == 'q':
                quit_matcher = True
                break
            if choice.isdigit() and 0 <= int(choice) <= len(valid_ranks):
                choice = int(choice)
                break
            print("Invalid input. Please enter a number from the list.")
            
        if choice == 0:
            print(f"{YELLOW}Skipped.{RESET}")
            skipped_count += 1
            continue

        if quit_matcher:
            break
            
        # 6. Process the Selection
        selected_rank = choice_map[choice]
        
        # Update Database securely using JIT indexing
        timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        if current_rank:
            audit_log_msg = f"Manual Update - {d_name} ({d_id}): Updated Clan Rank from '{current_rank}' to '{selected_rank}'."
        else:
            audit_log_msg = f"Manual Update - {d_name} ({d_id}): Assigned Clan Rank '{selected_rank}'."
        
        db.batch_update_by_id('Database', 'Discord ID', [{'id': d_id, 'col_name': 'Clan Rank', 'value': selected_rank}])
        db.append_audit_logs([audit_log_msg])
        
        print(f"{GREEN}✅ Assigned rank '{selected_rank}' to {d_name}!{RESET}")
        applied_count += 1

    print(f"\n{YELLOW}Final Progress: {skipped_count} skipped, {applied_count} applied.{RESET}")

    if applied_count > 0:
        print(f"\n{YELLOW}You assigned {applied_count} ranks during this session.{RESET}")
        print(f"Would you like to run a silent audit to update system flags? {DARK_GRAY}(This will clear 'Rank Mismatch' flags for members who are now correct){RESET}")
        while True:
            sync_after = input("Select [y/n]: ").strip().lower()
            if sync_after in ['y', 'n']:
                break
                
        if sync_after == 'y':
            print(f"\n{CYAN}Running silent audit... Please wait.{RESET}")
            # We set sync_only=False to ensure the audit logic runs to update flags
            orchestrator.run_orchestrator(force_wom=False, skip_webhook=True, sync_only=False)
            print(f"{GREEN}Audit complete!{RESET}\n")


if __name__ == '__main__':
    main()