#!/usr/bin/env python3
# everyman_manchester_module.py
# Scraper for Everyman Manchester (chain venue)
# https://www.everymancinema.com/venues-list/x11np-everyman-manchester-st-johns/
#
# Uses Everyman's gatsby-source-boxofficeapi endpoints for schedule + movie metadata.

from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Dict, Iterable, List, Optional

import requests

BASE_URL = "https://www.everymancinema.com"
API_BASE = f"{BASE_URL}/api/gatsby-source-boxofficeapi"

CINEMA_NAME = "Everyman Manchester"
THEATER_ID = "X11NP"  # From venue URL: x11np-everyman-manchester-st-johns

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
    synopsis = exhibitor.get("synopsis") or ""
    if isinstance(synopsis, str) and synopsis.strip():
        return synopsis.strip()
    return ""


def _extract_booking_url(show: Dict) -> str:
    booking = show.get("booking") or {}
    return booking.get("url", "")


def _fetch_scheduled_movie_ids(session: requests.Session, theater_id: str) -> List[str]:
    resp = session.get(SCHEDULED_MOVIES_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    # The API returns {'movieIds': {'titleAsc': [...], ...}, 'scheduledDays': {...}}
    movie_ids_data = data.get("movieIds", {})
    movie_ids = movie_ids_data.get("titleAsc", [])  # Use titleAsc ordering
    return [str(movie_id) for movie_id in movie_ids]


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


def scrape_everyman_manchester() -> List[Dict]:
    """
    Scrape Everyman Manchester showtimes using their API.

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
        session.cookies.set("selectedTheaterId", THEATER_ID)

        start = _range_start()
        end = start + dt.timedelta(days=WINDOW_DAYS)

        schedule_payload = _fetch_schedule(session, THEATER_ID, start, end)
        schedule = schedule_payload.get(THEATER_ID, {}).get("schedule", {}) or {}

        if not schedule:
            print(f"[{CINEMA_NAME}] No schedule data returned.", file=sys.stderr)
            return []

        movie_ids = _fetch_scheduled_movie_ids(session, THEATER_ID)
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

                    shows.append({
                        "cinema_name": CINEMA_NAME,
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
        key = (s["cinema_name"], s["movie_title"], s["date_text"], s["showtime"], s["booking_url"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_everyman_manchester()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)