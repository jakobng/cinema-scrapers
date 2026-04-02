#!/usr/bin/env python3
# electric_cinema_module.py
# Scraper for Electric Cinema (Portobello + White City)
# https://www.electriccinema.co.uk/programme/
#
# Data source: https://www.electriccinema.co.uk/data/data.json

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests

BASE_URL = "https://www.electriccinema.co.uk"
DATA_URL = f"{BASE_URL}/data/data.json"
CINEMA_NAME = "Electric Cinema"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_iso_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _cinema_display_name(cinema: Dict) -> str:
    title = _clean(cinema.get("title", ""))
    if title:
        return f"{CINEMA_NAME} {title}"
    return CINEMA_NAME


def scrape_electric_cinema() -> List[Dict]:
    """
    Scrape Electric Cinema showtimes from their JSON data feed.
    """
    shows: List[Dict] = []

    try:
        session = requests.Session()
        resp = session.get(DATA_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()

        cinemas = payload.get("cinemas", {})
        films = payload.get("films", {})
        screenings = payload.get("screenings", {})
        screening_types = payload.get("screeningTypes", {})

        for screening in screenings.values():
            date_text = screening.get("d", "")
            show_date = _parse_iso_date(date_text)
            if not show_date:
                continue
            if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                continue

            showtime = _clean(screening.get("t", ""))
            if not showtime:
                continue

            cinema_id = str(screening.get("cinema", ""))
            cinema = cinemas.get(cinema_id, {})
            cinema_name = _cinema_display_name(cinema)

            film_id = str(screening.get("film", ""))
            film = films.get(film_id, {})
            movie_title = _clean(film.get("title", ""))
            if not movie_title:
                continue

            detail_url = ""
            film_link = film.get("link", "")
            if film_link:
                detail_url = urljoin(BASE_URL, film_link)

            booking_url = ""
            screening_link = screening.get("link")
            if isinstance(screening_link, str) and screening_link:
                booking_url = urljoin(BASE_URL, screening_link)

            synopsis = _clean(film.get("short_synopsis", ""))
            director = _clean(film.get("director", ""))

            year = ""
            premiere = film.get("premiere", "")
            if isinstance(premiere, str) and premiere:
                year = premiere.split("-")[0]

            format_tags = []
            screening_type = screening.get("st", "")
            if screening_type and screening_type in screening_types:
                screening_title = screening_types[screening_type].get("title", "")
                if screening_title:
                    format_tags.append(screening_title)
            for tag in screening.get("a", []) or []:
                tag_text = _clean(tag)
                if tag_text:
                    format_tags.append(tag_text)

            shows.append({
                "cinema_name": cinema_name,
                "movie_title": movie_title,
                "movie_title_en": movie_title,
                "date_text": date_text,
                "showtime": showtime,
                "detail_page_url": detail_url,
                "booking_url": booking_url,
                "director": director,
                "year": year,
                "country": "",
                "runtime_min": "",
                "synopsis": synopsis[:500] if synopsis else "",
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
        key = (s["cinema_name"], s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_electric_cinema()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
