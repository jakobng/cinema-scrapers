#!/usr/bin/env python3
# cine_lumiere_module.py
# Scraper for Ciné Lumière (Institut Français du Royaume-Uni)
# https://www.institut-francais.org.uk/cine-lumiere/
#
# Structure: What's-on page lists films with links to detail pages
# Detail pages contain individual showtimes and booking links to Savoy Systems

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.institut-francais.org.uk"
# Note: /cine-lumiere/whats-on/ redirects to /whats-on/
WHATS_ON_URL = f"{BASE_URL}/whats-on/"
CINEMA_NAME = "Ciné Lumière"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 30  # Wider window as programming often announced far ahead


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_uk_date(date_str: str) -> Optional[dt.date]:
    """
    Parse UK date formats like "Fri 10 Jan", "10 January 2026", "Friday 10 January".
    Returns date object or None if parsing fails.
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Remove day name prefix if present (e.g., "Fri ", "Friday ")
    date_str = re.sub(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*[,\s]+", "", date_str, flags=re.IGNORECASE)

    # Remove ordinal suffixes (1st, 2nd, 3rd, 4th, etc.)
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    current_year = dt.date.today().year

    # Try various formats
    formats = [
        "%d %B %Y",      # 10 January 2026
        "%d %b %Y",      # 10 Jan 2026
        "%d %B",         # 10 January (assume current/next year)
        "%d %b",         # 10 Jan
        "%Y-%m-%d",      # 2026-01-10
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


def _parse_time_24h(time_str: str) -> Optional[str]:
    """
    Parse time format like "18:30", "6:30pm", "18.30".
    Returns 24-hour format string "HH:MM" or None.
    """
    if not time_str:
        return None

    time_str = time_str.strip().lower()

    # Try 24-hour format first: "18:30" or "18.30"
    match = re.match(r"(\d{1,2})[:\.](\d{2})(?:\s*(am|pm))?", time_str)
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

    # Try without minutes: "6pm"
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


def _extract_film_links(soup: BeautifulSoup) -> List[Dict]:
    """
    Extract film links from the what's-on page.
    Returns list of dicts with title, url.
    """
    films = {}  # url -> title mapping

    # Category slugs to skip (not individual films)
    skip_slugs = {
        "new-releases", "classics", "cinefamilies", "festivals-series",
        "special-screenings", "cinema", ""
    }

    # Look for links to /cinema/ detail pages
    for link in soup.select("a[href*='/cinema/']"):
        href = link.get("href", "")
        if not href:
            continue

        # Extract slug from URL: /cinema/film-name/ -> film-name
        match = re.search(r"/cinema/([^/]+)/?$", href)
        if not match:
            continue

        slug = match.group(1).lower()

        # Skip category pages
        if slug in skip_slugs:
            continue

        url = urljoin(BASE_URL, href)

        # Get title from link text
        title = _clean(link.get_text())

        # If title is too long (includes description), extract just the first part
        if title and len(title) > 80:
            # Often the title is on first line before description
            first_line = title.split("\n")[0] if "\n" in title else title
            title = _clean(first_line[:80])

        # If no title from link, try parent element
        if not title or len(title) < 2:
            parent = link.find_parent(["article", "div", "li"])
            if parent:
                for selector in ["h2", "h3", "h4", ".title", ".film-title", "strong"]:
                    title_elem = parent.select_one(selector)
                    if title_elem:
                        title = _clean(title_elem.get_text())
                        if title and len(title) > 1:
                            break

        # Store/update - prefer non-empty titles
        if url not in films or (title and len(title) > len(films.get(url, ""))):
            films[url] = title

    # Convert to list, using slug as fallback title
    result = []
    for url, title in films.items():
        if not title:
            # Generate title from slug: "a-monkey-in-winter" -> "A Monkey In Winter"
            match = re.search(r"/cinema/([^/]+)/?$", url)
            if match:
                title = match.group(1).replace("-", " ").title()

        if title:
            result.append({"title": title, "url": url})

    return result


def _extract_screenings_from_detail(soup: BeautifulSoup, film_title: str, detail_url: str) -> List[Dict]:
    """
    Extract individual screenings from a film detail page.
    Looks for date/time patterns and booking links.
    """
    shows = []
    page_text = soup.get_text()

    # Patterns for finding screenings
    # Ciné Lumière uses formats like "Sun 12 Jan at 15:30" or separate date/time elements

    # Pattern: "Day DD Mon at HH:MM" or "Day DD Month at HH:MM"
    datetime_pattern = re.compile(
        r"((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s+\d{4})?)"
        r"\s*(?:at|@|,)?\s*"
        r"(\d{1,2}[:\.]?\d{2}(?:\s*(?:am|pm))?)",
        re.IGNORECASE
    )

    # Find all matches in page text
    for match in datetime_pattern.finditer(page_text):
        date_str = match.group(1)
        time_str = match.group(2)

        parsed_date = _parse_uk_date(date_str)
        parsed_time = _parse_time_24h(time_str)

        if not parsed_date or not parsed_time:
            continue

        # Check if within date window
        if not (TODAY <= parsed_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
            continue

        shows.append({
            "cinema_name": CINEMA_NAME,
            "movie_title": film_title,
            "movie_title_en": film_title,
            "date_text": parsed_date.isoformat(),
            "showtime": parsed_time,
            "detail_page_url": detail_url,
            "booking_url": "",
            "director": "",
            "year": "",
            "country": "",
            "runtime_min": "",
            "synopsis": "",
        })

    # Alternative: Look for structured screening elements
    # Try to find screening time blocks
    for elem in soup.select(".screening, .showtime, .performance, [class*='screening'], [class*='time']"):
        text = elem.get_text()

        # Look for date and time in the element
        date_match = re.search(
            r"((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s+\d{4})?)",
            text, re.IGNORECASE
        )
        time_match = re.search(r"(\d{1,2}[:\.]?\d{2}(?:\s*(?:am|pm))?)", text, re.IGNORECASE)

        if date_match and time_match:
            parsed_date = _parse_uk_date(date_match.group(1))
            parsed_time = _parse_time_24h(time_match.group(1))

            if parsed_date and parsed_time:
                if TODAY <= parsed_date < TODAY + dt.timedelta(days=WINDOW_DAYS):
                    shows.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": film_title,
                        "movie_title_en": film_title,
                        "date_text": parsed_date.isoformat(),
                        "showtime": parsed_time,
                        "detail_page_url": detail_url,
                        "booking_url": "",
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": "",
                        "synopsis": "",
                    })

    # Try to extract film metadata
    director = ""
    year = ""
    runtime = ""
    country = ""

    # Look for metadata in page
    meta_text = page_text.lower()

    # Director patterns
    director_match = re.search(r"(?:directed?\s+by|director)[:\s]+([A-Za-z\s\-']+?)(?:\n|,|\||$)", page_text, re.IGNORECASE)
    if director_match:
        director = _clean(director_match.group(1))

    # Year pattern
    year_match = re.search(r"\b(19[5-9]\d|20[0-2]\d)\b", page_text)
    if year_match:
        year = year_match.group(1)

    # Runtime pattern
    runtime_match = re.search(r"(\d{2,3})\s*(?:min(?:ute)?s?|')", page_text, re.IGNORECASE)
    if runtime_match:
        runtime = runtime_match.group(1)

    # Country pattern (often in format "France, 2024, 95 mins")
    country_match = re.search(r"(France|UK|USA|Germany|Italy|Spain|Japan|South Korea|Belgium|Switzerland|Canada|Australia)", page_text, re.IGNORECASE)
    if country_match:
        country = country_match.group(1)

    # Update shows with metadata
    for show in shows:
        if director and not show.get("director"):
            show["director"] = director
        if year and not show.get("year"):
            show["year"] = year
        if runtime and not show.get("runtime_min"):
            show["runtime_min"] = runtime
        if country and not show.get("country"):
            show["country"] = country

    return shows


def _get_listings_from_whats_on(session: requests.Session) -> List[Dict]:
    """
    Fetch the what's-on page and extract film listings.
    Uses month view for more comprehensive listings.
    """
    films = []

    # Try multiple views to get comprehensive listings
    views = ["", "?view=week", "?view=month"]

    seen_urls = set()

    for view in views:
        try:
            url = WHATS_ON_URL + view
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            page_films = _extract_film_links(soup)

            for film in page_films:
                if film["url"] not in seen_urls:
                    seen_urls.add(film["url"])
                    films.append(film)

        except requests.RequestException as e:
            print(f"[{CINEMA_NAME}] Error fetching {url}: {e}", file=sys.stderr)
            continue

    return films


def scrape_cine_lumiere() -> List[Dict]:
    """
    Scrape Ciné Lumière showtimes.

    Process:
    1. Fetch what's-on page(s) to get list of current films
    2. For each film, visit detail page to extract individual showtimes

    Returns a list of showtime records with standard schema.
    """
    shows = []

    try:
        session = requests.Session()

        # Get list of films from what's-on page
        film_listings = _get_listings_from_whats_on(session)
        print(f"[{CINEMA_NAME}] Found {len(film_listings)} film listings", file=sys.stderr)

        if not film_listings:
            print(f"[{CINEMA_NAME}] Warning: No film listings found on main page", file=sys.stderr)
            return []

        # Visit each film's detail page to get showtimes
        for film in film_listings[:40]:  # Limit to avoid too many requests
            title = film["title"]
            url = film["url"]

            try:
                resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")

                # Try to get better title from the detail page
                h1 = soup.select_one("h1")
                if h1:
                    page_title = _clean(h1.get_text())
                    if page_title and len(page_title) > 1:
                        title = page_title

                film_shows = _extract_screenings_from_detail(soup, title, url)

                if film_shows:
                    print(f"[{CINEMA_NAME}] Found {len(film_shows)} screenings for '{title}'", file=sys.stderr)
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
    data = scrape_cine_lumiere()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
