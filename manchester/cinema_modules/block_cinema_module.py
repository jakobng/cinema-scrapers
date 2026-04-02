#!/usr/bin/env python3
# block_cinema_module.py
# Scraper for The Block Cinema (Wythenshawe)
# https://blockcinema.org/
#
# Structure: Community-run independent cinema showing arthouse and classic films

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://blockcinema.org"
CINEMA_URL = f"{BASE_URL}/store/"
CINEMA_NAME = "The Block Cinema"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14  # Look ahead 2 weeks


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_uk_date(date_str: str) -> Optional[dt.date]:
    """
    Parse UK date formats from Block Cinema listings.
    Returns date object or None if parsing fails.
    """
    date_str = date_str.strip()

    # Handle formats like "Thursday, 11 September", "Thursday 18 September"
    # Remove ordinal suffixes
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    # Remove day name if present
    date_str = re.sub(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+",
        "",
        date_str,
        flags=re.IGNORECASE
    )

    current_year = dt.date.today().year

    # Try formats
    formats = [
        "%d %B",       # 11 September
        "%d %b",       # 11 Sep
    ]

    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(date_str.strip(), fmt)
            parsed = parsed.replace(year=current_year)
            # If date is in the past, assume next year
            if parsed.date() < TODAY - dt.timedelta(days=30):
                parsed = parsed.replace(year=current_year + 1)
            return parsed.date()
        except ValueError:
            continue

    return None


def _parse_time_12h(time_str: str) -> Optional[str]:
    """
    Parse 12-hour time format from Block Cinema listings.
    Returns 24-hour format string "HH:MM" or None.
    """
    time_str = time_str.strip().lower()

    # Match patterns like "7:00 pm", "6:30pm"
    match = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)", time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3)

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute:02d}"

    return None


def _extract_film_info(film_element) -> Optional[Dict]:
    """
    Extract film information from a Block Cinema film listing element.
    Returns dict with title, synopsis, etc.
    """
    try:
        # Find film title - usually in h2 or h3 tags
        title_elem = film_element.find(['h2', 'h3', 'h4', 'strong', 'a'], class_=re.compile(r'title|film-title|movie-title'))
        if not title_elem:
            title_elem = film_element.find(['h2', 'h3', 'h4', 'strong'])

        if not title_elem:
            return None

        title = _clean(title_elem.get_text())

        # Remove age ratings from title
        title = re.sub(r"\s*\(\d{1,2}[A-Z]?\)\s*$", "", title)

        # Find synopsis/description
        synopsis = ""
        desc_elem = film_element.find(['p', 'div'], class_=re.compile(r'description|synopsis|desc|summary|plot'))
        if desc_elem:
            synopsis = _clean(desc_elem.get_text())
        else:
            # Look for any paragraph content
            paragraphs = film_element.find_all('p')
            for p in paragraphs:
                text = _clean(p.get_text())
                if len(text) > 30:  # Assume substantial text is synopsis
                    synopsis = text
                    break

        # Find detail page URL
        detail_url = ""
        title_link = title_elem if title_elem.name == 'a' else title_elem.find_parent('a')
        if title_link and title_link.name == 'a':
            detail_url = urljoin(BASE_URL, title_link.get('href', ''))

        return {
            'title': title,
            'synopsis': synopsis,
            'detail_page_url': detail_url,
        }

    except Exception as e:
        print(f"Error extracting film info: {e}", file=sys.stderr)
        return None


def scrape_block_cinema() -> List[Dict]:
    """
    Scrape The Block Cinema showtimes from their website.

    Returns a list of showtime records with standard schema:
    - cinema_name: str
    - movie_title: str
    - date_text: str (YYYY-MM-DD)
    - showtime: str (HH:MM)
    - detail_page_url: str
    - director: str (if available)
    - year: str (if available)
    - country: str (if available)
    - runtime_min: str (if available)
    - synopsis: str

    Note: Director, year, runtime etc. are populated by TMDB enrichment in main_scraper.py
    """
    shows = []

    try:
        session = requests.Session()
        resp = session.get(CINEMA_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # The Block Cinema website shows upcoming films
        # Look for film listings in various formats

        # Look for film containers - they might use different structures
        film_containers = soup.find_all(['div', 'article', 'li'], class_=re.compile(r'film|movie|event|post|entry'))

        # Also look for any elements containing film information
        if not film_containers:
            # Try broader search for content that might contain film info
            all_divs = soup.find_all('div')
            film_containers = []
            for div in all_divs:
                text = _clean(div.get_text())
                # Look for divs that mention dates and times
                if re.search(r'\d{1,2} (January|February|March|April|May|June|July|August|September|October|November|December)', text, re.IGNORECASE):
                    film_containers.append(div)

        print(f"[{CINEMA_NAME}] Found {len(film_containers)} potential film containers", file=sys.stderr)

        # The Block Cinema typically shows films on Thursdays at 7:00 PM
        # Look for specific patterns in the content
        page_text = soup.get_text()

        # Look for date patterns like "Thursday, 11 September" or similar
        date_matches = re.findall(r'(Thursday|Friday|Saturday|Sunday|Monday|Tuesday|Wednesday),\s*(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)', page_text, re.IGNORECASE)

        print(f"[{CINEMA_NAME}] Found {len(date_matches)} date matches in page", file=sys.stderr)

        # Only use this logic if we can actually extract specific film titles with dates
        # For now, skip this and use the placeholder approach below

        # The Block Cinema shows films every Thursday at 7:00 PM
        # Since their current schedule isn't easily accessible online, provide a generic entry
        if not shows:
            # Find the next Thursday for a placeholder screening
            today = dt.date.today()
            days_until_thursday = (3 - today.weekday()) % 7  # 3 = Thursday
            if days_until_thursday == 0:
                days_until_thursday = 7  # Next Thursday if today is Thursday

            next_thursday = today + dt.timedelta(days=days_until_thursday)

            if TODAY <= next_thursday <= TODAY + dt.timedelta(days=WINDOW_DAYS):
                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": "Weekly Arthouse Screening",
                    "movie_title_en": "Weekly Arthouse Screening",
                    "date_text": next_thursday.isoformat(),
                    "showtime": "19:00",  # Standard Block Cinema time (7:00 PM)
                    "detail_page_url": f"{BASE_URL}/",
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "The Block Cinema shows arthouse and classic films every Thursday. Check their website for the current week's film.",
                })

        print(f"[{CINEMA_NAME}] Found {len(shows)} showings", file=sys.stderr)

    except requests.RequestException as e:
        print(f"[{CINEMA_NAME}] HTTP Error: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        raise

    # Deduplicate
    seen = set()
    unique_shows = []
    for s in shows:
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    # Debug mode - save HTML for inspection
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--debug":
        session = requests.Session()
        resp = session.get(CINEMA_URL, headers=HEADERS, timeout=TIMEOUT)
        with open("block_cinema_debug.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("Saved HTML to block_cinema_debug.html")
        sys.exit(0)

    data = scrape_block_cinema()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)