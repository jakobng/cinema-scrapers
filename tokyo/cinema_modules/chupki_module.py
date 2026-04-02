# -*- coding: utf-8 -*-
"""
chupki_module.py
Scraper for Cinema Chupki Tabata, conforming to the standard format. (Final Version)

This version adds splitting of combined Japanese and English titles.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# --- Constants ---
CINEMA_NAME = "CINEMA Chupki TABATA"
BASE_URL = "https://chupki.jpn.org/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}
THIS_YEAR = dt.date.today().year

# --- Helper Functions ---

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch page {url}: {e}", file=sys.stderr)
        return None

def _parse_and_split_title(text: Optional[str]) -> tuple[str, str]:
    """
    Parses a movie title and splits it into Japanese and English parts if combined.
    Removes brackets and trailing notes.
    e.g. "『Movie（US）』 ＊Note" -> "Movie", ""
    e.g. "Underground アンダーグラウンド" -> "アンダーグラウンド", "Underground"
    """
    if not text:
        return "", ""

    # Remove content in full-width parentheses, e.g.（アメリカ）
    text = re.sub(r'（[^）]+）', '', text)
    # Remove special brackets
    text = text.replace("『", "").replace("』", "")
    # Remove notes like *6/26のみ 17:10-
    text = re.sub(r'\s+[＊✳︎].*$', '', text.strip())
    # Standard whitespace normalization
    text = " ".join(text.strip().split())

    # Attempt to split English and Japanese titles
    # Assuming English title often comes first or is separated by a space/full-width space
    # Look for a pattern like "English Title Japanese Title"
    match = re.match(r"([a-zA-Z0-9\s.,'&:-]+?)\s+([\u3000-\u9FFF\u3040-\u309F\u30A0-\u30FF\s]+)", text)
    if match:
        english_title = match.group(1).strip()
        japanese_title = match.group(2).strip()
        return japanese_title, english_title
    else:
        # If no clear split, assume the whole thing is the Japanese title, and English is empty
        return text, ""


# --- Scraping Logic ---

def _parse_movie_details(soup: BeautifulSoup) -> Dict[str, Dict]:
    """
    Parses all movie detail boxes on the page to build a cache.
    Keyed by cleaned movie title.
    """
    details_cache = {}
    movie_boxes = soup.select("section.movie .movie__box")
    print(f"INFO: [{CINEMA_NAME}] Found {len(movie_boxes)} movie detail boxes.", file=sys.stderr)

    for box in movie_boxes:
        title_tag = box.select_one("h4.movie__ttl")
        if not title_tag:
            continue

        full_title_text = title_tag.get_text()
        japanese_title, english_title = _parse_and_split_title(full_title_text)
        
        # Use the Japanese title as the key for the cache
        title_key = japanese_title 
        if not title_key or title_key in details_cache:
            continue

        details = {
            "movie_title": japanese_title,
            "movie_title_en": english_title,
            "director": None, "year": None, "runtime_min": None,
            "country": None, "synopsis": None, "purchase_url": None,
            "detail_page_url": BASE_URL
        }

        # Parse year, runtime, country from "2024年／131分／日本／ドキュメンタリー"
        if etc_tag := box.select_one("div.movie_etc"):
            etc_text = etc_tag.get_text(strip=True)
            parts = re.split(r'[／/]', etc_text)
            
            if m := re.search(r"(\d{4})", etc_text): details["year"] = m.group(1)
            # Ensure runtime is a number only
            if m := re.search(r"(\d+)\s*分", etc_text): details["runtime_min"] = m.group(1)
            elif m := re.search(r"(\d+)", etc_text): details["runtime_min"] = m.group(1)


            # Find country by excluding known non-country terms
            for part in parts:
                part = part.strip()
                # Check for specific patterns that indicate it's not a country name
                if not any(x in part for x in ['年', '分', '製作', 'ドキュメンタリー', 'カラー', 'モノクロ']) and not part.isdigit() and len(part) > 1:
                     # It's likely the country name
                    details["country"] = part.replace('合作','').strip()
                    break

        if info_tag := box.select_one("div.movie_info"):
            synopsis_text = " ".join(info_tag.get_text(separator="\n", strip=True).split())
            details["synopsis"] = synopsis_text
            # More precise regex for director: captures Japanese name, avoiding leading descriptive text
            # Looks for "氏名監督" or "監督 氏名" or "氏名 監督"
            director_match = re.search(r"(?:監督\s*|)([\u3040-\u30FF\u4E00-\u9FFF\s\・\ー\(\)「」『』]{2,20})\s*監督", synopsis_text)
            if director_match:
                # Take the captured group, clean up extra spaces and specific characters often found near names
                director_name = director_match.group(1).strip()
                # Remove common descriptive terms that might get caught
                director_name = re.sub(r"に真摯に向き合う|陶を受けた|初監督作品|による", "", director_name).strip()
                details["director"] = director_name
            else: # Fallback to a broader search for "監督" followed by a name if the primary regex fails
                 # This might still catch extra text if not carefully crafted
                if fallback_dir_match := re.search(r"監督[：:]*\s*([^\s／/・|,\n]+)", synopsis_text):
                    details["director"] = fallback_dir_match.group(1).strip()


        if btn_tag := box.select_one("a.movie__btn"):
            details["purchase_url"] = btn_tag.get("href")

        details_cache[title_key] = details
        print(f"  ... Cached details for '{title_key}'", file=sys.stderr)

    return details_cache

def _parse_schedule(soup: BeautifulSoup, details_cache: Dict, max_days: int) -> List[Dict]:
    """
    Parses the main timetable and merges with cached details.
    """
    timetable = soup.find("div", class_="timetable")
    if not timetable: return []

    header = timetable.find("h3", class_="timetable__ttl")
    if not header: return []

    header_text = header.get_text(" ", strip=True)
    date_match = re.search(r"(\d{1,2})月(\d{1,2})日.*?([～〜])\s*(?:(\d{1,2})月)?(\d{1,2})日", header_text)
    if not date_match: return []

    start_m_str, start_d_str, _, end_m_str, end_d_str = date_match.groups()
    start_month, start_day = int(start_m_str), int(start_d_str)
    end_day = int(end_d_str)
    end_month = int(end_m_str) if end_m_str else start_month

    start_date = dt.date(THIS_YEAR, start_month, start_day)
    end_date = dt.date(THIS_YEAR, end_month, end_day)
    # Handle year rollover if end_date is in the next year
    if start_date > end_date and start_month > end_month:
        end_date = dt.date(THIS_YEAR + 1, end_month, end_day)
    elif start_date > end_date and start_month <= end_month: # same month, but end_day is smaller, implies next year
         end_date = dt.date(THIS_YEAR + 1, end_month, end_day)


    closed_days_str = re.search(r"(?:休映|休館).*?([\d,]+)", header_text)
    closed_days = {int(d) for d in closed_days_str.group(1).split(',')} if closed_days_str else set()

    valid_dates = []
    current_date = dt.date.today() #
    cutoff = current_date + dt.timedelta(days=max_days) #
    while current_date <= end_date and current_date < cutoff: #
        if start_date <= current_date and current_date.day not in closed_days: #
            valid_dates.append(current_date) #
        current_date += dt.timedelta(days=1) #

    print(f"INFO: [{CINEMA_NAME}] Found valid dates: {[d.isoformat() for d in valid_dates]}", file=sys.stderr) #

    showings = []
    table = timetable.find("table") #
    if not table: return [] #

    for row in table.find_all("tr"): #
        th = row.find("th"); td = row.find("td") #
        if not (th and td): continue #

        time_match = re.search(r"(\d{1,2}:\d{2})", th.get_text(strip=True)) #
        if not time_match: continue #
        showtime = time_match.group(1) #
        
        # Use the cleaned Japanese title from the timetable cell to match the cache
        # Need to clean it similar to how cache keys are made
        cell_text_for_key = " ".join(td.get_text().strip().split())
        title_key, _ = _parse_and_split_title(cell_text_for_key) # Use the same cleaning logic for the key
        
        details = details_cache.get(title_key) #
        if not details: #
            print(f"WARN: [{CINEMA_NAME}] No details found in cache for title: '{title_key}'", file=sys.stderr) #
            details = {} #

        for showing_date in valid_dates: #
            # Ensure movie_title and movie_title_en are pulled from `details` which has the split titles
            showings.append({ #
                "cinema_name": CINEMA_NAME, #
                "movie_title": details.get("movie_title", title_key), # Use the split Japanese title from details, fallback to cleaned cell text
                "movie_title_en": details.get("movie_title_en", ""), # Use the split English title from details
                "date_text": showing_date.isoformat(), #
                "showtime": showtime, #
                **{k: v for k, v in details.items() if k not in ["movie_title", "movie_title_en"]}, # Add other details, excluding original title fields
            })

    return showings

def scrape_chupki(max_days: int = 14) -> List[Dict]:
    """
    Scrapes all movie showings and details from Cinema Chupki Tabata.
    """
    print(f"INFO: [{CINEMA_NAME}] Starting scrape...", file=sys.stderr) #
    soup = _fetch_soup(BASE_URL) #
    if not soup: return [] #

    details_cache = _parse_movie_details(soup) #
    showings = _parse_schedule(soup, details_cache, max_days) #
    
    showings.sort(key=lambda x: (x.get("date_text", ""), x.get("showtime", ""))) #

    print(f"INFO: [{CINEMA_NAME}] Scrape complete. Found {len(showings)} showings.", file=sys.stderr) #
    return showings #

# --- Main Execution ---

if __name__ == '__main__':
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8')

    all_showings = scrape_chupki() #

    if all_showings: #
        output_filename = f"chupki_showtimes.json" #
        output_path = Path(__file__).parent / output_filename #
        
        print(f"\nINFO: Writing {len(all_showings)} records to {output_path}...", file=sys.stderr) #
        with open(output_path, "w", encoding="utf-8") as f: #
            json.dump(all_showings, f, ensure_ascii=False, indent=2) #
        print(f"INFO: Successfully created {output_path}.", file=sys.stderr) #
        
        print("\n--- Sample of First Showing ---") #
        from pprint import pprint
        pprint(all_showings[0])
    else: #
        print(f"\nNo showings found for {CINEMA_NAME}.") #