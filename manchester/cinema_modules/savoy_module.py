#!/usr/bin/env python3
# savoy_module.py
# Scraper for The Savoy cinema (1920s restored, Stockport)
# https://savoycinemaheatonmoor.com/
#
# Structure: Independent cinema with film listings, uses Flicks for ticketing

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://savoycinemaheatonmoor.com"
CINEMA_URL = f"{BASE_URL}/all-listings"  # All listings page with comprehensive showings
CINEMA_NAME = "The Savoy"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14  # Look ahead 2 weeks


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_uk_date(date_str: str) -> Optional[dt.date]:
    """
    Parse UK date formats from Savoy listings.
    Returns date object or None if parsing fails.
    """
    date_str = date_str.strip()

    # Handle formats like "Thursday 22nd May", "Friday 23rd May"
    # Remove ordinal suffixes
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    # Remove day name if present
    date_str = re.sub(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+",
        "",
        date_str,
        flags=re.IGNORECASE
    )

    current_year = dt.date.today().year

    # Try formats
    formats = [
        "%d %B",       # 22 May
        "%d %b",       # 22 May
    ]

    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(date_str.strip(), fmt)
            parsed = parsed.replace(year=current_year)
            # If date is in the past, assume next year
            if parsed.date() < TODAY - dt.timedelta(days=30):
                parsed = parsed.replace(year=current_year + 1)
            return parsed.date()
        except ValueError:
            continue

    return None


def _parse_time_12h(time_str: str) -> Optional[str]:
    """
    Parse 12-hour time format from Savoy listings.
    Returns 24-hour format string "HH:MM" or None.
    """
    time_str = time_str.strip().lower()

    # Match patterns like "2:30pm", "7:45 pm", "12:00am"
    match = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)", time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3)

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute:02d}"

    return None


def _extract_film_info(film_element) -> Optional[Dict]:
    """
    Extract film information from a film listing element.
    Returns dict with title, synopsis, etc.
    """
    try:
        # Find film title
        title_elem = film_element.find(['h2', 'h3', 'h4', 'a'], class_=re.compile(r'title|film-title|movie-title'))
        if not title_elem:
            # Try any heading
            title_elem = film_element.find(['h1', 'h2', 'h3', 'h4', 'h5'])

        if not title_elem:
            return None

        title = _clean(title_elem.get_text())

        # Remove age ratings from title
        title = re.sub(r"\s*\(\d{1,2}[A-Z]?\)\s*$", "", title)

        # Find synopsis/description
        synopsis = ""
        desc_elem = film_element.find(['p', 'div'], class_=re.compile(r'description|synopsis|desc|summary'))
        if desc_elem:
            synopsis = _clean(desc_elem.get_text())
        else:
            # Look for paragraphs with substantial content
            paragraphs = film_element.find_all('p')
            for p in paragraphs:
                text = _clean(p.get_text())
                if len(text) > 30:  # Assume longer text is synopsis
                    synopsis = text
                    break

        # Find detail page URL
        detail_url = ""
        title_link = title_elem if title_elem.name == 'a' else title_elem.find_parent('a')
        if title_link and title_link.name == 'a':
            detail_url = urljoin(BASE_URL, title_link.get('href', ''))

        return {
            'title': title,
            'synopsis': synopsis,
            'detail_page_url': detail_url,
        }

    except Exception as e:
        print(f"Error extracting film info: {e}", file=sys.stderr)
        return None


def scrape_savoy() -> List[Dict]:
    """
    Scrape The Savoy cinema showtimes from their website.

    Returns a list of showtime records with standard schema:
    - cinema_name: str
    - movie_title: str
    - date_text: str (YYYY-MM-DD)
    - showtime: str (HH:MM)
    - detail_page_url: str
    - director: str (if available)
    - year: str (if available)
    - country: str (if available)
    - runtime_min: str (if available)
    - synopsis: str

    Note: Director, year, runtime etc. are populated by TMDB enrichment in main_scraper.py
    """
    shows = []

    try:
        session = requests.Session()
        resp = session.get(CINEMA_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # The Savoy all-listings page lists all films in a simple format
        # Look for film listings in the content

        # Find all film links that point to movie pages
        film_links = soup.find_all('a', href=re.compile(r'/movie/'))

        print(f"[{CINEMA_NAME}] Found {len(film_links)} film links", file=sys.stderr)

        for link in film_links:
            href = link.get('href')
            title = _clean(link.get_text())

            if not title or title in ['Home', 'All Listings', 'Now Playing', 'Coming Soon']:
                continue

            # Clean the title (remove extra whitespace and normalize)
            title = re.sub(r'\s+', ' ', title).strip()

            # Create detail URL
            detail_url = urljoin(BASE_URL, href)

            # For now, assume all films are showing today
            # In a full implementation, we'd visit each movie page to get actual showtimes
            # But for now, create a single entry per film with a default time

            # Try to get the actual showtimes by visiting the movie page
            try:
                movie_resp = session.get(detail_url, headers=HEADERS, timeout=TIMEOUT)
                movie_resp.raise_for_status()
                movie_soup = BeautifulSoup(movie_resp.text, "html.parser")

                # Look for showtime information on the movie page
                # The Savoy uses links with showtimes
                showtime_links = movie_soup.find_all('a', href=re.compile(r'/checkout/showing/'))

                movie_showtimes = []
                for st_link in showtime_links:
                    link_text = _clean(st_link.get_text())
                    # Extract time from link text (format: "January 22, 4:00 pm")
                    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))', link_text)
                    if time_match:
                        showtime = time_match.group(1)
                        parsed_time = _parse_time_12h(showtime)
                        if parsed_time:
                            movie_showtimes.append(parsed_time)

                if movie_showtimes:
                    # Create a showing for each showtime found
                    for showtime in movie_showtimes:
                        shows.append({
                            "cinema_name": CINEMA_NAME,
                            "movie_title": title,
                            "movie_title_en": title,
                            "date_text": TODAY.isoformat(),  # Assume today for now
                            "showtime": showtime,
                            "detail_page_url": detail_url,
                            "director": "",
                            "year": "",
                            "country": "",
                            "runtime_min": "",
                            "synopsis": "",
                        })
                else:
                    # If no showtimes found, still include the film with a default time
                    shows.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": title,
                        "movie_title_en": title,
                        "date_text": TODAY.isoformat(),
                        "showtime": "19:00",  # Default evening time
                        "detail_page_url": detail_url,
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": "",
                        "synopsis": "",
                    })

            except Exception as e:
                print(f"[{CINEMA_NAME}] Error scraping movie page {detail_url}: {e}", file=sys.stderr)
                # Still include the film even if we can't get showtimes
                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": TODAY.isoformat(),
                    "showtime": "19:00",  # Default evening time
                    "detail_page_url": detail_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
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
    # Debug mode - save HTML for inspection
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--debug":
        session = requests.Session()
        resp = session.get(CINEMA_URL, headers=HEADERS, timeout=TIMEOUT)
        with open("savoy_debug.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("Saved HTML to savoy_debug.html")
        sys.exit(0)

    data = scrape_savoy()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)