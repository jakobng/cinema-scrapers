#!/usr/bin/env python3
# genesis_module.py
# Scraper for Genesis Cinema (Mile End)
# https://genesiscinema.co.uk/whatson/all

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

BASE_URL = "https://genesiscinema.co.uk"
SCHEDULE_URL = f"{BASE_URL}/whatson/all"
CINEMA_NAME = "Genesis Cinema"

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
    path = os.getenv("GENESIS_HTML_PATH")
    if path:
        return _read_text_file(path)
    return None


def _clean(text: str) -> str:
    """Clean up whitespace in text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_date_from_panel_id(panel_id: str) -> Optional[dt.date]:
    """
    Parse date from panel ID like 'panel_20260109' (YYYYMMDD format).
    """
    if not panel_id:
        return None
    # Extract YYYYMMDD from panel_YYYYMMDD
    match = re.search(r"panel_(\d{8})", panel_id)
    if not match:
        return None
    date_str = match.group(1)
    try:
        return dt.datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        return None


def _parse_date_from_data_target(data_target: str) -> Optional[dt.date]:
    """
    Parse date from data-target attribute like '20260109' (YYYYMMDD format).
    """
    if not data_target:
        return None
    try:
        return dt.datetime.strptime(data_target, "%Y%m%d").date()
    except ValueError:
        return None


def _parse_time_text(value: str) -> Optional[str]:
    """
    Extract time from text like '20:30' or '8:30pm'.
    Returns 24-hour format HH:MM.
    """
    if not value:
        return None
    cleaned = value.strip().upper()
    # Try HH:MM format first
    match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", cleaned)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    period = match.group(3)

    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0

    return f"{hour:02d}:{minute:02d}"


def _parse_full_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    formats = ["%A %d %B %Y", "%A %d %b %Y"]
    for fmt in formats:
        try:
            return dt.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _extract_event_id(href: str) -> Optional[str]:
    """Extract event ID from URL like '/event/105804'."""
    if not href:
        return None
    match = re.search(r"/event/(\d+)", href)
    return match.group(1) if match else None


def _extract_perf_code(href: str) -> Optional[str]:
    """Extract performance code from booking URL."""
    if not href:
        return None
    match = re.search(r"perfCode=(\d+)", href)
    return match.group(1) if match else None


def _scrape_event_blocks(soup: BeautifulSoup) -> List[Dict]:
    shows: List[Dict] = []
    date_pattern = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}",
        re.IGNORECASE,
    )

    for h1 in soup.find_all("h1"):
        title_link = h1.find("a", href=re.compile(r"/event/\d+"))
        if not title_link:
            continue

        movie_title = _clean(title_link.get_text())
        if not movie_title:
            continue

        movie_href = title_link.get("href", "")
        detail_url = urljoin(BASE_URL, movie_href) if movie_href else ""

        container = h1.find_parent("div")
        while container and not container.find("a", href=re.compile(r"perfCode=\d+")):
            container = container.find_parent("div")
        if not container:
            continue

        for date_block in container.find_all("div"):
            text = date_block.get_text(" ", strip=True)
            match = date_pattern.search(text)
            if not match:
                continue
            show_date = _parse_full_date(match.group(0))
            if not show_date:
                continue
            if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                continue

            for time_link in date_block.find_all("a", href=re.compile(r"perfCode=\d+")):
                time_text = _clean(time_link.get_text())
                showtime = _parse_time_text(time_text)
                if not showtime:
                    continue

                booking_url = time_link.get("href", "")
                if booking_url and not booking_url.startswith("http"):
                    booking_url = urljoin(BASE_URL, booking_url)

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title,
                    "movie_title_en": movie_title,
                    "date_text": show_date.isoformat(),
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                    "booking_url": booking_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
                })

    return shows


def scrape_genesis() -> List[Dict]:
    """
    Scrape Genesis Cinema showtimes.

    The page structure:
    - Date tabs with data-target="YYYYMMDD"
    - Each date has a panel with id="panel_YYYYMMDD" and class="whatson_panel"
    - Movies are repeated in each date panel with their showtimes for that date
    - Movie titles are in <a href="/event/{id}"> elements
    - Showtimes are <a> elements linking to booking URLs with perfCode

    Optional override for offline testing:
    - GENESIS_HTML_PATH: path to a saved HTML file for the schedule page.
    """
    shows: List[Dict] = []

    try:
        html_override = _load_html_override()
        if html_override:
            soup = BeautifulSoup(html_override, "html.parser")
        else:
            session = requests.Session()
            session.trust_env = False
            resp = session.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

        # Find all date panels
        # The panels have id like "panel_20260109" and class "whatson_panel"
        panels = soup.select("[id^='panel_']")

        if not panels:
            # Try alternative selectors
            panels = soup.select(".whatson_panel")

        for panel in panels:
            panel_id = panel.get("id", "")
            show_date = _parse_date_from_panel_id(panel_id)

            if not show_date:
                # Try to extract date from data attributes or class
                data_target = panel.get("data-target", "")
                show_date = _parse_date_from_data_target(data_target)

            if not show_date:
                continue

            # Check if date is within our window
            if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                continue

            # Find all movie entries in this panel
            # Movies are typically in containers with images and title links
            # Look for links to /event/{id} pages
            movie_containers = panel.find_all(
                lambda tag: tag.name in ["div", "article", "section"] and
                tag.find("a", href=re.compile(r"/event/\d+"))
            )

            # If no containers found, try getting movies directly from the panel
            if not movie_containers:
                movie_containers = [panel]

            processed_movies = set()

            for container in movie_containers:
                # Find movie title and link
                title_link = container.find("a", href=re.compile(r"/event/\d+"))
                if not title_link:
                    continue

                movie_href = title_link.get("href", "")
                event_id = _extract_event_id(movie_href)

                # Get movie title - check for heading text or link text
                title_elem = title_link.find(["h1", "h2", "h3", "h4"])
                if title_elem:
                    movie_title = _clean(title_elem.get_text())
                else:
                    movie_title = _clean(title_link.get_text())

                if not movie_title or not event_id:
                    continue

                # Skip if we've already processed this movie for this date
                movie_key = (event_id, show_date.isoformat())
                if movie_key in processed_movies:
                    continue
                processed_movies.add(movie_key)

                # Build detail page URL
                detail_url = urljoin(BASE_URL, movie_href) if movie_href else ""

                # Find showtimes - look for booking links with perfCode
                # These are usually in the same container or nearby
                showtime_links = container.find_all(
                    "a", href=re.compile(r"perfCode=\d+")
                )

                # If no showtimes found in container, search wider
                if not showtime_links:
                    # Look for time patterns in any links nearby
                    all_links = container.find_all("a")
                    for link in all_links:
                        link_text = link.get_text().strip()
                        if re.match(r"\d{1,2}:\d{2}", link_text):
                            showtime_links.append(link)

                if not showtime_links:
                    # No showtimes found - skip this movie for this date
                    continue

                for time_link in showtime_links:
                    time_text = _clean(time_link.get_text())
                    showtime = _parse_time_text(time_text)

                    if not showtime:
                        continue

                    booking_url = time_link.get("href", "")
                    if not booking_url.startswith("http"):
                        booking_url = urljoin(BASE_URL, booking_url)

                    shows.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": movie_title,
                        "movie_title_en": movie_title,
                        "date_text": show_date.isoformat(),
                        "showtime": showtime,
                        "detail_page_url": detail_url,
                        "booking_url": booking_url,
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": "",
                        "synopsis": "",
                    })

        # Alternative approach: Parse by looking for all event links and times
        # if the panel-based approach didn't work well
        if not shows:
            print(f"[{CINEMA_NAME}] Panel-based parsing found no shows, trying alternative approach...", file=sys.stderr)
            shows = _scrape_alternative(soup)

        if not shows:
            shows = _scrape_event_blocks(soup)

        if not shows:
            print(f"[{CINEMA_NAME}] Note: No shows found. Page structure may have changed.", file=sys.stderr)
            print(f"[{CINEMA_NAME}] URL: {SCHEDULE_URL}", file=sys.stderr)

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
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


def _scrape_alternative(soup: BeautifulSoup) -> List[Dict]:
    """
    Alternative scraping approach when panel-based parsing fails.
    Look for date tab structure and process differently.
    """
    shows: List[Dict] = []

    # Find date tabs
    tabs = soup.select("[data-target]")
    date_map = {}

    for tab in tabs:
        data_target = tab.get("data-target", "")
        if data_target and re.match(r"\d{8}", data_target):
            show_date = _parse_date_from_data_target(data_target)
            if show_date and TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS):
                date_map[data_target] = show_date

    # Process each date's content
    for date_id, show_date in date_map.items():
        # Find the panel for this date
        panel = soup.find(id=f"panel_{date_id}")
        if not panel:
            panel = soup.find(attrs={"data-date": date_id})
        if not panel:
            continue

        # Find all movie links and their showtimes
        event_links = panel.find_all("a", href=re.compile(r"/event/\d+"))

        for event_link in event_links:
            movie_title = _clean(event_link.get_text())
            if not movie_title:
                continue

            movie_href = event_link.get("href", "")
            detail_url = urljoin(BASE_URL, movie_href)

            # Find sibling or nearby showtime links
            parent = event_link.parent
            if parent:
                time_links = parent.find_all("a", href=re.compile(r"perfCode="))
                for time_link in time_links:
                    time_text = _clean(time_link.get_text())
                    showtime = _parse_time_text(time_text)
                    if showtime:
                        booking_url = time_link.get("href", "")
                        shows.append({
                            "cinema_name": CINEMA_NAME,
                            "movie_title": movie_title,
                            "movie_title_en": movie_title,
                            "date_text": show_date.isoformat(),
                            "showtime": showtime,
                            "detail_page_url": detail_url,
                            "booking_url": booking_url,
                            "director": "",
                            "year": "",
                            "country": "",
                            "runtime_min": "",
                            "synopsis": "",
                        })

    return shows


if __name__ == "__main__":
    data = scrape_genesis()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\nTotal: {len(data)} showings")
