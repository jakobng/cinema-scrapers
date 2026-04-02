#!/usr/bin/env python3
# bfi_southbank_module.py
# Scraper for BFI Southbank cinema
# https://whatson.bfi.org.uk/
#
# Structure: BFI embeds showtime data as a JavaScript array in the page.
# We extract this array and parse it to get film listings.

from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import os
import re
import sys
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://whatson.bfi.org.uk"
SCHEDULE_URL = f"{BASE_URL}/Online/default.asp"
SCHEDULE_FALLBACK_URLS = [
    SCHEDULE_URL,
    f"{BASE_URL}/Online/",
]
CINEMA_NAME = "BFI Southbank"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 7


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _load_html_override() -> Optional[str]:
    path = os.getenv("BFI_HTML_PATH")
    if path:
        return _read_text_file(path)
    return None


def _load_json_ld_override() -> Optional[List[dict]]:
    path = os.getenv("BFI_JSON_LD_PATH")
    if not path:
        return None
    raw = _read_text_file(path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return None


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", html_lib.unescape(text).strip())


def _parse_bfi_date(date_str: str) -> Optional[dt.date]:
    """
    Parse BFI date format like "Friday 09 January 2026 18:10".
    Returns date object or None.
    """
    if not date_str:
        return None

    # Remove day name and time
    # Pattern: "DayName DD Month YYYY HH:MM"
    match = re.match(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})\s+(\w+)\s+(\d{4})",
        date_str,
        re.I
    )

    if match:
        day = int(match.group(1))
        month_name = match.group(2)
        year = int(match.group(3))

        months = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12
        }

        month = months.get(month_name.lower())
        if month:
            try:
                return dt.date(year, month, day)
            except ValueError:
                pass

    return None


def _parse_time(time_str: str) -> Optional[str]:
    """Parse time and return in HH:MM format."""
    if not time_str:
        return None
    cleaned = _clean(time_str).upper()

    match = re.search(r"(\d{1,2})[:\.](\d{2})\s*(AM|PM)?", cleaned)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3)
        if period == "PM" and hour != 12:
            hour += 12
        elif period == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    match = re.search(r"\b(\d{1,2})\s*(AM|PM)\b", cleaned)
    if match:
        hour = int(match.group(1))
        period = match.group(2)
        if period == "PM" and hour != 12:
            hour += 12
        elif period == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:00"

    return None


def _parse_date(date_str: str) -> Optional[dt.date]:
    """Parse date text into a date."""
    if not date_str:
        return None
    cleaned = _clean(date_str)
    if not cleaned:
        return None

    iso_match = re.search(r"\d{4}-\d{2}-\d{2}", cleaned)
    if iso_match:
        try:
            return dt.date.fromisoformat(iso_match.group())
        except ValueError:
            return None

    parsed = _parse_bfi_date(cleaned)
    if parsed:
        return parsed

    formats_with_year = [
        "%A %d %B %Y",
        "%a %d %B %Y",
        "%d %B %Y",
        "%d %b %Y",
    ]
    for fmt in formats_with_year:
        try:
            return dt.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    formats_without_year = [
        "%A %d %B",
        "%a %d %B",
        "%d %B",
        "%d %b",
    ]
    for fmt in formats_without_year:
        try:
            parsed_dt = dt.datetime.strptime(cleaned, fmt)
            parsed_dt = parsed_dt.replace(year=TODAY.year)
            if parsed_dt.date() < TODAY - dt.timedelta(days=30):
                parsed_dt = parsed_dt.replace(year=TODAY.year + 1)
            return parsed_dt.date()
        except ValueError:
            continue

    return None


