import os
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from loguru import logger
from constants import SHARED_DATA_DIR


def generate_dashboard_export(roster_data, history_db_path=None):
    """
    Generates a JSON export of clan members and their name change history for the ELT dashboard.
    
    Args:
        roster_data (list of dict): The parsed data from the Google Sheet 'Database' tab.
        history_db_path (str): Path to the Auditor's local SQLite database.
    """
    if not history_db_path:
        history_db_path = SHARED_DATA_DIR / "databases" / "history.db"
        
    # 1. Load Configuration & Define Path
    final_path = SHARED_DATA_DIR / "exports" / "roster_export.json"
    try:
        retain_days = int(os.getenv("DASHBOARD_EXPORT_RETAIN_DAYS", "30"))
    except ValueError:
        logger.error("Invalid DASHBOARD_EXPORT_RETAIN_DAYS. Defaulting to 30.")
        retain_days = 30

    # Ensure the final target directory (at least the fallback one) exists
    final_path.parent.mkdir(parents=True, exist_ok=True)

    # 3. Setup the JSON Payload
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=retain_days)).isoformat()
    export_payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_days_used": retain_days
        },
        "members": []
    }

    # 4. Fetch Name Changes from history.db
    all_name_changes = []

    if Path(history_db_path).exists():
        try:
            conn = sqlite3.connect(history_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Fetch all name changes
            cursor.execute("SELECT old_name, new_name, resolved_at FROM name_changes")
            all_name_changes = [dict(row) for row in cursor.fetchall()]

            conn.close()
        except sqlite3.Error as e:
            logger.error(f"Database error while reading history.db: {e}")
    else:
        logger.warning(f"Local history.db not found at '{history_db_path}'. Name change history will be empty.")

    # 5. Process Roster and format for the Dashboard
    for member in roster_data:
        discord_id = member.get("Discord ID", "")
        discord_name = member.get("Discord Name") or discord_id
        
        # Parse comma-separated RSNs
        rsns = [r.strip() for r in str(member.get("RSNs", "")).split(",") if r.strip()]
        wom_ids = [w.strip() for w in str(member.get("WOM IDs", "")).split(",") if w.strip()]
        
        if not rsns:
            continue # Skip users with no linked accounts

        # Gather relevant name change history for this specific user
        user_history = []
        for nc in all_name_changes:
            if nc["new_name"].lower() in [r.lower() for r in rsns] or nc["old_name"].lower() in [r.lower() for r in rsns]:
                user_history.append({
                    "old_name": nc["old_name"],
                    "new_name": nc["new_name"],
                    "date": nc["resolved_at"]
                })

        export_payload["members"].append({
            "discord_id": str(discord_id),
            "discord_name": discord_name,
            "current_rsns": rsns,
            "system_flags": [f.strip() for f in str(member.get("System Flags", "")).split(",") if f.strip()],
            "admin_flags": [f.strip() for f in str(member.get("Admin Flags", "")).split(",") if f.strip()],
            "name_history": user_history
        })

    # 6. Write JSON File safely
    try:
        tmp_path = final_path.with_suffix('.tmp')
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(export_payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, final_path) # Atomic swap
        logger.info(f"Successfully generated dashboard export at: {final_path} ({len(export_payload['members'])} users)")
    except IOError as e:
        logger.error(f"Failed to write dashboard export file to {final_path}: {e}")
        
    return final_path