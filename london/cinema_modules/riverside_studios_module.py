#!/usr/bin/env python3
# riverside_studios_module.py
# Scraper for Riverside Studios cinema (Hammersmith)
# https://riversidestudios.co.uk/whats-on/
#
# Structure:
# - Film listings on /whats-on/ page (may need category filter)
# - Each film detail page contains showtimes
# - TODO: Refine selectors once HTML structure is confirmed

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://riversidestudios.co.uk"
WHATS_ON_URL = f"{BASE_URL}/whats-on/"
CINEMA_NAME = "Riverside Studios"

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
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text.strip())


def _parse_date(date_str: str) -> Optional[dt.date]:
    """
    Parse date string in various formats.
    Returns date object or None.
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Handle "Today", "Tomorrow"
    lower = date_str.lower()
    if lower == "today":
        return TODAY
    if lower == "tomorrow":
        return TODAY + dt.timedelta(days=1)

    # Try ISO format first (YYYY-MM-DD)
    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if iso_match:
        try:
            return dt.date(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3))
            )
        except ValueError:
            pass

    # Try "DD MMM YYYY" or "DD MMMM YYYY" format
    # Also handles "Sun 11 Jan" or "11 Jan 2025"
    match = re.search(r"(\d{1,2})\s+(\w+)(?:\s+(\d{4}))?", date_str)
    if match:
        try:
            day = int(match.group(1))
            month_str = match.group(2).lower()[:3]
            year = int(match.group(3)) if match.group(3) else None

            month_map = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4,
                "may": 5, "jun": 6, "jul": 7, "aug": 8,
                "sep": 9, "oct": 10, "nov": 11, "dec": 12
            }
            month = month_map.get(month_str)
            if not month:
                return None

            if year is None:
                year = TODAY.year
                parsed_date = dt.date(year, month, day)
                # If date is more than 30 days in the past, assume next year
                if parsed_date < TODAY - dt.timedelta(days=30):
                    parsed_date = dt.date(year + 1, month, day)
                return parsed_date
            else:
                return dt.date(year, month, day)
        except ValueError:
            pass

    return None


def _parse_time(time_str: str) -> Optional[str]:
    """
    Parse time string in various formats.
    Returns HH:MM format or None.
    """
    if not time_str:
        return None

    time_str = time_str.strip()

    # Match patterns like "14:30", "2:30pm", "2.30pm", "7pm"
    # 24-hour format
    match_24h = re.match(r"(\d{1,2}):(\d{2})", time_str)
    if match_24h:
        hour = int(match_24h.group(1))
        minute = int(match_24h.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return f"{hour:02d}:{minute:02d}"

    # 12-hour format with am/pm
    match_12h = re.match(r"(\d{1,2})(?:[:\.](\d{2}))?\s*(am|pm)", time_str, re.I)
    if match_12h:
        try:
            hour = int(match_12h.group(1))
            minute = int(match_12h.group(2)) if match_12h.group(2) else 0
            period = match_12h.group(3).lower()

            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0

            if 0 <= hour < 24 and 0 <= minute < 60:
                return f"{hour:02d}:{minute:02d}"
        except ValueError:
            pass

    return None


def _extract_filter_data(html: str) -> List[Dict]:
    """
    Extract event data from _filter_data.push({...}) JavaScript calls.
    Uses brace counting to properly extract nested JSON objects.
    Returns list of event dictionaries.
    """
    events = []

    # Find all _filter_data.push( occurrences
    push_pattern = r'_filter_data\.push\('
    for match in re.finditer(push_pattern, html):
        start_idx = match.end()

        # Count braces to find the matching closing brace
        if start_idx >= len(html) or html[start_idx] != '{':
            continue

        brace_count = 0
        end_idx = start_idx
        in_string = False
        escape_next = False

        for i in range(start_idx, len(html)):
            char = html[i]

            if escape_next:
                escape_next = False
                continue

            if char == '\\':
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break

        if brace_count != 0:
            continue

        json_str = html[start_idx:end_idx]

        try:
            event = json.loads(json_str)
            events.append(event)
        except json.JSONDecodeError:
            # Try to fix common issues
            try:
                # Remove trailing commas before } or ]
                fixed = re.sub(r',\s*([}\]])', r'\1', json_str)
                event = json.loads(fixed)
                events.append(event)
            except json.JSONDecodeError:
                continue

    return events


def _is_cinema_event(event: Dict) -> bool:
    """
    Check if an event is a cinema event.
    Cinema events have event_type containing "101" or slot_tag "Cinema".
    """
    # Check event_type array
    event_types = event.get("event_type", [])
    if isinstance(event_types, list) and "101" in event_types:
        return True

    # Also check slot_tag as backup
    slot_tag = event.get("slot_tag", "")
    if isinstance(slot_tag, str) and "cinema" in slot_tag.lower():
        return True

    return False


def _parse_unix_timestamp(ts: str) -> Optional[dt.datetime]:
    """
    Parse Unix timestamp string to datetime.
    """
    try:
        return dt.datetime.fromtimestamp(int(ts))
    except (ValueError, TypeError, OSError):
        return None


def _extract_metadata_from_event(event: Dict) -> Dict:
    """
    Extract film metadata from an event dictionary.
    """
    metadata = {
        "director": "",
        "runtime_min": "",
        "synopsis": "",
        "year": "",
        "country": "",
    }

    # Extract runtime from duration field or description
    duration = event.get("duration", "")
    if duration:
        runtime_match = re.search(r"(\d+)\s*(?:min|mins|minutes)?", str(duration), re.I)
        if runtime_match:
            metadata["runtime_min"] = runtime_match.group(1)

    # Try to get synopsis from description or content fields
    for field in ["description", "content", "short_description", "blurb"]:
        if event.get(field):
            text = _clean(str(event[field]))
            # Strip HTML tags
            text = re.sub(r"<[^>]+>", " ", text)
            text = _clean(text)
            if text:
                metadata["synopsis"] = text[:500]
                break

    # Try to extract director from synopsis or other fields
    if metadata["synopsis"]:
        director_match = re.search(
            r"Director[:\s]+([A-Za-z\s\-\.]+?)(?:\s*[|\•\n,]|$)",
            metadata["synopsis"]
        )
        if director_match:
            metadata["director"] = _clean(director_match.group(1))

    return metadata


def _extract_booking_url_from_html(performance_html: str) -> str:
    """
    Extract booking URL from performance HTML snippet.
    """
    if not performance_html:
        return ""

    # Look for href in the HTML
    match = re.search(r'href="([^"]+)"', performance_html)
    if match:
        url = match.group(1)
        if url.startswith("/"):
            return BASE_URL + url
        return url
    return ""


def _extract_time_from_html(performance_html: str) -> Optional[str]:
    """
    Extract showtime from performance HTML snippet.
    """
    if not performance_html:
        return None

    # Look for time in performance-time div or just time pattern
    time_match = re.search(r"(\d{1,2}:\d{2})", performance_html)
    if time_match:
        time_str = time_match.group(1)
        parts = time_str.split(":")
        if len(parts) == 2:
            hour = int(parts[0])
            minute = int(parts[1])
            if 0 <= hour < 24 and 0 <= minute < 60:
                return f"{hour:02d}:{minute:02d}"
    return None


def _extract_showtimes_from_event(event: Dict) -> List[Dict]:
    """
    Extract showtimes from an event's performances data.
    """
    shows = []

    title = _clean(event.get("name", "") or event.get("title", ""))
    if not title:
        return []

    # Get the event URL
    event_url = event.get("url", "")
    if event_url and not event_url.startswith("http"):
        event_url = BASE_URL + event_url

    metadata = _extract_metadata_from_event(event)

    # Parse performances object
    # Format: {"unix_timestamp": [{"timestamp": "unix_ts", "html": "<a ...>time</a>"}, ...]}
    performances = event.get("performances", {})

    if not isinstance(performances, dict):
        return []

    for date_ts, perf_list in performances.items():
        # Parse the date from the key timestamp
        date_dt = _parse_unix_timestamp(date_ts)
        if not date_dt:
            continue

        show_date = date_dt.date()

        # Check if within our window
        if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
            continue

        if not isinstance(perf_list, list):
            continue

        for perf in perf_list:
            if not isinstance(perf, dict):
                continue

            # Get time from timestamp or HTML
            perf_ts = perf.get("timestamp", "")
            perf_html = perf.get("html", "")

            show_time = None

            # Try to get time from the timestamp
            if perf_ts:
                perf_dt = _parse_unix_timestamp(perf_ts)
                if perf_dt:
                    show_time = perf_dt.strftime("%H:%M")

            # Fall back to extracting from HTML
            if not show_time:
                show_time = _extract_time_from_html(perf_html)

            if not show_time:
                continue

            # Get booking URL from HTML
            booking_url = _extract_booking_url_from_html(perf_html)

            shows.append({
                "cinema_name": CINEMA_NAME,
                "movie_title": title,
                "movie_title_en": title,
                "date_text": show_date.isoformat(),
                "showtime": show_time,
                "detail_page_url": event_url,
                "booking_url": booking_url,
                "director": metadata["director"],
                "year": metadata["year"],
                "country": metadata["country"],
                "runtime_min": metadata["runtime_min"],
                "synopsis": metadata["synopsis"],
            })

    return shows


def scrape_riverside_studios() -> List[Dict]:
    """
    Scrape Riverside Studios cinema showtimes.

    The what's on page embeds all event data as JavaScript in
    _filter_data.push({...}) calls. Cinema events are identified
    by event_type containing "101" or slot_tag "Cinema".

    Returns a list of showtime records with standard schema.
    """
    shows = []

    try:
        session = requests.Session()

        # Fetch the what's on page
        print(f"[{CINEMA_NAME}] Fetching listings from {WHATS_ON_URL}", file=sys.stderr)
        resp = session.get(WHATS_ON_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        # Extract event data from JavaScript
        events = _extract_filter_data(resp.text)
        print(f"[{CINEMA_NAME}] Found {len(events)} total events in page data", file=sys.stderr)

        # Filter for cinema events
        cinema_events = [e for e in events if _is_cinema_event(e)]
        print(f"[{CINEMA_NAME}] Found {len(cinema_events)} cinema events", file=sys.stderr)

        # Extract showtimes from each cinema event
        for event in cinema_events:
            event_shows = _extract_showtimes_from_event(event)
            shows.extend(event_shows)

        print(f"[{CINEMA_NAME}] Found {len(shows)} total showings", file=sys.stderr)

        if not shows:
            print(f"[{CINEMA_NAME}] Note: No shows found. Page structure may need analysis.", file=sys.stderr)

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
    data = scrape_riverside_studios()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
