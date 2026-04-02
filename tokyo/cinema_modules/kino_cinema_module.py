
"""
kino_cinema_module.py
Scraper for Kino Cinéma (Shinjuku & Tachikawa).
Scrapes today's schedule from the main page and fetches movie details.
"""

import re
import sys
import datetime
from typing import List, Dict, Optional
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

# Constants
BASE_URL = "https://kinocinema.jp"
LOCATIONS = {
    "shinjuku": "kino cinéma新宿",
    "tachikawa": "kino cinéma立川髙島屋S.C.館",
}

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    try:
        resp = requests.get(url, timeout=10, verify=False)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"ERROR [Kino Cinema]: Failed to fetch {url} - {e}", file=sys.stderr)
        return None

def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def parse_detail_page(url: str) -> Dict:
    """
    Fetches detail page to extract Director, Year, Runtime, Country.
    """
    soup = fetch_soup(url)
    details = {
        "director": None,
        "year": None,
        "country": None,
        "runtime_min": None,
        "original_title": None,
    }
    if not soup:
        return details

    # Runtime and Year (in main visual info)
    # <div class="detail-main-visual__date">2025/08公開</div>
    date_div = soup.select_one(".detail-main-visual__date")
    if date_div:
        date_text = clean_text(date_div.get_text())
        m = re.search(r"(\d{4})", date_text)
        if m:
            # Guard: ignore if followed by month or 'Release' (公開)
            suffix_check = date_text[m.end():]
            if not re.match(r"[/年]\d+月", suffix_check) and "公開" not in suffix_check:
                details["year"] = m.group(1)

    # <span class="detail-main-visual__time">175分</span>
    time_span = soup.select_one(".detail-main-visual__time")
    if time_span:
        time_text = clean_text(time_span.get_text())
        m = re.search(r"(\d+)", time_text)
        if m:
            details["runtime_min"] = m.group(1)

    # Director and others in .movie-info
    # <section class="movie-info">
    #   <h5 class="heading-tertiary">監督</h5><p>李 相日</p>
    info_section = soup.select_one(".movie-info")
    if info_section:
        current_header = None
        for child in info_section.children:
            if child.name == "h5":
                current_header = clean_text(child.get_text())
            elif child.name == "p" and current_header:
                content = clean_text(child.get_text())
                if "監督" in current_header:
                    details["director"] = content
                elif "原題" in current_header:
                    details["original_title"] = content
                elif "製作国" in current_header or "国" in current_header: # Guessing header name
                    # Only if header explicitly says Country.
                    # The sample didn't show country header, but if it appears:
                    if len(content) < 20: # Sanity check
                        details["country"] = content
                current_header = None # Reset

    return details

def scrape_location(location_slug: str, cinema_name_jp: str) -> List[Dict]:
    url = f"{BASE_URL}/{location_slug}/"
    print(f"INFO [Kino Cinema]: Scraping {cinema_name_jp} ({url})")
    soup = fetch_soup(url)
    if not soup:
        return []

    # Get today's date
    today = datetime.date.today()
    date_text_iso = today.isoformat() # e.g. "2026-01-14"

    # Find the active schedule container
    # The HTML structure seems to have multiple .schedule__item but usually only the current day is populated in the initial HTML?
    # Actually, the user's snippet showed:
    # <div class="schedule__item"> ... content ... </div> (Implicitly active?)
    # or <div class="schedule__item -active">?
    # I'll look for ALL .schedule__item that contain .schedule__movie.
    
    schedule_items = soup.select(".schedule__item")
    
    # We need to figure out WHICH day corresponds to which item if there are multiple populated.
    # The day buttons have index.
    # <li class="schedule__day-btn -current"> matches the active item index?
    # Usually tabs work by index.
    # But if only one is populated (as I suspected from curl output), I can just scrape whatever I find.
    # However, to be safe, let's assume the FIRST populated item corresponds to the FIRST button (Today).
    
    # Let's find the first item with movies.
    target_item = None
    for item in schedule_items:
        if item.select(".schedule__movie"):
            target_item = item
            break
    
    if not target_item:
        print(f"WARN [Kino Cinema]: No schedule found on page for {location_slug}.")
        return []

    # Parse movies
    results = []
    
    # Cache detail pages to avoid refetching
    detail_cache = {}

    for movie_div in target_item.select(".schedule__movie"):
        title_tag = movie_div.select_one(".schedule__title a")
        if not title_tag:
            # Maybe title is just text?
            title_tag = movie_div.select_one(".schedule__title")
        
        if not title_tag:
            continue

        movie_title = clean_text(title_tag.get_text())
        detail_rel_url = title_tag.get("href") if title_tag.name == "a" else None
        
        # Parse screens and times
        # A movie can have multiple screens listed?
        # Structure: .schedule__movie > .schedule__screen > ul > li
        
        screens = movie_div.select(".schedule__screen")
        for screen_div in screens:
            screen_name_tag = screen_div.select_one(".schedule__screen-name")
            screen_name = clean_text(screen_name_tag.get_text()) if screen_name_tag else ""
            # e.g. "THEATER 1 294席" -> "THEATER 1"
            screen_name = re.sub(r"\s*\d+席.*", "", screen_name).strip()

            for li in screen_div.select("ul.schedule__time-selecter li"):
                # Times: <em class="schedule__start-time">12:20</em>
                start_time_tag = li.select_one(".schedule__start-time")
                if not start_time_tag:
                    continue
                
                showtime = clean_text(start_time_tag.get_text())
                if not re.match(r"\d{1,2}:\d{2}", showtime):
                    continue

                # Details
                details = {}
                if detail_rel_url:
                    full_detail_url = urljoin(BASE_URL, detail_rel_url)
                    if full_detail_url not in detail_cache:
                        print(f"INFO [Kino Cinema]: Fetching details for {movie_title}")
                        detail_cache[full_detail_url] = parse_detail_page(full_detail_url)
                    details = detail_cache[full_detail_url]
                
                results.append({
                    "cinema_name": cinema_name_jp,
                    "movie_title": movie_title,
                    "movie_title_en": details.get("original_title"),
                    "date_text": date_text_iso,
                    "showtime": showtime,
                    "screen_name": screen_name,
                    "director": details.get("director"),
                    "year": details.get("year"),
                    "country": details.get("country"),
                    "runtime_min": details.get("runtime_min"),
                    "detail_page_url": full_detail_url if detail_rel_url else None,
                    "purchase_url": None # Could extract from <a> in li if present
                })

    return results

def scrape_kino_cinema() -> List[Dict]:
    all_data = []
    for slug, name in LOCATIONS.items():
        all_data.extend(scrape_location(slug, name))
    return all_data

if __name__ == "__main__":
    data = scrape_kino_cinema()
    print(f"Found {len(data)} showings.")
    if data:
        print(data[0])
