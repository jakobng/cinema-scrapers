#!/usr/bin/env python3
# cinema_museum_module.py
# Scraper for The Cinema Museum, Kennington
# https://cinemamuseum.org.uk/
#
# Structure: WordPress site with events/screenings
# Features regular film screenings including "Kennington Bioscope" silent film series
# Uses cloudscraper to handle bot protection (503 errors)

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

from bs4 import BeautifulSoup

BASE_URL = "https://cinemamuseum.org.uk"
EVENTS_URL = f"{BASE_URL}/schedule/"
ALT_EVENTS_URL = f"{BASE_URL}/category/events/"
CINEMA_NAME = "The Cinema Museum"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 30  # Cinema Museum events often scheduled further in advance


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_date_text(date_str: str) -> Optional[dt.date]:
    """
    Parse date formats like "January 15, 2026", "15 January 2026", "15th January 2026".
    Returns date object or None if parsing fails.
    """
    date_str = date_str.strip()

    # Remove ordinal suffixes
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    # Remove day name if present
    date_str = re.sub(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[,\s]+",
        "",
        date_str,
        flags=re.IGNORECASE
    )

    current_year = dt.date.today().year

    formats = [
        "%B %d, %Y",    # January 15, 2026
        "%B %d %Y",     # January 15 2026
        "%d %B %Y",     # 15 January 2026
        "%d %B",        # 15 January
        "%B %d",        # January 15
        "%Y-%m-%d",     # 2026-01-15 (ISO format)
    ]

    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(date_str.strip(), fmt)
            if "%Y" not in fmt:
                parsed = parsed.replace(year=current_year)
                if parsed.date() < TODAY - dt.timedelta(days=30):
                    parsed = parsed.replace(year=current_year + 1)
            return parsed.date()
        except ValueError:
            continue

    return None


def _parse_time(time_str: str) -> Optional[str]:
    """
    Parse time formats like "7:30pm", "19:30", "7.30pm".
    Returns 24-hour format string "HH:MM" or None.
    """
    time_str = time_str.strip().lower()

    # Match HH:MM or HH.MM
    match = re.search(r"(\d{1,2})[:.](\d{2})\s*(am|pm)?", time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3)

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    # Match "7pm" or "7 pm" format
    match = re.search(r"(\d{1,2})\s*(am|pm)", time_str)
    if match:
        hour = int(match.group(1))
        period = match.group(2)

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        if 0 <= hour <= 23:
            return f"{hour:02d}:00"

    return None


def _extract_time_from_text(text: str) -> Optional[str]:
    """Extract time from a text block that might contain multiple pieces of info."""
    # Common patterns for event times
    patterns = [
        r"(?:doors?\s*(?:open)?\s*(?:at)?\s*)?(\d{1,2}[:.]?\d{0,2}\s*(?:am|pm))",
        r"(?:starts?\s*(?:at)?\s*)(\d{1,2}[:.]?\d{0,2}\s*(?:am|pm))",
        r"(?:film\s*(?:starts?)?\s*(?:at)?\s*)(\d{1,2}[:.]?\d{0,2}\s*(?:am|pm))",
        r"(\d{1,2}[:.]?\d{2}\s*(?:am|pm))",
        r"(\d{2}:\d{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            time_str = match.group(1)
            parsed = _parse_time(time_str)
            if parsed:
                return parsed

    return None


def _create_session():
    """Create a session with regular requests. Cloudscraper is avoided due to SSL issues with this site."""
    session = requests.Session()
    # Using a curl-like User-Agent as the site blocks modern browsers but allows curl
    session.headers.update({
        "User-Agent": "curl/8.0.0",
        "Accept": "*/*",
    })
    return session


def _fetch_page(session, url: str) -> Optional[str]:
    """Fetch a page with error handling."""
    try:
        resp = session.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error fetching {url}: {e}", file=sys.stderr)
        return None


def _extract_events_from_schedule(soup: BeautifulSoup) -> List[Dict]:
    """
    Extract events from the schedule page.
    WordPress event plugins often use specific class patterns.
    """
    shows = []

    # Try different WordPress event structures

    # Pattern 1: Event list items with date/time/title
    events = soup.select(".tribe-events-calendar-list__event, .event-item, .event, .tribe-event")

    for event in events:
        title_elem = event.select_one(
            ".tribe-events-calendar-list__event-title a, "
            ".event-title, .entry-title, h2 a, h3 a"
        )
        if not title_elem:
            continue

        title = _clean(title_elem.get_text())
        detail_url = title_elem.get("href", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = urljoin(BASE_URL, detail_url)

        # Look for date
        date_elem = event.select_one(
            ".tribe-events-calendar-list__event-date-tag-datetime, "
            ".event-date, .date, time"
        )
        event_date = None
        if date_elem:
            # Try datetime attribute first
            datetime_attr = date_elem.get("datetime", "")
            if datetime_attr:
                event_date = _parse_date_text(datetime_attr.split("T")[0])
            if not event_date:
                event_date = _parse_date_text(_clean(date_elem.get_text()))

        # Look for time
        time_elem = event.select_one(".event-time, .time, .start-time")
        event_time = None
        if time_elem:
            event_time = _parse_time(_clean(time_elem.get_text()))

        # If no specific time element, try to extract from text
        if not event_time:
            event_text = _clean(event.get_text())
            event_time = _extract_time_from_text(event_text)

        # Default time for Cinema Museum events (films typically start at 7:30pm)
        if event_date and not event_time:
            event_time = "19:30"

        if title and event_date:
            if TODAY <= event_date < TODAY + dt.timedelta(days=WINDOW_DAYS):
                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": event_date.isoformat(),
                    "showtime": event_time or "19:30",
                    "detail_page_url": detail_url,
                    "booking_url": detail_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
                    "format_tags": [],
                })

    # Pattern 2: Article-based events (common WordPress pattern)
    if not events:
        articles = soup.select("article, .post, .hentry")
        for article in articles:
            title_elem = article.select_one(".entry-title a, h2 a, h3 a")
            if not title_elem:
                continue

            title = _clean(title_elem.get_text())
            detail_url = title_elem.get("href", "")
            if detail_url and not detail_url.startswith("http"):
                detail_url = urljoin(BASE_URL, detail_url)

            # Skip non-screening posts
            article_text = _clean(article.get_text()).lower()
            if not any(kw in article_text for kw in ["screening", "film", "cinema", "bioscope", "showing"]):
                continue

            # Try to find date in the article
            date_elem = article.select_one(".entry-date, .post-date, time")
            event_date = None
            if date_elem:
                datetime_attr = date_elem.get("datetime", "")
                if datetime_attr:
                    event_date = _parse_date_text(datetime_attr.split("T")[0])
                if not event_date:
                    event_date = _parse_date_text(_clean(date_elem.get_text()))

            # Extract time from article text
            event_time = _extract_time_from_text(article_text)

            if title and event_date:
                if TODAY <= event_date < TODAY + dt.timedelta(days=WINDOW_DAYS):
                    shows.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": title,
                        "movie_title_en": title,
                        "date_text": event_date.isoformat(),
                        "showtime": event_time or "19:30",
                        "detail_page_url": detail_url,
                        "booking_url": detail_url,
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": "",
                        "synopsis": "",
                        "format_tags": [],
                    })

    return shows


