import os
import sqlite3
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from loguru import logger
from file_utils import safe_write_report

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHARED_DATA_DIR = PROJECT_ROOT / "shared_data"

# --- CONFIGURATION & TUNING ---

# Minimum combined chats/broadcasts in a single month to validate a rank.
# Prevents someone accidentally holding 'Diamond' for 1 message from breaking the system.
MIN_ACTIVITY_TO_VALIDATE_RANK = 3

# Default diminishing returns for chats (Limit, Points per chat)
DEFAULT_CHAT_TIERS = [
    (50, 1.0),           # First 50 chats: 1.0 points each
    (150, 0.5),          # Next 150 chats: 0.5 points each
    (float('inf'), 0.1)  # Anything beyond 200: 0.1 points each
]

# Default diminishing returns for broadcasts (Limit, Points per broadcast)
DEFAULT_BROADCAST_TIERS = [
    (10, 0.5),           # First 10 broadcasts: 0.5 points each
    (float('inf'), 0.1)  # Anything beyond 10: 0.1 points each
]

# Rank Hierarchy Classifications
PROGRESSION_RANKS = ["Sapphire", "Emerald", "Ruby", "Diamond", "Dragonstone", "Onyx", "Zenyte"]
SPECIAL_RANKS = {"Guest", "Helper"}
STAFF_RANKS = {"Warden", "Proselyte", "Major", "Master", "Deputy_owner", "Owner", "Elite", "Sniper", "Destroyer", "Administrator"}

# Promotion requirements and scoring tuning to reach the target rank from the previous rank.
# This structure allows you to override the upkeep cost, chat tiers, and broadcast tiers for specific rank transitions.
PROMOTION_THRESHOLDS = {
    "Emerald": {
        "points": 60, "min_months": 1, "upkeep": 5.0,
        "chat_tiers": DEFAULT_CHAT_TIERS, "broadcast_tiers": DEFAULT_BROADCAST_TIERS
    },
    "Ruby": {
        "points": 350, "min_months": 2, "upkeep": 15.0,
        "chat_tiers": DEFAULT_CHAT_TIERS, "broadcast_tiers": DEFAULT_BROADCAST_TIERS
    },
    "Diamond": {
        "points": 450, "min_months": 4, "upkeep": 10.0,
        "chat_tiers": DEFAULT_CHAT_TIERS, "broadcast_tiers": DEFAULT_BROADCAST_TIERS
    },
    "Dragonstone": {
        "points": 1000, "min_months": 8, "upkeep": 10.0, 
        "chat_tiers": DEFAULT_CHAT_TIERS, "broadcast_tiers": DEFAULT_BROADCAST_TIERS
    },
    "Onyx": {
        "points": 2000, "min_months": 16, "upkeep": 10.0,
        "chat_tiers": DEFAULT_CHAT_TIERS, "broadcast_tiers": DEFAULT_BROADCAST_TIERS
    },
    "Zenyte": {
        "points": 3000, "min_months": 24, "upkeep": 5.0,
        "chat_tiers": DEFAULT_CHAT_TIERS, "broadcast_tiers": DEFAULT_BROADCAST_TIERS
    }
}

def calculate_points(chats, broadcasts, chat_tiers, broadcast_tiers):
    points = 0.0
    
    # Calculate Chat Points
    c_rem = chats
    for limit, weight in chat_tiers:
        if c_rem <= 0: break
        take = min(c_rem, limit)
        points += take * weight
        c_rem -= take
        
    # Calculate Broadcast Points
    b_rem = broadcasts
    for limit, weight in broadcast_tiers:
        if b_rem <= 0: break
        take = min(b_rem, limit)
        points += take * weight
        b_rem -= take
        
    return points

