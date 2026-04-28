"""
sync_collection_log.py

A standalone helper script to rebuild the historical_collection_logs.toml file
by scraping the live OSRS Wiki Collection Log page.

Features:
- Preserves existing initial counts that are > 0, discarding 0 counts to prevent bloat.
- Dynamically recreates groups and item arrays based on the Wiki's structure.
- Automatically downloads missing item icons, converts them to .webp, and saves
  them to the custom_icons directory for the dashboard to use.
"""

import os
import re
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from io import BytesIO
from PIL import Image
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from loguru import logger

# --- Paths ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
SHARED_CONFIG_DIR = PROJECT_ROOT / "shared_config"
ASSETS_DIR = SHARED_CONFIG_DIR / "assets"
CUSTOM_ICON_DIR = ASSETS_DIR / "custom_icons"

TOML_PATH = SHARED_CONFIG_DIR / "historical_collection_logs.toml"
TOML_OUT_PATH = SHARED_CONFIG_DIR / "historical_collection_logs_updated.toml"
ITEMS_JSON_PATH = ASSETS_DIR / "items-complete.json"

WIKI_URL = "https://oldschool.runescape.wiki/w/Collection_log"
WIKI_BASE = "https://oldschool.runescape.wiki"

def get_safe_filename(item_name: str) -> str:
    """Replicates the Streamlit dashboard's custom icon filename logic."""
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '', item_name.replace(' ', '_'))
    return safe_name + ".webp"

