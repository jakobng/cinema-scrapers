from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

API_URL = "https://www.tfam.museum/ashx/Event.ashx?ddlLang=zh-tw"
DETAIL_PAGE_TEMPLATE = "https://www.tfam.museum/Event/Event_page.aspx?ddlLang=zh-tw&id={event_id}"
RESERVATION_PAGE_TEMPLATE = "https://www.tfam.museum/Event/Reservation_Page.aspx?ddlLang=zh-tw&EduID={event_id}"
CINEMA_NAME = "臺北市立美術館"
KEYWORDS = (
    "電影",
    "放映",
    "影片",
    "影展",
    "紀錄片",
    "錄像",
    "膠卷",
    "實驗電影",
    "影像放映",
    "film",
    "screening",
    "cinema",
    "video",
)


def _fetch_events() -> List[Dict]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(
                API_URL,
                json={"JJMethod": "GetEv"},
                headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json; charset=utf-8"},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("Data") or []
            if isinstance(data, list):
                return data
            raise ValueError("Unexpected TFAM payload")
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError("Failed to fetch TFAM events")


def _clean_text(value: str) -> str:
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _is_screening_candidate(*values: object) -> bool:
    haystack = " ".join(_clean_text(str(value or "")) for value in values).lower()
    return any(keyword.lower() in haystack for keyword in KEYWORDS)


def _extract_first_time(text: str) -> Optional[str]:
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23:
        return None
    return f"{hour:02d}:{minute:02d}"


def scrape_tfam() -> List[Dict]:
    today = datetime.now().date().isoformat()
    try:
        events = _fetch_events()
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] event fetch failed: {exc}", file=sys.stderr)
        return []

    results: List[Dict] = []
    for item in events:
        title = _clean_text(item.get("EduName") or "")
        content = _clean_text(item.get("Content") or "")
        kind = _clean_text(item.get("Kind") or "")
        area = _clean_text(item.get("Area") or "")
        if not title or not _is_screening_candidate(title, content, kind, area):
            continue

        begin_date = str(item.get("BeginDate") or "").strip().replace("/", "-")
        if not re.match(r"^20\d{2}-\d{2}-\d{2}$", begin_date) or begin_date < today:
            continue

        event_id = str(item.get("EduID") or "").strip()
        if not event_id:
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
                "synopsis": content,
                "date_text": begin_date,
                "showtime": _extract_first_time(content),
                "screen_name": area or None,
                "detail_page_url": DETAIL_PAGE_TEMPLATE.format(event_id=event_id),
                "booking_url": RESERVATION_PAGE_TEMPLATE.format(event_id=event_id)
                if str(item.get("EduReserve") or "").strip() not in {"", "0"}
                else None,
                "image_url": None,
                "tags": [tag for tag in [kind] if tag],
            }
        )

    return results
