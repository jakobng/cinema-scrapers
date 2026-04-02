#!/usr/bin/env python3
# phoenix_cinema_module.py
# Scraper for Phoenix Cinema (East Finchley)
# https://www.phoenixcinema.co.uk/
#
# Structure: Movie pages include SEO markup with showtime links like:
# <h1>Showtimes</h1><h2><a href="/checkout/showing/...">January 8, 4:45 pm</a></h2>

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.phoenixcinema.co.uk"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
CINEMA_NAME = "Phoenix Cinema"
NOW_PLAYING_URL = f"{BASE_URL}/now-playing"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14

FALLBACK_LISTING_URLS = [
    f"{BASE_URL}/now-playing",
    f"{BASE_URL}/coming-soon",
    f"{BASE_URL}/movies",
]


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _load_html_override() -> Optional[str]:
    path = os.getenv("PHOENIX_HTML_PATH")
    if path:
        return _read_text_file(path)
    return None


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_showtime_text(text: str) -> Optional[dt.datetime]:
    cleaned = _clean(text)
    if not cleaned:
        return None

    formats = [
        "%B %d, %Y, %I:%M %p",
        "%B %d, %Y, %I %p",
        "%B %d, %Y, %H:%M",
        "%B %d, %I:%M %p",
        "%B %d, %I %p",
        "%B %d, %H:%M",
    ]

    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(cleaned, fmt)
            if "%Y" not in fmt:
                parsed = parsed.replace(year=TODAY.year)
                if parsed.date() < TODAY - dt.timedelta(days=30):
                    parsed = parsed.replace(year=TODAY.year + 1)
            return parsed
        except ValueError:
            continue

    return None


def _parse_date_only(text: str) -> Optional[dt.date]:
    cleaned = _clean(text)
    if not cleaned:
        return None

    cleaned = re.sub(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[,\s]+",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    formats = [
        "%B %d, %Y",
        "%B %d %Y",
        "%B %d",
        "%d %B %Y",
        "%d %B",
        "%d %b %Y",
        "%d %b",
        "%b %d, %Y",
        "%b %d %Y",
        "%b %d",
    ]

    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(cleaned, fmt)
            if "%Y" not in fmt:
                parsed = parsed.replace(year=TODAY.year)
                if parsed.date() < TODAY - dt.timedelta(days=30):
                    parsed = parsed.replace(year=TODAY.year + 1)
            return parsed.date()
        except ValueError:
            continue

    return None


