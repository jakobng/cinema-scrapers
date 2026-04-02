#!/usr/bin/env python3
# rich_mix_module.py
# Scraper for Rich Mix cinema
# https://www.richmix.org.uk/
#
# Structure:
# - Film listings on /whats-on/ page with links to /cinema/[slug]/
# - Each film detail page contains showtimes organized by date
# - Dates in format "Sun 11 Jan", times in format "2.20pm"
# - Uses Spektrix for ticketing with booking links like /book-online/[id]

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.richmix.org.uk"
WHATS_ON_URL = f"{BASE_URL}/whats-on/"
CINEMA_NAME = "Rich Mix"

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
    Parse date string in formats like "Sun 11 Jan", "Today", "Tomorrow".
    Returns date object or None.
    """
    if not date_str:
        return None

    date_str = date_str.strip().lower()

    if date_str == "today":
        return TODAY
    if date_str == "tomorrow":
        return TODAY + dt.timedelta(days=1)

    # Parse "Sun 11 Jan" or "11 Jan" format
    # Try with day of week
    match = re.match(r"(?:\w+\s+)?(\d{1,2})\s+(\w+)", date_str, re.I)
    if not match:
        return None

    try:
        day = int(match.group(1))
        month_str = match.group(2).lower()[:3]

        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "may": 5, "jun": 6, "jul": 7, "aug": 8,
            "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        month = month_map.get(month_str)
        if not month:
            return None

        # Determine year - if date seems to be in the past, assume next year
        current_year = TODAY.year
        try:
            parsed_date = dt.date(current_year, month, day)
        except ValueError:
            return None

        # If date is more than 30 days in the past, assume next year
        if parsed_date < TODAY - dt.timedelta(days=30):
            parsed_date = dt.date(current_year + 1, month, day)

        return parsed_date
    except (ValueError, AttributeError):
        return None


def _parse_time(time_str: str) -> Optional[str]:
    """
    Parse time string in format "2.20pm" or "7.00pm".
    Returns HH:MM format or None.
    """
    if not time_str:
        return None

    time_str = time_str.strip().lower()

    # Match patterns like "2.20pm", "12.00pm", "7pm"
    match = re.match(r"(\d{1,2})(?:\.(\d{2}))?(?:\s*)?(am|pm)", time_str)
    if not match:
        return None

    try:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        period = match.group(3)

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute:02d}"
    except (ValueError, AttributeError):
        return None


def _extract_cinema_links(soup: BeautifulSoup) -> List[str]:
    """
    Extract all cinema film links from the what's on page.
    Returns list of URLs like https://richmix.org.uk/cinema/film-slug/
    """
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Match full URLs like https://richmix.org.uk/cinema/something/
        if re.match(r"^https?://(?:www\.)?richmix\.org\.uk/cinema/[^/]+/?$", href):
            full_url = href.rstrip("/") + "/"
            if full_url not in links:
                links.append(full_url)
        # Also match relative URLs like /cinema/something/
        elif re.match(r"^/cinema/[^/]+/?$", href):
            full_url = BASE_URL + href.rstrip("/") + "/"
            if full_url not in links:
                links.append(full_url)
    return links


def _extract_film_metadata(soup: BeautifulSoup) -> Dict:
    """
    Extract film metadata from the detail page.
    Returns dict with director, runtime_min, synopsis, year, country.
    """
    metadata = {
        "director": "",
        "runtime_min": "",
        "synopsis": "",
        "year": "",
        "country": "",
    }

    # Look for the film info section
    # Director is often in format "Director: Name" or similar
    page_text = soup.get_text(" ", strip=True)

    # Try to find director
    director_match = re.search(r"Director[:\s]+([A-Za-z\s\-\.]+?)(?:\s*[|\•]|\s*Duration|\s*Cast|\s*$)", page_text)
    if director_match:
        metadata["director"] = _clean(director_match.group(1))

    # Try to find runtime - look for "Duration: X minutes" or "X minutes"
    runtime_match = re.search(r"(?:Duration[:\s]*)?(\d+)\s*(?:min(?:ute)?s?)", page_text, re.I)
    if runtime_match:
        metadata["runtime_min"] = runtime_match.group(1)

    # Look for synopsis in meta description or specific elements
    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc and meta_desc.get("content"):
        metadata["synopsis"] = _clean(meta_desc["content"])[:500]

    # Also try og:description
    if not metadata["synopsis"]:
        og_desc = soup.find("meta", {"property": "og:description"})
        if og_desc and og_desc.get("content"):
            metadata["synopsis"] = _clean(og_desc["content"])[:500]

    return metadata


def _extract_showtimes_from_detail_page(soup: BeautifulSoup, film_url: str) -> List[Dict]:
    """
    Extract showtimes from a film detail page.
    Returns list of showtime records.
    """
    shows = []

    # Get film title from page
    title = ""
    title_elem = soup.find("h1")
    if title_elem:
        title = _clean(title_elem.get_text())

    if not title:
        # Try og:title
        og_title = soup.find("meta", {"property": "og:title"})
        if og_title and og_title.get("content"):
            title = _clean(og_title["content"])
            # Remove "- Rich Mix" suffix if present
            title = re.sub(r"\s*[-–]\s*Rich Mix.*$", "", title, flags=re.I)

    if not title:
        return []

    # Clean up title - remove status text and ratings
    # Remove patterns like "now showing 15", "From Fri 9 Jan 12A", etc.
    title = re.sub(r"\s+now showing\s*\d*[A-Z]*\s*$", "", title, flags=re.I)
    title = re.sub(r"\s+From\s+\w+\s+\d+\s+\w+\s*\d*[A-Z]*\s*$", "", title, flags=re.I)
    # Remove standalone ratings at the end like "15", "12A", "PG", "U", "18"
    title = re.sub(r"\s+(?:U|PG|12A?|15|18|tbc)\s*$", "", title, flags=re.I)
    title = _clean(title)

    # Get metadata
    metadata = _extract_film_metadata(soup)

    # Find the booking/showtimes section
    # Looking for patterns like "Today: 2.20pm, 5.40pm" or date headers with time links

    # Strategy 1: Look for booking links with /book-online/ pattern
    # The times are often links with format like <a href="/book-online/1794002">2.20pm</a>

    current_date = None
    page_content = soup.get_text(" ", strip=True)

    # Look for date sections with times
    # Pattern: "Today" or "Tomorrow" or "Sun 11 Jan" followed by times
    date_pattern = r"(Today|Tomorrow|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+\w+)"
    time_pattern = r"(\d{1,2}(?:\.\d{2})?(?:am|pm))"

    # Find all booking links and their context
    booking_links = soup.find_all("a", href=re.compile(r"/book-online/\d+"))

    if booking_links:
        # Extract parent context to find dates
        for link in booking_links:
            time_text = _clean(link.get_text())
            parsed_time = _parse_time(time_text)
            if not parsed_time:
                continue

            booking_url = BASE_URL + link["href"]

            # Try to find the date for this time by looking at parent elements
            parent = link.parent
            found_date = None

            # Walk up the tree to find date context
            for _ in range(10):  # Limit depth
                if parent is None:
                    break
                parent_text = parent.get_text(" ", strip=True)

                # Look for date in the parent text
                date_match = re.search(date_pattern, parent_text, re.I)
                if date_match:
                    found_date = _parse_date(date_match.group(1))
                    break
                parent = parent.parent

            if not found_date:
                # Default to today if we can't find a date
                found_date = TODAY

            # Check if date is within our window
            if not (TODAY <= found_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                continue

            shows.append({
                "cinema_name": CINEMA_NAME,
                "movie_title": title,
                "movie_title_en": title,
                "date_text": found_date.isoformat(),
                "showtime": parsed_time,
                "detail_page_url": film_url,
                "booking_url": booking_url,
                "director": metadata["director"],
                "year": metadata["year"],
                "country": metadata["country"],
                "runtime_min": metadata["runtime_min"],
                "synopsis": metadata["synopsis"],
                "format_tags": [],
            })

    # Strategy 2: If no booking links found, try to parse text patterns
    if not shows:
        # Split page into sections and look for date/time patterns
        sections = re.split(date_pattern, page_content, flags=re.I)

        i = 1  # Start from 1 since split puts matches at odd indices
        while i < len(sections):
            date_text = sections[i] if i < len(sections) else None
            content = sections[i + 1] if i + 1 < len(sections) else ""

            if date_text:
                parsed_date = _parse_date(date_text)
                if parsed_date and TODAY <= parsed_date < TODAY + dt.timedelta(days=WINDOW_DAYS):
                    # Find all times in the following content
                    times = re.findall(time_pattern, content, re.I)
                    for time_text in times:
                        parsed_time = _parse_time(time_text)
                        if parsed_time:
                            shows.append({
                                "cinema_name": CINEMA_NAME,
                                "movie_title": title,
                                "movie_title_en": title,
                                "date_text": parsed_date.isoformat(),
                                "showtime": parsed_time,
                                "detail_page_url": film_url,
                                "booking_url": "",
                                "director": metadata["director"],
                                "year": metadata["year"],
                                "country": metadata["country"],
                                "runtime_min": metadata["runtime_min"],
                                "synopsis": metadata["synopsis"],
                                "format_tags": [],
                            })
            i += 2

    return shows


def scrape_rich_mix() -> List[Dict]:
    """
    Scrape Rich Mix cinema showtimes.

    Fetches the what's on page to get film links, then scrapes each
    film's detail page for showtimes.

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

        # Fetch the what's on page to get film links
        print(f"[{CINEMA_NAME}] Fetching listings from {WHATS_ON_URL}", file=sys.stderr)
        resp = session.get(WHATS_ON_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        cinema_links = _extract_cinema_links(soup)

        print(f"[{CINEMA_NAME}] Found {len(cinema_links)} film pages", file=sys.stderr)

        # Fetch each film detail page
        for film_url in cinema_links:
            try:
                print(f"[{CINEMA_NAME}] Fetching {film_url}", file=sys.stderr)
                resp = session.get(film_url, headers=HEADERS, timeout=TIMEOUT)
                resp.raise_for_status()

                film_soup = BeautifulSoup(resp.text, "html.parser")
                film_shows = _extract_showtimes_from_detail_page(film_soup, film_url)
                shows.extend(film_shows)

            except requests.RequestException as e:
                print(f"[{CINEMA_NAME}] Error fetching {film_url}: {e}", file=sys.stderr)
                continue

        print(f"[{CINEMA_NAME}] Found {len(shows)} total showings", file=sys.stderr)

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
    data = scrape_rich_mix()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
