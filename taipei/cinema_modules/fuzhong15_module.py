from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.fuzhong15.ntpc.gov.tw/xcmovie?xsmsid=0m361641875264878260"
BASE_ORIGIN = "https://www.fuzhong15.ntpc.gov.tw"
CINEMA_NAME = "府中15放映院"


def _fetch_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def _parse_detail(detail_url: str) -> Dict:
    soup = _fetch_soup(detail_url)
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    metadata: Dict[str, str] = {}

    for idx, line in enumerate(lines):
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        if line == "導演：":
            metadata["director"] = next_line
        elif line == "年份":
            metadata["year"] = next_line
        elif line == "國家":
            metadata["country"] = next_line
        elif line == "語言":
            metadata["source_audio_language"] = next_line
        elif line == "字幕":
            metadata["source_subtitle_language"] = next_line

    language_parts = []
    if metadata.get("source_audio_language"):
        language_parts.append(f"語言 {metadata['source_audio_language']}")
    if metadata.get("source_subtitle_language"):
        language_parts.append(f"字幕 {metadata['source_subtitle_language']}")
    if language_parts:
        metadata["source_language_note"] = " ".join(language_parts)

    synopsis_lines: List[str] = []
    collecting = False
    for line in lines:
        if line.startswith("劇情簡介"):
            collecting = True
            continue
        if not collecting:
            continue
        if line.startswith(("更新日期", "TOP", "【Facebook】")):
            break
        synopsis_lines.append(line)
    if synopsis_lines:
        metadata["synopsis"] = " ".join(synopsis_lines).strip()

    return metadata


def scrape_fuzhong15() -> List[Dict]:
    try:
        response = requests.get(BASE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] schedule fetch failed: {exc}", file=sys.stderr)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.select_one("table.ListTable")
    if not table:
        return []

    current_year = datetime.now().year
    results: List[Dict] = []
    detail_cache: Dict[str, Dict] = {}

    for row in table.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        date_raw = cells[0].get_text(" ", strip=True)
        time_raw = cells[1].get_text(" ", strip=True)
        title_cell = cells[2]
        runtime_raw = cells[3].get_text(" ", strip=True)

        date_match = re.search(r"(\d{2})/(\d{2})", date_raw)
        time_match = re.search(r"(\d{1,2}:\d{2})", time_raw)
        runtime_match = re.search(r"(\d+)\s*min", runtime_raw, re.IGNORECASE)
        if not date_match or not time_match:
            continue

        detail_link = title_cell.find("a")
        detail_url = urljoin(BASE_ORIGIN, detail_link["href"]) if detail_link and detail_link.get("href") else BASE_URL

        movie_title = re.sub(r"\s+[報售]$", "", title_cell.get_text(" ", strip=True)).strip()
        if detail_url not in detail_cache:
            try:
                detail_cache[detail_url] = _parse_detail(detail_url)
            except requests.RequestException as exc:
                print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {detail_url} {exc}", file=sys.stderr)
                detail_cache[detail_url] = {}
        detail = detail_cache[detail_url]

        results.append(
            {
                "cinema_name": CINEMA_NAME,
                "movie_title": movie_title,
                "movie_title_en": None,
                "director": detail.get("director"),
                "director_en": "",
                "year": detail.get("year"),
                "country": detail.get("country"),
                "runtime_min": runtime_match.group(1) if runtime_match else None,
                "synopsis": detail.get("synopsis", ""),
                "date_text": f"{current_year:04d}-{int(date_match.group(1)):02d}-{int(date_match.group(2)):02d}",
                "showtime": time_match.group(1),
                "detail_page_url": detail_url,
                "booking_url": None,
                "source_audio_language": detail.get("source_audio_language"),
                "source_subtitle_language": detail.get("source_subtitle_language"),
                "source_language_note": detail.get("source_language_note"),
            }
        )

    return results
