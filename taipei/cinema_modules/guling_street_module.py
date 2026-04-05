from __future__ import annotations

import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.glt.org.tw/"
CINEMA_NAME = "牯嶺街小劇場"
SEARCH_QUERIES = ("放映", "電影", "影展", "膠卷", "實驗電影")
KEYWORDS = (
    "電影",
    "放映",
    "影片",
    "影展",
    "紀錄片",
    "動畫",
    "膠卷",
    "16mm",
    "8mm",
    "錄像",
    "實驗電影",
    "film",
    "screening",
    "cinema",
    "video",
)


def _fetch_bytes(url: str, *, params: Optional[Dict[str, str]] = None) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def _fetch_soup(url: str) -> BeautifulSoup:
    return BeautifulSoup(_fetch_bytes(url), "html.parser")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _extract_intro(text: str) -> str:
    normalized = _clean_text(text)
    markers = (
        ("【活動簡介】", ("【活動資訊】", "【購票資訊】", "【講師介紹】")),
        ("【節目簡介】", ("【購票資訊】", "【影片介紹】", "【活動資訊】")),
        ("【影片介紹】", ("【購票資訊】", "【活動資訊】")),
    )
    for start_marker, stop_markers in markers:
        start = normalized.find(start_marker)
        if start == -1:
            continue
        chunk = normalized[start + len(start_marker) :].strip(" /")
        stop_positions = [chunk.find(marker) for marker in stop_markers if chunk.find(marker) != -1]
        if stop_positions:
            chunk = chunk[: min(stop_positions)]
        return chunk.strip(" /")
    return normalized[:400].strip()


def _extract_first_date(text: str) -> Optional[str]:
    patterns = (
        r"((20\d{2})[./年]\s*(\d{1,2})[./月]\s*(\d{1,2})日?)",
        r"((20\d{2})-(\d{1,2})-(\d{1,2}))",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            year = int(match.group(2))
            month = int(match.group(3))
            day = int(match.group(4))
            try:
                return datetime(year, month, day).date().isoformat()
            except ValueError:
                return None
    return None


def _extract_first_time(text: str) -> Optional[str]:
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23:
        return None
    return f"{hour:02d}:{minute:02d}"


def _extract_date_and_time(text: str) -> Tuple[Optional[str], Optional[str]]:
    markers = ("放映時間", "活動時間", "演出時間", "時間", "日期")
    for marker in markers:
        for match in re.finditer(rf"{marker}[｜:：]?\s*([^\n]{{0,220}})", text):
            chunk = match.group(1)
            date_text = _extract_first_date(chunk)
            if date_text:
                return date_text, _extract_first_time(chunk)
    return None, None


def _extract_location(text: str) -> Optional[str]:
    match = re.search(r"(?:地點|放映廳|演出地點)[｜:：]?\s*([^\n]{2,220})", text)
    if not match:
        return None
    value = match.group(1)
    for marker in ("講師｜", "報名｜", "報名連結｜", "主辦單位", "/"):
        if marker in value:
            value = value.split(marker, 1)[0]
    return _clean_text(value)


def _extract_booking_url(soup: BeautifulSoup) -> Optional[str]:
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href.startswith("http"):
            continue
        if "glt.org.tw" in href:
            continue
        return href
    return None


def _extract_image_url(soup: BeautifulSoup) -> Optional[str]:
    tag = soup.select_one('meta[property="og:image"]')
    if tag:
        value = str(tag.get("content") or "").strip()
        if value:
            return value
    return None


def _is_screening_candidate(title: str, text: str) -> bool:
    haystack = f"{title} {text}".lower()
    return any(keyword.lower() in haystack for keyword in KEYWORDS)


def scrape_guling_street() -> List[Dict]:
    today = datetime.now().date().isoformat()
    links: Set[str] = set()

    for query in SEARCH_QUERIES:
        try:
            rss_bytes = _fetch_bytes(f"{BASE_URL}?feed=rss2", params={"s": query})
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] feed fetch failed for {query}: {exc}", file=sys.stderr)
            continue

        try:
            root = ET.fromstring(rss_bytes)
        except ET.ParseError as exc:
            print(f"ERROR: [{CINEMA_NAME}] feed parse failed for {query}: {exc}", file=sys.stderr)
            continue

        for item in root.findall(".//item"):
            link = str(item.findtext("link") or "").strip()
            if link:
                links.add(link)

    results: List[Dict] = []
    for link in sorted(links):
        try:
            soup = _fetch_soup(link)
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {link} {exc}", file=sys.stderr)
            continue

        article = soup.select_one("article")
        raw_text = (article or soup).get_text("\n", strip=True)
        text = _clean_text(raw_text)
        title = _clean_text((soup.title.get_text(" ", strip=True) if soup.title else "").split("|", 1)[0])
        synopsis = _extract_intro(text)
        if not title or not _is_screening_candidate(title, synopsis):
            continue

        date_text, showtime = _extract_date_and_time(raw_text)
        if not date_text or date_text < today:
            continue

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
                "synopsis": synopsis,
                "date_text": date_text,
                "showtime": showtime,
                "screen_name": _extract_location(raw_text),
                "detail_page_url": link,
                "booking_url": _extract_booking_url(soup),
                "image_url": _extract_image_url(soup),
                "tags": ["screening_program"],
            }
        )

    return results
