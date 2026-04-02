#!/usr/bin/env python3
# castle_cinema_module.py
# Scraper for The Castle Cinema, Hackney
# https://thecastlecinema.com/calendar/
#
# Structure: Programme tiles with performance buttons containing data-start-time.

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://thecastlecinema.com"
SCHEDULE_URL = f"{BASE_URL}/calendar/"
CINEMA_NAME = "The Castle Cinema"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_start_time(start_text: str) -> Optional[dt.datetime]:
    if not start_text:
        return None
    try:
        return dt.datetime.fromisoformat(start_text)
    except ValueError:
        return None


def _parse_filters(raw_filters: str) -> List[str]:
    if not raw_filters:
        return []
    tags = []
    for part in raw_filters.split(","):
        cleaned = _clean(part)
        if cleaned:
            tags.append(cleaned)
    return tags


def scrape_castle_cinema() -> List[Dict]:
    """
    Scrape The Castle Cinema showtimes from the calendar page.
    """
    shows = []

    try:
        session = requests.Session()
        resp = session.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        tiles = soup.select(".programme-tile")
        print(f"[{CINEMA_NAME}] Found {len(tiles)} programme tiles", file=sys.stderr)

        for tile in tiles:
            title_elem = tile.select_one(".tile-name h1")
            if not title_elem:
                continue

            film_title = _clean(title_elem.get_text())
            if not film_title:
                continue

            detail_link = tile.select_one("a[href^='/programme/']")
            detail_url = ""
            if detail_link:
                detail_url = detail_link.get("href", "")
                if detail_url:
                    detail_url = urljoin(BASE_URL, detail_url)

            synopsis_elem = tile.select_one(".tile-subname")
            synopsis = _clean(synopsis_elem.get_text()) if synopsis_elem else ""

            time_buttons = tile.select(".film-times a.performance-button")
            for button in time_buttons:
                start_text = button.get("data-start-time", "")
                start_dt = _parse_start_time(start_text)
                if not start_dt:
                    continue

                show_date = start_dt.date()
                if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                    continue

                showtime = start_dt.strftime("%H:%M")

                booking_url = button.get("href", "")
                if booking_url and not booking_url.startswith("http"):
                    booking_url = urljoin(BASE_URL, booking_url)

                format_tags = []
                format_tags.extend(_parse_filters(button.get("data-filters", "")))

                screening_type = button.select_one(".screening-type")
                if screening_type:
                    screening_text = _clean(screening_type.get_text())
                    if screening_text:
                        format_tags.append(screening_text)

                seen_tags = []
                for tag in format_tags:
                    if tag not in seen_tags:
                        seen_tags.append(tag)

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": film_title,
                    "movie_title_en": film_title,
                    "date_text": show_date.isoformat(),
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                    "booking_url": booking_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": synopsis[:500] if synopsis else "",
                    "format_tags": seen_tags,
                })

        print(f"[{CINEMA_NAME}] Found {len(shows)} showings", file=sys.stderr)

    except requests.RequestException as e:
        print(f"[{CINEMA_NAME}] HTTP Error: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        raise

    seen = set()
    unique_shows = []
    for s in shows:
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_castle_cinema()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
