import json
import os
import sys
import requests

# Add current dir to path to import main_scraper
sys.path.append(os.path.abspath('london-cinema-scrapers'))
from main_scraper import enrich_listings_with_tmdb_links, load_tmdb_cache

def reprocess():
    api_key = "da2b1bc852355f12a86dd5e7ec48a1ee"
    file_path = 'london-cinema-scrapers/data/showtimes.json'
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Filter to only films without tmdb_id
    # Actually, main_scraper.enrich_listings_with_tmdb_links handles checking cache
    # But we want to force it to retry things that previously failed (marked as None in cache)
    
    cache = load_tmdb_cache()
    
    # Optional: Clear 'None' entries in cache to force re-search with new cleaning rules
    keys_to_retry = [k for k, v in cache.items() if v is None]
    print(f"Clearing {len(keys_to_retry)} 'Not Found' entries from cache to retry with new logic...")
    for k in keys_to_retry:
        del cache[k]

    session = requests.Session()
    
    # We pass the full data; the function will process everything but only API search for missing ones
    updated_data = enrich_listings_with_tmdb_links(data, cache, session, api_key)

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(updated_data, f, ensure_ascii=False, indent=2)
    
    print("\nEnrichment complete. Updated showtimes.json")

if __name__ == "__main__":
    reprocess()
