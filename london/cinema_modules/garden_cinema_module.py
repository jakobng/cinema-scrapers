#!/usr/bin/env python3
# garden_cinema_module.py
# Scraper for The Garden Cinema, Covent Garden
# https://www.thegardencinema.co.uk/
#
# Structure: Films listed by date on homepage with embedded screening times

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.thegardencinema.co.uk"
SCHEDULE_URL = BASE_URL  # Schedule is on the main page
CINEMA_NAME = "The Garden Cinema"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_uk_date_short(date_str: str) -> Optional[dt.date]:
    """
    Parse short UK date formats like "Thu 08 Jan", "Fri 09 Jan".
    Returns date object or None.
    """
    date_str = date_str.strip()

    # Remove day name prefix
    date_str = re.sub(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+", "", date_str, flags=re.I)

    current_year = dt.date.today().year

    # Try formats
    formats = [
        "%d %b",       # 08 Jan
        "%d %B",       # 08 January
        "%d %b %Y",    # 08 Jan 2025
    ]

    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(date_str.strip(), fmt)
            if "%Y" not in fmt:
                parsed = parsed.replace(year=current_year)
                # If date is in past, assume next year
                if parsed.date() < TODAY - dt.timedelta(days=30):
                    parsed = parsed.replace(year=current_year + 1)
            return parsed.date()
        except ValueError:
            continue

    return None


def _parse_time_24h(time_str: str) -> Optional[str]:
    """
    Parse 24-hour time format like "15:00", "17:45".
    Returns "HH:MM" format string or None.
    """
    time_str = time_str.strip()

    match = re.match(r"(\d{1,2}):(\d{2})", time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return f"{hour:02d}:{minute:02d}"

    return None


def _parse_film_stats(stats_text: str) -> Dict[str, str]:
    """
    Parse stats line like "Joachim Trier, Norway, France, Germany, Denmark, 2025, 133m."
    Returns dict with director, country, year, runtime_min.
    """
    result = {
        "director": "",
        "country": "",
        "year": "",
        "runtime_min": "",
    }

    if not stats_text:
        return result

    parts = [p.strip() for p in stats_text.split(",")]

    for part in parts:
        # Year (4 digits)
        if re.match(r"^\d{4}$", part):
            result["year"] = part
        # Runtime (e.g., "133m", "133m.", "90 min")
        elif re.match(r"^\d+m\.?$", part) or re.match(r"^\d+\s*min", part, re.I):
            runtime_match = re.search(r"(\d+)", part)
            if runtime_match:
                result["runtime_min"] = runtime_match.group(1)
        # First part is usually director
        elif not result["director"] and len(part) > 2:
            result["director"] = part

    # Countries are usually in the middle
    countries = []
    for part in parts[1:]:  # Skip director
        if not re.match(r"^\d", part) and len(part) > 1 and len(part) < 20:
            if part not in [result["director"], result["year"]]:
                if not re.search(r"\d+m", part):
                    countries.append(part)
    if countries:
        result["country"] = ", ".join(countries[:3])  # Limit to 3 countries

    return result


def scrape_garden_cinema() -> List[Dict]:
    """
    Scrape The Garden Cinema showtimes from their homepage.

    Returns a list of showtime records with standard schema.
    """
    shows = []

    try:
        session = requests.Session()
        resp = session.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find all film blocks
        film_blocks = soup.select(".films-list__by-date__film")
        print(f"[{CINEMA_NAME}] Found {len(film_blocks)} film blocks", file=sys.stderr)

        for film_block in film_blocks:
            # Extract film title
            title_elem = film_block.select_one(".films-list__by-date__film__title a")
            if not title_elem:
                continue

            film_title = _clean(title_elem.get_text())
            # Remove rating suffix if embedded in title
            film_title = re.sub(r"\s*(PG|U|12A?|15|18|TBC)\s*$", "", film_title).strip()

            if not film_title:
                continue

            # Extract detail page URL
            detail_url = title_elem.get("href", "")
            if detail_url and not detail_url.startswith("http"):
                detail_url = urljoin(BASE_URL, detail_url)

            # Extract synopsis
            synopsis_elem = film_block.select_one(".films-list__by-date__film__synopsis")
            synopsis = _clean(synopsis_elem.get_text()) if synopsis_elem else ""

            # Extract stats (director, year, runtime, countries)
            stats_elem = film_block.select_one(".films-list__by-date__film__stats")
            stats_text = _clean(stats_elem.get_text()) if stats_elem else ""
            metadata = _parse_film_stats(stats_text)

            # Extract screening times
            screening_panels = film_block.select(".screening-panel")

            for panel in screening_panels:
                # Get date from panel
                date_elem = panel.select_one(".screening-panel__date-title")
                if not date_elem:
                    continue

                date_text = date_elem.get_text(strip=True)
                show_date = _parse_uk_date_short(date_text)

                if not show_date:
                    continue

                # Check if within our window
                if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                    continue

                # Get times from this panel
                time_elems = panel.select(".screening-time a.screening")

                for time_elem in time_elems:
                    time_str = time_elem.get_text(strip=True)
                    parsed_time = _parse_time_24h(time_str)

                    if not parsed_time:
                        continue

                    # Get booking URL
                    booking_url = time_elem.get("href", "")

                    shows.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": film_title,
                        "movie_title_en": film_title,
                        "date_text": show_date.isoformat(),
                        "showtime": parsed_time,
                        "detail_page_url": detail_url,
                        "booking_url": booking_url,
                        "director": metadata.get("director", ""),
                        "year": metadata.get("year", ""),
                        "country": metadata.get("country", ""),
                        "runtime_min": metadata.get("runtime_min", ""),
                        "synopsis": synopsis[:500] if synopsis else "",
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
    data = scrape_garden_cinema()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
