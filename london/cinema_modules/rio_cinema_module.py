#!/usr/bin/env python3
# rio_cinema_module.py
# Scraper for Rio Cinema (Dalston)
# https://riocinema.org.uk/Rio.dll/WhatsOn

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests

BASE_URL = "https://riocinema.org.uk"
BASE_DLL_URL = f"{BASE_URL}/Rio.dll/"
SCHEDULE_URL = f"{BASE_URL}/Rio.dll/WhatsOn"
CINEMA_NAME = "Rio Cinema"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _load_html_override() -> Optional[str]:
    """Allow offline testing via environment variable."""
    path = os.getenv("RIO_HTML_PATH")
    if path:
        return _read_text_file(path)
    return None


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(text).strip())


def _parse_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_time(value: str) -> Optional[str]:
    if not value:
        return None
    cleaned = _clean(value)
    match = re.search(r"(\d{1,2})[:.](\d{2})", cleaned)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    match = re.search(r"\b(\d{3,4})\b", cleaned)
    if match:
        digits = match.group(1).zfill(4)
        hour = int(digits[:2])
        minute = int(digits[2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    return None


def _extract_events_json(html_text: str) -> Optional[Dict]:
    marker = "var Events ="
    start = html_text.find(marker)
    if start == -1:
        return None
    start = html_text.find("{", start)
    if start == -1:
        return None

    depth = 0
    end = None
    for idx in range(start, len(html_text)):
        char = html_text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break

    if end is None:
        return None

    raw = html_text[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.replace("\r", "").replace("\n", "")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def scrape_rio_cinema() -> List[Dict]:
    """
    Scrape Rio Cinema showtimes from the embedded JSON on the WhatsOn page.
    """
    shows: List[Dict] = []

    try:
        html_override = _load_html_override()
        if html_override:
            html_text = html_override
        else:
            session = requests.Session()
            session.trust_env = False
            resp = session.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            html_text = resp.text

        data = _extract_events_json(html_text)
        if not data:
            print(f"[{CINEMA_NAME}] Warning: Could not extract Events JSON from page", file=sys.stderr)
            return []

        for event in data.get("Events", []):
            title = _clean(event.get("Title", ""))
            if not title:
                continue

            detail_url = event.get("URL", "") or ""
            if detail_url and not detail_url.startswith("http"):
                detail_url = urljoin(BASE_DLL_URL, detail_url)

            director = _clean(event.get("Director", ""))
            year = _clean(str(event.get("Year") or ""))
            country = _clean(event.get("Country", ""))
            runtime_min = _clean(str(event.get("RunningTime") or ""))
            synopsis = _clean(event.get("Synopsis", ""))

            for perf in event.get("Performances", []) or []:
                show_date = _parse_date(perf.get("StartDate", ""))
                if not show_date:
                    continue

                if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                    continue

                showtime = _parse_time(perf.get("StartTimeAndNotes", "")) or _parse_time(perf.get("StartTime", ""))
                if not showtime:
                    continue

                booking_url = perf.get("URL", "") or ""
                if booking_url and not booking_url.startswith("http"):
                    booking_url = urljoin(BASE_DLL_URL, booking_url)

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
                    "synopsis": synopsis,
                })

        if not shows:
            print(f"[{CINEMA_NAME}] Note: No shows found. Page structure may have changed.", file=sys.stderr)
            print(f"[{CINEMA_NAME}] URL: {SCHEDULE_URL}", file=sys.stderr)

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
        if key in seen:
            continue
        seen.add(key)
        unique_shows.append(show)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


def scrape_rio() -> List[Dict]:
    return scrape_rio_cinema()


if __name__ == "__main__":
    data = scrape_rio_cinema()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\nTotal: {len(data)} showings")
