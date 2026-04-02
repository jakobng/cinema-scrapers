#!/usr/bin/env python3
# ica_module.py
# Scraper for ICA (Institute of Contemporary Arts) Cinema
# https://www.ica.art/films
#
# Structure: Film listings on /films, detail pages contain individual showtimes
# Showtimes displayed as plain text: "01:45 pm" | "Fri, 09 Jan 2026" | "Cinema 2"

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.ica.art"
FILMS_URL = f"{BASE_URL}/films"
CINEMA_NAME = "ICA Cinema"

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


def _parse_uk_date(date_str: str) -> Optional[dt.date]:
    """
    Parse UK date formats like "Fri, 09 Jan 2026", "9 January 2026", "09 Jan".
    Returns date object or None if parsing fails.
    """
    date_str = date_str.strip()

    # Remove day name prefix if present (e.g., "Fri, ")
    date_str = re.sub(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s*", "", date_str, flags=re.IGNORECASE)

    # Remove ordinal suffixes (1st, 2nd, 3rd, 4th, etc.)
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    current_year = dt.date.today().year

    # Try various formats
    formats = [
        "%d %B %Y",      # 9 January 2026
        "%d %b %Y",      # 09 Jan 2026
        "%d %B",         # 9 January (assume current/next year)
        "%d %b",         # 09 Jan
        "%Y-%m-%d",      # 2026-01-09
    ]

    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(date_str.strip(), fmt)
            # If no year in format, determine year
            if "%Y" not in fmt:
                parsed = parsed.replace(year=current_year)
                if parsed.date() < TODAY - dt.timedelta(days=30):
                    parsed = parsed.replace(year=current_year + 1)
            return parsed.date()
        except ValueError:
            continue

    return None


def _parse_time_12h(time_str: str) -> Optional[str]:
    """
    Parse 12-hour time format like "1:45 pm", "6.20pm", "6:20 pm".
    Returns 24-hour format string "HH:MM" or None.
    """
    time_str = time_str.strip().lower()

    # Handle both : and . as separators
    # Match patterns like "1:45 pm", "6.20pm", "12:00 am"
    match = re.match(r"(\d{1,2})[:\.](\d{2})\s*(am|pm)", time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3)

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute:02d}"

    # Also try without minutes (e.g., "2pm")
    match = re.match(r"(\d{1,2})\s*(am|pm)", time_str)
    if match:
        hour = int(match.group(1))
        period = match.group(2)

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        return f"{hour:02d}:00"

    return None


def _extract_title_from_detail_page(soup: BeautifulSoup, detail_url: str, fallback_title: str) -> str:
    """
    Extract the actual film title from a detail page.
    Falls back to URL slug or the provided fallback title.
    """
    # Method 1: Look for h1 or primary heading
    h1 = soup.find("h1")
    if h1:
        title = _clean(h1.get_text())
        # Skip if it's a generic program heading
        if title and not title.lower().startswith(("in focus:", "narrow margin", "long takes")):
            return title

    # Method 2: Look for title in metadata block
    # ICA often has: "_Ballet_, dir. Frederick Wiseman, US 1995, 170 min."
    meta_pattern = re.compile(r"_([^_]+)_,\s*dir\.", re.IGNORECASE)
    page_text = soup.get_text()
    meta_match = meta_pattern.search(page_text)
    if meta_match:
        return meta_match.group(1).strip()

    # Method 3: Extract from URL slug as fallback
    # e.g., /films/menus-plaisirs-les-troisgros -> "Menus Plaisirs Les Troisgros"
    slug_match = re.search(r"/films/([^/]+)/?$", detail_url)
    if slug_match:
        slug = slug_match.group(1)
        # Skip program slugs
        if not slug.startswith(("in-focus-", "narrow-margin-", "long-takes")):
            # Convert slug to title case
            title = slug.replace("-", " ").title()
            return title

    return fallback_title


def _is_program_page(soup: BeautifulSoup, url: str) -> bool:
    """
    Detect if this is a program/series page (like "In Focus: Frederick Wiseman")
    that contains multiple films, rather than an individual film page.
    """
    # Check URL patterns for program pages
    program_patterns = [
        r"/films/in-focus-",
        r"/films/narrow-margin-",
        r"/films/long-takes",
        r"/films/off-circuit",
    ]
    for pattern in program_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True

    return False


