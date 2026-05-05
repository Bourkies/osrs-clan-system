import os
import sys
import time
import signal
import argparse
from dotenv import load_dotenv
from loguru import logger

from db_manager import DBManager
from webhook_manager import WebhookManager
from wom_client import WomClient

import discord_sync
import audit_logic
import wom_sync
import dashboard_exporter
from constants import SystemFlag, SHARED_SECRETS_DIR, SHARED_DATA_DIR
import backup_manager
import activity_reporter
import rank_up_suggester
import inactivity_monitor

load_dotenv(SHARED_SECRETS_DIR / ".env")

LOG_LEVEL = os.getenv('AUDITOR_LOG_LEVEL', 'INFO').upper()

# Configure loguru
logger.remove() # Remove default stderr handler (which defaults to DEBUG)
logger.add(sys.stderr, level=LOG_LEVEL)
logger.add(SHARED_DATA_DIR / "logs" / "auditor" / "auditor.log", rotation="10 MB", retention="1 month", level=LOG_LEVEL)

SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DISCORD_GUILD_ID = os.getenv('DISCORD_GUILD_ID')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')
AUDIT_LOG_RETENTION_COUNT = int(os.getenv('AUDIT_LOG_RETENTION_COUNT', '2000'))

if not SPREADSHEET_ID:
    raise ValueError("Missing SPREADSHEET_ID in .env file.")

# --- Smart Lock Implementation ---
LOCK_FILE = SHARED_DATA_DIR / "auditor.lock"

def acquire_lock(timeout=600, check_interval=10):
    start_time = time.time()
    while True:
        try:
            with open(LOCK_FILE, 'x') as f:
                f.write(str(os.getpid()))
            logger.info("Lock acquired successfully.")
            return True
        except FileExistsError:
            # Check for stale lock file (e.g., from a previous hard crash)
            try:
                if time.time() - os.path.getmtime(LOCK_FILE) > 3600:  # 1 hour threshold
                    logger.warning(f"Stale lock file detected (older than 1 hour). Removing: {LOCK_FILE}")
                    os.remove(LOCK_FILE)
                    continue  # Loop back and try acquiring the lock again
            except OSError:
                pass  # File might have just been deleted by another process
                
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                logger.error(f"Timeout ({timeout}s) waiting for lock file to be released: {LOCK_FILE}")
                sys.exit(1)
            logger.info(f"Lock file exists. Waiting... ({int(elapsed)}/{timeout}s)")
            time.sleep(check_interval)

def release_lock():
    try:
        # Only remove the lock if it belongs to the current process
        with open(LOCK_FILE, 'r') as f:
            pid = f.read().strip()
        if pid == str(os.getpid()):
            os.remove(LOCK_FILE)
            logger.info("Lock released.")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"Error releasing lock: {e}")

def run_orchestrator(force_wom=False, skip_webhook=False, sync_only=False):
    logger.info("Initializing Orchestrator...")
    db = DBManager(SPREADSHEET_ID)
    
    # Execute Daily Backup Policy
    retention = os.getenv('BACKUP_RETENTION_DAYS', 30)
    backup_manager.run_backup(db, retention_days=retention)

    wom = WomClient()
    webhook = WebhookManager(DISCORD_WEBHOOK_URL)
    
    if force_wom:
        wom.clear_cache()

    db.append_audit_logs(["System Action - System (N/A): Auditor run started."])

    rank_rules = db.get_all_records('Reference_Data')
    config_records = db.get_all_records('System_Config')
    system_config = {str(row.get('Setting Name', '')).strip(): str(row.get('Value', '')).strip() for row in config_records}
    target_clan_name = system_config.get('Target Clan Name', 'Unknown Clan')

    audit_logs = []

    role_map = discord_sync.sync_roles(db, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, audit_logs)
    discord_sync.sync_members(db, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, role_map, audit_logs)
    untracked_members, banned_members, failed_wom_updates = wom_sync.sync_wom_data(db, wom, target_clan_name, audit_logs)
    
    report_sections = []
    
    if not sync_only:
        # Bundle the state into a single payload so audits can extract what they need
        audit_context = {
            'target_clan_name': target_clan_name,
            'role_map': role_map,
            'webhook': webhook,
            'banned_members': banned_members,
            'untracked_members': untracked_members,
            'failed_wom_updates': failed_wom_updates
        }
        
        audit_sections = audit_logic.audit_roster(
            db, 
            rank_rules, 
            audit_logs, 
            context=audit_context
        )
        report_sections.extend(audit_sections)

    db.append_audit_logs(audit_logs)

    if not sync_only:
        webhook.save_full_report(report_sections)

    if not skip_webhook and not sync_only:
        webhook.send_report(report_sections)
        
    if not sync_only:
        # Export the Roster to JSON for the ELT Dashboard pipeline
        roster_data = db.get_all_records('Database')
        dashboard_exporter.generate_dashboard_export(roster_data)
        
        # Generate Markdown Reports
        logger.info("Executing Post-Audit Reporting Scripts...")
        activity_reporter.generate_activity_report()
        rank_up_suggester.generate_suggestions(roster_data, rank_rules)
        inactivity_monitor.generate_inactivity_report(roster_data, rank_rules)
        
    db.trim_audit_logs(keep_last=AUDIT_LOG_RETENTION_COUNT)
    db.append_audit_logs(["System Action - System (N/A): Auditor run finished."])

def handle_shutdown_signal(signum, frame):
    logger.warning(f"Received shutdown signal ({signum}). Gracefully releasing locks and exiting...")
    sys.exit(0)

def main():
    # Register signal handlers for graceful shutdown (e.g., Docker stop/restart)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    signal.signal(signal.SIGINT, handle_shutdown_signal)

    parser = argparse.ArgumentParser(description="OSRS Clan Auditor")
    parser.add_argument('--force-wom', action='store_true', help='Force clear and refresh the entire WOM cache.')
    parser.add_argument('--no-webhook', action='store_true', help='Run full sync and audit, but skip sending the Discord webhook.')
    parser.add_argument('--sync-only', action='store_true', help='Sync APIs to database, but skip audits and webhook.')
    args = parser.parse_args()

    try:
        acquire_lock()
        run_orchestrator(force_wom=args.force_wom, skip_webhook=args.no_webhook, sync_only=args.sync_only)
    finally:
        release_lock()

if __name__ == '__main__':
    main()