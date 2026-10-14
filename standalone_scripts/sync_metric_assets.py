"""
sync_metric_assets.py

Downloads and optimizes assets for OSRS metrics (skills, bosses, activities):
1. Small 32x32 sprite icons from Wise Old Man CDN -> shared_config/assets/metric_icons/{metric}_icon.webp
2. Larger transparent content artwork from OSRS Wiki MediaWiki API ->
   - shared_config/assets/content_art/raw/{metric}_raw.png
   - shared_config/assets/content_art/card/{metric}_card.webp (~8-12 KB)

Features:
- Respects 1.2s delay for Wiki API requests.
- Uses configured user_agent from secrets.toml.
- 30-day retry cooldown on failed lookups in asset_sync_state.json.
- Skips already-downloaded assets for 0ms execution on rerun.
"""

import os
import sys
import time
import json
import re
from pathlib import Path
from io import BytesIO
import requests
from PIL import Image

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from loguru import logger

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SHARED_CONFIG_DIR = Path(os.getenv("SHARED_CONFIG_DIR", PROJECT_ROOT / "shared_config"))
SHARED_SECRETS_DIR = Path(os.getenv("SHARED_SECRETS_DIR", PROJECT_ROOT / "shared_secrets"))
SHARED_DATA_DIR = Path(os.getenv("SHARED_DATA_DIR", PROJECT_ROOT / "shared_data"))

ASSETS_DIR = SHARED_CONFIG_DIR / "assets"
METRIC_ICONS_DIR = ASSETS_DIR / "metric_icons"
CONTENT_ART_RAW_DIR = ASSETS_DIR / "content_art" / "raw"
CONTENT_ART_CARD_DIR = ASSETS_DIR / "content_art" / "card"
STATE_FILE = ASSETS_DIR / "asset_sync_state.json"
WOM_STATS_FILE = SHARED_DATA_DIR / "exports" / "wom_group_stats.json"

# Ensure directories exist
METRIC_ICONS_DIR.mkdir(parents=True, exist_ok=True)
CONTENT_ART_RAW_DIR.mkdir(parents=True, exist_ok=True)
CONTENT_ART_CARD_DIR.mkdir(parents=True, exist_ok=True)

WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"
WOM_CDN_BASE = "https://wiseoldman.net/img/metrics"

# Special metric-to-wiki title overrides
WIKI_TITLE_OVERRIDES = {
    # Raids & complex names
    "chambers_of_xeric": "Chambers of Xeric logo",
    "chambers_of_xeric_cm": "Chambers of Xeric logo",
    "theatre_of_blood": "Theatre of Blood logo",
    "theatre_of_blood_hard_mode": "Theatre of Blood logo",
    "tombs_of_amascut": "Tombs of Amascut logo",
    "tombs_of_amascut_expert": "Tombs of Amascut logo",
    "barrows_chests": "Barrows Chest",
    "gauntlet": "Crystalline Hunllef",
    "corrupted_gauntlet": "Corrupted Hunllef",
    "tzkal_zuk": "TzKal-Zuk",
    "tztok_jad": "TzTok-Jad",
    "the_leviathan": "The Leviathan",
    "the_whisperer": "The Whisperer",
    "duke_sucellus": "Duke Sucellus",
    "vardorvis": "Vardorvis",
    "sol_heredit": "Sol Heredit",
    "colosseum": "Fortis Colosseum",
    "lunar_chests": "Moons of Peril",
    "hueycoatl": "The Hueycoatl",
    "amoxliatl": "Amoxliatl",
    "yama": "Yama",
    # Skills
    "overall": "Stats icon",
    "attack": "Attack icon",
    "defence": "Defence icon",
    "strength": "Strength icon",
    "hitpoints": "Hitpoints icon",
    "ranged": "Ranged icon",
    "prayer": "Prayer icon",
    "magic": "Magic icon",
    "cooking": "Cooking icon",
    "woodcutting": "Woodcutting icon",
    "fletching": "Fletching icon",
    "fishing": "Fishing icon",
    "firemaking": "Firemaking icon",
    "crafting": "Crafting icon",
    "smithing": "Smithing icon",
    "mining": "Mining icon",
    "herblore": "Herblore icon",
    "agility": "Agility icon",
    "thieving": "Thieving icon",
    "slayer": "Slayer icon",
    "farming": "Farming icon",
    "runecraft": "Runecraft icon",
    "hunter": "Hunter icon",
    "construction": "Construction icon",
    # Activities
    "clue_scrolls_all": "Clue scroll",
    "clue_scrolls_beginner": "Clue scroll (beginner)",
    "clue_scrolls_easy": "Clue scroll (easy)",
    "clue_scrolls_medium": "Clue scroll (medium)",
    "clue_scrolls_hard": "Clue scroll (hard)",
    "clue_scrolls_elite": "Clue scroll (elite)",
    "clue_scrolls_master": "Clue scroll (master)",
    "last_man_standing": "Last Man Standing logo",
    "soul_wars_zeal": "Soul Wars logo",
    "guardians_of_the_rift": "Guardians of the Rift logo"
}


def load_user_agent():
    """Loads configured Wiki user agent from secrets.toml."""
    secrets_path = SHARED_SECRETS_DIR / "secrets.toml"
    if secrets_path.exists():
        try:
            with open(secrets_path, "rb") as f:
                data = tomllib.load(f)
                ua = data.get("api_settings", {}).get("user_agent")
                if ua and "YOUR_APP_NAME" not in ua:
                    return ua
        except Exception:
            pass
    return "AU OSRS Discord Dashboard - Discord: bourkes"