def _extract_films_from_program_page(soup: BeautifulSoup, session: requests.Session) -> List[Dict]:
    """
    Extract individual film listings from a program page.
    Returns list of {title, url} for each film in the program.
    """
    films = []
    seen_urls = set()

    # Look for film links within the program page
    # These typically link to individual film detail pages
    for link in soup.select("a[href*='/films/']"):
        href = link.get("href", "")
        if not href or href in seen_urls:
            continue

        # Skip self-referential and navigation links
        if re.search(r"/films/(in-focus-|narrow-margin-|long-takes|off-circuit|\d{4}$|today|tomorrow)", href):
            continue

        seen_urls.add(href)
        url = urljoin(BASE_URL, href)
        title = _clean(link.get_text())

        if title and len(title) > 2:
            films.append({
                "title": title,
                "url": url,
            })

    return films


def _extract_screenings_from_detail_page(soup: BeautifulSoup, film_title: str, detail_url: str) -> List[Dict]:
    """
    Extract individual screenings from a film detail page.
    Screenings are typically shown as: time | date | venue
    """
    shows = []

    # First, try to get the actual film title from the page
    actual_title = _extract_title_from_detail_page(soup, detail_url, film_title)

    # Get the full page text for pattern matching
    page_text = soup.get_text()

    # Look for screening patterns in the text
    # Pattern: time (1:45 pm) followed by date (Fri, 09 Jan 2026) and optionally venue (Cinema 2)
    # Multiple screenings may be listed

    # Try to find screening blocks - they often appear in a structured section
    # Look for common patterns

    # Pattern 1: Look for links with "Book tickets" near time/date info
    book_links = soup.find_all("a", string=re.compile(r"book\s*tickets?", re.I))

    # Pattern 2: Look for time patterns in the page
    time_pattern = re.compile(r"(\d{1,2}[:\.]?\d{2}\s*(?:am|pm))", re.I)
    date_pattern = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s*\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{4}", re.I)

    # Find all time matches and nearby dates
    times_found = time_pattern.findall(page_text)
    dates_found = date_pattern.findall(page_text)

    # Try to pair times with dates
    # Look for screening info blocks
    screening_blocks = []

    # Method 1: Look for structured screening elements
    # ICA may use various selectors for screenings
    for selector in [".screening", ".showtime", ".performance", ".event-time",
                     "[class*='screening']", "[class*='showtime']", "li", "p"]:
        elements = soup.select(selector)
        for elem in elements:
            text = elem.get_text()
            time_match = time_pattern.search(text)
            date_match = date_pattern.search(text)

            if time_match and date_match:
                screening_blocks.append({
                    "time_str": time_match.group(1),
                    "date_str": date_match.group(0),
                    "venue": "",
                    "text": text
                })

    # Method 2: Parse adjacent text patterns
    # Look for lines containing both time and date
    lines = page_text.split("\n")
    for line in lines:
        line = line.strip()
        time_match = time_pattern.search(line)
        date_match = date_pattern.search(line)

        if time_match and date_match:
            # Check if we already have this
            existing = any(
                b["time_str"] == time_match.group(1) and b["date_str"] == date_match.group(0)
                for b in screening_blocks
            )
            if not existing:
                # Try to extract venue (Cinema 1, Cinema 2, etc.)
                venue_match = re.search(r"(Cinema\s*\d+|Theatre)", line, re.I)
                screening_blocks.append({
                    "time_str": time_match.group(1),
                    "date_str": date_match.group(0),
                    "venue": venue_match.group(1) if venue_match else "",
                    "text": line
                })

    # If no structured screenings found, try a broader search
    if not screening_blocks:
        # Look for any pairing of time and date in proximity
        # This is a fallback for less structured pages
        for i, time_str in enumerate(times_found):
            if i < len(dates_found):
                screening_blocks.append({
                    "time_str": time_str,
                    "date_str": dates_found[i],
                    "venue": "",
                    "text": ""
                })

    # Convert screening blocks to show records
    for block in screening_blocks:
        parsed_time = _parse_time_12h(block["time_str"])
        parsed_date = _parse_uk_date(block["date_str"])

        if not parsed_time or not parsed_date:
            continue

        # Check if within date window
        if not (TODAY <= parsed_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
            continue

        shows.append({
            "cinema_name": CINEMA_NAME,
            "movie_title": actual_title,
            "movie_title_en": actual_title,
            "date_text": parsed_date.isoformat(),
            "showtime": parsed_time,
            "detail_page_url": detail_url,
            "booking_url": "",
            "venue": block.get("venue", ""),
            "director": "",
            "year": "",
            "country": "",
            "runtime_min": "",
            "synopsis": "",
        })

    return shows


def _get_film_listings(session: requests.Session) -> List[dict]:
    """
    Fetch the main films page and extract film listings.
    Returns list of dicts with title, url, date_range.
    """
    films = []
    skip_paths = {
        "/films",
        "/films/",
        "/films/today",
        "/films/tomorrow",
        "/films/next-7-days",
    }

    resp = session.get(FILMS_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Look for film items
    # ICA uses .item elements with links to film pages
    items = soup.select(".item a[href*='/films/']")

    seen_urls = set()
    for item in items:
        href = item.get("href", "")
        if not href or href in seen_urls:
            continue

        # Skip non-film links (like /films itself)
        if href in skip_paths or re.fullmatch(r"/films/\d{4}", href):
            continue

        seen_urls.add(href)
        url = urljoin(BASE_URL, href)

        # Try to get title
        title_elem = item.select_one(".title")
        if title_elem:
            title = _clean(title_elem.get_text())
        else:
            title = _clean(item.get_text())

        # Try to get date range
        date_elem = item.select_one(".date")
        date_range = _clean(date_elem.get_text()) if date_elem else ""

        if title:
            films.append({
                "title": title,
                "url": url,
                "date_range": date_range,
            })

    # Also look for broader item patterns
    if not films:
        for item in soup.select("a[href*='/films/']"):
            href = item.get("href", "")
            if not href or href in seen_urls or href in skip_paths or re.fullmatch(r"/films/\d{4}", href):
                continue

            seen_urls.add(href)
            url = urljoin(BASE_URL, href)
            title = _clean(item.get_text())

            if title and len(title) > 2:
                films.append({
                    "title": title,
                    "url": url,
                    "date_range": "",
                })

    return films


def scrape_ica() -> List[Dict]:
    """
    Scrape ICA Cinema showtimes.

    Process:
    1. Fetch main /films page to get list of current films
    2. For each film, visit detail page to extract individual showtimes

    Returns a list of showtime records with standard schema:
    - cinema_name: str
    - movie_title: str
    - date_text: str (YYYY-MM-DD)
    - showtime: str (HH:MM)
    - detail_page_url: str
    - director, year, country, runtime_min, synopsis: str (optional)
    """
    shows = []

    try:
        session = requests.Session()

        # Get list of films
        film_listings = _get_film_listings(session)
        print(f"[{CINEMA_NAME}] Found {len(film_listings)} film listings", file=sys.stderr)

        if not film_listings:
            print(f"[{CINEMA_NAME}] Warning: No film listings found on main page", file=sys.stderr)
            return []

        # Track URLs we've already processed to avoid duplicates
        processed_urls = set()

        # Visit each film's detail page to get showtimes
        for film in film_listings[:30]:  # Limit to avoid too many requests
            title = film["title"]
            url = film["url"]

            if url in processed_urls:
                continue
            processed_urls.add(url)

            try:
                resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")

                # Check if this is a program page (e.g., "In Focus: Frederick Wiseman")
                if _is_program_page(soup, url):
                    print(f"[{CINEMA_NAME}] Detected program page: '{title}', extracting individual films...", file=sys.stderr)
                    # Extract individual film links from the program page
                    program_films = _extract_films_from_program_page(soup, session)
                    print(f"[{CINEMA_NAME}]   Found {len(program_films)} films in program", file=sys.stderr)

                    # Process each individual film
                    for pf in program_films[:15]:  # Limit films per program
                        pf_url = pf["url"]
                        pf_title = pf["title"]

                        if pf_url in processed_urls:
                            continue
                        processed_urls.add(pf_url)

                        try:
                            pf_resp = session.get(pf_url, headers=HEADERS, timeout=TIMEOUT)
                            pf_resp.raise_for_status()
                            pf_soup = BeautifulSoup(pf_resp.text, "html.parser")

                            pf_shows = _extract_screenings_from_detail_page(pf_soup, pf_title, pf_url)
                            if pf_shows:
                                print(f"[{CINEMA_NAME}]   Found {len(pf_shows)} screenings for '{pf_shows[0]['movie_title']}'", file=sys.stderr)
                                shows.extend(pf_shows)

                        except Exception as e:
                            print(f"[{CINEMA_NAME}]   Error processing program film {pf_title}: {e}", file=sys.stderr)
                            continue
                else:
                    # Regular film detail page
                    film_shows = _extract_screenings_from_detail_page(soup, title, url)

                    if film_shows:
                        print(f"[{CINEMA_NAME}] Found {len(film_shows)} screenings for '{film_shows[0]['movie_title']}'", file=sys.stderr)
                        shows.extend(film_shows)

            except requests.RequestException as e:
                print(f"[{CINEMA_NAME}] Error fetching {url}: {e}", file=sys.stderr)
                continue
            except Exception as e:
                print(f"[{CINEMA_NAME}] Error processing {title}: {e}", file=sys.stderr)
                continue

        print(f"[{CINEMA_NAME}] Total: {len(shows)} showings found", file=sys.stderr)

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
    data = scrape_ica()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
