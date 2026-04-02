#!/usr/bin/env python3
# jw3_module.py
# Scraper for JW3 Cinema
# https://www.jw3.org.uk/cinema
#
# JW3 is a Jewish community centre in London with a cinema showing
# a mix of mainstream, arthouse, and Jewish-themed films.
#
# Data source: Spektrix API at system.spektrix.com/jw3/api/v3/Events
# filtered by attribute_Genre="Cinema"

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests

# Spektrix API endpoint
API_URL = "https://system.spektrix.com/jw3/api/v3/Events"
BASE_URL = "https://purchase.jw3.org.uk"
CINEMA_NAME = "JW3 Cinema"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 30  # JW3 often lists events well in advance


def _clean(text: str) -> str:
    """Clean whitespace, decode HTML entities, and normalize text."""
    if not text:
        return ""
    text = html.unescape(text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r"\s+", " ", text.strip())


def _parse_iso_datetime(iso_str: str) -> Optional[dt.datetime]:
    """Parse ISO format datetime string."""
    if not iso_str:
        return None

    try:
        # Handle formats like "2025-01-15T19:30:00+00:00" or "2025-01-15T19:30:00Z"
        iso_str = iso_str.replace("Z", "+00:00")
        # Python's fromisoformat handles the +00:00 offset
        return dt.datetime.fromisoformat(iso_str)
    except ValueError:
        pass

    # Try without timezone
    try:
        return dt.datetime.fromisoformat(iso_str.split("+")[0].split("Z")[0])
    except ValueError:
        return None


def _parse_duration(duration_val) -> str:
    """Parse duration value to minutes."""
    if not duration_val:
        return ""

    # If it's already a number, return it as minutes
    if isinstance(duration_val, (int, float)):
        return str(int(duration_val))

    duration_str = str(duration_val)

    # Handle ISO 8601 duration format like "PT2H15M"
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration_str)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        return str(hours * 60 + minutes)

    # Handle "2h 15m" or "135 mins" format
    hours_match = re.search(r"(\d+)\s*h", duration_str, re.IGNORECASE)
    mins_match = re.search(r"(\d+)\s*m", duration_str, re.IGNORECASE)

    hours = int(hours_match.group(1)) if hours_match else 0
    minutes = int(mins_match.group(1)) if mins_match else 0

    if hours or minutes:
        return str(hours * 60 + minutes)

    # Try plain number
    plain_match = re.match(r"(\d+)", duration_str)
    if plain_match:
        return plain_match.group(1)

    return ""


def scrape_jw3() -> List[Dict]:
    """
    Scrape JW3 Cinema showtimes from the Spektrix API.

    Returns a list of showtime records with standard schema:
    - cinema_name: str
    - movie_title: str
    - date_text: str (YYYY-MM-DD)
    - showtime: str (HH:MM)
    - detail_page_url: str
    - booking_url: str
    - director, year, country, runtime_min, synopsis: str (optional)
    """
    shows = []

    try:
        session = requests.Session()
        resp = session.get(API_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        events = resp.json()

        if not isinstance(events, list):
            print(f"[{CINEMA_NAME}] Warning: Unexpected API response format", file=sys.stderr)
            return []

        print(f"[{CINEMA_NAME}] Found {len(events)} total events in API", file=sys.stderr)

        # Filter for cinema events
        cinema_events = [
            e for e in events
            if e.get("attribute_Genre") == "Cinema" and e.get("isOnSale")
        ]

        print(f"[{CINEMA_NAME}] Found {len(cinema_events)} cinema events", file=sys.stderr)

        for event in cinema_events:
            title = _clean(event.get("name", ""))
            if not title:
                continue

            # Get event details
            description = _clean(event.get("description", ""))
            duration = _parse_duration(event.get("duration", ""))
            web_event_id = event.get("webEventId", "")

            # Build event URL
            if web_event_id:
                event_url = f"{BASE_URL}/Event/{web_event_id}"
            else:
                event_url = BASE_URL

            # Parse showtimes from firstInstanceDateTime and lastInstanceDateTime
            # Note: instanceDates is a display string, not a list of dates
            first_dt_str = event.get("firstInstanceDateTime", "")
            last_dt_str = event.get("lastInstanceDateTime", "")

            first_dt = _parse_iso_datetime(first_dt_str)
            last_dt = _parse_iso_datetime(last_dt_str)

            if not first_dt:
                continue

            # Check if the event falls within our date window
            # Use first_dt as the primary date
            show_date = first_dt.date()

            # Check if within window
            if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                # Also check if last_dt is within window (for events spanning multiple days)
                if last_dt:
                    show_date = last_dt.date()
                    if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                        continue
                    # Use first_dt if last_dt is in range but first_dt isn't
                    # This handles events where we're in the middle of their run
                    first_dt = last_dt
                    show_date = first_dt.date()
                else:
                    continue

            showtime = first_dt.strftime("%H:%M")

            shows.append({
                "cinema_name": CINEMA_NAME,
                "movie_title": title,
                "movie_title_en": title,
                "date_text": show_date.isoformat(),
                "showtime": showtime,
                "detail_page_url": event_url,
                "booking_url": event_url,
                "director": "",
                "year": "",
                "country": "",
                "runtime_min": duration,
                "synopsis": description[:500] if description else "",
                "format_tags": [],
            })

        print(f"[{CINEMA_NAME}] Processed {len(shows)} showings within date window", file=sys.stderr)

    except requests.RequestException as e:
        print(f"[{CINEMA_NAME}] HTTP Error: {e}", file=sys.stderr)
        # Return empty list - don't raise to prevent main scraper from failing
        return []
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        raise

    # Deduplicate by (title, date, showtime)
    seen = set()
    unique_shows = []
    for s in shows:
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_jw3()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
