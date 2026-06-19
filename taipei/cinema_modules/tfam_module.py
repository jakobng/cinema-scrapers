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
# Event types that are talks/tours/workshops rather than screenings. The museum's
# moving-image exhibition blurbs trip the KEYWORDS above (錄像/影像), so a curator
# talk about a video-art show was being emitted as a "film". Veto those.
NEGATIVE_KEYWORDS = (
    "開講",
    "講座",
    "座談",
    "工作坊",
    "導覽",
    "課程",
    "研習",
    "讀書會",
    "工作假期",
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


def _is_non_screening_event(*values: object) -> bool:
    haystack = " ".join(_clean_text(str(value or "")) for value in values)
    return any(keyword in haystack for keyword in NEGATIVE_KEYWORDS)


def _extract_first_time(text: str) -> Optional[str]:
    # Honour Chinese AM/PM markers; the site writes e.g. "下午2:00" which must
    # become 14:00, not 02:00.
    match = re.search(r"(上午|中午|下午|晚上|凌晨)?\s*(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)
    if not match:
        return None
    meridiem = match.group(1)
    hour = int(match.group(2))
    minute = int(match.group(3))
    if meridiem in ("下午", "晚上") and hour < 12:
        hour += 12
    elif meridiem == "中午" and hour < 12:
        hour = 12
    elif meridiem in ("上午", "凌晨") and hour == 12:
        hour = 0
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
        if _is_non_screening_event(title, kind):
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
