#!/usr/bin/env python3
# regent_street_module.py
# Scraper for Regent Street Cinema (Oxford Circus)
# https://www.regentstreetcinema.com/now-playing
#
# Structure:
# - Now Playing page links to /movie/{slug} detail pages.
# - Movie detail pages include showtimes as links like:
#   <a href="/checkout/showing/...">January 9, 7:30 pm</a>
# - Movie metadata available via JSON-LD Movie schema.

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.regentstreetcinema.com"
NOW_PLAYING_URL = f"{BASE_URL}/now-playing"
CINEMA_NAME = "Regent Street Cinema"

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
    path = os.getenv("REGENT_STREET_HTML_PATH")
    if path:
        return _read_text_file(path)
    return None


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_iso_duration(duration: str) -> str:
    if not duration:
        return ""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration)
    if not match:
        return ""
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    total_minutes = hours * 60 + minutes
    return str(total_minutes) if total_minutes else ""


def _parse_showtime_text(text: str) -> Optional[dt.datetime]:
    cleaned = _clean(text).lower()
    if not cleaned:
        return None

    match = re.search(
        r"([a-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?\s*,?\s*(\d{1,2})(?:[:\.](\d{2}))?\s*(am|pm)",
        cleaned,
        re.I,
    )
    if not match:
        return None

    month_str = match.group(1)[:3].lower()
    day = int(match.group(2))
    year = int(match.group(3)) if match.group(3) else TODAY.year
    hour = int(match.group(4))
    minute = int(match.group(5) or 0)
    period = match.group(6).lower()

    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "may": 5, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    month = month_map.get(month_str)
    if not month:
        return None

    if period == "pm" and hour != 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0

    try:
        parsed = dt.datetime(year, month, day, hour, minute)
    except ValueError:
        return None

    if not match.group(3) and parsed.date() < TODAY - dt.timedelta(days=30):
        try:
            parsed = parsed.replace(year=year + 1)
        except ValueError:
            return None

    return parsed


def _extract_movie_links(soup: BeautifulSoup) -> List[str]:
    links = []

    for link in soup.select("a[href*='/checkout/showing/']"):
        href = link.get("href", "")
        # Match slug: /checkout/showing/slug/id or /checkout/showing/slug
        match = re.search(r"/checkout/showing/([^/]+)", href)
        if not match:
            continue
        movie_slug = match.group(1)
        movie_url = f"{BASE_URL}/movie/{movie_slug}"
        if movie_url not in links:
            links.append(movie_url)

    if links:
        return links

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/movie/" not in href:
            continue
        if href.startswith("/movie/"):
            href = urljoin(BASE_URL, href)
        if href.startswith(BASE_URL + "/movie/") and href not in links:
            links.append(href)

    return links


def _extract_movie_metadata(soup: BeautifulSoup) -> Dict[str, str]:
    metadata = {
        "title": "",
        "director": "",
        "year": "",
        "runtime_min": "",
        "synopsis": "",
    }

    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "Movie":
                continue

            metadata["title"] = node.get("name", "") or metadata["title"]
            metadata["synopsis"] = node.get("description", "") or metadata["synopsis"]
            metadata["runtime_min"] = _parse_iso_duration(node.get("duration", "")) or metadata["runtime_min"]

            date_created = node.get("dateCreated", "")
            if isinstance(date_created, str) and len(date_created) >= 4:
                metadata["year"] = date_created[:4]

            directors = node.get("director")
            if isinstance(directors, list) and directors:
                first_director = directors[0]
                if isinstance(first_director, dict):
                    metadata["director"] = first_director.get("name", "") or metadata["director"]
            elif isinstance(directors, dict):
                metadata["director"] = directors.get("name", "") or metadata["director"]

    if not metadata["title"]:
        title_el = soup.select_one("[itemprop='name']") or soup.find("h1")
        if title_el:
            metadata["title"] = _clean(title_el.get_text())

    return metadata


def _extract_showtimes(soup: BeautifulSoup, detail_url: str) -> List[Dict]:
    shows = []
    metadata = _extract_movie_metadata(soup)
    title = metadata["title"]
    if not title:
        return shows

    for link in soup.select("a[href*='/checkout/showing/']"):
        time_text = _clean(link.get_text())
        parsed_dt = _parse_showtime_text(time_text)
        if not parsed_dt:
            continue

        show_date = parsed_dt.date()
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
            "showtime": parsed_dt.strftime("%H:%M"),
            "detail_page_url": detail_url,
            "booking_url": booking_url,
            "director": metadata["director"],
            "year": metadata["year"],
            "country": "",
            "runtime_min": metadata["runtime_min"],
            "synopsis": metadata["synopsis"],
            "format_tags": [],
        })

    return shows


def scrape_regent_street() -> List[Dict]:
    """
    Scrape Regent Street Cinema showtimes.
    """
    shows: List[Dict] = []

    try:
        html_override = _load_html_override()
        session = requests.Session()

        if html_override:
            movie_pages = [("", html_override)]
        else:
            resp = session.get(NOW_PLAYING_URL, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            movie_links = _extract_movie_links(soup)

            if not movie_links:
                raise ValueError("No movie links found on now playing page.")

            movie_pages = []
            for movie_url in movie_links:
                resp = session.get(movie_url, headers=HEADERS, timeout=TIMEOUT)
                resp.raise_for_status()
                movie_pages.append((movie_url, resp.text))

        for movie_url, html in movie_pages:
            soup = BeautifulSoup(html, "html.parser")
            shows.extend(_extract_showtimes(soup, movie_url))

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
    data = scrape_regent_street()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
