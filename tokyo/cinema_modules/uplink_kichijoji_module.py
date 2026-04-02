# -*- coding: utf-8 -*-
"""
uplink_kichijoji_module.py
Scraper for アップリンク吉祥寺 (Uplink Kichijoji), conforming to the standard format.

[FIX 10]: Final version.
- Removed the unreliable page-wide 'year' search. Year is now ONLY
  parsed from the spec block. (Fixes "宝島" "1952" bug).
- Added '\d\.\dc' to blocklist to fix "パリタクシー" "5.1c" bug.
"""

import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# --- Constants ---
CINEMA_NAME = "アップリンク吉祥寺"
SCHEDULE_URL = "https://joji.uplink.co.jp/schedule"
BASE_URL = "https://joji.uplink.co.jp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/5.0 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/5.0"
}

# --- Cache ---
_detail_cache: Dict[str, Dict[str, Optional[str]]] = {}


# --- Helper Functions ---

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        time.sleep(0.2) # Be polite
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch page {url}: {e}", file=sys.stderr)
        return None

def _clean_text(text: Optional[str]) -> str:
    """Normalizes whitespace for display text."""
    if not text: return ""
    return ' '.join(text.strip().split())

def _parse_date_from_header(date_str: str, year: int) -> Optional[dt.date]:
    """Parses date strings like '11.11火' from the schedule list header."""
    if match := re.match(r"(\d{1,2})\.(\d{1,2})", date_str):
        month, day = map(int, match.groups())
        try:
            return dt.date(year, month, day)
        except ValueError:
            return None
    return None

def _parse_detail_page(soup: BeautifulSoup, detail_url: str) -> Dict[str, Optional[str]]:
    """
    Scrapes the individual movie detail page for rich metadata.
    [FIX 10: Robust parsing]
    """
    details = {
        "movie_title": None, "movie_title_en": None, "director": None,
        "year": None, "runtime_min": None, "country": None,
        "synopsis": None, "detail_page_url": detail_url
    }

    # --- Titles ---
    if title_tag := soup.select_one("h1.single-header-heading"):
        if en_tag := title_tag.find("small", class_="original-title"):
            details["movie_title_en"] = _clean_text(en_tag.extract().text)
        details["movie_title"] = _clean_text(title_tag.text)
    
    # --- Main Content Block ---
    div_wysiwyg = soup.select_one("div.l-wysiwyg")
    if not div_wysiwyg:
        if not details["movie_title"]:
            if og_title := soup.select_one('meta[property="og:title"]'):
                details["movie_title"] = _clean_text(og_title.get("content", "").split("–")[0])
        return details

    full_text = div_wysiwyg.get_text(separator="\n")

    # --- Synopsis ---
    synopsis = None
    # Priority 1: Find 【STORY】 header
    if story_header := div_wysiwyg.find(lambda tag: tag.name in ['h2', 'h3', 'p', 'strong'] and "【STORY】" in tag.text):
        for next_tag in story_header.find_next_siblings():
            if next_tag.name == 'p' and next_tag.text and len(_clean_text(next_tag.text)) > 50:
                synopsis = _clean_text(next_tag.text)
                break
    
    # Priority 2: Find first long paragraph *after* an <hr>
    if not synopsis:
        if hr := div_wysiwyg.find("hr"):
            for next_tag in hr.find_next_siblings():
                 if next_tag.name == 'p' and next_tag.text and len(_clean_text(next_tag.text)) > 100:
                    synopsis = _clean_text(next_tag.text)
                    break
    
    # Priority 3: Fallback to first long paragraph
    if not synopsis:
        for p in div_wysiwyg.find_all("p"):
            if not p.find(["img", "iframe", "strong"]):
                text = _clean_text(p.text)
                if len(text) > 120 and "※" not in text and "登壇者" not in text: 
                    synopsis = text
                    break
    details["synopsis"] = synopsis

    # --- Robust Spec Parsing ---
    
    # 1. Director (page-wide search is acceptable)
    if match := re.search(r"(?:監督・脚本|監督)：([^\n]+)", full_text, re.MULTILINE):
        details["director"] = _clean_text(match.group(1).split('/')[0])

    # 2. Find *last* spec block `(...)`
    # This is the ONLY place we get Year, Runtime, Country from.
    spec_text = None
    for match in re.finditer(r"（([^）]+)）", full_text):
        candidate = match.group(1)
        if "年" in candidate or "分" in candidate:
            spec_text = candidate # Last one wins
            
    if spec_text:
        # 3. Parse Year, Runtime, Country ONLY from this block
        if year_match := re.search(r"(\d{4})年", spec_text):
            # Guard: ignore if followed by month (e.g. 2026年1月)
            suffix_check = spec_text[year_match.end():]
            if not re.match(r"\s*\d+月", suffix_check):
                details["year"] = year_match.group(1)
        
        if runtime_match := re.search(r"(\d+)分", spec_text):
            details["runtime_min"] = runtime_match.group(1)
        
        # [FIX 10] Aggressive blocklist
        blocklist = re.compile(
            r"(\d{4}年|\d+分|\d{4}|\d{2}年|\d\.\dc|ch|DCP|G|カラー|ドキュメンタリー|\d+:\d|ビスタ|ステレオ|英語|フランス語|日本語|スコープ|シネマスコープ)", 
            re.IGNORECASE
        )
        spec_parts = [p.strip() for p in spec_text.split('／') if p.strip()]
        found_country = None
        for part in spec_parts:
            if not blocklist.search(part) and len(part) < 20:
                found_country = part
                break
        if found_country:
            details["country"] = found_country.split('・')[0].split('/')[0].strip().removesuffix("映画")

    # 4. Fallback ONLY for runtime (often listed separately)
    if not details["runtime_min"]:
        if match := re.search(r"(\d+)分", full_text):
            details["runtime_min"] = match.group(1)
            
    # [FIX 10] No page-wide fallback for 'year' or 'country'.

    # Fallback title
    if not details["movie_title"]:
        if og_title := soup.select_one('meta[property="og:title"]'):
            details["movie_title"] = _clean_text(og_title.get("content", "").split("–")[0])

    return details


