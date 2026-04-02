#!/usr/bin/env python3
# act_one_module.py
# Scraper for ActOne Cinema & Cafe (Acton)
# https://www.actonecinema.co.uk/now-playing/
#
# Data source: Indy Systems GraphQL API.

from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://www.actonecinema.co.uk"
GRAPHQL_URL = f"{BASE_URL}/graphql"
CINEMA_NAME = "ActOne Cinema & Cafe"

SITE_ID = 93
CIRCUIT_ID = 23

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-GB,en;q=0.7",
    "Circuit-Id": str(CIRCUIT_ID),
    "Client-Type": "consumer",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/now-playing/",
    "Site-Id": str(SITE_ID),
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
}

TIMEOUT = 30
TODAY = dt.date.today()
WINDOW_DAYS = 14
LONDON_TZ = ZoneInfo("Europe/London")

DATES_QUERY = """
query ($siteIds: [ID]) {
  datesWithShowing(siteIds: $siteIds) {
    value
  }
}
"""

SHOWINGS_QUERY = """
query ($date: String, $siteIds: [ID]) {
  showingsForDate(date: $date, siteIds: $siteIds) {
    data {
      id
      time
      movie {
        id
        name
        urlSlug
        synopsis
        directedBy
        duration
        releaseDate
        genre
        allGenres
        rating
      }
      screen {
        id
        name
      }
    }
  }
}
"""


def _clean(text: str) -> str:
    if not text:
        return ""
    return " ".join(text.split())


def _parse_iso_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _parse_showing_time(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LONDON_TZ)
    return parsed.astimezone(LONDON_TZ)


def _coerce_year(value: str) -> str:
    value = _clean(value or "")
    if len(value) >= 4 and value[:4].isdigit():
        return value[:4]
    return ""


def _coerce_runtime(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return _clean(str(value))


def _post_graphql(session: requests.Session, query: str, variables: Dict) -> Dict:
    resp = session.post(
        GRAPHQL_URL,
        headers=HEADERS,
        json={"query": query, "variables": variables},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        print(f"[{CINEMA_NAME}] GraphQL errors: {payload['errors']}", file=sys.stderr)
    return payload.get("data") or {}


def _fetch_dates(session: requests.Session) -> List[dt.date]:
    data = _post_graphql(session, DATES_QUERY, {"siteIds": [SITE_ID]})
    raw_value = (data.get("datesWithShowing") or {}).get("value")
    if not raw_value:
        return []
    try:
        date_values = json.loads(raw_value)
    except json.JSONDecodeError:
        return []

    dates = []
    for value in date_values:
        parsed = _parse_iso_date(value)
        if parsed:
            dates.append(parsed)
    return dates


def _build_booking_url(showing_id: str, slug: str) -> str:
    if slug:
        return f"{BASE_URL}/checkout/showing/{slug}/{showing_id}"
    return f"{BASE_URL}/checkout/showing/{showing_id}"


def scrape_act_one_cinema() -> List[Dict]:
    """
    Scrape ActOne Cinema showtimes using the Indy Systems GraphQL endpoint.
    """
    shows: List[Dict] = []

    try:
        session = requests.Session()
        dates = _fetch_dates(session)

        if not dates:
            raise ValueError("No dates returned from ActOne GraphQL.")

        window_end = TODAY + dt.timedelta(days=WINDOW_DAYS)
        dates = [d for d in dates if TODAY <= d < window_end]

        for show_date in dates:
            data = _post_graphql(
                session,
                SHOWINGS_QUERY,
                {"date": show_date.isoformat(), "siteIds": [SITE_ID]},
            )
            showings = (data.get("showingsForDate") or {}).get("data") or []

            for showing in showings:
                show_dt = _parse_showing_time(showing.get("time"))
                if not show_dt:
                    continue

                local_date = show_dt.date()
                if not (TODAY <= local_date < window_end):
                    continue

                movie = showing.get("movie") or {}
                title = _clean(movie.get("name"))
                if not title:
                    continue

                slug = _clean(movie.get("urlSlug"))
                detail_url = f"{BASE_URL}/movie/{slug}" if slug else ""
                booking_url = _build_booking_url(showing.get("id", ""), slug)

                synopsis = _clean(movie.get("synopsis"))

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": local_date.isoformat(),
                    "showtime": show_dt.strftime("%H:%M"),
                    "detail_page_url": detail_url,
                    "booking_url": booking_url,
                    "director": _clean(movie.get("directedBy")),
                    "year": _coerce_year(movie.get("releaseDate")),
                    "country": "",
                    "runtime_min": _coerce_runtime(movie.get("duration")),
                    "synopsis": synopsis[:500] if synopsis else "",
                    "format_tags": [],
                })

        print(f"[{CINEMA_NAME}] Found {len(shows)} showings", file=sys.stderr)

    except requests.RequestException as exc:
        print(f"[{CINEMA_NAME}] HTTP Error: {exc}", file=sys.stderr)
        raise
    except Exception as exc:
        print(f"[{CINEMA_NAME}] Error: {exc}", file=sys.stderr)
        raise

    seen = set()
    unique_shows = []
    for show in shows:
        key = (show["movie_title"], show["date_text"], show["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(show)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_act_one_cinema()
    print(json.dumps(data, ensure_ascii=True, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
