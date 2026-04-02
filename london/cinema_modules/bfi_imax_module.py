#!/usr/bin/env python3
# bfi_imax_module.py
# Scraper for BFI IMAX cinema
# https://whatson.bfi.org.uk/imax/Online/default.asp

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
SCHEDULE_URL = f"{BASE_URL}/imax/Online/default.asp"
CINEMA_NAME = "BFI IMAX"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html_lib.unescape(text).strip())


def _parse_bfi_date(date_str: str) -> Optional[dt.date]:
    if not date_str:
        return None
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
    return None


def _parse_date(date_str: str) -> Optional[dt.date]:
    if not date_str:
        return None
    cleaned = _clean(date_str)
    iso_match = re.search(r"\d{4}-\d{2}-\d{2}", cleaned)
    if iso_match:
        try:
            return dt.date.fromisoformat(iso_match.group())
        except ValueError:
            pass
    return _parse_bfi_date(cleaned)


def _extract_js_array_from_html(html: str, anchor: str) -> Optional[list]:
    idx = html.find(anchor)
    if idx == -1: return None
    start = html.find("[", idx)
    if start == -1: return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escape: escape = False
            elif ch == "\\": escape = True
            elif ch == "\"": in_string = False
        else:
            if ch == "\"": in_string = True
            elif ch == "[": depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    raw = html[start:i + 1]
                    try: return json.loads(raw)
                    except: return None
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
        if idx is None or idx >= len(row): return ""
        val = row[idx]
        return val if isinstance(val, str) else ""

    for row in results:
        if not isinstance(row, list): continue
        item_type = get_value(row, "type")
        # In IMAX page, type is "IMAX"
        if item_type and item_type != "IMAX":
            continue
            
        title = _clean(get_value(row, "description") or get_value(row, "name"))
        if not title: continue

        start_date_text = get_value(row, "start_date")
        start_time_text = get_value(row, "start_date_time")
        show_date = _parse_date(start_date_text)
        show_time = _parse_time(start_time_text) or _parse_time(start_date_text)
        if not show_date or not show_time: continue

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


def _fetch_schedule_html() -> str:
    session = requests.Session()
    session.trust_env = False
    try:
        resp = session.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 403 or _looks_like_cloudflare_challenge(resp.text):
            try:
                import cloudscraper
                scraper = cloudscraper.create_scraper()
                resp = scraper.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
            except Exception as e:
                print(f"[{CINEMA_NAME}] Cloudscraper failed: {e}", file=sys.stderr)
        
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error fetching: {e}", file=sys.stderr)
        return ""


def scrape_bfi_imax() -> List[Dict]:
    shows = []
    html_text = _fetch_schedule_html()
    if not html_text:
        return []

    event_nodes = _extract_article_context_events(html_text)
    for event in event_nodes:
        title = event["name"]
        parsed_dt = dt.datetime.fromisoformat(event["startDate"])
        show_date = parsed_dt.date()
        
        if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
            continue

        full_url = urljoin(SCHEDULE_URL, event["url"])
        booking_url = full_url
        detail_page_url = full_url
        if "&BOparam::WScontent::loadArticle::context_id=" in full_url:
            detail_page_url = re.sub(r"&BOparam::WScontent::loadArticle::context_id=[^&]+", "", full_url)

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

    seen = set()
    unique_shows = []
    for s in shows:
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_bfi_imax()
    print(json.dumps(data, ensure_ascii=False, indent=2))