def main():
    logger.info("Starting Collection Log Sync...")
    
    # 1. Ensure directories exist
    CUSTOM_ICON_DIR.mkdir(parents=True, exist_ok=True)
    
    # 2. Load existing items-complete.json to know which icons we already have
    known_icons = set()
    if ITEMS_JSON_PATH.exists():
        with open(ITEMS_JSON_PATH, 'r', encoding='utf-8') as f:
            items_data = json.load(f)
            for item_info in items_data.values():
                name = item_info.get('name')
                if name and item_info.get('icon'):
                    known_icons.add(name.lower())
        logger.info(f"Loaded {len(known_icons)} known items from items-complete.json.")
    else:
        logger.warning(f"items-complete.json not found at {ITEMS_JSON_PATH}. All missing icons will be downloaded.")

    # 3. Load existing TOML to preserve counts > 0 and preserve the settings header
    kept_counts = []
    header_lines = []
    if TOML_PATH.exists():
        with open(TOML_PATH, 'rb') as f:
            existing_toml = tomllib.load(f)
        
        for ic in existing_toml.get('initial_counts', []):
            if int(ic.get('count', 0)) > 0:
                kept_counts.append(ic)
        logger.info(f"Preserved {len(kept_counts)} historical items with counts > 0 (discarded 0s).")

        # Extract the exact header text (everything before initial_counts) to preserve dynamic settings and comments
        with open(TOML_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                # Stop at the functional TOML variables instead of relying on a fragile comment string
                if line.strip().startswith('initial_counts') or line.strip().startswith('[[groups]]'):
                    break
                header_lines.append(line)
            
    # Fallback default settings if header is empty or file doesn't exist
    if not header_lines:
        header_lines = [
            "# --- Settings ---\n",
            'other_group_name = "Miscellaneous Drops"\n',
            'default_group_sort = "config"\n',
            'default_item_sort = "config"\n\n',
            "# --- Filtering Rules ---\n",
            "exclude_rules = []\n\n",
            "# --- Initial Counts ---\n"
        ]
    
    # 4. Scrape the Wiki
    logger.info(f"Fetching live Collection Log from {WIKI_URL}...")
    headers = {"User-Agent": "OSRS Clan System ETL - Collection Log Sync Script"}
    response = requests.get(WIKI_URL, headers=headers)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.content, "html.parser")
    
    groups = []
    current_group_title = None
    
    # Find all headings and tables in the document sequentially
    for element in soup.find_all(['h2', 'h3', 'h4', 'h5', 'table']):
        
        if element.name in ['h2', 'h3', 'h4', 'h5']:
            headline = element.find(class_='mw-headline')
            if headline:
                text = headline.get_text(strip=True)
            else:
                text = element.get_text(strip=True)
            
            # Clean up the text (remove [edit] tags if they got caught)
            text = re.sub(r'\[edit\]', '', text, flags=re.IGNORECASE).strip()
            
            # We want to ignore major category headings and focus on the sub-headings (e.g., "Abyssal Sire")
            ignore_list = ["contents", "bosses", "raids", "clues", "minigames", "other", "navigation menu", "personal search"]
            if text.lower() in ignore_list:
                continue
                
            # Stop parsing entirely when we hit Duplicate entries to avoid parsing footer tables
            if text.lower() == "duplicate entries":
                break
                
            current_group_title = text
                
        elif element.name == 'table' and 'wikitable' in element.get('class', []):
            if not current_group_title:
                continue
                
            # Filter out summary tables (they usually have "Category" in the first row)
            first_row_text = element.find('tr').get_text(strip=True).lower() if element.find('tr') else ""
            if "category" in first_row_text and ("bosses" in first_row_text or "raids" in first_row_text):
                continue
                
            # Parse the item cells in the wikitable
            current_group_items = []
            for td in element.find_all(['td', 'th']):
                img_tag = td.find('img')
                if not img_tag:
                    continue
                    
                img_url = img_tag.get('src') or img_tag.get('data-src')
                
                item_name = None
                links = td.find_all('a')
                for a in links:
                    link_text = a.get_text(strip=True)
                    if link_text:
                        item_name = link_text
                        break
                
                if item_name and img_url:
                    if item_name not in current_group_items:
                        current_group_items.append(item_name)
                        
                        # 5. Icon Management
                        if item_name.lower() not in known_icons:
                            webp_filename = get_safe_filename(item_name)
                            webp_path = CUSTOM_ICON_DIR / webp_filename
                            
                            if not webp_path.exists():
                                logger.info(f"Downloading missing icon: {item_name}...")
                                try:
                                    # Ensure full URL
                                    if img_url.startswith('/'):
                                        full_img_url = WIKI_BASE + img_url
                                    else:
                                        full_img_url = img_url
                                        
                                    img_resp = requests.get(full_img_url, headers=headers)
                                    img_resp.raise_for_status()
                                    
                                    image = Image.open(BytesIO(img_resp.content))
                                    if image.mode != 'RGBA':
                                        image = image.convert('RGBA')
                                    image.save(webp_path, "WEBP")
                                except Exception as e:
                                    logger.error(f"Failed to download/convert icon for {item_name}: {e}")

            if current_group_items:
                # Save the group
                groups.append({"title": current_group_title, "items": current_group_items})
                # Clear the title so subsequent unrelated tables don't get merged into it
                current_group_title = None

    logger.info(f"Successfully parsed {len(groups)} Collection Log groups from the Wiki.")

    # 6. Write the updated TOML
    with open(TOML_OUT_PATH, 'w', encoding='utf-8') as f:
        # Write preserved settings header
        for line in header_lines:
            f.write(line)
            
        f.write("initial_counts = [\n")
        for ic in kept_counts:
            safe_name = ic.get('name', '').replace('"', '\\"')
            f.write(f'    {{ name = "{safe_name}", count = {ic.get("count", 0)} }},\n')
        f.write("]\n\n")
        
        f.write("# --- Item Groups ---\n")
        for group in groups:
            f.write("[[groups]]\n")
            safe_title = group["title"].replace('"', '\\"')
            f.write(f'title = "{safe_title}"\n')
            f.write("items = [\n")
            for item in group["items"]:
                safe_item = item.replace('"', '\\"')
                f.write(f'    "{safe_item}",\n')
            f.write("]\n\n")

    logger.success(f"Finished! Cleaned TOML successfully saved to {TOML_OUT_PATH.name}. Please review and rename it to replace the original.")

if __name__ == "__main__":
    main()