#!/usr/bin/env python3
# sands_films_module.py
# Scraper for Sands Films Cinema Club
# https://sandsfilms.co.uk / https://watch.eventive.org/sandsfilms
#
# Sands Films operates a virtual cinema through the Eventive platform.
# Films are broadcast live on Tuesdays at 8PM London time and remain
# available for catch-up viewing for a limited duration.
#
# Structure: Next.js app with embedded __NEXT_DATA__ JSON containing
# all film listings with availability windows.

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://watch.eventive.org"
SCHEDULE_URL = f"{BASE_URL}/sandsfilms"
CINEMA_NAME = "Sands Films Cinema Club"

# Physical location for reference
LOCATION = "82 St Marychurch Street, Rotherhithe, London SE16 4HZ"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 30  # Longer window since this is on-demand content


def _clean(text: str) -> str:
    """Clean whitespace, decode HTML entities, and normalize text."""
    if not text:
        return ""
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text.strip())


def _extract_film_title(name: str) -> str:
    """
    Extract the actual film title from the Eventive listing name.
    Removes the 'Sands Films Cinema Club online presentation' suffix
    and other common prefixes/patterns.
    """
    if not name:
        return ""

    # Remove common suffix
    title = re.sub(r":\s*Sands Films Cinema Club online presentation\s*$", "", name, flags=re.IGNORECASE)

    # Remove year prefixes like "1956: " or "Films of 1975 " or "Films of 1975"
    title = re.sub(r"^(?:Films of\s+)?\d{4}:\s*", "", title)
    title = re.sub(r"^Films of\s+\d{4}\s+", "", title)

    # Clean up prefixes like "Pagnol first three films; "
    if ";" in title:
        parts = title.split(";")
        # Take the last part as it's usually the actual film name
        title = parts[-1].strip()

    return _clean(title)


def _parse_iso_datetime(iso_str: str) -> Optional[dt.datetime]:
    """Parse ISO format datetime string."""
    if not iso_str:
        return None

    try:
        # Handle formats like "2025-01-28T19:05:00.000Z"
        iso_str = iso_str.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(iso_str)
    except ValueError:
        pass

    return None


def _extract_next_data(html_content: str) -> dict:
    """
    Extract the __NEXT_DATA__ JSON from the page HTML.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}

    try:
        data = json.loads(script.string)
        return data.get("props", {}).get("pageProps", {})
    except json.JSONDecodeError:
        return {}


def _extract_metadata_from_description(description_html: str) -> dict:
    """
    Extract metadata (director, year, runtime) from the film description HTML.
    """
    metadata = {
        "director": "",
        "year": "",
        "runtime_min": "",
        "country": "",
    }

    if not description_html:
        return metadata

    # Parse HTML
    soup = BeautifulSoup(description_html, "html.parser")
    text = soup.get_text()

    # Extract year
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if year_match:
        metadata["year"] = year_match.group(1)

    # Extract director - often in format "Director: Name" or "(Director Name, Year)"
    director_match = re.search(r"Director[s]?[:\s]+([^,\n]+)", text, re.IGNORECASE)
    if director_match:
        metadata["director"] = _clean(director_match.group(1))
    else:
        # Try pattern like "(Federico Fellini, 1986)"
        paren_match = re.search(r"\(([^,]+),\s*\d{4}\)", text)
        if paren_match:
            metadata["director"] = _clean(paren_match.group(1))

    # Extract runtime
    runtime_match = re.search(r"(\d+)\s*(?:min(?:ute)?s?|mins?)", text, re.IGNORECASE)
    if runtime_match:
        metadata["runtime_min"] = runtime_match.group(1)

    return metadata


def scrape_sands_films() -> List[Dict]:
    """
    Scrape Sands Films Cinema Club showtimes from their Eventive page.

    Since this is a virtual cinema with on-demand content, we list films
    that are currently available or will become available within the window.
    The "showtime" is set to the broadcast time (typically 8PM London) on
    the start date, with format tags indicating it's virtual/on-demand.

    Returns a list of showtime records with standard schema:
    - cinema_name: str
    - movie_title: str
    - date_text: str (YYYY-MM-DD)
    - showtime: str (HH:MM)
    - detail_page_url: str
    - booking_url: str
    - director, year, country, runtime_min, synopsis: str (optional)
    - format_tags: list (optional)
    """
    shows = []

    try:
        session = requests.Session()
        resp = session.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        page_data = _extract_next_data(resp.text)

        if not page_data:
            print(f"[{CINEMA_NAME}] Warning: Could not extract Next.js data from page", file=sys.stderr)
            return []

        initial_data = page_data.get("initialData", {})
        sections = initial_data.get("sections", [])

        if not sections:
            print(f"[{CINEMA_NAME}] Warning: No sections found in page data", file=sys.stderr)
            return []

        total_items = sum(len(s.get("items", [])) for s in sections)
        print(f"[{CINEMA_NAME}] Found {len(sections)} sections with {total_items} items", file=sys.stderr)

        seen_ids = set()

        for section in sections:
            items = section.get("items", [])

            for item in items:
                item_id = item.get("id", "")

                # Skip duplicates (same film may appear in multiple sections)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                name = item.get("name", "")
                title = _extract_film_title(name)
                if not title:
                    continue

                # Parse availability times
                start_time_str = item.get("start_time", "")
                end_time_str = item.get("end_time", "")

                start_dt = _parse_iso_datetime(start_time_str)
                end_dt = _parse_iso_datetime(end_time_str)

                if not start_dt:
                    continue

                # Convert to London time (naive - just use date)
                start_date = start_dt.date()
                end_date = end_dt.date() if end_dt else start_date

                # Check if within our window:
                # - Currently available (start <= today <= end)
                # - Or starting soon (start is within WINDOW_DAYS)
                window_end = TODAY + dt.timedelta(days=WINDOW_DAYS)

                # Skip if already ended
                if end_date < TODAY:
                    continue

                # Skip if starting too far in future
                if start_date > window_end:
                    continue

                # Determine the display date
                # For currently available content, use TODAY
                # For upcoming content, use the start_date
                is_coming_soon = item.get("coming_soon", False) or start_date > TODAY

                if is_coming_soon:
                    display_date = start_date
                else:
                    # For currently available on-demand, show as available today
                    display_date = TODAY

                # Only include if display date is within our window
                if not (TODAY <= display_date < window_end):
                    continue

                # Extract showtime from start_time (typically 8PM)
                showtime = start_dt.strftime("%H:%M") if start_dt else "20:00"

                # Build URLs
                detail_url = f"{BASE_URL}/sandsfilms/play/{item_id}"
                booking_url = detail_url  # Same page for purchasing

                # Build format tags
                format_tags = ["Virtual Cinema", "On-demand"]
                if is_coming_soon:
                    format_tags.append("Coming Soon")

                # Add availability end info
                if end_dt:
                    format_tags.append(f"Until {end_date.strftime('%d %b')}")

                short_desc = item.get("short_description", "")

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": display_date.isoformat(),
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                    "booking_url": booking_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": short_desc,
                    "format_tags": format_tags,
                })

        print(f"[{CINEMA_NAME}] Found {len(shows)} showings within date window", file=sys.stderr)

    except requests.RequestException as e:
        print(f"[{CINEMA_NAME}] HTTP Error: {e}", file=sys.stderr)
        raise
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
    data = scrape_sands_films()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
