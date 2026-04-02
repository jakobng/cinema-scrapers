from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.jackandbetty.net/"
# Date search URL template: https://www.jackandbetty.net/cinema/search/term/YYYY-MM-DD/
SEARCH_URL_TEMPLATE = "https://www.jackandbetty.net/cinema/search/term/{date_str}/"
CINEMA_NAME = "横浜シネマ・ジャック＆ベティ"


def clean_text(text: str) -> str:
    """Normalize whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup object, or None on error."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def parse_date_range(range_text: str) -> Optional[tuple[datetime, datetime]]:
    """
    Parse text like '1月10日(土)〜1月16日(金)'
    """
    match = re.findall(r"(\d+)月(\d+)日", range_text)
    if len(match) != 2:
        return None
    
    current_year = datetime.now().year
    
    def to_dt(m, d):
        # Heuristic for year wrap
        if int(m) < datetime.now().month and datetime.now().month > 10:
            y = current_year + 1
        else:
            y = current_year
        return datetime(y, int(m), int(d))

    start_dt = to_dt(match[0][0], match[0][1])
    end_dt = to_dt(match[1][0], match[1][1])
    return start_dt, end_dt


def parse_movie_block(block: BeautifulSoup, target_date_iso: str) -> List[Dict]:
    """
    Parse a movie block (cinemalistCont) from a date search result page.
    """
    showings = []
    target_dt = datetime.strptime(target_date_iso, "%Y-%m-%d")
    
    title_tag = block.select_one(".mtitle a")
    if not title_tag:
        return []
    
    movie_title = clean_text(title_tag.get_text())
    detail_url = urljoin(BASE_URL, title_tag.get("href", ""))
    
    # Metadata parsing
    dl_text = block.select_one(".clL dl").get_text() if block.select_one(".clL dl") else ""
    director = None
    dir_match = re.search(r"【監督】(.*?)(?:\n|【|$)", dl_text)
    if dir_match:
        director = clean_text(dir_match.group(1))
    
    # Showtimes table (usually id="mtj" or similar in clR)
    # The search page for a specific date STILL lists all ranges for that movie.
    # We must find the range that includes target_date_iso.
    rows = block.select(".clR table tr")
    for row in rows:
        th = row.select_one("th")
        td = row.select_one("td")
        if not th or not td:
            continue
            
        range_text = clean_text(th.get_text())
        date_range = parse_date_range(range_text)
        if not date_range:
            continue
            
        start_dt, end_dt = date_range
        # Check if target date is in this range
        if start_dt <= target_dt <= end_dt:
            time_text_raw = clean_text(td.get_text())
            # Extract times like "10:30〜12:25" or "10:30"
            # Some entries have multiple times per row
            times = re.findall(r"(\d{1,2}:\d{2})(?:〜\d{1,2}:\d{2})?", time_text_raw)
            for t in times:
                showings.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title,
                    "movie_title_en": None,
                    "director": director,
                    "year": None,
                    "country": None,
                    "runtime_min": None,
                    "date_text": target_date_iso,
                    "showtime": t,
                    "detail_page_url": detail_url,
                    "program_title": None,
                    "purchase_url": "https://schedule.eigaland.com/schedule?webKey=f005657d-7131-479e-a734-c42c14d98f9f",
                })
            
    return showings


def scrape_jack_and_betty() -> List[Dict]:
    """
    Scrape Jack and Betty Yokohama screenings for the next 7 days.
    """
    results: List[Dict] = []
    
    # Scrape for today and the next 6 days
    for i in range(7):
        target_date = datetime.now() + timedelta(days=i)
        date_iso = target_date.strftime("%Y-%m-%d")
        search_url = SEARCH_URL_TEMPLATE.format(date_str=date_iso)
        
        soup = fetch_soup(search_url)
        if not soup:
            continue
            
        movie_blocks = soup.select(".cinemalistCont")
        for block in movie_blocks:
            showings = parse_movie_block(block, date_iso)
            results.extend(showings)
            
    # Deduplicate since same ranges might appear across multiple search days
    seen = set()
    unique_results = []
    for r in results:
        key = (r["movie_title"], r["date_text"], r["showtime"])
        if key not in seen:
            seen.add(key)
            unique_results.append(r)
            
    return unique_results


if __name__ == "__main__":
    data = scrape_jack_and_betty()
    print(f"{len(data)} unique showings found")
    for d in data[:5]:
        print(d)