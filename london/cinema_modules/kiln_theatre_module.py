#!/usr/bin/env python3
# kiln_theatre_module.py
# Scraper for Kiln Theatre Cinema (Kilburn)
# https://kilntheatre.com/cinema-listings/

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://kilntheatre.com"
CINEMA_LISTINGS_URL = f"{BASE_URL}/cinema-listings/"
CINEMA_NAME = "Kiln Theatre"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 21  # Look 3 weeks ahead


def _clean(text: str) -> str:
    """Clean up whitespace in text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_date_text(date_text: str) -> Optional[dt.date]:
    """
    Parse date strings like "Wednesday 7th January" or "Friday 10th January 2026".
    Handles ordinal suffixes (st, nd, rd, th).
    """
    if not date_text:
        return None

    # Remove ordinal suffixes
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_text, flags=re.IGNORECASE)
    cleaned = _clean(cleaned)

    # Try with year first
    formats_with_year = [
        "%A %d %B %Y",
        "%a %d %B %Y",
        "%A %d %b %Y",
    ]

    for fmt in formats_with_year:
        try:
            return dt.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    # Try without year (assume current/next year)
    formats_without_year = [
        "%A %d %B",
        "%a %d %B",
        "%A %d %b",
    ]

    current_year = TODAY.year

    for fmt in formats_without_year:
        try:
            parsed = dt.datetime.strptime(cleaned, fmt)
            # Assume current year, but if date is in the past, use next year
            result = parsed.replace(year=current_year).date()
            if result < TODAY - dt.timedelta(days=7):  # Allow a week buffer
                result = parsed.replace(year=current_year + 1).date()
            return result
        except ValueError:
            continue

    return None


def _parse_time_text(time_text: str) -> Optional[str]:
    """
    Parse time strings like "11.00AM", "1.30PM", "8.00PM", "14:30".
    Returns 24-hour format HH:MM.
    """
    if not time_text:
        return None

    cleaned = time_text.strip().upper()

    # Handle formats like "11.00AM" or "1.30PM"
    match = re.search(r"(\d{1,2})[:\.](\d{2})\s*(AM|PM)?", cleaned)
    if not match:
        # Try just hour like "8PM"
        match = re.search(r"(\d{1,2})\s*(AM|PM)", cleaned)
        if match:
            hour = int(match.group(1))
            period = match.group(2)
            minute = 0
        else:
            return None
    else:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3)

    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0

    return f"{hour:02d}:{minute:02d}"


def _extract_certificate(text: str) -> str:
    """Extract film certificate like (12A), (15), (PG) from text."""
    match = re.search(r"\(([UPGA0-9]+)\)", text)
    return match.group(1) if match else ""


def scrape_kiln_theatre() -> List[Dict]:
    """
    Scrape Kiln Theatre Cinema showtimes.

    The page has:
    - "Now Showing" and "Coming Soon" sections with film posters
    - A calendar view with dates and showtimes
    - Booking links with instance IDs
    """
    shows: List[Dict] = []

    try:
        session = requests.Session()
        session.trust_env = False

        resp = session.get(CINEMA_LISTINGS_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Method 1: Parse the calendar/schedule view
        # Look for date headers and associated showtimes

        # Find all date sections - typically h3 or similar with day names
        date_headers = soup.find_all(
            lambda tag: tag.name in ["h3", "h4", "h5", "strong", "div"] and
            tag.get_text() and
            re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)",
                     tag.get_text(), re.IGNORECASE)
        )

        current_date = None

        for header in date_headers:
            header_text = _clean(header.get_text())
            parsed_date = _parse_date_text(header_text)

            if not parsed_date:
                continue

            # Check date is within our window
            if not (TODAY <= parsed_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                continue

            current_date = parsed_date

            # Find the container that holds this date's showtimes
            # Usually a parent or sibling element
            container = header.parent
            if not container:
                continue

            # Look for showtime links in this section
            # Links typically go to /whats-on/[film]/book/[id]/
            showtime_links = container.find_all(
                "a", href=re.compile(r"/whats-on/.+/book/")
            )

            if not showtime_links:
                # Try looking in the next sibling
                next_sibling = header.find_next_sibling()
                if next_sibling:
                    showtime_links = next_sibling.find_all(
                        "a", href=re.compile(r"/whats-on/.+/book/")
                    )

            for link in showtime_links:
                link_text = _clean(link.get_text())
                href = link.get("href", "")

                # Extract film title from the link text or href
                # Text format: "[Time] [Film Title] ([Certificate])"
                # Or nested elements with strong for time, span for title

                time_elem = link.find("strong")
                title_elem = link.find("span")

                if time_elem and title_elem:
                    time_text = _clean(time_elem.get_text())
                    title_text = _clean(title_elem.get_text())
                else:
                    # Parse from combined text
                    time_match = re.match(r"(\d{1,2}[:\.]?\d{0,2}\s*(?:AM|PM)?)",
                                         link_text, re.IGNORECASE)
                    if time_match:
                        time_text = time_match.group(1)
                        title_text = link_text[time_match.end():].strip()
                    else:
                        continue

                showtime = _parse_time_text(time_text)
                if not showtime:
                    continue

                # Clean up title - remove certificate
                movie_title = re.sub(r"\s*\([UPGA0-9]+\)\s*$", "", title_text).strip()
                if not movie_title:
                    # Try extracting from href
                    href_match = re.search(r"/whats-on/([^/]+)/", href)
                    if href_match:
                        movie_title = href_match.group(1).replace("-", " ").title()

                if not movie_title:
                    continue

                # Build URLs
                booking_url = urljoin(BASE_URL, href) if href else ""

                # Detail page is the film page without /book/
                detail_match = re.search(r"(/whats-on/[^/]+/)", href)
                detail_url = urljoin(BASE_URL, detail_match.group(1)) if detail_match else ""

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title,
                    "movie_title_en": movie_title,
                    "date_text": current_date.isoformat(),
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                    "booking_url": booking_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
                })

        # Method 2: If calendar parsing didn't work well, try parsing film pages directly
        if not shows:
            shows = _scrape_from_film_cards(soup, session)

        if not shows:
            print(f"[{CINEMA_NAME}] Note: No shows found. Page structure may have changed.",
                  file=sys.stderr)

    except requests.RequestException as e:
        print(f"[{CINEMA_NAME}] HTTP Error: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        return []

    # Deduplicate
    seen = set()
    unique_shows = []
    for s in shows:
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


def _scrape_from_film_cards(soup: BeautifulSoup, session: requests.Session) -> List[Dict]:
    """
    Alternative approach: Find film cards and follow links to get showtimes.
    """
    shows: List[Dict] = []

    # Find film card links - typically images or titles linking to /whats-on/[film]/
    film_links = soup.find_all("a", href=re.compile(r"^/whats-on/[^/]+/?$"))

    seen_films = set()

    for link in film_links:
        href = link.get("href", "")

        # Skip if we've already processed this film
        if href in seen_films:
            continue
        seen_films.add(href)

        # Get film title from link text or nested elements
        title_elem = link.find(["h5", "h4", "h3", "span"])
        if title_elem:
            movie_title = _clean(title_elem.get_text())
        else:
            movie_title = _clean(link.get_text())

        # Remove certificate from title
        movie_title = re.sub(r"\s*\([UPGA0-9]+\)\s*$", "", movie_title).strip()

        if not movie_title or len(movie_title) < 2:
            continue

        # Skip non-film items (like "See All Listings")
        if any(skip in movie_title.lower() for skip in ["see all", "listings", "book now"]):
            continue

        detail_url = urljoin(BASE_URL, href)

        # Fetch the film page to get showtimes
        try:
            film_resp = session.get(detail_url, headers=HEADERS, timeout=TIMEOUT)
            film_resp.raise_for_status()
            film_soup = BeautifulSoup(film_resp.text, "html.parser")

            # Look for showtime/booking links on the film page
            booking_links = film_soup.find_all("a", href=re.compile(r"/book/"))

            for booking_link in booking_links:
                booking_text = _clean(booking_link.get_text())
                booking_href = booking_link.get("href", "")

                # Try to find associated date and time
                # Usually in parent elements or nearby text
                parent = booking_link.parent
                if not parent:
                    continue

                parent_text = _clean(parent.get_text())

                # Look for date pattern
                date_match = re.search(
                    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\w+)",
                    parent_text, re.IGNORECASE
                )

                if date_match:
                    date_str = date_match.group(0)
                    show_date = _parse_date_text(date_str)
                else:
                    continue

                if not show_date or not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                    continue

                # Look for time
                time_match = re.search(r"(\d{1,2}[:\.]?\d{0,2}\s*(?:AM|PM)?)",
                                      booking_text, re.IGNORECASE)
                if time_match:
                    showtime = _parse_time_text(time_match.group(1))
                else:
                    continue

                if not showtime:
                    continue

                booking_url = urljoin(BASE_URL, booking_href)

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title,
                    "movie_title_en": movie_title,
                    "date_text": show_date.isoformat(),
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                    "booking_url": booking_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
                })

        except requests.RequestException:
            continue

    return shows


if __name__ == "__main__":
    data = scrape_kiln_theatre()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\nTotal: {len(data)} showings")