# --- Main Scraping Logic ---

def scrape_uplink_kichijoji() -> List[Dict[str, str]]:
    """
    Scrapes all movie showings from the Uplink Kichijoji static schedule page.
    """
    print(f"INFO: [{CINEMA_NAME}] Starting scrape of {SCHEDULE_URL}", file=sys.stderr)
    main_soup = _fetch_soup(SCHEDULE_URL)
    if not main_soup:
        return []

    showings = []
    
    current_year_str_tag = main_soup.select_one("h1.archive_header-heading")
    if not current_year_str_tag:
        print(f"ERROR: [{CINEMA_NAME}] Could not find year header. Aborting.", file=sys.stderr)
        return []
        
    current_year_str = current_year_str_tag.text.split('.')[0]
    try:
        current_year = int(current_year_str)
    except Exception:
        current_year = dt.date.today().year
        print(f"WARN: [{CINEMA_NAME}] Could not parse year. Defaulting to {current_year}.", file=sys.stderr)

    day_blocks = main_soup.select("div.list-calendar-wrap")
    print(f"INFO: [{CINEMA_NAME}] Found {len(day_blocks)} day blocks to parse.", file=sys.stderr)
    
    today = dt.date.today()
    cutoff_date = today + dt.timedelta(days=14) # Scrape 14 days

    for day_block in day_blocks:
        date_header_tag = day_block.select_one("div.list-calendar-header p.list-calendar-header-inner")
        if not date_header_tag:
            continue
        
        date_str = _clean_text(date_header_tag.text) 
        parsed_date = _parse_date_from_header(date_str, current_year)
        if not parsed_date:
            print(f"WARN: [{CINEMA_NAME}] Could not parse date: {date_str}", file=sys.stderr)
            continue
            
        if not (today <= parsed_date < cutoff_date):
            continue

        iso_date = parsed_date.isoformat()
        # print(f"INFO: [{CINEMA_NAME}] Processing date {iso_date}...", file=sys.stderr) # Too noisy

        movie_articles = day_block.select("li.tagged-film article")
        if not movie_articles:
             continue # No movies this day

        for movie_article in movie_articles:
            try:
                title_tag = movie_article.select_one("h1.list-calendar-heading a")
                if not title_tag:
                    continue
                
                detail_url = urljoin(BASE_URL, title_tag.get('href', ''))
                if not detail_url:
                    continue
                
                # --- Detail Caching Logic ---
                if detail_url not in _detail_cache:
                    print(f"  -> Fetching details for: {detail_url}", file=sys.stderr)
                    detail_soup = _fetch_soup(detail_url)
                    if detail_soup:
                        _detail_cache[detail_url] = _parse_detail_page(detail_soup, detail_url)
                    else:
                        _detail_cache[detail_url] = {"detail_page_url": detail_url} 
                
                details = _detail_cache.get(detail_url, {})

                # Fallback titles from schedule page
                if not details.get("movie_title"):
                    title_en_tag = title_tag.select_one("small.original-title")
                    details["movie_title_en"] = _clean_text(title_en_tag.extract().text) if en_tag else None
                    details["movie_title"] = _clean_text(title_tag.find(string=True, recursive=False))
                
                # --- Showtime Loop ---
                for s_block in movie_article.select("div.list-calendar-inner"):
                    time_tag = s_block.select_one("p.list-calendar-date")
                    if not time_tag:
                        continue
                    
                    showtime = _clean_text(time_tag.find(string=True, recursive=False))
                    
                    if not re.match(r"^\d{1,2}:\d{2}$", showtime):
                        continue 

                    showings.append({
                        "cinema_name": CINEMA_NAME,
                        "date_text": iso_date,
                        "showtime": showtime,
                        "screen_name": None, 
                        **details 
                    })
            
            except Exception as e:
                print(f"ERROR: [{CINEMA_NAME}] Failed to parse a movie article on {iso_date}: {e}", file=sys.stderr)

    # De-duplicate and sort
    unique = { (s["date_text"], s.get("movie_title"), s["showtime"]): s for s in showings }
    final_list = sorted(list(unique.values()), key=lambda r: (r.get("date_text", ""), r.get("movie_title", ""), r.get("showtime", "")))
    print(f"INFO: [{CINEMA_NAME}] Scrape complete. Found {len(final_list)} unique showings.", file=sys.stderr)
    return final_list

# --- Main Execution ---

if __name__ == '__main__':
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
            
    all_showings = scrape_uplink_kichijoji()
    
    if all_showings:
        output_filename = "uplink_kichijoji_showtimes.json"
        output_path = Path(__file__).parent / output_filename
        
        print(f"\nINFO: Writing {len(all_showings)} records to {output_path}...", file=sys.stderr)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_showings, f, ensure_ascii=False, indent=2)
        print(f"INFO: Successfully created {output_path}.", file=sys.stderr)
        
        print("\n--- Sample of First Showing ---")
        from pprint import pprint
        sample = all_showings[0]
        for s in all_showings:
            # Find a good example with full data
            if s.get("director") and s.get("year") and s.get("country"):
                sample = s
                break
        pprint(sample)
    else:
        print(f"\nNo showings found for {CINEMA_NAME}.")