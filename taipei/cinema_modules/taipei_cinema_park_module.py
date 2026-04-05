from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://www.cinemapark.taipei/event_list.aspx"
DETAIL_URL = "https://www.cinemapark.taipei/content.aspx"
BASE_URL = "https://www.cinemapark.taipei"
CINEMA_NAME = "臺北市電影主題公園"
KEYWORDS = (
    "放映",
    "戶外放映",
    "電公映",
    "pop-up cinema",
    "screening",
    "播映",
)


def _request_json(url: str, *, params: Optional[Dict[str, str]] = None, data: Optional[Dict[str, str]] = None) -> Dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.request(
                "POST" if data is not None else "GET",
                url,
                params=params,
                data=data,
                headers={"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"Unexpected JSON payload from {url}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def _clean_text(value: str) -> str:
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _extract_booking_url(html: str) -> Optional[str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href.startswith("http"):
            continue
        if "cinemapark.taipei" in href:
            continue
        return href
    return None


def _is_screening_candidate(*values: object) -> bool:
    haystack = " ".join(_clean_text(str(value or "")) for value in values).lower()
    return any(keyword in haystack for keyword in KEYWORDS)


def _parse_datetime(value: object) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _image_url(filename: object) -> Optional[str]:
    value = str(filename or "").strip()
    if not value:
        return None
    return f"{BASE_URL}/retrieve/{value.lstrip('/')}"


def scrape_taipei_cinema_park() -> List[Dict]:
    today = datetime.now().date()
    try:
        listing_payload = _request_json(
            LISTING_URL,
            data={"q": "get", "r": "0.123", "data": '{"p":1,"ps":100,"SubKind":"","Kind":"","Keyword":""}'},
        )
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] listing fetch failed: {exc}", file=sys.stderr)
        return []

    items = (listing_payload.get("list") or {}).get("items") or []
    if not isinstance(items, list):
        return []

    results: List[Dict] = []
    seen_ids: Set[str] = set()
    for item in items:
        item_id = str(item.get("Id") or "").strip()
        pid = str(item.get("PID") or "3").strip() or "3"
        if not item_id or item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        title = _clean_text(item.get("Title") or "")
        summary = _clean_text(item.get("ContentDesc") or "")
        start_dt = _parse_datetime(item.get("PublishDate"))
        end_dt = _parse_datetime(item.get("EventEndDate")) or start_dt
        if not start_dt or not end_dt or end_dt.date() < today:
            continue
        if not _is_screening_candidate(title, summary):
            continue

        try:
            detail_payload = _request_json(DETAIL_URL, params={"q": "get", "id": item_id, "pid": pid})
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {item_id} {exc}", file=sys.stderr)
            continue

        detail = detail_payload.get("item") or {}
        content_html = str(detail.get("ContentDesc") or item.get("ContentDesc") or "")
        content_text = _clean_text(content_html)
        if not _is_screening_candidate(title, content_text):
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
                "synopsis": content_text,
                "date_text": start_dt.date().isoformat(),
                "showtime": start_dt.strftime("%H:%M") if start_dt.time() != datetime.min.time() else None,
                "screen_name": _clean_text(detail.get("PlaceName") or CINEMA_NAME) or CINEMA_NAME,
                "detail_page_url": f"{DETAIL_URL}?id={item_id}&pid={pid}",
                "booking_url": _extract_booking_url(content_html),
                "image_url": _image_url(detail.get("ImageFileName") or item.get("ImageFileName")),
                "tags": [tag for tag in [_clean_text(detail.get("Kind") or item.get("Kind") or "")] if tag],
            }
        )

    return results
