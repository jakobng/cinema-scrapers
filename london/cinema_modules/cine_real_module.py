#!/usr/bin/env python3
# cine_real_module.py
# Scraper for Ciné-Real (Hackney)
# https://cine-real.com/pages/next-screenings

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --- Constants ---
CINEMA_NAME = "Ciné-Real"
BASE_URL = "https://www.cine-real.com"
SCHEDULE_URL = f"{BASE_URL}/pages/next-screening"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}
TIMEOUT = 30

TODAY = dt.date.today()
YEAR = TODAY.year


def _clean_text(text: str) -> str:
    """Clean whitespace from text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _parse_date_and_time(date_text: str, time_text: str) -> Tuple[Optional[dt.date], Optional[str]]:
    """
    Parse date from text like "Wednesday 21st January" and time from "The Third Man on original 16mm, 7.30pm".
    """
    # Parse Date
    date_match = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)", date_text)
    if not date_match:
        return None, None
    
    day = int(date_match.group(1))
    month_str = date_match.group(2)
    
    try:
        # Try full month name first
        try:
            date_obj = dt.datetime.strptime(f"{day} {month_str} {YEAR}", "%d %B %Y").date()
        except ValueError:
            # Try abbreviated month name
            date_obj = dt.datetime.strptime(f"{day} {month_str} {YEAR}", "%d %b %Y").date()

        # Handle year rollover if the month is earlier than the current month
        if date_obj.month < TODAY.month:
             # Re-parse for next year (using same logic as above for simplicity, assuming format consistency)
             try:
                date_obj = dt.datetime.strptime(f"{day} {month_str} {YEAR + 1}", "%d %B %Y").date()
             except ValueError:
                date_obj = dt.datetime.strptime(f"{day} {month_str} {YEAR + 1}", "%d %b %Y").date()
    except ValueError:
        return None, None

    # Parse Time
    time_match = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)", time_text, re.IGNORECASE)
    
    if not time_match:
         return date_obj, None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    meridiem = time_match.group(3).lower()

    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
        
    return date_obj, f"{hour:02d}:{minute:02d}"


def scrape_cine_real() -> List[Dict]:
    """
    Scrape Ciné-Real showtimes.
    """
    shows: List[Dict] = []

    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # The structure seems to be paragraphs in .editor-content
        # <p><b>Wednesday 21st January</b></p>
        # <p><a href="...">Film Title ..., 7.30pm</a></p>
        
        content_div = (
            soup.find("div", class_="editor-content")
            or soup.find("div", class_="rte")
            or soup.find("div", class_="page-content")
            or soup.find("main")
            or soup
        )
        if not content_div:
            print(f"[{CINEMA_NAME}] Warning: Could not find main content container", file=sys.stderr)
            return []

        current_date = None
        
        for p in content_div.find_all(["p", "h2", "h3", "h4", "a"]):
            text = _clean_text(p.get_text())
            
            # Check for date line (usually bold)
            # <b>Wednesday 21st January</b>
            if (p.find(["b", "strong"]) or p.name in {"h2", "h3", "h4"}) and re.search(r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+", text):
                # Try to parse as date
                # Use a dummy time string just to trigger the date parsing logic in helper
                d, _ = _parse_date_and_time(text, "12pm")
                if d:
                    current_date = d
                    continue

            # Check for movie link line
            # <a href="...">The Third Man on original 16mm, 7.30pm</a>
            link = p if p.name == "a" else p.find("a")
            if link and current_date:
                link_text = _clean_text(link.get_text())
                href = link.get("href")
                
                if not href:
                    continue

                if href.startswith("/"):
                    href = urljoin(BASE_URL, href)
                
                # Extract time first
                # Use a dummy date text that is guaranteed to work with our parser to just extract time
                _, showtime = _parse_date_and_time("1st January", link_text)
                
                if not showtime:
                    continue
                
                # Title is everything before the time info roughly
                # A simple split by comma might work for "Title, Time"
                parts = link_text.rsplit(",", 1)
                title_candidate = parts[0]
                
                # Clean up title
                # Remove "on 16mm" or "on original 16mm"
                title = re.sub(r"\s+on\s+(?:original\s+)?16mm", "", title_candidate, flags=re.IGNORECASE)
                title = _clean_text(title)

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": current_date.isoformat(),
                    "showtime": showtime,
                    "detail_page_url": SCHEDULE_URL,
                    "booking_url": href,
                    "director": "", # Details not readily available in list
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": ""
                })

    except Exception as exc:
        print(f"[{CINEMA_NAME}] Error: {exc}", file=sys.stderr)
        return []

    seen = set()
    unique_shows = []
    for s in shows:
        key = (s.get("movie_title"), s.get("date_text"), s.get("showtime"), s.get("booking_url"))
        if key in seen:
            continue
        seen.add(key)
        unique_shows.append(s)

    return unique_shows


def scrape_cine_real_wrapper() -> List[Dict]:
    return scrape_cine_real()


if __name__ == "__main__":
    data = scrape_cine_real()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\nTotal: {len(data)} showings")
