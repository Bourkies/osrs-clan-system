import os
import csv
from datetime import datetime, timedelta
import shutil
import stat
from loguru import logger
from constants import SHARED_DATA_DIR

# List of tabs to back up. Explicitly skipping 'Audit_Log' as it is append-only and space-heavy.
BACKUP_TABS = ['System_Schema', 'Reference_Data', 'System_Config', 'Discord_Roles', 'Database']

def run_backup(db_manager, retention_days=30):
    try:
        retention_days = int(retention_days)
    except (ValueError, TypeError):
        retention_days = 30

    backups_dir = str(SHARED_DATA_DIR / 'backups')
    os.makedirs(backups_dir, exist_ok=True)

    today_str = datetime.utcnow().strftime('%Y-%m-%d')
    today_backup_dir = os.path.join(backups_dir, today_str)

    if os.path.exists(today_backup_dir):
        logger.info(f"Backup for {today_str} already exists. Skipping backup export.")
    else:
        logger.info(f"Creating database backup for {today_str}...")
        os.makedirs(today_backup_dir, exist_ok=True)
        _export_to_csv(db_manager, today_backup_dir)
        logger.success(f"Database successfully backed up to {today_backup_dir}")

    _prune_backups(backups_dir, retention_days)

def _export_to_csv(db_manager, backup_dir):
    for tab_name in BACKUP_TABS:
        try:
            headers = db_manager.get_headers(tab_name)
            records = db_manager.get_all_records(tab_name)
            
            file_path = os.path.join(backup_dir, f"{tab_name}.csv")
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                if not headers:
                    continue
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                for row in records:
                    writer.writerow(row)
        except Exception as e:
            logger.error(f"Failed to backup tab {tab_name}: {e}")

def _remove_readonly(func, path, _):
    """Clear the readonly bit and reattempt the removal."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def _prune_backups(backups_dir, retention_days):
    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
    
    months = {}
    all_backups = []
    
    # Group backups into months
    for item in os.listdir(backups_dir):
        item_path = os.path.join(backups_dir, item)
        if os.path.isdir(item_path):
            try:
                b_date = datetime.strptime(item, '%Y-%m-%d')
                all_backups.append(b_date)
                month_key = b_date.strftime('%Y-%m')
                if month_key not in months:
                    months[month_key] = []
                months[month_key].append(b_date)
            except ValueError:
                pass # Ignore directories that don't match the YYYY-MM-DD pattern
                
    for month_key in months:
        months[month_key].sort() # Sort dates oldest to newest within the month
        
    pruned_count = 0
    for b_date in all_backups:
        if b_date >= cutoff_date or b_date == months[b_date.strftime('%Y-%m')][0]:
            continue # Keep if it falls within retention period OR is the oldest backup of its month
            
        b_dir = os.path.join(backups_dir, b_date.strftime('%Y-%m-%d'))
        try:
            shutil.rmtree(b_dir, onerror=_remove_readonly)
            pruned_count += 1
        except Exception as e: logger.error(f"Failed to delete old backup {b_dir}: {e}")
            
    if pruned_count > 0:
        logger.info(f"Pruned {pruned_count} old backups (Retention: {retention_days} days).")