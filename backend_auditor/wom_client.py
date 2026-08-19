import os
import json
import time
import requests
from urllib.parse import quote
from loguru import logger
from constants import SHARED_DATA_DIR

class WomClient:
    def __init__(self, cache_dir=None, use_cache=True, cache_ttl=None):
        self.base_url = 'https://api.wiseoldman.net/v2'
        self.headers = {'User-Agent': os.getenv('WOM_USER_AGENT', 'OSRS Clan Management Tool')}

        api_key = os.getenv('WOM_API_KEY')
        if api_key:
            self.headers['x-api-key'] = api_key
            self.base_delay = 0.7  # ~85 requests per minute
        else:
            self.base_delay = 3.5  # ~17 requests per minute

        self.cache_dir = cache_dir if cache_dir else str(SHARED_DATA_DIR / 'caches')
        self.cache_file = os.path.join(self.cache_dir, 'wom_cache.json')
        self.use_cache = use_cache
        
        # Granular Cache TTL Configurations (Defaults: Group=5h, Player Min=3d, Player Max=7d, Batch=9%)
        fallback_ttl = cache_ttl if cache_ttl is not None else 18000
        self.group_ttl = int(os.getenv('WOM_GROUP_CACHE_TTL_SECONDS', os.getenv('WOM_CACHE_TTL_SECONDS', fallback_ttl)))
        self.player_min_ttl = int(os.getenv('WOM_PLAYER_MIN_CACHE_TTL_SECONDS', 259200))
        self.player_max_ttl = int(os.getenv('WOM_PLAYER_MAX_CACHE_TTL_SECONDS', 604800))
        self.player_batch_percent = float(os.getenv('WOM_PLAYER_BATCH_PERCENT', 0.09))
        self.cache_ttl = self.group_ttl

        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
            
        self.cache = self._load_cache()
        
    def clear_cache(self):
        """Completely wipes the local WOM cache."""
        self.cache = {}
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
        logger.info("WOM Cache has been forcibly cleared.")

    def clear_group_cache(self):
        """Clears only the group-related cache keys from WOM cache."""
        keys_to_remove = [k for k in self.cache.keys() if k.startswith("group_")]
        for k in keys_to_remove:
            del self.cache[k]
        self._save_cache()
        logger.info(f"WOM Group Cache cleared ({len(keys_to_remove)} keys removed).")

    def get_cache_timestamp(self, cache_key):
        """Returns the unix timestamp of cached key, or 0 if missing/uncached."""
        if cache_key in self.cache:
            return self.cache[cache_key].get('timestamp', 0)
        return 0

    def _load_cache(self):
        if self.use_cache and os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load cache: {e}")
        return {}

    def _save_cache(self):
        if self.use_cache:
            try:
                with open(self.cache_file, 'w') as f:
                    json.dump(self.cache, f)
            except Exception as e:
                logger.error(f"Failed to save cache: {e}")

    def get(self, endpoint, cache_key=None, force_refresh=False, ttl=None):
        effective_ttl = ttl if ttl is not None else self.group_ttl
        if cache_key and self.use_cache and not force_refresh:
            if cache_key in self.cache:
                cached = self.cache[cache_key]
                # Only return cache if it has not expired
                if time.time() - cached.get('timestamp', 0) < effective_ttl:
                    logger.info(f"WOM Cache Hit: '{cache_key}'")
                    return cached['data']

        url = f"{self.base_url}{endpoint}"
        for attempt in range(3):
            try:
                res = requests.get(url, headers=self.headers, timeout=10)
                logger.info(f"WOM API Request (Fresh) [Attempt {attempt+1}/3]: {endpoint} - Status: {res.status_code}")
                
                if res.status_code == 200:
                    data = res.json()
                    if cache_key and self.use_cache:
                        self.cache[cache_key] = {
                            'timestamp': time.time(),
                            'data': data
                        }
                        self._save_cache()
                    time.sleep(self.base_delay) # Padding to respect WOM API rate limits
                    return data
                elif res.status_code == 404:
                    time.sleep(self.base_delay)
                    return None
                elif res.status_code == 429:
                    if attempt == 0:
                        logger.warning("WOM API 429 Rate Limit hit. Pausing 15 seconds before retry 1...")
                        time.sleep(15)
                    elif attempt == 1:
                        logger.warning("WOM API 429 Rate Limit hit. Pausing 70 seconds before retry 2...")
                        time.sleep(70)
                    else:
                        raise Exception("WOM API returned 429 after max retries")
                else:
                    raise Exception(f"WOM API returned {res.status_code}")
            except Exception as e:
                if attempt == 2:
                    logger.error(f"WOM API request failed for {endpoint}: {e}")
                    raise
                elif "429" not in str(e):
                    # Catch connection/timeout errors and apply the same staggered retry logic
                    if attempt == 0:
                        logger.warning(f"WOM API connection error: {e}. Retrying in 15 seconds...")
                        time.sleep(15)
                    elif attempt == 1:
                        logger.warning(f"WOM API connection error: {e}. Retrying in 70 seconds...")
                        time.sleep(70)

    def post(self, endpoint, body=None):
        url = f"{self.base_url}{endpoint}"
        for attempt in range(3):
            try:
                res = requests.post(url, headers=self.headers, json=body, timeout=10)
                logger.info(f"WOM API POST Request [Attempt {attempt+1}/3]: {endpoint} - Status: {res.status_code}")
                
                if res.status_code in (200, 201):
                    time.sleep(self.base_delay)
                    try:
                        return res.json()
                    except ValueError:
                        return True
                elif res.status_code == 429:
                    if attempt == 0:
                        logger.warning("WOM API 429 Rate Limit hit on POST. Pausing 15 seconds before retry 1...")
                        time.sleep(15)
                    elif attempt == 1:
                        logger.warning("WOM API 429 Rate Limit hit on POST. Pausing 70 seconds before retry 2...")
                        time.sleep(70)
                    else:
                        raise Exception("WOM API returned 429 after max retries")
                elif res.status_code in (400, 404):
                    logger.warning(f"WOM API POST rejected for {endpoint} - Status: {res.status_code}, Message: {res.text}")
                    time.sleep(self.base_delay)
                    return None
                else:
                    raise Exception(f"WOM API POST returned {res.status_code}")
            except Exception as e:
                if attempt == 2:
                    logger.error(f"WOM API POST request failed for {endpoint}: {e}")
                    raise
                elif "429" not in str(e):
                    if attempt == 0:
                        logger.warning(f"WOM API connection error on POST: {e}. Retrying in 15 seconds...")
                        time.sleep(15)
                    elif attempt == 1:
                        logger.warning(f"WOM API connection error on POST: {e}. Retrying in 70 seconds...")
                        time.sleep(70)
