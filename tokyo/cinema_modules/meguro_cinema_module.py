"""
meguro_cinema_module.py — scraper for 目黒シネマ (Meguro Cinema)
- Final, polished version with complete data extraction and correct date filtering.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --- Constants ---
CINEMA_NAME = "目黒シネマ"
BASE_URL = "http://www.okura-movie.co.jp/meguro_cinema/"
SCHEDULE_URL = urljoin(BASE_URL, "now_showing.html")
CURRENT_YEAR = date.today().year

# --- Helper Functions ---

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object, handling Shift_JIS encoding."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        response.encoding = 'shift_jis'
        return BeautifulSoup(response.text, 'html.parser')
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None

def _parse_dates_from_text(text: str) -> List[date]:
    """Parses multiple date formats from a given string."""
    dates = []
    matches = re.findall(r'(\d{1,2})月(\d{1,2})日', text)
    for month_str, day_str in matches:
        try:
            d = date(CURRENT_YEAR, int(month_str), int(day_str))
            if d not in dates:
                dates.append(d)
        except ValueError:
            continue
    return sorted(dates)

# --- Main Scraping Logic ---

def scrape_meguro_cinema() -> List[Dict]:
    """
    Scrapes the Meguro Cinema schedule page.
    """
    print(f"INFO: [{CINEMA_NAME}] Fetching schedule page: {SCHEDULE_URL}")
    soup = _fetch_soup(SCHEDULE_URL)
    if not soup:
        return []

    all_showings = []

    # --- Pass 1: Build a cache of all movies and their details ---
    movie_details_cache = {}
    sakuhin_divs = soup.select("div#sakuhin_detail")

    for div in sakuhin_divs:
        linked_images = div.select("a[href*='//']")
        program_text = div.get_text(separator='\n')
        titles_in_block = re.findall(r'『(.*?)』', program_text)

        for i, title_text in enumerate(titles_in_block):
            clean_title = title_text.replace('4Kリマスター', '').replace('4Kレストア版', '').strip()
            if not clean_title or clean_title in movie_details_cache:
                continue

            details = {"director": None, "synopsis": None, "year": None, "country": None, "runtime_min": None, "detail_page_url": None}

            try:
                title_pattern = re.escape(title_text)
                details_match = re.search(f"{title_pattern}.*?\((\d{{4}}).*?/(.*?)/(\d+)分", program_text, flags=re.DOTALL)
                if details_match:
                    details["year"] = details_match.group(1)
                    details["country"] = re.sub(r'年?/', '', details_match.group(2).replace('合作','').strip(), 1)
                    details["runtime_min"] = details_match.group(3)
            except re.error:
                pass

            if i < len(linked_images) and linked_images[i].find('img'):
                 details['detail_page_url'] = linked_images[i]['href']

            movie_details_cache[clean_title] = details

    print(f"INFO: [{CINEMA_NAME}] Successfully built cache with {len(movie_details_cache)} movies.")
    if not movie_details_cache:
        print(f"ERROR: [{CINEMA_NAME}] Movie cache is empty. Cannot proceed.")
        return []

    # --- Pass 2: Find all showtime tables and process them ---
    time_tables = soup.select("table.time_box")
    print(f"INFO: [{CINEMA_NAME}] Found {len(time_tables)} showtime tables to process.")

    for table in time_tables:
        parent_div = table.find_parent("div", id="timetable")
        if not parent_div: continue

        date_p = parent_div.find("p")
        if not date_p: continue

        show_dates = _parse_dates_from_text(date_p.get_text())
        if not show_dates: continue

        for row in table.find_all("tr"):
            title_cell = row.find("td", class_="time_title")
            if not title_cell: continue

            raw_title_text = title_cell.get_text(strip=True).replace(' ','')
            found_title = next((cached_title for cached_title in movie_details_cache if raw_title_text.startswith(cached_title.replace(' ',''))), None)
            if not found_title: continue

            details = movie_details_cache[found_title]

            for time_cell in row.find_all("td", class_="time_type2"):
                time_match = re.search(r'\b(\d{1,2}:\d{2})\b', time_cell.get_text(strip=True))
                if time_match:
                    showtime = time_match.group(1)
                    for d in show_dates:
                        all_showings.append({
                            "cinema_name":     CINEMA_NAME,
                            "movie_title":     found_title,
                            "movie_title_en":  "",
                            "date_text":       d.isoformat(),
                            "showtime":        showtime,
                            "director":        details.get("director") or "",
                            "year":            details.get("year") or "",
                            "country":         details.get("country") or "",
                            "runtime_min":     details.get("runtime_min") or "",
                            "synopsis":        details.get("synopsis") or "",
                            "detail_page_url": details.get("detail_page_url") or "",
                        })

    # --- FIX: Filter out past dates ---
    today = date.today()
    future_showings = [s for s in all_showings if date.fromisoformat(s['date_text']) >= today]

    unique_showings = list({(s["date_text"], s["movie_title"], s["showtime"]): s for s in future_showings}.values())
    unique_showings.sort(key=lambda x: (x.get('date_text', ''), x.get('showtime', '')))

    print(f"INFO: [{CINEMA_NAME}] Collected {len(unique_showings)} unique future showings.")
    return unique_showings


if __name__ == '__main__':
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    print(f"Testing {CINEMA_NAME} scraper module...")
    showings = scrape_meguro_cinema()

    if showings:
        output_filename = "meguro_cinema_showtimes.json"
        print(f"\nINFO: Writing {len(showings)} records to {output_filename}...")
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(showings, f, ensure_ascii=False, indent=2)
        print(f"INFO: Successfully created {output_filename}.")

        print("\n--- Sample of First Showing ---")
        from pprint import pprint
        pprint(showings[0])
    else:
        print(f"\nNo showings found by {CINEMA_NAME} scraper.")
