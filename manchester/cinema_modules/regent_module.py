#!/usr/bin/env python3
# regent_module.py
# Scraper for Regent Cinema (1931 venue in Marple)
# https://regentmarple.co.uk/
#
# Structure: Independent cinema with traditional website format

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://regentmarple.co.uk"
WHATSON_URL = f"{BASE_URL}/RegentCinemaMarple.dll/WhatsOn"
CINEMA_NAME = "Regent Cinema"

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
    Parse UK date formats from Regent listings.
    Returns date object or None if parsing fails.
    """
    date_str = date_str.strip()

    # Handle formats like "Friday 22nd November", "Saturday 23rd November"
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
        "%d %B",       # 22 November
        "%d %b",       # 22 Nov
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
    Parse 12-hour time format from Regent listings.
    Returns 24-hour format string "HH:MM" or None.
    """
    time_str = time_str.strip().lower()

    # Match patterns like "2:30pm", "7:45 pm", "12:15am"
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
    Extract film information from a Regent film listing element.
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


def scrape_regent() -> List[Dict]:
    """
    Scrape Regent Cinema showtimes from their website.

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
        resp = session.get(WHATSON_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for embedded JSON data with Events
        events_data = None
        scripts = soup.find_all('script')
        for script in scripts:
            script_text = script.get_text()
            if '{"Events":' in script_text:
                # Extract the JSON data
                json_start = script_text.find('{"Events":')
                if json_start != -1:
                    json_str = script_text[json_start:]
                    # Find the end of the JSON object
                    brace_count = 0
                    end_pos = json_start
                    for i, char in enumerate(script_text[json_start:], json_start):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end_pos = i + 1
                                break
                    json_str = script_text[json_start:end_pos]
                    try:
                        events_data = json.loads(json_str)
                        break
                    except json.JSONDecodeError:
                        continue

        # If JSON found, parse it
        if events_data and 'Events' in events_data:
            print(f"[{CINEMA_NAME}] Found {len(events_data['Events'])} events in JSON data", file=sys.stderr)

            for event in events_data['Events']:
                title = event.get('Title', '').strip()
                if not title:
                    continue

                # Skip non-film events if needed (Type 298 seems to be films)
                event_type = event.get('Type')
                if event_type and event_type != 298:  # 298 appears to be film type
                    continue

                director = event.get('Director', '')
                year = event.get('Year', '')
                synopsis = event.get('Synopsis', '')
                running_time = event.get('RunningTime', '')

                # Process performances
                performances = event.get('Performances', [])
                for perf in performances:
                    start_date = perf.get('StartDate')
                    start_time = perf.get('StartTime')

                    if start_date and start_time:
                        try:
                            # Parse date
                            event_date = dt.date.fromisoformat(start_date)

                            # Parse time (format: "1945" for 19:45)
                            if len(start_time) == 4 and start_time.isdigit():
                                hours = int(start_time[:2])
                                minutes = int(start_time[2:])
                                showtime = f"{hours:02d}:{minutes:02d}"
                            else:
                                showtime = start_time

                            # Check if within our date window
                            if TODAY <= event_date <= TODAY + dt.timedelta(days=WINDOW_DAYS):
                                shows.append({
                                    "cinema_name": CINEMA_NAME,
                                    "movie_title": title,
                                    "movie_title_en": title,
                                    "date_text": event_date.isoformat(),
                                    "showtime": showtime,
                                    "detail_page_url": event.get('URL', ''),
                                    "director": director,
                                    "year": year,
                                    "country": event.get('Country', ''),
                                    "runtime_min": str(running_time) if running_time else '',
                                    "synopsis": synopsis,
                                })

                        except (ValueError, IndexError) as e:
                            print(f"[{CINEMA_NAME}] Error parsing performance: {e}", file=sys.stderr)
                            continue

            print(f"[{CINEMA_NAME}] Found {len(shows)} showings from JSON", file=sys.stderr)
            return shows

        else:
            # Fallback to HTML parsing if no JSON found
            print(f"[{CINEMA_NAME}] No JSON data found, falling back to HTML parsing", file=sys.stderr)

            # Find film listings - independent cinemas often use simpler structures
            film_containers = soup.find_all(['div', 'article', 'tr', 'li'], class_=re.compile(r'film|movie|showing|event|item'))

            print(f"[{CINEMA_NAME}] Found {len(film_containers)} potential film containers", file=sys.stderr)

            for container in film_containers:
                # Extract event info
                event_info = _extract_event_info(container)
                if not event_info:
                    continue

                # Parse date - look in the container for date information
                event_date = None

                # Look for date patterns in the container text
                container_text = _clean(container.get_text())
                date_patterns = [
                    r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December))',
                    r'((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))'
                ]

                for pattern in date_patterns:
                    date_match = re.search(pattern, container_text, re.IGNORECASE)
                    if date_match:
                        event_date = _parse_uk_date(date_match.group(1))
                        if event_date:
                            break

                # If still no date, check if this is for today or upcoming
                if not event_date:
                    # Look for date indicators in the text
                    if re.search(r'\b(today|tomorrow|this week|coming soon)\b', container_text, re.IGNORECASE):
                        # Try to determine which day
                        if re.search(r'\btomorrow\b', container_text, re.IGNORECASE):
                            event_date = TODAY + dt.timedelta(days=1)
                        else:
                            event_date = TODAY

                # Parse showtime
                showtime_parsed = ""
                if event_info['showtime']:
                    showtime_parsed = _parse_time_12h(event_info['showtime'])

                # If we have both date and time, create the showing
                if event_date and showtime_parsed:
                    # Check if within our date window
                    if TODAY <= event_date < TODAY + dt.timedelta(days=WINDOW_DAYS):
                        shows.append({
                            "cinema_name": CINEMA_NAME,
                            "movie_title": event_info['title'],
                            "movie_title_en": event_info['title'],  # Will be populated by TMDB
                            "date_text": event_date.isoformat(),
                            "showtime": showtime_parsed,
                            "detail_page_url": event_info['detail_page_url'],
                            "director": "",  # Will be populated by TMDB
                            "year": "",      # Will be populated by TMDB
                            "country": "",   # Will be populated by TMDB
                            "runtime_min": "",  # Will be populated by TMDB
                            "synopsis": event_info['description'],
                        })

            print(f"[{CINEMA_NAME}] Found {len(shows)} showings from HTML fallback", file=sys.stderr)

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
    data = scrape_regent()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)