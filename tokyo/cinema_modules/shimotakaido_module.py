"""
shimotakaido_module.py — scraper for Shimotakaido Cinema (下高井戸シネマ)
- FIXED: Showtime extraction now strips "作品日替り" and other non-time text.
- FIXED: Ensures strictly HH:MM format for compatibility.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

CINEMA_NAME = "下高井戸シネマ"
BASE_URL = "https://shimotakaidocinema.com/"
SCHEDULE_PAGE_URL = urljoin(BASE_URL, "schedule/schedule.html")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}
TIMEOUT = 20

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding # Ensure correct encoding for JP text
        return BeautifulSoup(resp.content, "html.parser")
    except requests.RequestException as e:
        print(f"ERROR [{CINEMA_NAME}]: Could not fetch {url}: {e}", file=sys.stderr)
        return None

def _clean_text(text: str) -> str:
    """A helper to normalize whitespace."""
    return " ".join(text.strip().split())

def _parse_runtime(text: str) -> Optional[str]:
    """Parses '1h39' into '99' minutes."""
    if not text: return None
    hours, minutes = 0, 0
    if h_match := re.search(r"(\d+)h", text):
        hours = int(h_match.group(1))
    if m_match := re.search(r"(\d+)", text.split('h')[-1]):
        minutes = int(m_match.group(1))
    total_minutes = hours * 60 + minutes
    return str(total_minutes) if total_minutes > 0 else None

# ---------------------------------------------------------------------------
# Detail & Schedule Parsing
# ---------------------------------------------------------------------------

def _parse_all_details(soup: BeautifulSoup) -> Dict[str, Dict]:
    """Parses all movie detail blocks on the schedule page."""
    details_cache = {}

    for box in soup.select("div.box"):
        title_tag = box.select_one("span.eiga-title")
        if not title_tag:
            continue

        title = _clean_text(title_tag.get_text())
        if not title: continue

        details = {
            "director": None, "year": None, "runtime_min": None, "country": None,
            "synopsis": None, "detail_page_url": None,
        }

        stuff_p = box.select_one("p.stuff")
        if stuff_p:
            stuff_text = _clean_text(stuff_p.get_text(separator=' '))
            year_match = re.search(r"(\d{4})年?", stuff_text)
            runtime_match = re.search(r"(\d+h\d*)", stuff_text)
            director_match = re.search(r"監督(?:・脚本)?[：／]([^/]+)", stuff_text)

            if year_match: details["year"] = year_match.group(1)
            if runtime_match: details["runtime_min"] = _parse_runtime(runtime_match.group(1))
            if director_match: details["director"] = director_match.group(1).strip()

            country_parts = stuff_text.split('/')
            if len(country_parts) > 1 and not (year_match and year_match.group(1) in country_parts[1]):
                details["country"] = country_parts[1].strip()

        note_p = box.select_one("p.note")
        if note_p:
            details["synopsis"] = _clean_text(note_p.get_text())

        hp_link = box.select_one("a[href][target='_blank']")
        if hp_link:
            details["detail_page_url"] = hp_link['href']

        details_cache[title] = details
        # Fallback for partial matches (e.g. if schedule omits subtitle)
        if ' ' in title:
            details_cache[title.split(' ')[0]] = details

    return details_cache

# ---------------------------------------------------------------------------
# Core Scraper
# ---------------------------------------------------------------------------

def scrape_shimotakaido(max_days: int = 14) -> List[Dict[str, str]]:
    """Scrapes the Shimotakaido Cinema schedule page."""
    print(f"INFO [{CINEMA_NAME}]: Fetching schedule page: {SCHEDULE_PAGE_URL}")
    soup = _fetch_soup(SCHEDULE_PAGE_URL)
    if not soup:
        return []

    details_cache = _parse_all_details(soup)
    print(f"INFO [{CINEMA_NAME}]: Found details for {len(details_cache)} films.")

    table = soup.find("table", class_="sche-table")
    if not table:
        print(f"ERROR [{CINEMA_NAME}]: Schedule table not found", file=sys.stderr)
        return []

    rows = table.find("tbody").find_all("tr")
    if not rows or len(rows) < 2: return []

    today = date.today()
    year = today.year
    header_cells = rows[0].find_all("td", class_="sche-td-2")
    date_ranges = []
    
    # Parse Date Headers
    for cell in header_cells:
        text = cell.get_text(strip=True)
        m = re.search(r"(\d{1,2})/(\d{1,2}).*?[-–]\s*(\d{1,2})/(\d{1,2})", text)
        if not m: continue

        m1, d1, m2, d2 = map(int, m.groups())
        # Handle year rollover (Dec -> Jan)
        start = date(year, m1, d1)
        if m1 < today.month and (today.month - m1) > 6:
             start = date(year + 1, m1, d1)
        elif m1 > today.month and (m1 - today.month) > 6:
             start = date(year - 1, m1, d1)

        end_year = start.year if m2 >= m1 else start.year + 1
        end = date(end_year, m2, d2)
        date_ranges.append((start, end))

    all_showings: List[Dict] = []
    
    # Parse Schedule Rows
    for tr in rows[1:]:
        cells = tr.find_all("td", class_="sche-td")
        # Ensure we match cells to headers safely
        for idx, cell in enumerate(cells):
            if idx >= len(date_ranges): break
            start_date, end_date = date_ranges[idx]

            link = cell.find("a")
            if not link: continue

            text_parts = [s.strip() for s in link.stripped_strings]
            if len(text_parts) < 2: continue

            # Robust Title/Time Extraction
            # Shimotakaido often puts title first, then time at the end
            # Time can be "10:00" or "18:25 作品日替り"
            title = text_parts[0]
            raw_time = text_parts[-1]
            
            # Extract pure HH:MM
            time_match = re.search(r"(\d{1,2}[:：]\d{2})", raw_time)
            if not time_match:
                # Fallback: check other parts for time?
                for part in reversed(text_parts):
                     time_match = re.search(r"(\d{1,2}[:：]\d{2})", part)
                     if time_match: break
            
            if not time_match: continue
            
            clean_time = time_match.group(1).replace("：", ":")
            # Pad hour if needed (9:00 -> 09:00)
            if len(clean_time) == 4: clean_time = "0" + clean_time

            details = {}
            for cache_title, detail_data in details_cache.items():
                if title in cache_title or cache_title in title:
                    details = detail_data
                    break

            current_date = start_date
            while current_date <= end_date:
                all_showings.append({
                    "cinema_name":     CINEMA_NAME,
                    "movie_title":     title,
                    "movie_title_en":  "",
                    "date_text":       current_date.isoformat(),
                    "showtime":        clean_time,
                    "director":        details.get("director", "") or "",
                    "year":            details.get("year", "") or "",
                    "country":         details.get("country", "") or "",
                    "runtime_min":     details.get("runtime_min", "") or "",
                    "synopsis":        details.get("synopsis", "") or "",
                    "detail_page_url": details.get("detail_page_url", "") or "",
                })
                current_date += timedelta(days=1)

    # --- Filter for the specified date window ---
    cutoff_date = today + timedelta(days=max_days)
    future_showings = [
        s for s in all_showings
        if today <= date.fromisoformat(s['date_text']) < cutoff_date
    ]

    unique = list({(s["date_text"], s["movie_title"], s["showtime"]): s for s in future_showings}.values())
    print(f"INFO [{CINEMA_NAME}]: Collected {len(unique)} unique showings within the {max_days}-day window.")
    return unique

# ---------------------------------------------------------------------------
# CLI Test Harness
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass

    print(f"Testing {CINEMA_NAME} scraper…")
    shows = scrape_shimotakaido(max_days=14) 
    if not shows:
        print("No showings found — check warnings above.")
        sys.exit(1)

    shows.sort(key=lambda x: (x["date_text"], x["showtime"]))

    output_filename = "shimotakaido_showtimes.json"
    print(f"\nINFO: Writing {len(shows)} records to {output_filename}...")
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(shows, f, ensure_ascii=False, indent=2)
    print(f"INFO: Successfully created {output_filename}.")