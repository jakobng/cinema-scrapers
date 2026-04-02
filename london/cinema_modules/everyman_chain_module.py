#!/usr/bin/env python3
# everyman_chain_module.py
# Scraper for Everyman Cinemas in London
# https://www.everymancinema.com/
#
# Uses Everyman's gatsby-source-boxofficeapi endpoints for schedule + movie metadata.

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from typing import Dict, Iterable, List, Optional

import requests

BASE_URL = "https://www.everymancinema.com"
API_BASE = f"{BASE_URL}/api/gatsby-source-boxofficeapi"

TIME_ZONE = "Europe/London"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,*/*",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30
WINDOW_DAYS = 14

SCHEDULE_URL = f"{API_BASE}/schedule"
MOVIES_URL = f"{API_BASE}/movies"
SCHEDULED_MOVIES_URL = f"{API_BASE}/scheduledMovies"

LONDON_VENUES = {
    "Everyman Baker Street": "X0712",
    "Everyman Barnet": "X06SI",
    "Everyman Belsize Park": "X077P",
    "Everyman Borough Yards": "G011I",
    "Everyman Brentford": "G049A",
    "Everyman Broadgate": "X11NT",
    "Everyman Canary Wharf": "X0VPB",
    "Everyman Chelsea": "X078X",
    "Everyman Crystal Palace": "X11DR",
    "Everyman Hampstead": "X06ZW",
    "Everyman King's Cross": "X0X5P",
    "Everyman Maida Vale": "X0LWI",
    "Everyman Muswell Hill": "X06SN",
    "Everyman Screen on the Green": "X077O",
    "Everyman Stratford International": "G029X",
    "Everyman The Whiteley": "G05D7",
}

def _range_start() -> dt.datetime:
    now = dt.datetime.now()
    if now.hour < 3:
        now -= dt.timedelta(days=1)
    return now.replace(hour=3, minute=0, second=0, microsecond=0)


def _iter_chunks(items: List[str], size: int = 50) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _parse_directors(movie: Dict) -> str:
    directors = movie.get("directors", {}).get("nodes", []) or []
    names = []
    for entry in directors:
        person = entry.get("person") or {}
        first = person.get("firstName") or ""
        last = person.get("lastName") or ""
        name = " ".join(part for part in [first, last] if part).strip()
        if name:
            names.append(name)
    return ", ".join(names)


def _parse_runtime_minutes(movie: Dict) -> str:
    runtime = movie.get("runtime")
    if isinstance(runtime, (int, float)) and runtime > 0:
        minutes = int(round(runtime / 60))
        return str(minutes) if minutes > 0 else ""
    return ""


def _parse_year(movie: Dict) -> str:
    release = movie.get("release")
    if isinstance(release, str) and len(release) >= 4:
        return release[:4]
    releases = movie.get("releases") or []
    if isinstance(releases, list) and releases:
        released_at = releases[0].get("releasedAt")
        if isinstance(released_at, str) and len(released_at) >= 4:
            return released_at[:4]
    return ""


def _parse_synopsis(movie: Dict) -> str:
    exhibitor = movie.get("exhibitor") or {}
    synopsis = exhibitor.get("synopsis") or movie.get("synopsis") or ""
    return synopsis.strip()


def _extract_booking_url(show: Dict) -> str:
    data = show.get("data") or {}
    for ticketing in data.get("ticketing") or []:
        urls = ticketing.get("urls") or []
        if urls:
            return urls[0]
    return ""


def _fetch_scheduled_movie_ids(session: requests.Session, theater_id: str) -> List[str]:
    params = {"theaterId": theater_id, "includeAllMovies": "true"}
    resp = session.get(SCHEDULED_MOVIES_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    movie_ids = payload.get("movieIds", {}).get("titleAsc", []) or []
    return list(dict.fromkeys(movie_ids))


def _fetch_movie_metadata(session: requests.Session, movie_ids: List[str]) -> Dict[str, Dict]:
    metadata = {}
    for chunk in _iter_chunks(movie_ids):
        params = [("ids", movie_id) for movie_id in chunk]
        resp = session.get(MOVIES_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        for movie in resp.json():
            movie_id = str(movie.get("id") or "")
            if movie_id:
                metadata[movie_id] = movie
    return metadata


def _fetch_schedule(session: requests.Session, theater_id: str, start: dt.datetime, end: dt.datetime) -> Dict:
    theater_json = json.dumps({"id": theater_id, "timeZone": TIME_ZONE}, separators=( ",", ":"))
    params = [
        ("from", start.strftime("%Y-%m-%dT%H:%M:%S")),
        ("to", end.strftime("%Y-%m-%dT%H:%M:%S")),
        ("theaters", theater_json),
    ]
    resp = session.get(SCHEDULE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()

def scrape_venue(session: requests.Session, cinema_name: str, theater_id: str) -> List[Dict]:
    """
    Scrape a single Everyman venue.
    """
    venue_shows: List[Dict] = []
    print(f"   Scraping {cinema_name} ({theater_id})...", file=sys.stderr)
    
    try:
        session.cookies.set("selectedTheaterId", theater_id)

        start = _range_start()
        end = start + dt.timedelta(days=WINDOW_DAYS)

        schedule_payload = _fetch_schedule(session, theater_id, start, end)
        schedule = schedule_payload.get(theater_id, {}).get("schedule", {}) or {}
        
        if not schedule:
            print(f"   [{cinema_name}] No schedule data returned.", file=sys.stderr)
            return []

        movie_ids = _fetch_scheduled_movie_ids(session, theater_id)
        movie_metadata = _fetch_movie_metadata(session, movie_ids)

        for movie_id, date_map in schedule.items():
            movie = movie_metadata.get(str(movie_id))
            if not movie:
                continue
            title = movie.get("title", "").strip()
            if not title:
                continue

            director = _parse_directors(movie)
            year = _parse_year(movie)
            runtime_min = _parse_runtime_minutes(movie)
            synopsis = _parse_synopsis(movie)

            for date_text, showtimes in (date_map or {}).items():
                if not showtimes:
                    continue
                for show in showtimes:
                    starts_at = show.get("startsAt")
                    if not starts_at:
                        continue
                    try:
                        show_dt = dt.datetime.fromisoformat(starts_at)
                    except ValueError:
                        continue
                    if not (start.date() <= show_dt.date() <= end.date()):
                        continue

                    booking_url = _extract_booking_url(show)
                    format_tags = show.get("tags") or []

                    venue_shows.append({
                        "cinema_name": cinema_name,
                        "movie_title": title,
                        "movie_title_en": title,
                        "date_text": show_dt.date().isoformat(),
                        "showtime": show_dt.strftime("%H:%M"),
                        "detail_page_url": f"{BASE_URL}/film-listing/{movie_id}",
                        "booking_url": booking_url,
                        "director": director,
                        "year": year,
                        "country": "",
                        "runtime_min": runtime_min,
                        "synopsis": synopsis,
                        "format_tags": format_tags,
                    })
    except Exception as e:
        print(f"   [{cinema_name}] Error: {e}", file=sys.stderr)
        return []

    return venue_shows

def scrape_everyman_locations() -> List[Dict]:
    """
    Scrape all London Everyman locations.
    """
    all_shows: List[Dict] = []
    session = requests.Session()
    
    for name, theater_id in LONDON_VENUES.items():
        shows = scrape_venue(session, name, theater_id)
        all_shows.extend(shows)
        time.sleep(0.5) # Be polite

    seen = set()
    unique_shows = []
    for show in all_shows:
        key = (show["cinema_name"], show["movie_title"], show["date_text"], show["showtime"], show["booking_url"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(show)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_everyman_locations()
    print(json.dumps(data, ensure_ascii=True, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings from {len(LONDON_VENUES)} venues.", file=sys.stderr)
