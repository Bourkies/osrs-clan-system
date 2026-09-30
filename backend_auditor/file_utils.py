import os
import json
from pathlib import Path
from loguru import logger

def safe_write_report(file_path: Path | str, content: str) -> bool:
    """
    Safely writes text content to a file using an atomic rename operation.
    If the target file is locked by the host OS (e.g., opened in a Windows editor),
    it catches the error, logs a warning, and skips the save rather than crashing.
    
    Args:
        file_path: The target file path.
        content: The string content to write to the file.
        
    Returns:
        bool: True if successful, False if the write was skipped or failed.
    """
    target_path = Path(file_path)
    temp_path = target_path.with_suffix(target_path.suffix + '.tmp')
    
    try:
        # Write completely to a temporary file first
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Atomically replace the target file with the temp file
        os.replace(temp_path, target_path)
        logger.info(f"Successfully saved report to: {target_path.name}")
        return True
        
    except PermissionError as e:
        logger.warning(f"File lock encountered: Could not overwrite {target_path.name}. It might be open in another program. Skipping save.")
    except Exception as e:
        logger.error(f"Unexpected error saving report {target_path.name}: {e}")
        
    # Cleanup temp file on failure
    if temp_path.exists():
        try:
            os.remove(temp_path)
        except Exception:
            pass
            
    return False

# Mapping of WOM player types to short tags
TYPE_ABBREVIATIONS = {
    'regular': 'M',
    'ironman': 'I',
    'hardcore': 'HC',
    'ultimate': 'UIM',
    'group_ironman': 'GIM',
    'hardcore_group_ironman': 'HCGIM',
    'unranked_group_ironman': 'GIM',
}

def get_account_type_tag(wid, wom_type_map) -> str:
    """Returns ' [M]', ' [I]', ' [HC]', ' [UIM]', etc. or '' if unknown/unmapped."""
    if not wid or not wom_type_map:
        return ""
    raw_type = wom_type_map.get(str(wid).strip())
    if not raw_type:
        return ""
    abbr = TYPE_ABBREVIATIONS.get(str(raw_type).strip().lower(), "")
    return f" [{abbr}]" if abbr else ""

def load_wom_cache_maps(cache_file=None):
    """
    Parses wom_cache.json to extract:
    - wom_activity_map: {w_id: latest_date}
    - wom_type_map: {w_id: player_type}
    """
    from datetime import datetime
    from constants import SHARED_DATA_DIR

    if cache_file is None:
        cache_file = SHARED_DATA_DIR / "caches" / "wom_cache.json"
    cache_path = Path(cache_file)
    wom_activity_map = {}
    wom_type_map = {}

    if not cache_path.exists():
        return wom_activity_map, wom_type_map

    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            wom_cache = json.load(f)

        for key, entry in wom_cache.items():
            if key.startswith("player_") or key.startswith("group_details_"):
                data = entry.get("data", {})
                if "memberships" in data:
                    for membership in data.get("memberships", []):
                        player = membership.get("player", {})
                        w_id = str(player.get("id"))
                        last_changed = player.get("lastChangedAt")
                        p_type = player.get("type")
                        if w_id and w_id != 'None':
                            if p_type and w_id not in wom_type_map:
                                wom_type_map[w_id] = p_type
                            if last_changed:
                                try:
                                    parsed_date = datetime.strptime(last_changed[:10], "%Y-%m-%d").date()
                                    if w_id not in wom_activity_map or parsed_date > wom_activity_map[w_id]:
                                        wom_activity_map[w_id] = parsed_date
                                except Exception:
                                    pass
                w_id = str(data.get("id"))
                last_changed = data.get("lastChangedAt")
                p_type = data.get("type")
                if w_id and w_id != 'None':
                    if p_type and w_id not in wom_type_map:
                        wom_type_map[w_id] = p_type
                    if last_changed:
                        try:
                            parsed_date = datetime.strptime(last_changed[:10], "%Y-%m-%d").date()
                            if w_id not in wom_activity_map or parsed_date > wom_activity_map[w_id]:
                                wom_activity_map[w_id] = parsed_date
                        except Exception:
                            pass
    except Exception as e:
        logger.error(f"Failed to read WOM cache: {e}")

    return wom_activity_map, wom_type_map