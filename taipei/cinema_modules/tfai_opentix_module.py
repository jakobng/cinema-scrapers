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

ORGANIZER_ID = "1435869159970869249"
TOPICS_URL = f"https://csm.api.opentix.life/organizers/{ORGANIZER_ID}/topics"
EVENT_URL_TEMPLATE = "https://www.opentix.life/event/{program_id}?o=tfai"
CINEMA_NAME = "國家電影及視聽文化中心"
TAIPEI_TZ = timezone(timedelta(hours=8))
HELPER_SCRIPT = Path(__file__).with_name("tfai_opentix_extract.js")
LATIN_NAME_RE = re.compile(r"([A-Z][A-Za-zÀ-ÿ.\-'\s]+)$")


def _request_with_retry(session: requests.Session, url: str, *, params: Dict | None = None) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(3):
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


def _parse_description(program: Dict) -> Dict[str, str | None]:
    lines = _strip_html(program.get("description", ""))
    runtime = None
    year = None
    country = None
    director = ""
    director_en = ""
    synopsis_lines: List[str] = []

    for line in lines:
        if runtime is None:
            runtime_match = re.search(r"片長[:：]\s*(\d+)", line)
            if runtime_match:
                runtime = runtime_match.group(1)

        if director or "｜" not in line or not re.search(r"｜\s*(19|20)\d{2}\s*｜", line):
            continue

        parts = [part.strip() for part in line.split("｜") if part.strip()]
        if len(parts) >= 3:
            director = parts[0]
            country = parts[1]
            year_match = re.search(r"\b(19|20)\d{2}\b", parts[2])
            if year_match:
                year = year_match.group(0)
            latin = LATIN_NAME_RE.search(director)
            director_en = latin.group(1).strip() if latin else ""

    boilerplate_prefixes = (
        "國影電影編號",
        "放映規格",
        "級別",
        "片長",
        "發音",
        "字幕",
        "During ",
    )
    metadata_line = next(
        (line for line in lines if "｜" in line and re.search(r"｜\s*(19|20)\d{2}\s*｜", line)),
        "",
    )
    start_collecting = False
    for line in lines:
        if metadata_line and line == metadata_line:
            start_collecting = True
            continue
        if not start_collecting:
            continue
        if line.startswith(boilerplate_prefixes) or line.startswith("▲") or "Non-English language film" in line:
            continue
        if re.fullmatch(r"[A-Za-z0-9 ,.'&:;!?()\-/]+", line):
            continue
        synopsis_lines.append(line)

    synopsis = " ".join(synopsis_lines).strip()
    return {
        "director": director or None,
        "director_en": director_en or "",
        "year": year,
        "country": country,
        "runtime_min": runtime,
        "synopsis": synopsis,
    }


def _collect_program_refs(session: requests.Session) -> List[Dict]:
    response = _request_with_retry(
        session,
        TOPICS_URL,
        params={"topicPage": 1, "topicRowCount": 10, "contentRowCount": 10},
    )
    payload = response.json().get("result", {}).get("data", [])

    program_refs: Dict[str, Dict] = {}
    for topic in payload:
        topic_name = topic.get("name", "")
        for content in topic.get("contents", []):
            if content.get("type") != 0:
                continue
            if content.get("displayCategory") != "電影":
                continue
            if "套票" in (content.get("name") or ""):
                continue
            program_id = str(content.get("id") or "")
            if not program_id:
                continue
            program_refs[program_id] = {
                "id": program_id,
                "name": content.get("name") or "",
                "image_url": content.get("imageUrl") or "",
                "topic_name": topic_name,
            }
    return list(program_refs.values())


def scrape_tfai_opentix() -> List[Dict]:
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True, text=True, timeout=10)
    except Exception as exc:
        print(f"ERROR: [{CINEMA_NAME}] node is required for TFAI OPENTIX decoding: {exc}", file=sys.stderr)
        return []

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    try:
        program_refs = _collect_program_refs(session)
    except Exception as exc:
        print(f"ERROR: [{CINEMA_NAME}] OPENTIX topic fetch failed: {exc}", file=sys.stderr)
        return []

    results: List[Dict] = []
    for ref in program_refs:
        detail_url = EVENT_URL_TEMPLATE.format(program_id=ref["id"])
        try:
            html = _request_with_retry(session, detail_url).text
            program = _decode_program_from_html(html)
        except Exception as exc:
            print(f"ERROR: [{CINEMA_NAME}] OPENTIX event fetch failed: {detail_url} {exc}", file=sys.stderr)
            continue

        parsed = _parse_description(program)
        image_url = ref.get("image_url") or program.get("imageUrl") or ""
        tags = [tag.get("text") for tag in program.get("programTags", []) if tag.get("text")]
        if ref.get("topic_name"):
            tags.append(ref["topic_name"])

        base_item = {
            "cinema_name": CINEMA_NAME,
            "movie_title": program.get("name") or ref.get("name") or "",
            "movie_title_en": program.get("enUsName") or None,
            "director": parsed["director"],
            "director_en": parsed["director_en"],
            "year": parsed["year"],
            "country": parsed["country"],
            "runtime_min": parsed["runtime_min"],
            "synopsis": parsed["synopsis"],
            "detail_page_url": detail_url,
            "booking_url": detail_url,
            "image_url": image_url or None,
            "tags": sorted(set(tags)),
        }

        for event_venue in program.get("eventVenues", []):
            venue = event_venue.get("venue", {})
            for event in event_venue.get("events", []):
                start_ts = event.get("startDateTime")
                if not start_ts:
                    continue
                start_dt = datetime.fromtimestamp(start_ts, TAIPEI_TZ)
                item = dict(base_item)
                item["date_text"] = start_dt.date().isoformat()
                item["showtime"] = start_dt.strftime("%H:%M")
                item["screen_name"] = venue.get("name") or ""
                results.append(item)

    return results