def _extract_times(text: str) -> List[str]:
    times: List[str] = []
    for match in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE):
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3).lower()
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            times.append(f"{hour:02d}:{minute:02d}")

    if not times:
        for match in re.finditer(r"\b(\d{1,2})[:.](\d{2})\b", text):
            hour = int(match.group(1))
            minute = int(match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                times.append(f"{hour:02d}:{minute:02d}")
    return times


def _extract_showtimes_from_section(soup: BeautifulSoup) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    heading = None
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        if "showtimes" in _clean(h.get_text()).lower():
            heading = h
            break

    if not heading:
        return entries

    current_date: Optional[dt.date] = None
    for elem in heading.find_all_next():
        if elem.name in {"h1", "h2", "h3", "h4"} and elem is not heading:
            break
        text = _clean(elem.get_text(" ", strip=True))
        if not text:
            continue

        date_candidate = _parse_date_only(text)
        if date_candidate:
            current_date = date_candidate

        times = _extract_times(text)
        if not times or not current_date:
            continue

        link = elem if elem.name == "a" else elem.find("a")
        booking_url = ""
        if link and link.get("href"):
            booking_url = link.get("href", "")
            if booking_url and not booking_url.startswith("http"):
                booking_url = urljoin(BASE_URL, booking_url)

        for time_str in times:
            try:
                hour, minute = map(int, time_str.split(":"))
            except ValueError:
                continue
            entries.append({
                "dt": dt.datetime.combine(current_date, dt.time(hour=hour, minute=minute)),
                "booking_url": booking_url,
            })

    return entries


def _parse_iso_datetime(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _iter_json_nodes(value: object):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_json_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_nodes(item)


def _extract_showtimes_from_json_ld(soup: BeautifulSoup) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nodes = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
        for node in nodes:
            for item in _iter_json_nodes(node):
                node_type = item.get("@type")
                if node_type:
                    if isinstance(node_type, list):
                        is_event = any("Event" in t for t in node_type if isinstance(t, str))
                    else:
                        is_event = isinstance(node_type, str) and "Event" in node_type
                    if not is_event:
                        continue
                start_value = item.get("startDate") or item.get("startTime")
                if not isinstance(start_value, str):
                    continue
                parsed_dt = _parse_iso_datetime(start_value)
                if not parsed_dt:
                    continue
                entries.append({"dt": parsed_dt, "booking_url": ""})
    return entries


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

        if isinstance(data, list):
            nodes = data
        else:
            nodes = [data]

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "Movie":
                continue
            metadata["title"] = node.get("name", "")
            metadata["synopsis"] = node.get("description", "")
            metadata["runtime_min"] = _parse_iso_duration(node.get("duration", ""))
            date_created = node.get("dateCreated", "")
            if isinstance(date_created, str) and len(date_created) >= 4:
                metadata["year"] = date_created[:4]
            directors = node.get("director")
            if isinstance(directors, list) and directors:
                director_name = directors[0].get("name") if isinstance(directors[0], dict) else ""
                metadata["director"] = director_name or ""
            elif isinstance(directors, dict):
                metadata["director"] = directors.get("name", "")
            return metadata

    title_el = soup.select_one("[data-test-id='movie-title'], .movie-info .text-h6")
    if title_el:
        metadata["title"] = _clean(title_el.get_text())

    return metadata


def _extract_showtime_links(soup: BeautifulSoup) -> List[Dict[str, str]]:
    showtimes = []
    for link in soup.select("a[href*='/checkout/showing/']"):
        showtime_text = _clean(link.get_text())
        if not showtime_text:
            continue
        href = link.get("href", "")
        if href and not href.startswith("http"):
            href = urljoin(BASE_URL, href)
        showtimes.append({"text": showtime_text, "booking_url": href})
    return showtimes


def _extract_sitemap_locs(xml_text: str) -> List[str]:
    try:
        root = ET.fromstring(xml_text)
        return [loc.text.strip() for loc in root.iter() if loc.tag.endswith("loc") and loc.text]
    except ET.ParseError:
        soup = BeautifulSoup(xml_text, "html.parser")
        return [loc.get_text(strip=True) for loc in soup.find_all("loc")]


def _extract_js_object_from_html(html: str, anchor: str) -> Optional[dict]:
    if not html:
        return None
    idx = html.find(anchor)
    if idx == -1:
        return None
    start = html.find("{", idx)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "\"":
                in_string = False
        else:
            if ch == "\"":
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw = html[start:i + 1]
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return None
    return None


def _parse_iso_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_time_value(value: str) -> Optional[str]:
    cleaned = _clean(value).lower()
    if not cleaned:
        return None
    match = re.search(r"(\d{1,2})[:.](\d{2})", cleaned)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    match = re.search(r"\b(\d{3,4})\b", cleaned)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            hour = int(digits[0])
            minute = int(digits[1:])
        else:
            hour = int(digits[:2])
            minute = int(digits[2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    return None


def _scrape_now_playing_events(session: requests.Session) -> List[Dict]:
    shows: List[Dict] = []

    try:
        resp = session.get(NOW_PLAYING_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = _extract_js_object_from_html(resp.text, "var Events")
        if not data:
            return []
        events = data.get("Events", [])
        if not isinstance(events, list):
            return []

        for event in events:
            if not isinstance(event, dict):
                continue
            title = _clean(event.get("Title", "")) or _clean(event.get("Name", ""))
            if not title:
                continue

            detail_page_url = event.get("URL", "") or NOW_PLAYING_URL
            booking_base = detail_page_url or f"{BASE_URL}/PhoenixCinemaLondon.dll/"

            format_tags = []
            tags = event.get("Tags", [])
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, dict):
                        fmt = _clean(tag.get("Format", ""))
                        if fmt:
                            format_tags.append(fmt)

            director = _clean(event.get("Director", ""))
            year = str(event.get("Year", "") or "").strip()
            runtime_min = str(event.get("RunningTime", "") or "").strip()
            synopsis = _clean(event.get("Synopsis", ""))
            country = _clean(event.get("Country", ""))

            performances = event.get("Performances", [])
            if not isinstance(performances, list):
                continue

            for perf in performances:
                if not isinstance(perf, dict):
                    continue
                show_date = _parse_iso_date(perf.get("StartDate", ""))
                show_time = _parse_time_value(perf.get("StartTimeAndNotes", "") or perf.get("StartTime", ""))
                if not show_date or not show_time:
                    continue
                if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                    continue

                booking_url = perf.get("URL", "") or ""
                if booking_url and not booking_url.startswith("http"):
                    booking_url = urljoin(booking_base, booking_url)

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": show_date.isoformat(),
                    "showtime": show_time,
                    "detail_page_url": detail_page_url,
                    "booking_url": booking_url or detail_page_url,
                    "director": director,
                    "year": year,
                    "country": country,
                    "runtime_min": runtime_min,
                    "synopsis": synopsis,
                    "format_tags": format_tags,
                })

    except requests.RequestException as exc:
        print(f"[{CINEMA_NAME}] Now playing fetch failed: {exc}", file=sys.stderr)

    return shows


def _fetch_movie_urls(session: requests.Session) -> List[str]:
    movie_urls: List[str] = []

    try:
        resp = session.get(SITEMAP_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        locs = _extract_sitemap_locs(resp.text)
        sitemap_urls = []
        for url_text in locs:
            if "/movie/" in url_text:
                movie_urls.append(url_text)
            elif url_text.endswith(".xml") or "sitemap" in url_text:
                sitemap_urls.append(url_text)

        for sitemap_url in sitemap_urls:
            try:
                sitemap_resp = session.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
                sitemap_resp.raise_for_status()
                for url_text in _extract_sitemap_locs(sitemap_resp.text):
                    if "/movie/" in url_text:
                        movie_urls.append(url_text)
            except requests.RequestException as exc:
                print(f"[{CINEMA_NAME}] Child sitemap fetch failed ({sitemap_url}): {exc}", file=sys.stderr)
    except requests.RequestException as exc:
        print(f"[{CINEMA_NAME}] Sitemap fetch failed: {exc}", file=sys.stderr)

    if movie_urls:
        return sorted(set(movie_urls))

    for listing_url in FALLBACK_LISTING_URLS:
        try:
            resp = session.get(listing_url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a[href*='/movie/']"):
                href = link.get("href", "")
                if href and not href.startswith("http"):
                    href = urljoin(BASE_URL, href)
                if "/movie/" in href:
                    movie_urls.append(href)
        except requests.RequestException as exc:
            print(f"[{CINEMA_NAME}] Listing fetch failed ({listing_url}): {exc}", file=sys.stderr)

    return sorted(set(movie_urls))


def scrape_phoenix_cinema() -> List[Dict]:
    """
    Scrape Phoenix Cinema showtimes from individual movie pages.

    Returns a list of showtime records with standard schema.
    """
    shows: List[Dict] = []

    try:
        html_override = _load_html_override()
        session = requests.Session()
        session.trust_env = False

        if html_override:
            movie_pages = [("", html_override)]
        else:
            movie_urls = _fetch_movie_urls(session)
            movie_pages = []
            for movie_url in movie_urls:
                resp = session.get(movie_url, headers=HEADERS, timeout=TIMEOUT)
                resp.raise_for_status()
                movie_pages.append((movie_url, resp.text))

        for movie_url, html in movie_pages:
            soup = BeautifulSoup(html, "html.parser")
            metadata = _extract_movie_metadata(soup)
            title = metadata["title"]

            if not title:
                continue

            parsed_entries: List[Dict[str, object]] = []
            for showtime in _extract_showtime_links(soup):
                parsed_dt = _parse_showtime_text(showtime["text"])
                if not parsed_dt:
                    continue
                parsed_entries.append({"dt": parsed_dt, "booking_url": showtime["booking_url"]})

            if not parsed_entries:
                parsed_entries = _extract_showtimes_from_section(soup)

            if not parsed_entries:
                parsed_entries = _extract_showtimes_from_json_ld(soup)

            for entry in parsed_entries:
                parsed_dt = entry.get("dt")
                if not isinstance(parsed_dt, dt.datetime):
                    continue

                show_date = parsed_dt.date()
                if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                    continue

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": show_date.isoformat(),
                    "showtime": parsed_dt.strftime("%H:%M"),
                    "detail_page_url": movie_url or "",
                    "booking_url": entry.get("booking_url") or movie_url or "",
                    "director": metadata["director"],
                    "year": metadata["year"],
                    "country": "",
                    "runtime_min": metadata["runtime_min"],
                    "synopsis": metadata["synopsis"],
                    "format_tags": [],
                })

        if not shows:
            shows = _scrape_now_playing_events(session)

        print(f"[{CINEMA_NAME}] Found {len(shows)} showings", file=sys.stderr)

    except requests.RequestException as exc:
        print(f"[{CINEMA_NAME}] HTTP Error: {exc}", file=sys.stderr)
        raise
    except Exception as exc:
        print(f"[{CINEMA_NAME}] Error: {exc}", file=sys.stderr)
        raise

    return shows


if __name__ == "__main__":
    data = scrape_phoenix_cinema()
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
    for s in data[:5]:
        print(s)
