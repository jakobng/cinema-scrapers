#!/usr/bin/env python3
# nickel_module.py
# Scraper for The Nickel, Clerkenwell (grindhouse cinema)
# https://thenickel.co.uk/
#
# Note: The Nickel uses client-side rendering for detailed schedule.
# We extract basic info from screening links on the main page and
# parse date from individual screening pages.

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://thenickel.co.uk"
SCHEDULE_URL = BASE_URL
CINEMA_NAME = "The Nickel"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 30  # Nickel shows cult films, often scheduled far ahead


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_film_info(link_text: str) -> Dict[str, str]:
    """
    Parse film info from link text like:
    "EYES OF FIRE(1983,USA,Avery Crounse)A group of settlers..."

    Returns dict with title, year, country, director, synopsis.
    """
    result = {
        "title": "",
        "year": "",
        "country": "",
        "director": "",
        "synopsis": "",
    }

    if not link_text:
        return result

    # Pattern: TITLE(YEAR,COUNTRY,Director)Synopsis
    match = re.match(r'^(.+?)\((\d{4}),([^,]+),([^)]+)\)(.*)$', link_text)
    if match:
        result["title"] = _clean(match.group(1))
        result["year"] = match.group(2)
        result["country"] = _clean(match.group(3))
        result["director"] = _clean(match.group(4))
        result["synopsis"] = _clean(match.group(5))[:500]
    else:
        # Try simpler pattern without full metadata
        # TITLE(YEAR,COUNTRY)Synopsis or just TITLE
        match2 = re.match(r'^(.+?)\((\d{4})', link_text)
        if match2:
            result["title"] = _clean(match2.group(1))
            result["year"] = match2.group(2)
        else:
            # Just use the whole thing as title
            result["title"] = _clean(link_text.split('(')[0] if '(' in link_text else link_text)

    return result


def _parse_date_from_title(title: str) -> Optional[dt.date]:
    """
    Parse date from screening page title like "EYES OF FIRE (8 Jan)"
    """
    match = re.search(r'\((\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\)', title, re.I)
    if match:
        day = int(match.group(1))
        month_str = match.group(2)

        months = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        month = months.get(month_str.lower())

        if month:
            year = TODAY.year
            try:
                date = dt.date(year, month, day)
                # If date is in the past, assume next year
                if date < TODAY - dt.timedelta(days=7):
                    date = dt.date(year + 1, month, day)
                return date
            except ValueError:
                pass

    return None


def _fetch_screening_details(screening_url: str) -> Tuple[Optional[dt.date], Optional[str]]:
    """
    Fetch a screening page to get the date and time.
    Returns (date, time) tuple.
    """
    try:
        resp = requests.get(screening_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Get date from page title
        title = soup.title.string if soup.title else ""
        show_date = _parse_date_from_title(title)

        # Look for time in page content
        text = soup.get_text()
        time_match = re.search(r'(\d{1,2}):(\d{2})', text)
        show_time = None
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            if 0 <= hour < 24 and 0 <= minute < 60:
                show_time = f"{hour:02d}:{minute:02d}"

        return show_date, show_time

    except Exception as e:
        print(f"[{CINEMA_NAME}] Error fetching {screening_url}: {e}", file=sys.stderr)
        return None, None


def scrape_nickel() -> List[Dict]:
    """
    Scrape The Nickel showtimes.

    Note: Limited scraping due to client-side rendering.
    Extracts film info from main page links.
    """
    shows = []

    try:
        session = requests.Session()
        resp = session.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find all screening links
        screening_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/screening/' in href:
                text = a.get_text(strip=True)
                if text and len(text) > 10:
                    full_url = urljoin(BASE_URL, href)
                    screening_links.append((full_url, text))

        print(f"[{CINEMA_NAME}] Found {len(screening_links)} screening links", file=sys.stderr)

        # Process each screening (limit to avoid too many requests)
        processed = set()
        for url, link_text in screening_links[:50]:  # Limit to 50 screenings
            # Skip duplicates
            if url in processed:
                continue
            processed.add(url)

            # Parse film info from link text
            film_info = _parse_film_info(link_text)

            if not film_info["title"]:
                continue

            # Fetch date/time from screening page
            show_date, show_time = _fetch_screening_details(url)

            if not show_date:
                continue

            # Check if within our window
            if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                continue

            # Default time if not found (The Nickel typically has evening screenings)
            if not show_time:
                show_time = "20:00"

            shows.append({
                "cinema_name": CINEMA_NAME,
                "movie_title": film_info["title"],
                "movie_title_en": film_info["title"],
                "date_text": show_date.isoformat(),
                "showtime": show_time,
                "detail_page_url": url,
                "booking_url": url,
                "director": film_info.get("director", ""),
                "year": film_info.get("year", ""),
                "country": film_info.get("country", ""),
                "runtime_min": "",
                "synopsis": film_info.get("synopsis", ""),
                "format_tags": [],
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
    data = scrape_nickel()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