def _parse_iso_datetime(value: str) -> Optional[dt.datetime]:
    """Parse ISO-ish datetime strings, normalizing Z offsets."""
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _iter_json_nodes(value: object) -> Iterable[dict]:
    """Yield dict nodes from nested JSON structures."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_json_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_nodes(item)


def _extract_json_ld(soup: BeautifulSoup) -> List[dict]:
    """Collect JSON-LD blocks from the page."""
    blocks: List[dict] = []
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            blocks.append(data)
        elif isinstance(data, list):
            blocks.extend([item for item in data if isinstance(item, dict)])
    return blocks


def _extract_js_array_from_html(html: str, anchor: str) -> Optional[list]:
    if not html:
        return None
    idx = html.find(anchor)
    if idx == -1:
        return None
    start = html.find("[", idx)
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
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    raw = html[start:i + 1]
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return None
    return None


def _extract_article_context_events(html: str) -> List[dict]:
    names = _extract_js_array_from_html(html, "searchNames")
    results = _extract_js_array_from_html(html, "searchResults")
    if not names or not results:
        return []

    name_index = {name: idx for idx, name in enumerate(names)}
    events = []

    def get_value(row: list, key: str) -> str:
        idx = name_index.get(key)
        if idx is None or idx >= len(row):
            return ""
        value = row[idx]
        return value if isinstance(value, str) else ""

    for row in results:
        if not isinstance(row, list):
            continue
        item_type = get_value(row, "type")
        # DEBUG: print(f"Item type: {item_type}")
        if item_type and item_type != "BFI Southbank":
            if item_type == "IMAX":
                print("DEBUG: Found IMAX entry in main BFI site!")
            continue
        category = _clean(get_value(row, "category"))
        venue_name = _clean(get_value(row, "venue_name"))
        venue_group = _clean(get_value(row, "venue_group"))
        if category.lower() == "education":
            continue
        if "library" in venue_name.lower() or "education" in venue_name.lower():
            continue
        if "library" in venue_group.lower() or "education" in venue_group.lower():
            continue
        title = _clean(
            get_value(row, "description")
            or get_value(row, "short_description")
            or get_value(row, "name")
        )
        if not title:
            continue

        start_date_text = get_value(row, "start_date")
        start_time_text = get_value(row, "start_date_time")
        show_date = _parse_date(start_date_text)
        show_time = _parse_time(start_time_text) or _parse_time(start_date_text)
        if not show_date or not show_time:
            continue

        detail_path = ""
        for key in ("additional_info", "group", "options"):
            candidate = get_value(row, key)
            if "default.asp?doWork::WScontent::loadArticle" in candidate:
                detail_path = candidate
                break
        if not detail_path:
            detail_path = get_value(row, "additional_info")

        events.append({
            "name": title,
            "startDate": f"{show_date.isoformat()}T{show_time}",
            "url": detail_path,
        })

    return events


def _looks_like_cloudflare_challenge(html: str) -> bool:
    if not html:
        return False
    lowered = html.lower()
    return "just a moment" in lowered or "cf-ray" in lowered or "cloudflare" in lowered


def _fetch_schedule_html() -> tuple:
    session = requests.Session()
    session.trust_env = False
    referer = f"{BASE_URL}/"
    headers = {**HEADERS, "Referer": referer}

    last_resp = None
    for url in SCHEDULE_FALLBACK_URLS:
        try:
            session.get(referer, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            pass
        resp = session.get(url, headers=headers, timeout=TIMEOUT)
        last_resp = resp
        if resp.status_code == 403 or _looks_like_cloudflare_challenge(resp.text):
            continue
        resp.raise_for_status()
        return resp.text, session

    try:
        import cloudscraper
    except Exception:
        raise RuntimeError(
            "BFI blocked the request (Cloudflare). Install cloudscraper or provide BFI_HTML_PATH."
        ) from None

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    scraper.trust_env = False
    for url in SCHEDULE_FALLBACK_URLS:
        try:
            scraper.get(referer, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            pass
        resp = scraper.get(url, headers=headers, timeout=TIMEOUT)
        last_resp = resp
        if resp.status_code == 403 or _looks_like_cloudflare_challenge(resp.text):
            continue
        resp.raise_for_status()
        return resp.text, scraper

    if last_resp is not None:
        last_resp.raise_for_status()
    raise RuntimeError("BFI request failed with no response")


def _fetch_detail_html(
    detail_url: str,
    session: Optional[requests.Session] = None,
    referer: str = "",
) -> str:
    if not detail_url:
        return ""
    headers = HEADERS
    if referer:
        headers = {**HEADERS, "Referer": referer}
    active_session = session
    if active_session is None:
        active_session = requests.Session()
        active_session.trust_env = False
    try:
        resp = active_session.get(detail_url, headers=headers, timeout=TIMEOUT)
        if resp.status_code == 403 or _looks_like_cloudflare_challenge(resp.text):
            try:
                import cloudscraper
            except Exception:
                print(f"[{CINEMA_NAME}] Cloudscraper not available for detail pages.", file=sys.stderr)
            else:
                scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False}
                )
                scraper.trust_env = False
                try:
                    scraper.cookies.update(active_session.cookies)
                except Exception:
                    pass
                resp = scraper.get(detail_url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error fetching detail page: {e}", file=sys.stderr)
        return ""


def _normalize_title_for_compare(text: str) -> str:
    if not text:
        return ""
    lowered = _clean(text).lower()
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _should_override_title(original: str, detail_title: str) -> bool:
    if not detail_title:
        return False
    if not original:
        return True
    original_norm = _normalize_title_for_compare(original)
    detail_norm = _normalize_title_for_compare(detail_title)
    if not detail_norm:
        return False
    if original_norm == detail_norm:
        return False
    return detail_norm in original_norm or original_norm in detail_norm


def _extract_year_from_text(text: str) -> str:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    return match.group(1) if match else ""


def _extract_runtime_from_text(text: str) -> str:
    match = re.search(r"(\d{2,3})\s*min", text, re.IGNORECASE)
    return match.group(1) if match else ""


def _extract_detail_metadata(detail_html: str) -> Dict[str, str]:
    metadata = {
        "title": "",
        "director": "",
        "year": "",
        "country": "",
        "runtime_min": "",
        "synopsis": "",
    }
    if not detail_html:
        return metadata

    soup = BeautifulSoup(detail_html, "html.parser")

    title_elem = soup.find("h1")
    if title_elem:
        metadata["title"] = _clean(title_elem.get_text(" ", strip=True))

    info_wrappers = soup.select("ul.Film-info__information li.Film-info__information__wrapper")
    info_values: List[str] = []
    for wrapper in info_wrappers:
        heading_elem = wrapper.select_one(".Film-info__information__heading")
        value_elem = wrapper.select_one(".Film-info__information__value")
        value_text = _clean(value_elem.get_text(" ", strip=True)) if value_elem else ""
        if value_text:
            info_values.append(value_text)

        heading = _clean(heading_elem.get_text(" ", strip=True)) if heading_elem else ""
        heading_norm = heading.lower()
        if not heading_norm or not value_text:
            continue
        if "director" in heading_norm and not metadata["director"]:
            metadata["director"] = value_text
        elif ("runtime" in heading_norm or "running time" in heading_norm or "duration" in heading_norm) and not metadata["runtime_min"]:
            metadata["runtime_min"] = _extract_runtime_from_text(value_text)
        elif "year" in heading_norm and not metadata["year"]:
            metadata["year"] = _extract_year_from_text(value_text)
        elif "country" in heading_norm and not metadata["country"]:
            metadata["country"] = value_text

    if not metadata["year"] or not metadata["runtime_min"] or not metadata["country"]:
        for value_text in info_values:
            if not metadata["year"]:
                metadata["year"] = _extract_year_from_text(value_text) or metadata["year"]
            if not metadata["runtime_min"]:
                metadata["runtime_min"] = _extract_runtime_from_text(value_text) or metadata["runtime_min"]
            if metadata["year"] and not metadata["country"]:
                year_match = re.search(r"\b(19\d{2}|20\d{2})\b", value_text)
                if year_match:
                    country_candidate = value_text[:year_match.start()].strip(" ,.-")
                    if country_candidate:
                        metadata["country"] = country_candidate

    synopsis_elem = soup.select_one(".Page__description")
    if synopsis_elem:
        metadata["synopsis"] = _clean(synopsis_elem.get_text(" ", strip=True))

    return metadata


def _enrich_shows_with_detail_pages(
    shows: List[Dict],
    session: Optional[requests.Session] = None,
    referer: str = "",
) -> List[Dict]:
    if not shows:
        return shows
    detail_cache: Dict[str, Dict[str, str]] = {}
    for show in shows:
        detail_url = show.get("detail_page_url") or ""
        if not detail_url:
            continue
        if detail_url not in detail_cache:
            detail_html = _fetch_detail_html(detail_url, session=session, referer=referer)
            detail_cache[detail_url] = _extract_detail_metadata(detail_html) if detail_html else {}
        metadata = detail_cache.get(detail_url) or {}
        if not metadata:
            continue
        detail_title = metadata.get("title", "")
        if detail_title and _should_override_title(show.get("movie_title", ""), detail_title):
            show["movie_title"] = detail_title
            show["movie_title_en"] = detail_title
        for key in ("director", "year", "country", "runtime_min", "synopsis"):
            if metadata.get(key) and not show.get(key):
                show[key] = metadata[key]
    return shows


def _collect_event_nodes(json_ld: List[dict]) -> List[dict]:
    """Return JSON-LD nodes that represent events."""
    events: List[dict] = []
    for block in json_ld:
        for node in _iter_json_nodes(block):
            node_type = node.get("@type")
            if isinstance(node_type, list):
                is_event = any("Event" in t for t in node_type if isinstance(t, str))
            else:
                is_event = isinstance(node_type, str) and "Event" in node_type
            if is_event:
                events.append(node)
    return events


def scrape_bfi_southbank() -> List[Dict]:
    """
    Scrape BFI Southbank showtimes.

    Returns a list of showtime records with standard schema:
    - cinema_name: str
    - movie_title: str
    - date_text: str (YYYY-MM-DD)
    - showtime: str (HH:MM)
    - detail_page_url: str
    - director: str (optional)
    - year: str (optional)
    - country: str (optional)
    - runtime_min: str (optional)
    - synopsis: str (optional)
    - movie_title_en: str (optional, same as movie_title for UK)

    Optional overrides for offline testing:
    - BFI_HTML_PATH: path to a saved HTML file for the schedule page.
    - BFI_JSON_LD_PATH: path to a JSON/JSON-LD blob to parse instead of the page.
    """
    shows = []

    try:
        # BFI's schedule page may require session handling or specific parameters
        html_override = _load_html_override()
        html_text = ""
        soup = None
        detail_session = None
        if html_override:
            html_text = html_override
            soup = BeautifulSoup(html_override, "html.parser")
            detail_session = requests.Session()
            detail_session.trust_env = False
        else:
            html_text, detail_session = _fetch_schedule_html()
            soup = BeautifulSoup(html_text, "html.parser")

        if html_text:
            event_nodes = _extract_article_context_events(html_text)
        else:
            event_nodes = []

        json_ld_blocks = _load_json_ld_override()
        if json_ld_blocks is None and soup is not None:
            json_ld_blocks = _extract_json_ld(soup)
        if json_ld_blocks is None:
            json_ld_blocks = []
        event_nodes.extend(_collect_event_nodes(json_ld_blocks))

        for event in event_nodes:
            title = _clean(event.get("name", "")) or _clean(event.get("headline", ""))
            if not title:
                continue

            event_url = event.get("url", "")
            if event_url:
                # detail_url should be the general film page (strip context_id if present)
                # booking_url can be the specific performance page
                full_url = urljoin(SCHEDULE_URL, event_url)
                booking_url = full_url
                detail_page_url = full_url
                if "&BOparam::WScontent::loadArticle::context_id=" in full_url:
                    detail_page_url = re.sub(r"&BOparam::WScontent::loadArticle::context_id=[^&]+", "", full_url)
            else:
                detail_page_url = ""
                booking_url = ""

            sub_events = event.get("subEvent") or event.get("eventSchedule") or []
            if isinstance(sub_events, dict):
                sub_events = [sub_events]
            if not isinstance(sub_events, list):
                sub_events = []

            if sub_events:
                for sub in sub_events:
                    start_value = sub.get("startDate") or sub.get("startTime")
                    parsed_dt = _parse_iso_datetime(start_value)
                    if not parsed_dt:
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
                        "detail_page_url": detail_page_url,
                        "booking_url": booking_url,
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": "",
                        "synopsis": "",
                    })
            else:
                start_value = event.get("startDate") or event.get("startTime")
                parsed_dt = _parse_iso_datetime(start_value)
                if not parsed_dt:
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
                    "detail_page_url": detail_page_url,
                    "booking_url": booking_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
                })

        if not shows and soup is not None:
            listings = soup.select(".film-listing, .event-item, .showing, article")

            for listing in listings:
                title_elem = listing.select_one(".title, h3, h4, .film-title")
                if not title_elem:
                    continue

                title = _clean(title_elem.get_text())
                if not title:
                    continue

                date_elem = listing.select_one(".date, .showing-date, time")
                date_str = date_elem.get_text() if date_elem else ""
                show_date = _parse_date(date_str)
                if not show_date:
                    continue

                if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                    continue

                time_elem = listing.select_one(".time, .showing-time")
                time_str = time_elem.get_text() if time_elem else ""
                show_time = _parse_time(time_str)
                if not show_time:
                    continue

                link_elem = listing.select_one("a[href]")
                detail_page_url = ""
                booking_url = ""
                if link_elem and link_elem.get("href"):
                    full_url = urljoin(SCHEDULE_URL, link_elem["href"])
                    booking_url = full_url
                    detail_page_url = full_url
                    if "&BOparam::WScontent::loadArticle::context_id=" in full_url:
                        detail_page_url = re.sub(r"&BOparam::WScontent::loadArticle::context_id=[^&]+", "", full_url)

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": show_date.isoformat(),
                    "showtime": show_time,
                    "detail_page_url": detail_page_url,
                    "booking_url": booking_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
                })

        if not shows:
            print(f"[{CINEMA_NAME}] Note: No shows found. Page structure may need analysis.", file=sys.stderr)
            print(f"[{CINEMA_NAME}] URL: {SCHEDULE_URL}", file=sys.stderr)

    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        raise

    shows = _enrich_shows_with_detail_pages(shows, session=detail_session, referer=SCHEDULE_URL)

    # Deduplicate
    seen = set()
    unique_shows = []
    for s in shows:
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_bfi_southbank()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
