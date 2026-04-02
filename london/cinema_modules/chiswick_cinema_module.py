#!/usr/bin/env python3
# chiswick_cinema_module.py
# Scraper for Chiswick Cinema
# https://www.chiswickcinema.co.uk/whats-on
#
# Strategy:
# - Pull /whats-on for movie links.
# - Visit each movie page and parse showtime links in the SEO HTML.

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.chiswickcinema.co.uk"
LISTINGS_URL = f"{BASE_URL}/whats-on"
CINEMA_NAME = "Chiswick Cinema"

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


def _resolve_date(month: int, day: int) -> Optional[dt.date]:
    try:
        candidate = dt.date(TODAY.year, month, day)
    except ValueError:
        return None

    if candidate < TODAY - dt.timedelta(days=30):
        try:
            candidate = dt.date(TODAY.year + 1, month, day)
        except ValueError:
            return None

    return candidate


def _parse_showtime_text(text: str) -> Optional[dt.datetime]:
    if not text:
        return None

    text = _clean(text).lower()
    text = re.sub(r"\s*(am|pm)$", r" \1", text)

    match = re.match(
        r"([a-z]+)\s+(\d{1,2}),\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        text,
        flags=re.I,
    )
    if not match:
        return None

    month_str, day_str, hour_str, minute_str, ampm = match.groups()
    try:
        month = dt.datetime.strptime(month_str[:3], "%b").month
    except ValueError:
        return None

    day = int(day_str)
    hour = int(hour_str)
    minute = int(minute_str) if minute_str else 0

    if ampm.lower() == "pm" and hour != 12:
        hour += 12
    if ampm.lower() == "am" and hour == 12:
        hour = 0

    show_date = _resolve_date(month, day)
    if not show_date:
        return None

    return dt.datetime(show_date.year, show_date.month, show_date.day, hour, minute)


def _extract_movie_metadata(soup: BeautifulSoup) -> Dict[str, str]:
    metadata = {
        "director": "",
        "runtime_min": "",
        "year": "",
        "synopsis": "",
    }

    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc and meta_desc.get("content"):
        metadata["synopsis"] = _clean(meta_desc["content"])[:500]

    scripts = soup.find_all("script", {"type": "application/ld+json"})
    for script in scripts:
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "@graph" in data:
            items = data.get("@graph") or []
        elif isinstance(data, dict):
            items = [data]

        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") != "Movie":
                continue

            if not metadata["synopsis"] and item.get("description"):
                metadata["synopsis"] = _clean(item.get("description"))[:500]

            director = item.get("director")
            if director and not metadata["director"]:
                if isinstance(director, list):
                    director = director[0] if director else {}
                if isinstance(director, dict):
                    metadata["director"] = _clean(director.get("name", ""))

            duration = item.get("duration")
            if duration and not metadata["runtime_min"]:
                match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration)
                if match:
                    hours = int(match.group(1) or 0)
                    minutes = int(match.group(2) or 0)
                    runtime = hours * 60 + minutes
                    if runtime:
                        metadata["runtime_min"] = str(runtime)

            date_created = item.get("dateCreated")
            if date_created and not metadata["year"]:
                year_match = re.match(r"(\d{4})", str(date_created))
                if year_match:
                    metadata["year"] = year_match.group(1)

            return metadata

    return metadata


def _extract_movie_title(soup: BeautifulSoup) -> str:
    title_elem = soup.find(attrs={"itemprop": "name"})
    if title_elem:
        title = _clean(title_elem.get_text())
        if title:
            return title

    og_title = soup.find("meta", {"property": "og:title"})
    if og_title and og_title.get("content"):
        return _clean(og_title["content"])

    h1 = soup.find("h1")
    if h1:
        return _clean(h1.get_text())

    return ""


def _extract_movie_links(soup: BeautifulSoup) -> List[str]:
    links = []
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not href:
            continue
        parsed = urlparse(href)
        path = parsed.path or ""
        if not re.match(r"^/movie/[a-z0-9\\-]+/?$", path, flags=re.I):
            continue
        full = urljoin(BASE_URL, path)
        if full not in links:
            links.append(full)
    return links


def scrape_chiswick_cinema() -> List[Dict]:
    """
    Scrape Chiswick Cinema showtimes from movie pages.
    """
    shows = []

    try:
        session = requests.Session()

        print(f"[{CINEMA_NAME}] Fetching listings from {LISTINGS_URL}", file=sys.stderr)
        resp = session.get(LISTINGS_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        listings_soup = BeautifulSoup(resp.text, "html.parser")
        movie_links = _extract_movie_links(listings_soup)

        print(f"[{CINEMA_NAME}] Found {len(movie_links)} movie pages", file=sys.stderr)

        for movie_url in movie_links:
            try:
                resp = session.get(movie_url, headers=HEADERS, timeout=TIMEOUT)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                title = _extract_movie_title(soup)
                if not title:
                    continue

                metadata = _extract_movie_metadata(soup)

                for link in soup.select("a[href*='/checkout/showing/']"):
                    time_text = _clean(link.get_text())
                    start_dt = _parse_showtime_text(time_text)
                    if not start_dt:
                        continue

                    show_date = start_dt.date()
                    if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                        continue

                    booking_url = link.get("href", "")
                    if booking_url and not booking_url.startswith("http"):
                        booking_url = urljoin(BASE_URL, booking_url)

                    shows.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": title,
                        "movie_title_en": title,
                        "date_text": show_date.isoformat(),
                        "showtime": start_dt.strftime("%H:%M"),
                        "detail_page_url": movie_url,
                        "booking_url": booking_url,
                        "director": metadata["director"],
                        "year": metadata["year"],
                        "country": "",
                        "runtime_min": metadata["runtime_min"],
                        "synopsis": metadata["synopsis"],
                        "format_tags": [],
                    })

            except requests.RequestException as e:
                print(f"[{CINEMA_NAME}] Error fetching {movie_url}: {e}", file=sys.stderr)
                continue

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
    data = scrape_chiswick_cinema()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
