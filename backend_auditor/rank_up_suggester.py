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
    ranks = [r.strip() for r in ranks_str.split(",")]
    
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
            
    return None

def generate_suggestions():
    logger.info("Starting Clan Rank-Up Suggester...")
    input_db = SHARED_DATA_DIR / "databases" / "activity.db"
    output_md = SHARED_DATA_DIR / "reports" / "rank_up_suggestions.md"
    roster_json = SHARED_DATA_DIR / "exports" / "roster_export.json"
    
    if not input_db.exists():
        logger.error(f"Input Database not found at {input_db}. Please run 'activity_reporter.py' first.")
        return
        
    user_data = defaultdict(list)
    all_months = set()
    
    user_status_map = {}
    if roster_json.exists():
        try:
            with open(roster_json, 'r', encoding='utf-8') as f:
                roster_data = json.load(f)
                for user in roster_data.get('members', []):
                    user_status_map[str(user.get('discord_id'))] = {
                        'system_flags': user.get('system_flags', []),
                        'admin_flags': user.get('admin_flags', [])
                    }
        except Exception as e:
            logger.warning(f"Could not read roster_export.json: {e}")

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
        
        # Determine True Rank from the most recent active month
        true_rank = next((get_highest_rank(rec['ranks']) for rec in reversed(records) if rec['total'] >= MIN_ACTIVITY_TO_VALIDATE_RANK), None)
        
        if not true_rank or true_rank in ("Staff", "Special", "Zenyte") or true_rank not in PROGRESSION_RANKS:
            continue
            
        target_rank = PROGRESSION_RANKS[PROGRESSION_RANKS.index(true_rank) + 1]
        thresholds = PROMOTION_THRESHOLDS[target_rank]
        
        # Find earliest month they had this rank to start scoring
        achieved_month = next((rec['month'] for rec in records if get_highest_rank(rec['ranks']) == true_rank), records[-1]['month'])
                
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
                net_pts = calculate_points(record_dict[m_str]['chats'], record_dict[m_str]['broadcasts'], chat_tiers, broadcast_tiers) - upkeep
                total_points = max(0, total_points + net_pts)
            else:
                total_points = max(0, total_points - upkeep) # Decay inactive months
                
            curr_m = 1 if curr_m == 12 else curr_m + 1
            curr_y += 1 if curr_m == 1 else 0
                
        suggestion_record = {
            'name': records[-1]['name'], 'current_rank': true_rank, 'target_rank': target_rank,
            'points': total_points, 'required_points': thresholds['points'],
            'months_in_rank': total_calendar_months, 'min_months': thresholds['min_months'],
            'warning_str': warning_str
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
            lines.append(f"* **{s['name']}**{s['warning_str']}")
            lines.append(f"  * Rank: {s['current_rank']} ➡️ **{s['target_rank']}**")
            lines.append(f"  * Points: **{s['points']:.1f}** / {s['required_points']} | Time in Rank: **{s['months_in_rank']}** / {s['min_months']} Months\n")
            
    if early_suggestions:
        early_suggestions.sort(key=lambda x: (PROGRESSION_RANKS.index(x['target_rank']), x['points']), reverse=True)
        lines.append("## ⏳ Close to Promotion (Early Consideration)")
        lines.append("> *Members who have reached at least 80% of the required points and are within 1 month of the time requirement.*\n")
        for s in early_suggestions:
            lines.append(f"* **{s['name']}**{s['warning_str']}")
            lines.append(f"  * Rank: {s['current_rank']} ➡️ **{s['target_rank']}**")
            lines.append(f"  * Points: **{s['points']:.1f}** / {s['required_points']} | Time in Rank: **{s['months_in_rank']}** / {s['min_months']} Months\n")
            
    if safe_write_report(output_md, "\n".join(lines)):
        logger.success(f"Successfully generated rank up suggestions at {output_md} ({len(suggestions)} ready, {len(early_suggestions)} early consideration)")

if __name__ == '__main__':
    generate_suggestions()