def get_highest_rank(ranks_str):
    if not ranks_str or ranks_str.lower() == 'none':
        return None
        
    ranks = [r.strip() for r in ranks_str.split(",") if r.strip()]
    if not ranks:
        return None
    
    # 1. Staff/Special bypasses automated progression
    for r in ranks:
        if r in STAFF_RANKS:
            return "Staff"
            
    # 2. Find highest progression rank
    highest_idx = -1
    highest_rank = None
    for r in ranks:
        if r in PROGRESSION_RANKS:
            idx = PROGRESSION_RANKS.index(r)
            if idx > highest_idx:
                highest_idx = idx
                highest_rank = r
                
    if highest_rank:
        return highest_rank
        
    # 3. Check default/guest ranks
    for r in ranks:
        if r in SPECIAL_RANKS:
            return "Special"
            
    # 4. Wildcard / Event Rank check (If they had ranks but none matched above)
    return "Wildcard"

def generate_suggestions(roster_data=None, rank_rules=None):
    logger.info("Starting Clan Rank-Up Suggester...")
    input_db = SHARED_DATA_DIR / "databases" / "activity.db"
    output_md = SHARED_DATA_DIR / "reports" / "rank_up_suggestions.md"
    
    if not input_db.exists():
        logger.error(f"Input Database not found at {input_db}. Please run 'activity_reporter.py' first.")
        return
        
    user_data = defaultdict(list)
    all_months = set()
    
    user_status_map = {}
    user_roster_map = {}
    
    if roster_data:
        for user in roster_data:
            did = str(user.get('Discord ID', '')).replace("'", "").strip()
            user_roster_map[did] = user
            user_status_map[did] = {
                'system_flags': [f.strip() for f in str(user.get('System Flags', '')).split(',') if f.strip()],
                'admin_flags': [f.strip() for f in str(user.get('Admin Flags', '')).split(',') if f.strip()]
            }
    else:
        roster_json = SHARED_DATA_DIR / "exports" / "roster_export.json"
        if roster_json.exists():
            try:
                with open(roster_json, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)
                    for user in r_data.get('members', []):
                        did = str(user.get('discord_id', '')).replace("'", "").strip()
                        user_status_map[did] = {
                            'system_flags': user.get('system_flags', []),
                            'admin_flags': user.get('admin_flags', [])
                        }
            except Exception as e:
                logger.warning(f"Could not read roster_export.json: {e}")

    def get_rank_level(rank_str):
        if rank_str in STAFF_RANKS or rank_str in SPECIAL_RANKS: return 999
        if rank_str in PROGRESSION_RANKS: return PROGRESSION_RANKS.index(rank_str)
        return -1
        
    discord_role_to_level = {}
    ig_rank_to_level = {}
    sheet_rank_to_base = {}
    
    if rank_rules:
        for rule in rank_rules:
            r_name = str(rule.get('Clan Rank', '')).strip()
            main_ig = str(rule.get('Main In-Game Rank', '')).strip()
            base_rank = main_ig.title()
            
            # Map complex sheet rank names (e.g. "Ruby (Red Square) Event Planner") back to the base "Ruby"
            if base_rank in PROGRESSION_RANKS:
                sheet_rank_to_base[r_name] = base_rank
                
            lvl = get_rank_level(base_rank)
            if lvl == -1:
                lvl = get_rank_level(r_name)
                
            if lvl >= 0:
                roles = [r.strip().replace("'", "") for r in str(rule.get('Required Discord Roles', '')).split(',') if r.strip()]
                for role in roles:
                    discord_role_to_level[role] = max(discord_role_to_level.get(role, -1), lvl)
                    
                if main_ig:
                    ig_rank_to_level[main_ig.lower()] = max(ig_rank_to_level.get(main_ig.lower(), -1), lvl)
                alt_ranks = [r.strip().lower() for r in str(rule.get('Allowed Alt Ranks', '')).split(',') if r.strip()]
                for ar in alt_ranks:
                    ig_rank_to_level[ar] = max(ig_rank_to_level.get(ar, -1), lvl)

    logger.info(f"Reading aggregated activity data from {input_db}...")
    try:
        conn = sqlite3.connect(input_db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Aggregate daily granular data into month blocks to perfectly preserve decay math
        cursor.execute("""
            SELECT Discord_ID, Discord_Name, substr(Date, 1, 7) as Month, 
                   SUM(Chats) as chats, SUM(Broadcasts) as broadcasts,
                   SUM(Total_Activity) as total,
                   GROUP_CONCAT(Seen_Ranks) as ranks
            FROM daily_activity 
            GROUP BY Discord_ID, Discord_Name, Month
        """)
        
        for row in cursor.fetchall():
            discord_id = str(row['Discord_ID'])
            
            # Filter out explicitly excluded users using the JSON roster
            if user_status_map:
                status = user_status_map.get(discord_id)
                if not status:
                    continue  # User not in the roster export at all
                
                if any(f in status['system_flags'] for f in ['Archived', 'Not in Discord', 'Banned in Clan']) or 'Banned' in status['admin_flags']:
                    continue
                
            all_months.add(row['Month'])
            
            raw_ranks = str(row['ranks'] or '').split(',')
            clean_ranks = set([r.strip() for r in raw_ranks if r.strip() and r.strip() != 'None'])
            
            user_data[discord_id].append({
                'name': row['Discord_Name'], 'month': row['Month'],
                'chats': int(row['chats']), 'broadcasts': int(row['broadcasts']),
                'total': int(row['total']), 'ranks': ",".join(clean_ranks)
            })
            
        conn.close()
    except Exception as e:
        logger.error(f"Failed to read from {input_db}: {e}")
        return
            
    db_age_months = 0
    if all_months:
        min_m = min(all_months)
        max_m = max(all_months)
        min_y, min_mo = map(int, min_m.split('-'))
        max_y, max_mo = map(int, max_m.split('-'))
        db_age_months = (max_y - min_y) * 12 + (max_mo - min_mo) + 1
            
    logger.info(f"Loaded activity history for {len(user_data)} members spanning {db_age_months} months.")
    logger.info("Evaluating activity points and applying decay...")

    suggestions = []
    early_suggestions = []
    for user_id, records in user_data.items():
        records.sort(key=lambda x: x['month'])
        user_name = records[-1]['name']
        
        # 1. Identity from Sheet: Determine True Rank from Google Sheet first
        sheet_rank = ""
        if user_id in user_roster_map:
            sheet_rank = str(user_roster_map[user_id].get('Clan Rank', '')).strip()
            
        true_rank = sheet_rank_to_base.get(sheet_rank)
        rank_source = "Sheet"
        
        # Fallback to DB history if unmapped or missing from the sheet
        if not true_rank:
            true_rank = next((get_highest_rank(rec['ranks']) for rec in reversed(records) if rec['total'] >= MIN_ACTIVITY_TO_VALIDATE_RANK and get_highest_rank(rec['ranks']) != "Wildcard"), None)
            rank_source = "DB History"
        
        if not true_rank or true_rank in ("Staff", "Special", "Zenyte") or true_rank not in PROGRESSION_RANKS:
            continue
            
        target_rank = PROGRESSION_RANKS[PROGRESSION_RANKS.index(true_rank) + 1]
        thresholds = PROMOTION_THRESHOLDS[target_rank]
        
        logger.debug(f"[{user_name}] True Rank: {true_rank} (Source: {rank_source}) | Target: {target_rank}")
        
        # --- 2/3 Consensus Check ---
        if user_id in user_roster_map:
            user = user_roster_map[user_id]
            target_lvl = PROGRESSION_RANKS.index(target_rank)
            platforms_at_or_above = 0
            
            # 1. Sheet Rank (Using mapped base rank to solve the -1 issue)
            sheet_lvl = get_rank_level(true_rank)
            if sheet_lvl >= target_lvl:
                platforms_at_or_above += 1
                
            # 2. Game Ranks
            game_ranks = [r.strip().lower() for r in str(user.get('Game Ranks', '')).split(',') if r.strip()]
            game_lvl = max([ig_rank_to_level.get(r, -1) for r in game_ranks] + [-1])
            if game_lvl >= target_lvl:
                platforms_at_or_above += 1
                
            # 3. Discord Ranks
            discord_roles = [r.strip().replace("'", "") for r in str(user.get('Discord Ranks', '')).split(',') if r.strip()]
            discord_lvl = max([discord_role_to_level.get(r, -1) for r in discord_roles] + [-1])
            if discord_lvl >= target_lvl:
                platforms_at_or_above += 1
                
            logger.debug(f"  └─ Consensus Check: Game={game_lvl >= target_lvl}, Discord={discord_lvl >= target_lvl}, Sheet={sheet_lvl >= target_lvl} -> ({platforms_at_or_above}/3)")
                
            if platforms_at_or_above >= 2:
                logger.debug(f"  └─ Skipping: Already holds {target_rank} (or higher) in {platforms_at_or_above}/3 ecosystems.")
                continue # User already holds this rank (or higher) in at least 2/3 ecosystems
        
        # --- History Tracking with Wildcard Support ---
        # Traverse history backwards from the most recent month.
        # We maintain their rank streak as long as the DB shows their true_rank OR a Wildcard.
        achieved_month = records[-1]['month']
        for rec in reversed(records):
            rec_rank = get_highest_rank(rec['ranks'])
            
            if rec_rank == true_rank or rec_rank == "Wildcard":
                achieved_month = rec['month']
            elif rec_rank is None:
                # No ranks recorded at all (e.g. inactive month) - skip over it to see if streak existed before gap
                continue
            else:
                # Streak broken by an explicitly different progression rank
                break
                
        logger.debug(f"  └─ Streak tracked back to {achieved_month}")
                
        start_y, start_m = map(int, achieved_month.split('-'))
        latest_y, latest_m = map(int, records[-1]['month'].split('-'))
        total_calendar_months = (latest_y - start_y) * 12 + (latest_m - start_m) + 1
        
        record_dict = {r['month']: r for r in records}
        total_points = 0.0
        curr_y, curr_m = start_y, start_m
        
        upkeep = thresholds.get("upkeep", 20.0)
        chat_tiers = thresholds.get("chat_tiers", DEFAULT_CHAT_TIERS)
        broadcast_tiers = thresholds.get("broadcast_tiers", DEFAULT_BROADCAST_TIERS)
        
        # Collect warnings for members who qualify but have outstanding issues
        warnings = []
        if user_status_map and user_id in user_status_map:
            status = user_status_map[user_id]
            for sf in status['system_flags']:
                if sf not in ['OK', 'Archived', 'Not in Discord', 'Banned in Clan']:
                    warnings.append(sf)
            for af in status['admin_flags']:
                if af not in ['Banned', 'OK']:
                    warnings.append(af)
                    
        warning_str = f" ⚠️ *[Flags: {', '.join(warnings)}]*" if warnings else ""
        
        for _ in range(total_calendar_months):
            m_str = f"{curr_y:04d}-{curr_m:02d}"
            if m_str in record_dict:
                earned = calculate_points(record_dict[m_str]['chats'], record_dict[m_str]['broadcasts'], chat_tiers, broadcast_tiers)
                net_pts = earned - upkeep
                total_points = max(0, total_points + net_pts)
                logger.debug(f"    ├─ Month {m_str}: Scored {earned:.1f} pts, Upkeep -{upkeep:.1f}. Net: {net_pts:.1f}. Total: {total_points:.1f}")
            else:
                total_points = max(0, total_points - upkeep) # Decay inactive months
                logger.debug(f"    ├─ Month {m_str}: Inactive. Upkeep -{upkeep:.1f}. Total: {total_points:.1f}")
                
            curr_m = 1 if curr_m == 12 else curr_m + 1
            curr_y += 1 if curr_m == 1 else 0
            
        logger.debug(f"  └─ Final Result: {total_points:.1f}/{thresholds['points']} points | {total_calendar_months}/{thresholds['min_months']} months")
                
        # Get account list details
        member = user_roster_map.get(user_id, {})
        rsns_raw = str(member.get('RSNs', '')).strip()
        rsns_list = [r.strip() for r in rsns_raw.split(',') if r.strip()]
        
        ranks_raw = str(member.get('Game Ranks', '')).strip()
        ranks_list = [r.strip() for r in ranks_raw.split(',') if r.strip()]
        
        clans_raw = str(member.get('Account Clan', '')).strip()
        clans_list = [c.strip() for c in clans_raw.split(',') if c.strip()]
        
        account_lines = []
        for i in range(len(rsns_list)):
            rsn = rsns_list[i]
            rank = ranks_list[i] if i < len(ranks_list) else "Unknown"
            clan = clans_list[i] if i < len(clans_list) else "Unknown"
            account_lines.append(f"    * `{rsn}` (Rank: `{rank}` | Clan: *{clan}*)")
            
        if not account_lines:
            account_lines.append("    * *None*")

        suggestion_record = {
            'discord_id': user_id,
            'name': records[-1]['name'], 'current_rank': true_rank, 'target_rank': target_rank,
            'points': total_points, 'required_points': thresholds['points'],
            'months_in_rank': total_calendar_months, 'min_months': thresholds['min_months'],
            'warning_str': warning_str,
            'account_lines': account_lines
        }
        
        meets_full = (total_points >= thresholds['points'] and total_calendar_months >= thresholds['min_months'])
        
        if meets_full:
            suggestions.append(suggestion_record)
        else:
            # Early Consideration Check (80% points and within 1 month of time limit)
            early_req_points = thresholds['points'] * 0.8
            early_req_months = max(1, thresholds['min_months'] - 1)
            if total_points >= early_req_points and total_calendar_months >= early_req_months:
                early_suggestions.append(suggestion_record)
            
    # Write Report
    output_md.parent.mkdir(parents=True, exist_ok=True)
    
    lines = [
        "# 🏆 Clan Rank-Up Suggestions",
        f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"> **Note:** This report is automatically generated based on Discord chat and broadcast activity. The database currently contains **{db_age_months} months** of historical data. Ranks requiring more time than this may require manual legacy review.\n"
    ]
    
    if not suggestions:
        lines.append("*No members currently meet the full criteria for a rank up.*\n")
    else:
        suggestions.sort(key=lambda x: (PROGRESSION_RANKS.index(x['target_rank']), x['points']), reverse=True)
        lines.append("## 🎯 Ready for Promotion\n")
        for s in suggestions:
            lines.append(f"* **{s['name']}** <@{s['discord_id']}>{s['warning_str']}")
            lines.append(f"  * Rank: {s['current_rank']} ➡️ **{s['target_rank']}**")
            lines.append(f"  * Points: **{s['points']:.1f}** / {s['required_points']} | Time in Rank: **{s['months_in_rank']}** / {s['min_months']} Months")
            lines.append("  * Accounts:")
            lines.extend(s['account_lines'])
            lines.append("")
            
    if early_suggestions:
        early_suggestions.sort(key=lambda x: (PROGRESSION_RANKS.index(x['target_rank']), x['points']), reverse=True)
        lines.append("## ⏳ Close to Promotion (Early Consideration)")
        lines.append("> *Members who have reached at least 80% of the required points and are within 1 month of the time requirement.*\n")
        for s in early_suggestions:
            lines.append(f"* **{s['name']}** <@{s['discord_id']}>{s['warning_str']}")
            lines.append(f"  * Rank: {s['current_rank']} ➡️ **{s['target_rank']}**")
            lines.append(f"  * Points: **{s['points']:.1f}** / {s['required_points']} | Time in Rank: **{s['months_in_rank']}** / {s['min_months']} Months")
            lines.append("  * Accounts:")
            lines.extend(s['account_lines'])
            lines.append("")
            
    if safe_write_report(output_md, "\n".join(lines)):
        logger.success(f"Successfully generated rank up suggestions at {output_md} ({len(suggestions)} ready, {len(early_suggestions)} early consideration)")

if __name__ == '__main__':
    import sys
    from dotenv import load_dotenv
    from db_manager import DBManager
    
    env_path = PROJECT_ROOT / "shared_secrets" / ".env"
    load_dotenv(env_path)
    
    logger.remove()
    log_level = os.getenv('AUDITOR_LOG_LEVEL', 'INFO').upper()
    logger.add(sys.stderr, level=log_level)
    
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
    if not SPREADSHEET_ID:
        logger.error(f"Missing SPREADSHEET_ID in {env_path}")
        sys.exit(1)
        
    db = DBManager(SPREADSHEET_ID)
    logger.info("Fetching latest data from Google Sheets for standalone execution...")
    generate_suggestions(roster_data=db.get_all_records('Database'), rank_rules=db.get_all_records('Reference_Data'))