#!/usr/bin/env python3
# coldharbour_blue_module.py
# Scraper for Coldharbour Blue (Loughborough Junction)
# Uses The Events Calendar JSON API:
# https://www.coldharbourblue.com/wp-json/tribe/events/v1/events/

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.coldharbourblue.com"
EVENTS_API_URL = f"{BASE_URL}/wp-json/tribe/events/v1/events/"
CINEMA_NAME = "Coldharbour Blue"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 30


def _clean(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text.strip())


def _parse_start_datetime(raw: str) -> Optional[dt.datetime]:
    if not raw:
        return None
    try:
        return dt.datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return _clean(text)


def _extract_format_tags(event: dict) -> List[str]:
    tags = []
    for group in ("categories", "tags"):
        items = event.get(group, []) or []
        for item in items:
            name = _clean(item.get("name", "")) if isinstance(item, dict) else ""
            if name and name not in tags:
                tags.append(name)
    if event.get("featured") and "Featured" not in tags:
        tags.append("Featured")
    return tags


def _extract_synopsis(event: dict) -> str:
    raw = event.get("excerpt") or event.get("description") or ""
    synopsis = _strip_html(raw)
    return synopsis[:500]


def _fetch_events(session: requests.Session, start_date: dt.date, end_date: dt.date) -> List[dict]:
    events = []
    params = {
        "page": 1,
        "per_page": 100,
        "start_date": f"{start_date.isoformat()} 00:00:00",
        "end_date": f"{end_date.isoformat()} 23:59:59",
    }

    while True:
        resp = session.get(EVENTS_API_URL, headers=HEADERS, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()

        events.extend(payload.get("events", []) or [])

        total_pages = payload.get("total_pages", 1)
        try:
            total_pages = int(total_pages)
        except (TypeError, ValueError):
            total_pages = 1

        if params["page"] >= total_pages:
            break
        params["page"] += 1

    return events


def scrape_coldharbour_blue() -> List[Dict]:
    """
    Scrape Coldharbour Blue showtimes from The Events Calendar JSON API.
    """
    shows = []

    try:
        session = requests.Session()
        window_end = TODAY + dt.timedelta(days=WINDOW_DAYS)

        print(f"[{CINEMA_NAME}] Fetching events via API", file=sys.stderr)
        events = _fetch_events(session, TODAY, window_end)
        print(f"[{CINEMA_NAME}] Found {len(events)} events", file=sys.stderr)

        for event in events:
            title = _clean(event.get("title", ""))
            if not title:
                continue

            start_dt = _parse_start_datetime(event.get("start_date", ""))
            if not start_dt:
                continue

            show_date = start_dt.date()
            if not (TODAY <= show_date < window_end):
                continue

            showtime = start_dt.strftime("%H:%M")
            detail_url = event.get("url", "") or ""
            booking_url = event.get("website", "") or detail_url

            shows.append({
                "cinema_name": CINEMA_NAME,
                "movie_title": title,
                "movie_title_en": title,
                "date_text": show_date.isoformat(),
                "showtime": showtime,
                "detail_page_url": detail_url,
                "booking_url": booking_url,
                "director": "",
                "year": "",
                "country": "",
                "runtime_min": "",
                "synopsis": _extract_synopsis(event),
                "format_tags": _extract_format_tags(event),
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
    data = scrape_coldharbour_blue()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
