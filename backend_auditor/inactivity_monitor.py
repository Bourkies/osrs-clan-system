import os
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from loguru import logger
from constants import SHARED_DATA_DIR, SystemFlag
from file_utils import safe_write_report

def generate_inactivity_report(all_members, rank_rules):
    logger.info("Starting Clan Inactivity Monitor...")
    input_db = SHARED_DATA_DIR / "databases" / "activity.db"
    output_md = SHARED_DATA_DIR / "reports" / "inactivity_report.md"
    
    if not input_db.exists():
        logger.warning(f"Database not found at {input_db}. Skipping inactivity report.")
        return
        
    # 1. Parse Max Inactive Days configuration
    max_inactive_map = {}
    rank_order = []
    for rule in rank_rules:
        rank_name = str(rule.get('Clan Rank', '')).strip()
        if not rank_name: continue
        rank_order.append(rank_name)
        
        max_days_raw = str(rule.get('Max Inactive Days', '')).strip()
        if max_days_raw.isdigit():
            max_inactive_map[rank_name] = int(max_days_raw)
            
    # Reverse rank order so the report lists lowest ranks first
    rank_order.reverse()
            
    # 2. Fetch rolling activity stats in a single fast query
    activity_stats = {}
    try:
        conn = sqlite3.connect(input_db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                Discord_ID, 
                MAX(Date) as last_active,
                SUM(CASE WHEN Date >= date('now', '-30 days') THEN Chats ELSE 0 END) as chats_1m,
                SUM(CASE WHEN Date >= date('now', '-30 days') THEN Broadcasts ELSE 0 END) as broadcasts_1m,
                SUM(CASE WHEN Date >= date('now', '-90 days') THEN Chats ELSE 0 END) as chats_3m,
                SUM(CASE WHEN Date >= date('now', '-90 days') THEN Broadcasts ELSE 0 END) as broadcasts_3m,
                SUM(CASE WHEN Date >= date('now', '-180 days') THEN Chats ELSE 0 END) as chats_6m,
                SUM(CASE WHEN Date >= date('now', '-180 days') THEN Broadcasts ELSE 0 END) as broadcasts_6m,
                SUM(Chats) as chats_total,
                SUM(Broadcasts) as broadcasts_total
            FROM daily_activity
            GROUP BY Discord_ID
        """)
        
        for row in cursor.fetchall():
            activity_stats[str(row['Discord_ID'])] = dict(row)
            
        conn.close()
    except Exception as e:
        logger.error(f"Failed to query {input_db}: {e}")
        return
        
    # 3. Parse WOM cache to get lastChangedAt for in-game activity
    wom_cache_file = SHARED_DATA_DIR / "caches" / "wom_cache.json"
    wom_activity_map = {}
    if wom_cache_file.exists():
        try:
            with open(wom_cache_file, 'r', encoding='utf-8') as f:
                wom_cache = json.load(f)
                
            for key, entry in wom_cache.items():
                if key.startswith("player_") or key.startswith("group_details_"):
                    data = entry.get("data", {})
                    
                    # Handle group_details structure
                    if "memberships" in data:
                        for membership in data.get("memberships", []):
                            player = membership.get("player", {})
                            w_id = str(player.get("id"))
                            last_changed = player.get("lastChangedAt")
                            if w_id and w_id != 'None' and last_changed:
                                parsed_date = datetime.strptime(last_changed[:10], "%Y-%m-%d").date()
                                if w_id not in wom_activity_map or parsed_date > wom_activity_map[w_id]:
                                    wom_activity_map[w_id] = parsed_date
                                    
                    # Handle individual player structure
                    w_id = str(data.get("id"))
                    last_changed = data.get("lastChangedAt")
                    if w_id and w_id != 'None' and last_changed:
                        parsed_date = datetime.strptime(last_changed[:10], "%Y-%m-%d").date()
                        if w_id not in wom_activity_map or parsed_date > wom_activity_map[w_id]:
                            wom_activity_map[w_id] = parsed_date
                            
        except Exception as e:
            logger.error(f"Failed to read WOM cache for inactivity monitor: {e}")

    # 4. Evaluate Members
    today = datetime.utcnow().date()
    inactive_users = []
    potential_users = []
    
    for member in all_members:
        sys_flags = str(member.get('System Flags', ''))
        admin_flags = str(member.get('Admin Flags', ''))
        
        # Skip archived, banned, or approved leave members
        if SystemFlag.ARCHIVED.value in sys_flags or 'Banned' in admin_flags or 'On Leave' in admin_flags:
            continue
            
        clan_rank = str(member.get('Clan Rank', '')).strip()
        max_days = max_inactive_map.get(clan_rank)
        
        # If their rank has no configured max inactive days, skip them (e.g. Owner)
        if not max_days:
            continue
            
        discord_id = str(member.get('Discord ID', '')).replace("'", "").strip()
        stats = activity_stats.get(discord_id, {})
        
        # --- Get Discord / Broadcast Last Active ---
        last_active_str = stats.get('last_active')
        if last_active_str:
            discord_last_active_date = datetime.strptime(last_active_str, "%Y-%m-%d").date()
            discord_last_active_display = last_active_str
        else:
            # Fallback to Join Date if they have NO activity on record
            join_str = str(member.get('Join Date', '')).strip()
            try:
                discord_last_active_date = datetime.strptime(join_str, "%Y-%m-%d").date()
                discord_last_active_display = f"Never ({join_str})"
            except ValueError:
                discord_last_active_date = None
                discord_last_active_display = "Unknown"
                
        # --- Get WOM Last Changed Active ---
        wom_ids_str = str(member.get('WOM IDs', '')).strip()
        wom_ids = [w.strip() for w in wom_ids_str.split(',') if w.strip()]
        wom_dates = [wom_activity_map[wid] for wid in wom_ids if wid in wom_activity_map]
        
        wom_last_active_date = max(wom_dates) if wom_dates else None
        wom_last_active_display = wom_last_active_date.strftime("%Y-%m-%d") if wom_last_active_date else "Unknown"
        
        # --- Compare for True Last Active ---
        discord_days = (today - discord_last_active_date).days if discord_last_active_date else 9999
        wom_days = (today - wom_last_active_date).days if wom_last_active_date else 9999
        
        true_days_inactive = min(discord_days, wom_days)
            
        if discord_days > max_days or wom_days > max_days:
            discord_name = str(member.get('Discord Name', '')).strip()
            if not discord_name or discord_name.lower() == 'unknown':
                discord_name = discord_id
                
            user_data = {
                'discord_id': discord_id,
                'discord_name': discord_name,
                'rsns': str(member.get('RSNs', 'None')).strip(),
                'rank': clan_rank,
                'discord_days': discord_days,
                'wom_days': wom_days,
                'true_days': true_days_inactive,
                'discord_active': discord_last_active_display,
                'wom_active': wom_last_active_display,
                'limit': max_days,
                'stats': stats
            }
            
            if true_days_inactive > max_days:
                inactive_users.append(user_data)
            else:
                potential_users.append(user_data)
            
    # Sort by rank (lowest first), then by days inactive (highest first)
    def sort_key(x):
        return (rank_order.index(x['rank']) if x['rank'] in rank_order else 999, -x['true_days'])
        
    inactive_users.sort(key=sort_key)
    potential_users.sort(key=sort_key)
    
    # 5. Generate Markdown Report
    os.makedirs(output_md.parent, exist_ok=True)
    
    report_lines = [
        "# 💤 Inactivity Report",
        f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n",
        "> *In-Game activity is based on XP/Boss KC changes tracked by Wise Old Man.*\n",
        f"**Total Fully Inactive Members:** {len(inactive_users)}\n"
    ]
    
    def append_section(title, description, users_list):
        if not users_list:
            return
        report_lines.append(f"## {title}")
        report_lines.append(f"> *{description}*")
        report_lines.append("> *Format: (Chats / Broadcasts)*\n")
        
        current_rank = None
        for u in users_list:
            if u['rank'] != current_rank:
                current_rank = u['rank']
                report_lines.append(f"### {current_rank} (Limit: {u['limit']} Days)")
                
            s = u['stats']
            d_display = f"{u['discord_days']} Days ({u['discord_active']})" if u['discord_days'] != 9999 else u['discord_active']
            w_display = f"{u['wom_days']} Days ({u['wom_active']})" if u['wom_days'] != 9999 else u['wom_active']
            true_days_str = f"{u['true_days']} Days Inactive" if u['true_days'] != 9999 else "Never Active"
            
            report_lines.append(f"* **{u['discord_name']}** | RSNs: `{u['rsns']}`")
            report_lines.append(f"  * **{true_days_str}** (Chats & Broadcasts: {d_display} | WOM Updated: {w_display})")
            report_lines.append(f"  * *Activity:* 1M: {s.get('chats_1m', 0)}/{s.get('broadcasts_1m', 0)} | 3M: {s.get('chats_3m', 0)}/{s.get('broadcasts_3m', 0)} | 6M: {s.get('chats_6m', 0)}/{s.get('broadcasts_6m', 0)} | Total: {s.get('chats_total', 0)}/{s.get('broadcasts_total', 0)}\n")

    append_section("🚨 Fully Inactive Members", "Exceeded inactivity limit across ALL tracked metrics.", inactive_users)
    append_section("⚠️ Potentially Inactive", "Exceeded inactivity limit on ONE metric, but recently active on the other.", potential_users)

    if inactive_users:
        report_lines.append("## 📢 Removal Ping List (Fully Inactive Only)")
        for u in inactive_users:
            report_lines.append(f"<@{u['discord_id']}> {u['rsns']}")
            
    total_flagged = len(inactive_users) + len(potential_users)
    if safe_write_report(output_md, "\n".join(report_lines) + "\n"):
        logger.success(f"Successfully generated Inactivity Report for {total_flagged} members.")