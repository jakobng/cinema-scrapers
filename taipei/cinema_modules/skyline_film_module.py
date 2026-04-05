from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

ACTIVITY_API = "https://api.skyline.film/api/activity"
DETAIL_PAGE_TEMPLATE = "https://www.skyline.film/detail/{activity_id}"
CINEMA_NAME = "Skyline Film"
TAIPEI_TZ = timezone(timedelta(hours=8))


def _fetch_json(url: str, *, params: Optional[Dict[str, object]] = None) -> Dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"Unexpected JSON payload from {url}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def _split_bilingual_title(value: str) -> Tuple[str, Optional[str]]:
    title = re.sub(r"\s+", " ", str(value or "").strip())
    if not title:
        return "", None

    normalized = title.replace("’", "'").replace("–", "-")
    match = re.search(r"\s+[A-Za-z]", normalized)
    if match:
        zh_title = title[: match.start()].strip()
        en_title = title[match.start() :].strip()
        if zh_title and en_title and re.search(r"[\u3400-\u9fff]", zh_title):
            return zh_title, en_title
    return title, None


def _parse_runtime_minutes(text: str) -> Optional[str]:
    match = re.search(r"片長[:：]?\s*(?:(\d+)\s*h\s*)?(\d+)\s*m", text, flags=re.IGNORECASE)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    return str(hours * 60 + minutes)


def _clean_synopsis(text: str) -> str:
    cleaned = str(text or "").replace("\r", "")
    cleaned = cleaned.split("__", 1)[0]
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if lines and ("入場" in lines[0] or "開演" in lines[0] or "片長" in lines[0]):
        lines = lines[1:]

    filtered: List[str] = []
    for line in lines:
        if line.startswith("*若遇天候") or line.startswith("*"):
            break
        filtered.append(line)
    return " ".join(filtered).strip()


def scrape_skyline_film() -> List[Dict]:
    try:
        listing_payload = _fetch_json(ACTIVITY_API, params={"offset": 0, "limit": 50})
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] activity fetch failed: {exc}", file=sys.stderr)
        return []

    activities = listing_payload.get("content") or []
    if not isinstance(activities, list):
        return []

    results: List[Dict] = []
    for activity in activities:
        activity_id = str(activity.get("id") or "").strip()
        if not activity_id:
            continue

        try:
            detail_payload = _fetch_json(f"{ACTIVITY_API}/{activity_id}")
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {activity_id} {exc}", file=sys.stderr)
            continue

        detail = detail_payload.get("content") or {}
        content = detail.get("content") or {}
        tickets = detail.get("tickets") or []
        if not isinstance(tickets, list):
            continue

        detail_page_url = DETAIL_PAGE_TEMPLATE.format(activity_id=activity_id)
        screen_name = (detail.get("address") or {}).get("remark") or (detail.get("address") or {}).get("line") or ""
        base_tags = [tag for tag in detail.get("tags") or [] if isinstance(tag, str)]

        for ticket in tickets:
            start_ts = ticket.get("startDateTime")
            if not start_ts:
                continue

            start_dt = datetime.fromtimestamp(int(start_ts), TAIPEI_TZ)
            movie_title, movie_title_en = _split_bilingual_title(ticket.get("title") or "")
            intro = str(ticket.get("introduction") or "")
            tags = list(base_tags)
            if ticket.get("remainQuantity") == 0:
                tags.append("sold_out")

            results.append(
                {
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title,
                    "movie_title_en": movie_title_en,
                    "director": None,
                    "director_en": "",
                    "year": None,
                    "country": None,
                    "runtime_min": _parse_runtime_minutes(intro),
                    "synopsis": _clean_synopsis(intro)
                    or BeautifulSoup(content.get("summary") or "", "html.parser").get_text(" ", strip=True),
                    "date_text": start_dt.date().isoformat(),
                    "showtime": start_dt.strftime("%H:%M"),
                    "screen_name": screen_name,
                    "detail_page_url": detail_page_url,
                    "booking_url": detail_page_url,
                    "image_url": ticket.get("cover") or detail.get("webCover") or None,
                    "tags": sorted(set(tag for tag in tags if tag)),
                }
            )

    return results
