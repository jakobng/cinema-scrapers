#!/usr/bin/env python3
# cultplex_module.py
# Scraper for Cultplex Manchester (cult films, expanding venue)
# https://cultplex.co.uk/
#
# Structure: WordPress-based site with event listings showing film titles and dates

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://cultplex.co.uk"
WHATSON_URL = f"{BASE_URL}/Cultplex.dll/Home"  # Main listings page
CINEMA_NAME = "Cultplex"

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
    Parse UK date formats from Cultplex listings.
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
    Parse 12-hour time format from Cultplex listings.
    Returns 24-hour format string "HH:MM" or None.
    """
    time_str = time_str.strip().lower()

    # Match patterns like "7:30pm", "8:00 pm", "12:15am"
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


def _extract_event_info(event_element) -> Optional[Dict]:
    """
    Extract event information from an event listing element.
    Returns dict with title, description, date, time, etc.
    """
    try:
        # Find event title
        title_elem = event_element.find(['h3', 'h2', 'h4', 'a'], class_=re.compile(r'title|event-title'))
        if not title_elem:
            # Try finding any heading or link
            title_elem = event_element.find(['h1', 'h2', 'h3', 'h4', 'h5', 'a'])

        if not title_elem:
            return None

        title = _clean(title_elem.get_text())

        # Skip non-film events (quizzes, gaming, etc.)
        title_lower = title.lower()
        if any(keyword in title_lower for keyword in ['quiz', 'gaming', 'game', 'q&a', 'panel']):
            return None

        # Find description
        description = ""
        desc_elem = event_element.find(['p', 'div'], class_=re.compile(r'description|desc|summary'))
        if desc_elem:
            description = _clean(desc_elem.get_text())
        else:
            # Look for any paragraph content
            paragraphs = event_element.find_all('p')
            for p in paragraphs:
                text = _clean(p.get_text())
                if len(text) > 20:  # Assume substantial text is description
                    description = text
                    break

        # Find date and time information
        date_time_text = ""
        date_elem = event_element.find(['div', 'span', 'p'], class_=re.compile(r'date|time|datetime'))
        if date_elem:
            date_time_text = _clean(date_elem.get_text())

        # Extract time from description or date element
        showtime = ""
        time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm))', date_time_text + " " + description, re.IGNORECASE)
        if time_match:
            showtime = time_match.group(1)

        # Find detail page URL
        detail_url = ""
        more_link = event_element.find('a', string=re.compile(r'more|details|info', re.IGNORECASE))
        if more_link:
            detail_url = urljoin(BASE_URL, more_link.get('href', ''))
        else:
            # Try any link that might be to the event
            links = event_element.find_all('a')
            for link in links:
                href = link.get('href', '')
                if href and ('event' in href or 'film' in href):
                    detail_url = urljoin(BASE_URL, href)
                    break

        return {
            'title': title,
            'description': description,
            'date_time_text': date_time_text,
            'showtime': showtime,
            'detail_page_url': detail_url,
        }

    except Exception as e:
        print(f"Error extracting event info: {e}", file=sys.stderr)
        return None


def scrape_cultplex() -> List[Dict]:
    """
    Scrape Cultplex Manchester showtimes from their listings page.

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

        # Cultplex embeds JSON data in the HTML with events and performances
        # Look for the JSON data containing events
        script_tags = soup.find_all('script')
        events_data = None

        for script in script_tags:
            script_text = script.get_text()
            # Look for the Events JSON data
            if '"Events":' in script_text:
                # Extract the JSON object
                start_idx = script_text.find('{"Events":')
                if start_idx != -1:
                    # Find the end of the JSON object (look for closing brace followed by some delimiter)
                    brace_count = 0
                    end_idx = start_idx
                    for i, char in enumerate(script_text[start_idx:], start_idx):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end_idx = i + 1
                                break

                    json_str = script_text[start_idx:end_idx]
                    try:
                        events_data = json.loads(json_str)
                        break
                    except json.JSONDecodeError:
                        continue

        if not events_data or 'Events' not in events_data:
            return shows

        for event in events_data['Events']:
            # Only process film events (Type 298 seems to be films)
            if event.get('TypeDescription') != 'Film':
                continue

            title = event.get('Title', '').strip()
            synopsis = event.get('Synopsis', '').strip()
            director = event.get('Director', '').strip()
            year = event.get('Year', '').strip()
            country = event.get('Country', '').strip()
            runtime_min = str(event.get('RunningTime', '')) if event.get('RunningTime') else ""
            detail_url = event.get('URL', '')

            # Clean up the title (remove extra quotes, etc.)
            title = title.strip('"')

            # Skip non-film events that might have slipped through
            if any(keyword in title.lower() for keyword in ['quiz', 'gaming', 'game', 'q&a', 'panel', 'viewing party']):
                continue

            # Process performances
            performances = event.get('Performances', [])
            for perf in performances:
                start_date = perf.get('StartDate')
                start_time = perf.get('StartTime')  # This is in HHMM format (e.g., "1900")

                if not start_date or not start_time:
                    continue

                try:
                    # Parse date
                    event_date = dt.date.fromisoformat(start_date)

                    # Parse time - it's in HHMM format (e.g., "1900" = 19:00)
                    if len(start_time) == 4:
                        hours = int(start_time[:2])
                        minutes = int(start_time[2:])
                        showtime = f"{hours:02d}:{minutes:02d}"
                    else:
                        # Fallback for other formats
                        showtime = _parse_time_12h(start_time)
                        if not showtime:
                            continue

                    # Check if within our date window
                    if TODAY <= event_date < TODAY + dt.timedelta(days=WINDOW_DAYS):
                        shows.append({
                            "cinema_name": CINEMA_NAME,
                            "movie_title": title,
                            "movie_title_en": title,
                            "date_text": event_date.isoformat(),
                            "showtime": showtime,
                            "detail_page_url": detail_url,
                            "director": director,
                            "year": year,
                            "country": country,
                            "runtime_min": runtime_min,
                            "synopsis": synopsis,
                        })

                except (ValueError, TypeError) as e:
                    print(f"[{CINEMA_NAME}] Error parsing performance: {e}", file=sys.stderr)
                    continue

        print(f"[{CINEMA_NAME}] Found {len(shows)} total showings", file=sys.stderr)

    except requests.RequestException as e:
        print(f"[{CINEMA_NAME}] HTTP Error: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        raise

    # Deduplicate (shouldn't happen but just in case)
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
        resp = session.get(WHATSON_URL, headers=HEADERS, timeout=TIMEOUT)
        with open("cultplex_debug.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("Saved HTML to cultplex_debug.html")
        sys.exit(0)

    data = scrape_cultplex()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)