from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.spot.org.tw/index.html"
CINEMA_NAME = "SPOT台北之家"
MOVIE_LINK_RE = re.compile(r"https?://www\.spot\.org\.tw/movies/\d{6}/m\d+/movies\d{6}_m\d+\.html")


def _fetch_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.content.decode("utf-8", "ignore")


def _clean_lines(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]


def _parse_year(date_value: str) -> int:
    taipei_now = datetime.now(timezone(timedelta(hours=8)))
    month = int(date_value.split("/")[0])
    year = taipei_now.year
    if month < taipei_now.month - 6:
        year += 1
    return year


def _parse_date(date_value: str) -> str:
    month, day = [int(part) for part in date_value.split("/", 1)]
    year = _parse_year(date_value)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_director(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    latin = re.search(r"([A-Z][A-Za-z.\-'\s]+)$", cleaned)
    if latin:
        return cleaned, latin.group(1).strip()
    return cleaned, ""


def _parse_metadata(meta_line: str) -> Dict[str, str]:
    info: Dict[str, str] = {"year": "", "runtime_min": "", "country": ""}
    parts = [part.strip() for part in meta_line.split("|") if part.strip()]
    for part in parts:
        if not info["year"]:
            year_match = re.search(r"\b(19|20)\d{2}\b", part)
            if year_match:
                info["year"] = year_match.group(0)
        runtime_match = re.search(r"(\d+)\s*min", part, re.IGNORECASE)
        if runtime_match:
            info["runtime_min"] = runtime_match.group(1)
    ignored = {"color", "colour", "chinese subtitles"}
    for part in parts:
        lowered = part.lower()
        if (
            re.search(r"\b(19|20)\d{2}\b", part)
            or "min" in lowered
            or "subtitle" in lowered
            or lowered in ignored
            or lowered.endswith("ese")
            or lowered == "mandarin"
        ):
            continue
        if re.search(r"[A-Za-z]", part):
            info["country"] = part
    return info


def _parse_schedule(lines: List[str], detail_url: str, listing: Dict[str, str]) -> List[Dict]:
    results: List[Dict] = []
    try:
        start = lines.index("【本片放映時刻】") + 1
    except ValueError:
        return results

    current_date = ""
    for line in lines[start:]:
        if line.startswith("Add ") or line.startswith("No.18"):
            break
        if re.match(r"^\d{1,2}/\d{1,2}\(.+\)$", line):
            current_date = _parse_date(line.split("(", 1)[0])
            continue
        if re.match(r"^\d{1,2}:\d{2}$", line) and current_date:
            row = dict(listing)
            row["date_text"] = current_date
            row["showtime"] = line
            row["detail_page_url"] = detail_url
            results.append(row)
    return results


def scrape_spot_taipei() -> List[Dict]:
    try:
        homepage = _fetch_text(BASE_URL)
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] homepage fetch failed: {exc}", file=sys.stderr)
        return []

    detail_urls = sorted(set(MOVIE_LINK_RE.findall(homepage)))
    results: List[Dict] = []

    for detail_url in detail_urls:
        try:
            html = _fetch_text(detail_url)
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {detail_url} {exc}", file=sys.stderr)
            continue

        lines = _clean_lines(html)
        if "【本片放映時刻】" not in lines:
            continue

        try:
            title_idx = lines.index("++ 光點台北電影院 ++") + 1
        except ValueError:
            continue

        if title_idx + 5 >= len(lines):
            continue

        title_jp = lines[title_idx]
        title_en = lines[title_idx + 1] if re.search(r"[A-Za-z]", lines[title_idx + 1]) else ""
        director, director_en = _parse_director(lines[title_idx + 3])
        metadata = _parse_metadata(lines[title_idx + 5])

        synopsis_start = title_idx + 6
        synopsis_end = lines.index("【本片放映時刻】")
        synopsis = " ".join(lines[synopsis_start:synopsis_end]).strip()

        listing = {
            "cinema_name": CINEMA_NAME,
            "movie_title": title_jp,
            "movie_title_en": title_en or None,
            "director": director or None,
            "director_en": director_en or "",
            "year": metadata["year"] or None,
            "country": metadata["country"] or None,
            "runtime_min": metadata["runtime_min"] or None,
            "synopsis": synopsis or "",
            "booking_url": None,
        }
        results.extend(_parse_schedule(lines, detail_url, listing))

    return results

