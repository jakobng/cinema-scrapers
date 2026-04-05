from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.lightboxlib.org"
LISTING_URL = f"{BASE_URL}/events"
CINEMA_NAME = "Lightbox 攝影圖書室"
KEYWORDS = (
    "電影",
    "放映",
    "影片",
    "影像放映",
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


def _parse_date(text: str) -> Optional[str]:
    match = re.search(r"(20\d{2})\.(\d{1,2})\.(\d{1,2})", text)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))).date().isoformat()
    except ValueError:
        return None


def _parse_time(text: str) -> Optional[str]:
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)
    if not match:
        return None
    hour = int(match.group(1))
    if hour > 23:
        return None
    return f"{hour:02d}:{match.group(2)}"


def _extract_booking_url(soup: BeautifulSoup) -> Optional[str]:
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if href.startswith("https://lightboxlib.oen.tw/") or "accupass" in href.lower() or "kktix" in href.lower():
            return href
    return None


def _extract_image_url(soup: BeautifulSoup) -> Optional[str]:
    tag = soup.select_one('meta[property="og:image"]')
    if not tag:
        return None
    value = str(tag.get("content") or "").strip()
    return value or None


def scrape_lightbox() -> List[Dict]:
    today = datetime.now().date().isoformat()
    try:
        listing_soup = _fetch_soup(LISTING_URL)
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] listing fetch failed: {exc}", file=sys.stderr)
        return []

    links: List[str] = []
    seen_links: Set[str] = set()
    for anchor in listing_soup.select('a[href^="/events/"]'):
        href = str(anchor.get("href") or "").strip()
        if not href or href in seen_links:
            continue
        seen_links.add(href)
        links.append(urljoin(BASE_URL, href))

    results: List[Dict] = []
    for link in links:
        try:
            soup = _fetch_soup(link)
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {link} {exc}", file=sys.stderr)
            continue

        article = soup.select_one("article")
        text = _clean_text((article or soup).get_text(" ", strip=True))
        title = _clean_text((soup.title.get_text(" ", strip=True) if soup.title else "").split("|", 1)[0])
        if not title or not _is_screening_candidate(title, text):
            continue

        date_text = _parse_date(text)
        if not date_text or date_text < today:
            continue

        location_match = re.search(r"地點[│:：]\s*([^\n]{2,120})", text)
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
                "date_text": date_text,
                "showtime": _parse_time(text),
                "screen_name": screen_name,
                "detail_page_url": link,
                "booking_url": _extract_booking_url(soup),
                "image_url": _extract_image_url(soup),
                "tags": ["screening_program"],
            }
        )

    return results
