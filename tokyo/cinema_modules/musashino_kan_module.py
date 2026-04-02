"""
musashino_kan_module.py — scraper for Shinjuku Musashino‑kan

Revision #10 (Final, Final Fix)
───────────────────────────────────────────────────────────
* Corrected the check for the 'year/country' field to use a half-width
  slash, matching the normalized text it's searching within.
* This resolves the bug where the `year` was not being found despite the
  previous fix attempt.
* The scraper should now reliably capture all intended metadata.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# --- Constants ---
CINEMA_NAME = "新宿武蔵野館"
MAIN_SITE_URL = "https://shinjuku.musashino-k.jp/"
MOVIES_PAGE_URL = "https://shinjuku.musashino-k.jp/movies/"
SCHEDULE_PAGE_URL = "https://musashino.cineticket.jp/mk/theater/shinjuku/schedule"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

# --- Helper Functions ---

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return BeautifulSoup(r.content, "html.parser")
    except requests.RequestException as e:
        print(f"WARN: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None

def _clean(element: Optional[Tag | str]) -> str:
    """Extracts and normalizes whitespace from a BeautifulSoup element or string."""
    if element is None: return ""
    text = element.get_text(separator=' ', strip=True) if hasattr(element, 'get_text') else str(element)
    return ' '.join(unicodedata.normalize("NFKC", text).strip().split())

def _normalise_title(text: str) -> str:
    """Cleans movie titles by removing common prefixes and suffixes."""
    text = re.sub(r"^(?:【[^】]+】)+", "", text)
    text = re.sub(r"★.*$", "", text)
    text = text.replace('“', '「').replace('”', '」')
    
    # Aggressive suffix removal for TMDB matching
    remove_patterns = [
        r"\s*4K(?:デジタル)?(?:リマスター)?版?",
        r"\s*(?:デジタル)?リマスター版?",
        r"\s*ディレクターズ・カット版?",
        r"\s*完全版",
        r"\s*製作\d+周年記念.*",
    ]
    for pat in remove_patterns:
        text = re.sub(pat, "", text)
        
    return text.strip()

def _get_movie_detail_urls() -> Dict[str, str]:
    """
    Scrapes the main movies page to create a mapping of movie titles to their
    detail page URLs.
    """
    print(f"INFO: [{CINEMA_NAME}] Fetching movie list from {MOVIES_PAGE_URL}")
    movie_list_soup = _fetch_soup(MOVIES_PAGE_URL)
    if not movie_list_soup:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch the main movie list. Aborting.", file=sys.stderr)
        return {}

    movie_urls = {}
    for movie_article in movie_list_soup.select("article.movies.flex-item"):
        if link_tag := movie_article.find('a', href=True):
            url = link_tag['href']
            if title_tag := movie_article.select_one("h4.title"):
                title = _normalise_title(_clean(title_tag))
                movie_urls[title] = url
    
    print(f"INFO: [{CINEMA_NAME}] Found {len(movie_urls)} movies on the main list page.")
    return movie_urls

def _parse_movie_details(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """Parses the movie detail page to extract metadata."""
    details = {"director": None, "year": None, "country": None, "runtime_min": None, "synopsis": None}
    
    for dl in soup.find_all("dl"):
        dt = dl.find("dt")
        dd = dl.find("dd")
        if not dt or not dd: continue

        dt_text = _clean(dt)
        dd_text = _clean(dd)

        if "監督" in dt_text:
            details["director"] = dd_text
        # FINAL FIX: Check for the normalized string '製作年/製作国' (with a half-width slash)
        # because dt_text has already been passed through the _clean() function.
        elif "製作年/製作国" in dt_text:
            parts = dd_text.split('/')
            if len(parts) > 0 and (match := re.search(r'(\d{4})', parts[0])):
                details["year"] = match.group(1)
            if len(parts) > 1:
                details["country"] = parts[1].strip()
        elif "上映時間" in dt_text:
            if match := re.search(r'(\d+)時間(\d+)分', dd_text):
                h, m = map(int, match.groups())
                details["runtime_min"] = str(h * 60 + m)
            elif match := re.search(r'(\d+)分', dd_text):
                details["runtime_min"] = match.group(1)

    synopsis_parts = []
    if synopsis_container := soup.select_one("div.col.flex-item > div.module.module-text > div.wrapper > div.text-container > .text"):
        for p_tag in synopsis_container.find_all('p', recursive=False):
            synopsis_parts.append(_clean(p_tag))
    
    if synopsis_parts:
        details["synopsis"] = "\n".join(filter(None, synopsis_parts))
        
    return details

# --- Main Scraping Logic ---

def scrape_musashino_kan() -> List[Dict]:
    """Scrapes movie showtimes and details from the Musashino-kan website."""
    movie_to_url_map = _get_movie_detail_urls()
    if not movie_to_url_map:
        return []
        
    schedule_soup = _fetch_soup(SCHEDULE_PAGE_URL)
    if not schedule_soup:
        return []

    print(f"INFO: [{CINEMA_NAME}] Fetched schedule page: {SCHEDULE_PAGE_URL}")
    all_showings = []
    date_blocks = schedule_soup.find_all("div", id=re.compile(r"^dateJouei(\d{8})$"))
    print(f"INFO: [{CINEMA_NAME}] Found {len(date_blocks)} date blocks to process.")
    
    processed_details = {}

    for block in date_blocks:
        date_iso = datetime.strptime(block["id"][-8:], "%Y%m%d").date().isoformat()
        
        for panel in block.select("div.movie-panel"):
            title_tag = panel.select_one(".title-jp")
            if not title_tag: continue
            
            clean_title = _normalise_title(_clean(title_tag))
            
            detail_url = movie_to_url_map.get(clean_title)
            metadata = {"movie_title_en": None, "detail_page_url": detail_url}

            if detail_url:
                if detail_url not in processed_details:
                    print(f"INFO: [{CINEMA_NAME}] Scraping details for '{clean_title}' from {detail_url}")
                    detail_soup = _fetch_soup(detail_url)
                    processed_details[detail_url] = _parse_movie_details(detail_soup) if detail_soup else {}
                
                metadata.update(processed_details.get(detail_url, {}))

            for schedule_div in panel.select("div.movie-schedule"):
                showtime = _clean(schedule_div.select_one(".movie-schedule-begin"))
                if not showtime: continue

                all_showings.append({
                    "cinema_name": CINEMA_NAME, "movie_title": clean_title,
                    "date_text": date_iso, "showtime": showtime, **metadata,
                })

    unique_showings = list({(s["date_text"], s["movie_title"], s["showtime"]): s for s in all_showings}.values())
    unique_showings.sort(key=lambda x: (x.get('date_text', ''), x.get('showtime', '')))
    
    print(f"\nINFO: [{CINEMA_NAME}] Collected {len(unique_showings)} unique showings.")
    return unique_showings

# --- CLI Test Harness ---
if __name__ == '__main__':
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    showings = scrape_musashino_kan()
    if showings:
        output_filename = "musashino_kan_showtimes_updated.json"
        print(f"\nINFO: Writing {len(showings)} records to {output_filename}...")
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(showings, f, ensure_ascii=False, indent=2)
        print(f"INFO: Successfully created {output_filename}.")

        print("\n--- Sample of a successfully parsed movie (with year and URL) ---")
        from pprint import pprint
        
        for movie in showings:
            if movie.get('year') and movie.get('detail_page_url'):
                pprint(movie)
                break
        else:
            print("Could not find a movie with full details. Printing first available record:")
            if showings:
                pprint(showings[0])

    else:
        print(f"\nNo showings found by {CINEMA_NAME} scraper.")
