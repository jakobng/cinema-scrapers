from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.artistvillage.org/"
LISTING_URL = urljoin(BASE_URL, "event.php")
CINEMA_NAME = "寶藏巖國際藝術村"
KEYWORDS = (
    "電影",
    "放映",
    "影片",
    "錄像",
    "影像",
    "screening",
    "film",
    "cinema",
    "video",
)


def _fetch_soup(url: str) -> BeautifulSoup:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _is_screening_candidate(*values: object) -> bool:
    haystack = " ".join(_clean_text(str(value or "")) for value in values).lower()
    return any(keyword.lower() in haystack for keyword in KEYWORDS)


def _parse_date_range(text: str) -> tuple[Optional[str], Optional[str]]:
    match = re.search(r"(20\d{2})-(\d{2})-(\d{2})\s*~\s*(20\d{2})-(\d{2})-(\d{2})", text)
    if match:
        start = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        end = f"{match.group(4)}-{match.group(5)}-{match.group(6)}"
        return start, end
    single = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if single:
        value = f"{single.group(1)}-{single.group(2)}-{single.group(3)}"
        return value, value
    return None, None


def _parse_time(text: str) -> Optional[str]:
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)
    if not match:
        return None
    hour = int(match.group(1))
    if hour > 23:
        return None
    return f"{hour:02d}:{match.group(2)}"


def _extract_image_url(soup: BeautifulSoup) -> Optional[str]:
    tag = soup.select_one('meta[property="og:image"]')
    if not tag:
        return None
    value = str(tag.get("content") or "").strip()
    return value or None


def scrape_treasure_hill() -> List[Dict]:
    today = datetime.now().date().isoformat()
    try:
        listing_soup = _fetch_soup(LISTING_URL)
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] listing fetch failed: {exc}", file=sys.stderr)
        return []

    detail_links: List[str] = []
    seen_links: Set[str] = set()
    for anchor in listing_soup.select('a[href*="event-detail.php"]'):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(BASE_URL, href)
        if absolute in seen_links:
            continue
        seen_links.add(absolute)
        detail_links.append(absolute)

    results: List[Dict] = []
    for link in detail_links:
        try:
            soup = _fetch_soup(link)
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {link} {exc}", file=sys.stderr)
            continue

        detail = soup.select_one(".detail") or soup.select_one(".content") or soup
        text = _clean_text(detail.get_text(" ", strip=True))
        title_node = soup.select_one(".title")
        title = _clean_text(title_node.get_text(" ", strip=True) if title_node else "")
        if not title or not _is_screening_candidate(title, text):
            continue

        start_date, end_date = _parse_date_range(text)
        if not start_date or (end_date or start_date) < today:
            continue

        location_match = re.search(r"活動地點[：:]\s*([^\n]{2,120})", text)
        screen_name = _clean_text(location_match.group(1)) if location_match else CINEMA_NAME

        results.append(
            {
                "cinema_name": CINEMA_NAME,
                "movie_title": title,
                "movie_title_en": None,
                "director": None,
                "director_en": "",
                "year": None,
                "country": None,
                "runtime_min": None,
                "synopsis": text,
                "date_text": start_date,
                "showtime": _parse_time(text),
                "screen_name": screen_name,
                "detail_page_url": link,
                "booking_url": None,
                "image_url": _extract_image_url(soup),
                "tags": ["screening_program"],
            }
        )

    return results