def load_state():
    """Loads the 30-day lookup cooldown state."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"failed_lookups": {}}


def save_state(state):
    """Saves state atomically."""
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def get_metrics_list():
    """Reads metric keys from wom_group_stats.json, or returns fallback list."""
    if WOM_STATS_FILE.exists():
        try:
            with open(WOM_STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            leaders = data.get("data", {}).get("metricLeaders", {})
            metrics = set()
            for cat_data in leaders.values():
                if isinstance(cat_data, dict):
                    metrics.update(cat_data.keys())
            if metrics:
                logger.info(f"Loaded {len(metrics)} metrics from wom_group_stats.json")
                return sorted(metrics)
        except Exception as e:
            logger.warning(f"Could not load metrics from stats file: {e}")
    return []


def download_wom_sprite(metric: str) -> bool:
    """Downloads 32x32 sprite icon from WOM CDN and converts to WebP."""
    out_path = METRIC_ICONS_DIR / f"{metric}_icon.webp"
    if out_path.exists():
        return True

    url = f"{WOM_CDN_BASE}/{metric}.png"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            img.save(out_path, format="WEBP")
            logger.info(f"Downloaded WOM sprite for '{metric}' -> {out_path.name}")
            return True
        else:
            logger.warning(f"WOM CDN returned {r.status_code} for {metric}")
            return False
    except Exception as e:
        logger.error(f"Failed to download WOM sprite for {metric}: {e}")
        return False


def query_wiki_image(title: str, user_agent: str) -> tuple[str | None, bytes | None]:
    """
    Queries MediaWiki API using prop=pageimages for the article's official lead image.
    This automatically handles naming suffixes (e.g. Zulrah (serpentine), logos, detail icons).
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageimages",
        "pithumbsize": 400,
        "format": "json"
    }
    headers = {"User-Agent": user_agent}
    try:
        r = requests.get(WIKI_API_URL, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            pages = r.json().get("query", {}).get("pages", {})
            for page_info in pages.values():
                thumb = page_info.get("thumbnail", {})
                source_url = thumb.get("source")
                if source_url:
                    img_res = requests.get(source_url, headers=headers, timeout=15)
                    if img_res.status_code == 200:
                        return source_url, img_res.content
    except Exception as e:
        logger.warning(f"Wiki pageimages query failed for '{title}': {e}")
    return None, None



def download_wiki_artwork(metric: str, user_agent: str, state: dict) -> bool:
    """Downloads transparent character artwork from OSRS Wiki and generates card WebP."""
    raw_path = CONTENT_ART_RAW_DIR / f"{metric}_raw.png"
    card_path = CONTENT_ART_CARD_DIR / f"{metric}_card.webp"

    if card_path.exists() and raw_path.exists():
        return True

    # Check 30-day cooldown
    failed_lookups = state.setdefault("failed_lookups", {})
    last_fail = failed_lookups.get(metric, {}).get("last_attempt", 0)
    if (time.time() - last_fail) < (30 * 86400):
        return False  # Cooldown active

    # Determine titles to attempt
    candidate_titles = []
    if metric in WIKI_TITLE_OVERRIDES:
        candidate_titles.append(WIKI_TITLE_OVERRIDES[metric])
    
    # Generic format: e.g. "abyssal_sire" -> "Abyssal Sire"
    pretty_title = metric.replace("_", " ").title()
    if pretty_title not in candidate_titles:
        candidate_titles.append(pretty_title)

    img_data = None
    for candidate in candidate_titles:
        time.sleep(1.2)  # Polite throttle
        _, content = query_wiki_image(candidate, user_agent)
        if content:
            img_data = content
            break

    if img_data:
        try:
            # Save raw PNG archive
            with open(raw_path, "wb") as f:
                f.write(img_data)
            
            # Create optimized card WebP (max 350x350)
            img = Image.open(BytesIO(img_data))
            img.thumbnail((350, 350), Image.Resampling.LANCZOS)
            img.save(card_path, format="WEBP", quality=85)
            logger.info(f"Generated card art for '{metric}' -> {card_path.name} ({card_path.stat().st_size} bytes)")
            
            # Remove from failed lookups if previously there
            failed_lookups.pop(metric, None)
            return True
        except Exception as e:
            logger.error(f"Error processing image for {metric}: {e}")
            return False
    else:
        logger.info(f"No Wiki art found for '{metric}'. Entering 30-day cooldown.")
        failed_lookups[metric] = {
            "last_attempt": time.time(),
            "reason": "not_found"
        }
        return False


def main():
    logger.info("Starting Metric Assets Synchronizer...")
    user_agent = load_user_agent()
    logger.info(f"Using User-Agent: {user_agent}")
    
    state = load_state()
    metrics = get_metrics_list()
    if not metrics:
        logger.warning("No metrics found to process. Please run backend_auditor first.")
        return

    logger.info(f"Processing assets for {len(metrics)} metrics...")
    
    wom_success = 0
    wiki_success = 0
    
    for idx, metric in enumerate(metrics, start=1):
        # 1. WOM 32x32 sprite
        if download_wom_sprite(metric):
            wom_success += 1
            
        # 2. OSRS Wiki Artwork
        if download_wiki_artwork(metric, user_agent, state):
            wiki_success += 1
            
        if idx % 15 == 0 or idx == len(metrics):
            logger.info(f"Progress: [{idx}/{len(metrics)}] - Icons: {wom_success}, Artwork: {wiki_success}")
            save_state(state)

    save_state(state)
    logger.success(f"Asset Sync Finished: {wom_success} sprite icons and {wiki_success} card artwork items verified on disk.")


if __name__ == "__main__":
    main()