def _extract_json_ld_events(soup: BeautifulSoup) -> List[Dict]:
    """Extract events from JSON-LD structured data if available."""
    shows = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            events = []

            if isinstance(data, list):
                events = [d for d in data if d.get("@type") in ["Event", "ScreeningEvent"]]
            elif isinstance(data, dict):
                if data.get("@type") in ["Event", "ScreeningEvent"]:
                    events = [data]
                elif "@graph" in data:
                    events = [d for d in data["@graph"] if d.get("@type") in ["Event", "ScreeningEvent"]]

            for event in events:
                title = event.get("name", "")
                if not title:
                    continue

                # Parse start date/time
                start_date_str = event.get("startDate", "")
                event_date = None
                event_time = None

                if start_date_str:
                    if "T" in start_date_str:
                        date_part, time_part = start_date_str.split("T")[:2]
                        event_date = _parse_date_text(date_part)
                        event_time = _parse_time(time_part)
                    else:
                        event_date = _parse_date_text(start_date_str)

                detail_url = event.get("url", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = urljoin(BASE_URL, detail_url)

                if title and event_date:
                    if TODAY <= event_date < TODAY + dt.timedelta(days=WINDOW_DAYS):
                        shows.append({
                            "cinema_name": CINEMA_NAME,
                            "movie_title": title,
                            "movie_title_en": title,
                            "date_text": event_date.isoformat(),
                            "showtime": event_time or "19:30",
                            "detail_page_url": detail_url,
                            "booking_url": detail_url,
                            "director": "",
                            "year": "",
                            "country": "",
                            "runtime_min": "",
                            "synopsis": event.get("description", "")[:500] if event.get("description") else "",
                            "format_tags": [],
                        })

        except (json.JSONDecodeError, AttributeError):
            continue

    return shows


def scrape_cinema_museum() -> List[Dict]:
    """
    Scrape The Cinema Museum screenings and events.

    Returns a list of showtime records with standard schema.
    Note: Uses cloudscraper to handle bot protection on cinemamuseum.org.uk
    """
    shows = []

    try:
        session = _create_session()

        # Try main schedule URL first
        html_text = _fetch_page(session, EVENTS_URL)

        if not html_text:
            # Try alternative events URL
            html_text = _fetch_page(session, ALT_EVENTS_URL)

        if not html_text:
            print(f"[{CINEMA_NAME}] Could not fetch any events page", file=sys.stderr)
            return []

        soup = BeautifulSoup(html_text, "html.parser")

        # Try JSON-LD extraction first
        shows = _extract_json_ld_events(soup)

        # Fall back to HTML parsing
        if not shows:
            shows = _extract_events_from_schedule(soup)

        print(f"[{CINEMA_NAME}] Found {len(shows)} events", file=sys.stderr)

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
    if not HAS_CLOUDSCRAPER:
        print("Warning: cloudscraper not installed. Bot protection may block requests.", file=sys.stderr)
        print("Install with: pip install cloudscraper", file=sys.stderr)

    data = scrape_cinema_museum()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} events", file=sys.stderr)
