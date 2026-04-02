#!/usr/bin/env python3
# dochouse_module.py
# Scraper for Bertha DocHouse
# https://dochouse.org/
#
# Structure: Homepage contains embedded JSON data in a script tag
# Format: {"YYYY-MM-DD": [{"title": "...", "link": "...", "times": [...]}]}

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dochouse.org"
SCHEDULE_URL = BASE_URL  # Main page contains the schedule
CINEMA_NAME = "Bertha DocHouse"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _clean(text: str) -> str:
    """Clean whitespace, decode HTML entities, and normalize text."""
    if not text:
        return ""
    # Decode HTML entities like &#8211; to proper characters
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text.strip())


def _parse_datetime(datetime_str: str) -> Optional[tuple]:
    """
    Parse datetime string in format 'YYYY-MM-DD HH:MM:SS'.
    Returns (date, time_str) tuple or None.
    """
    if not datetime_str:
        return None

    try:
        parsed = dt.datetime.strptime(datetime_str.strip(), "%Y-%m-%d %H:%M:%S")
        return (parsed.date(), parsed.strftime("%H:%M"))
    except ValueError:
        pass

    # Try without seconds
    try:
        parsed = dt.datetime.strptime(datetime_str.strip(), "%Y-%m-%d %H:%M")
        return (parsed.date(), parsed.strftime("%H:%M"))
    except ValueError:
        pass

    return None


def _extract_schedule_json(html: str) -> dict:
    """
    Extract the schedule JSON data from the page HTML.
    The data is stored in a script tag as a raw JSON object (not assigned to a variable)
    with date keys like {"2026-01-09": [...], ...}
    """
    soup = BeautifulSoup(html, "html.parser")

    # Look for script tags containing schedule data
    for script in soup.find_all("script"):
        script_text = script.string
        if not script_text:
            continue

        # Skip if it doesn't look like our schedule data
        script_text = script_text.strip()
        if not script_text.startswith('{"20'):
            continue

        # The JSON is the entire script content - try to parse directly
        try:
            data = json.loads(script_text)
            if isinstance(data, dict) and any(
                re.match(r"\d{4}-\d{2}-\d{2}", k) for k in data.keys()
            ):
                return data
        except json.JSONDecodeError:
            # Try to extract just the JSON object
            start_idx = 0
            depth = 0
            end_idx = 0
            for i, char in enumerate(script_text):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break

            if end_idx > 0:
                try:
                    data = json.loads(script_text[start_idx:end_idx])
                    if isinstance(data, dict) and any(
                        re.match(r"\d{4}-\d{2}-\d{2}", k) for k in data.keys()
                    ):
                        return data
                except json.JSONDecodeError:
                    pass

    return {}


def scrape_dochouse() -> List[Dict]:
    """
    Scrape Bertha DocHouse showtimes from their homepage.

    The page embeds schedule data as JSON with date keys containing
    arrays of film objects with titles, links, certificates, and times.

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
        resp = session.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        html = resp.text

        # Extract JSON data from script
        schedule_data = _extract_schedule_json(html)

        if not schedule_data:
            print(f"[{CINEMA_NAME}] Warning: Could not extract schedule JSON from page", file=sys.stderr)
            return []

        total_films = sum(len(films) for films in schedule_data.values())
        print(f"[{CINEMA_NAME}] Found {len(schedule_data)} dates with {total_films} film entries", file=sys.stderr)

        for date_key, films in schedule_data.items():
            # Parse the date key
            try:
                show_date = dt.datetime.strptime(date_key, "%Y-%m-%d").date()
            except ValueError:
                continue

            # Check if within our date window
            if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                continue

            for film in films:
                title = _clean(film.get("title", ""))
                if not title:
                    continue

                detail_url = film.get("link", "")
                certificate = film.get("certificate", "")

                # Process each showtime for this film on this date
                times = film.get("times", [])
                for time_entry in times:
                    # Time entry format: {"date": "YYYY-MM-DD HH:MM:SS", "blink": "...", "sold_out": false}
                    datetime_str = time_entry.get("date", "")
                    parsed = _parse_datetime(datetime_str)
                    if not parsed:
                        continue

                    time_date, time_str = parsed

                    # Verify the date matches (sometimes times span multiple days)
                    if time_date != show_date:
                        # Check if this time's date is within our window
                        if not (TODAY <= time_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                            continue
                        # Use the actual time's date
                        actual_date = time_date
                    else:
                        actual_date = show_date

                    booking_url = time_entry.get("booking_link", "") or time_entry.get("blink", "")
                    sold_out = time_entry.get("sold_out", False)

                    # Build format tags
                    format_tags = []
                    if certificate:
                        format_tags.append(certificate)
                    if sold_out:
                        format_tags.append("Sold Out")

                    shows.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": title,
                        "movie_title_en": title,
                        "date_text": actual_date.isoformat(),
                        "showtime": time_str,
                        "detail_page_url": detail_url,
                        "booking_url": booking_url,
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": "",
                        "synopsis": "",
                        "format_tags": format_tags,
                    })

        print(f"[{CINEMA_NAME}] Found {len(shows)} showings within date window", file=sys.stderr)

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
    data = scrape_dochouse()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
