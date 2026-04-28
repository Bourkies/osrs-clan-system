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