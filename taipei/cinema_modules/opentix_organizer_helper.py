from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

TAIPEI_TZ = timezone(timedelta(hours=8))
HELPER_SCRIPT = Path(__file__).with_name("tfai_opentix_extract.js")
DEFAULT_EVENT_URL_TEMPLATE = "https://www.opentix.life/event/{program_id}"
NON_SCREENING_KEYWORDS = (
    "套票",
    "套組",
    "酒會",
    "頒獎",
    "論壇",
    "工作坊",
    "講座",
    "講堂",
    "大師班",
    "講演",
    "座談報名",
    "映前導讀",
)
NON_SCREENING_PATTERNS = (
    re.compile(r"開幕酒會"),
    re.compile(r"閉幕酒會"),
    re.compile(r"影展講座"),
)


def _request_with_retry(session: requests.Session, url: str, *, params: Dict | None = None) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def _strip_html(value: str) -> List[str]:
    soup = BeautifulSoup(value or "", "html.parser")
    return [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]


def _decode_program_from_html(html: str) -> Dict:
    completed = subprocess.run(
        ["node", str(HELPER_SCRIPT)],
        input=html,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=True,
    )
    return json.loads(completed.stdout)


def _looks_like_non_screening(*values: str) -> bool:
    text = " ".join(value for value in values if value).strip()
    if not text:
        return False
    if "開幕片" in text or "閉幕片" in text:
        return False
    if any(keyword in text for keyword in NON_SCREENING_KEYWORDS):
        return True
    return any(pattern.search(text) for pattern in NON_SCREENING_PATTERNS)


def _parse_description(program: Dict) -> Dict[str, str | None]:
    lines = _strip_html(program.get("description", ""))
    runtime = None
    year = None
    country = None
    director = None
    synopsis_lines: List[str] = []

    for line in lines:
        if runtime is None:
            runtime_match = re.search(r"(?:片長|Runtime)[:：]?\s*(\d+)", line, re.IGNORECASE)
            if runtime_match:
                runtime = runtime_match.group(1)

        if year is None:
            year_match = re.search(r"\b(19|20)\d{2}\b", line)
            if year_match:
                year = year_match.group(0)

        if director is None:
            director_match = re.search(r"(?:導演|Director)[:：]?\s*([^\n/]+)", line, re.IGNORECASE)
            if director_match:
                director = director_match.group(1).strip()

        if country is None:
            country_match = re.search(r"(?:國家|Country)[:：]?\s*([^\n/]+)", line, re.IGNORECASE)
            if country_match:
                country = country_match.group(1).strip()

    boilerplate_markers = (
        "售票",
        "退票",
        "票價",
        "購票",
        "套票",
        "折扣",
        "注意事項",
        "開賣",
        "影展資訊",
    )
    for line in lines:
        if len(line) < 10:
            continue
        if any(marker in line for marker in boilerplate_markers):
            continue
        synopsis_lines.append(line)
        if len(synopsis_lines) >= 3:
            break

    synopsis = " ".join(synopsis_lines).strip()
    return {
        "director": director,
        "year": year,
        "country": country,
        "runtime_min": runtime,
        "synopsis": synopsis,
    }


def _collect_program_refs(session: requests.Session, organizer_id: str) -> List[Dict]:
    url = f"https://csm.api.opentix.life/organizers/{organizer_id}/topics"
    page = 1
    program_refs: Dict[str, Dict] = {}

    while True:
        response = _request_with_retry(
            session,
            url,
            params={"topicPage": page, "topicRowCount": 20, "contentRowCount": 20},
        )
        result = response.json().get("result", {})
        topics = result.get("data", [])
        if not topics:
            break

        for topic in topics:
            topic_name = topic.get("name", "")
            for content in topic.get("contents", []):
                if content.get("type") != 0:
                    continue
                display_category = str(content.get("displayCategory") or "")
                if "電影" not in display_category:
                    continue
                name = content.get("name") or ""
                if _looks_like_non_screening(name, topic_name):
                    continue
                program_id = str(content.get("id") or "")
                if not program_id:
                    continue
                program_refs[program_id] = {
                    "id": program_id,
                    "name": name,
                    "image_url": content.get("imageUrl") or "",
                    "topic_name": topic_name,
                }

        next_page = result.get("nextPage")
        if not next_page or next_page == page:
            break
        page = next_page

    return list(program_refs.values())


def scrape_opentix_organizer(
    *,
    organizer_id: str,
    cinema_name: str,
    event_url_template: str = DEFAULT_EVENT_URL_TEMPLATE,
) -> List[Dict]:
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True, text=True, timeout=10)
    except Exception as exc:
        print(f"ERROR: [{cinema_name}] node is required for OPENTIX decoding: {exc}", file=sys.stderr)
        return []

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Connection": "close",
            "Accept": "application/json, text/plain, */*",
        }
    )

    try:
        program_refs = _collect_program_refs(session, organizer_id)
    except Exception as exc:
        print(f"ERROR: [{cinema_name}] OPENTIX topic fetch failed: {exc}", file=sys.stderr)
        return []

    today = datetime.now(TAIPEI_TZ).date()
    results: List[Dict] = []

    for ref in program_refs:
        detail_url = event_url_template.format(program_id=ref["id"])
        try:
            html = _request_with_retry(session, detail_url).text
            program = _decode_program_from_html(html)
        except Exception as exc:
            print(f"ERROR: [{cinema_name}] OPENTIX event fetch failed: {detail_url} {exc}", file=sys.stderr)
            continue

        program_name = program.get("name") or ref.get("name") or ""
        tag_texts = [tag.get("text") for tag in program.get("programTags", []) if tag.get("text")]
        if ref.get("topic_name"):
            tag_texts.append(ref["topic_name"])
        if _looks_like_non_screening(program_name, " ".join(tag_texts), program.get("enUsName") or ""):
            continue

        parsed = _parse_description(program)
        base_item = {
            "cinema_name": cinema_name,
            "movie_title": program_name,
            "movie_title_en": program.get("enUsName") or None,
            "director": parsed["director"],
            "director_en": parsed["director"] or "",
            "year": parsed["year"],
            "country": parsed["country"],
            "runtime_min": parsed["runtime_min"],
            "synopsis": parsed["synopsis"],
            "detail_page_url": detail_url,
            "booking_url": detail_url,
            "image_url": ref.get("image_url") or program.get("imageUrl") or None,
            "tags": sorted(set(tag_texts)),
        }

        for event_venue in program.get("eventVenues", []):
            venue = event_venue.get("venue", {})
            for event in event_venue.get("events", []):
                start_ts = event.get("startDateTime")
                if not start_ts:
                    continue
                start_dt = datetime.fromtimestamp(start_ts, TAIPEI_TZ)
                if start_dt.date() < today:
                    continue
                item = dict(base_item)
                item["date_text"] = start_dt.date().isoformat()
                item["showtime"] = start_dt.strftime("%H:%M")
                item["screen_name"] = venue.get("name") or ""
                results.append(item)

    return results
