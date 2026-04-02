#!/usr/bin/env python3
# lexi_cinema_module.py
# Scraper for The Lexi Cinema (Kensal Rise)
# https://thelexicinema.co.uk/
#
# Data source: homepage embeds a "var Events = {...}" JSON payload
# with film metadata and performance listings.

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests

BASE_URL = "https://thelexicinema.co.uk"
HOME_URL = f"{BASE_URL}/"
BOOKING_BASE_URL = f"{BASE_URL}/TheLexiCinema.dll/"
CINEMA_NAME = "The Lexi Cinema"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _load_html_override() -> Optional[str]:
    path = os.getenv("LEXI_HTML_PATH")
    if path:
        return _read_text_file(path)
    return None


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_iso_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _parse_showtime(raw_time: str) -> Optional[str]:
    if not raw_time:
        return None
    raw_time = raw_time.strip()
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", raw_time)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        return f"{hour:02d}:{minute:02d}"
    if re.fullmatch(r"\d{3,4}", raw_time):
        digits = raw_time.zfill(4)
        return f"{digits[:2]}:{digits[2:]}"
    return None


def _extract_events_payload(html: str) -> Dict:
    key = "var Events"
    idx = html.find(key)
    if idx == -1:
        return {}

    start = html.find("{", idx)
    if start == -1:
        return {}

    brace_count = 0
    in_string = False
    escape = False
    end = None

    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "\"":
                in_string = False
            continue

        if ch == "\"":
            in_string = True
        elif ch == "{":
            brace_count += 1
        elif ch == "}":
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                break

    if end is None:
        return {}

    payload_text = html[start:end]
    try:
        return json.loads(payload_text)
    except json.JSONDecodeError:
        return {}


def _coerce_year(value: str) -> str:
    value = _clean(str(value or ""))
    return value if re.fullmatch(r"\d{4}", value) else ""


def _coerce_runtime(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return str(int(value))
    except (ValueError, TypeError):
        return _clean(str(value))


def scrape_lexi_cinema() -> List[Dict]:
    """
    Scrape The Lexi Cinema showtimes from the homepage Events payload.
    """
    shows: List[Dict] = []

    try:
        html_override = _load_html_override()
        if html_override:
            html = html_override
        else:
            session = requests.Session()
            resp = session.get(HOME_URL, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            html = resp.text

        payload = _extract_events_payload(html)
        events = payload.get("Events", []) if isinstance(payload, dict) else []

        if not events:
            raise ValueError("Events payload not found or empty.")

        for event in events:
            title = _clean(event.get("Title", ""))
            if not title:
                continue

            director = _clean(event.get("Director", ""))
            year = _coerce_year(event.get("Year", ""))
            runtime_min = _coerce_runtime(event.get("RunningTime"))
            synopsis = _clean(event.get("Synopsis", ""))
            country = _clean(event.get("Country", ""))

            detail_url = event.get("URL", "") or ""
            if detail_url and not detail_url.startswith("http"):
                detail_url = urljoin(BASE_URL, detail_url)

            for perf in event.get("Performances") or []:
                date_text = _clean(perf.get("StartDate", ""))
                show_date = _parse_iso_date(date_text)
                if not show_date:
                    continue
                if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                    continue

                showtime = _parse_showtime(perf.get("StartTimeAndNotes") or perf.get("StartTime", ""))
                if not showtime:
                    continue

                booking_url = perf.get("URL", "") or ""
                if booking_url and not booking_url.startswith("http"):
                    booking_url = urljoin(BOOKING_BASE_URL, booking_url)

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": show_date.isoformat(),
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                    "booking_url": booking_url,
                    "director": director,
                    "year": year,
                    "country": country,
                    "runtime_min": runtime_min,
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
    data = scrape_lexi_cinema()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
