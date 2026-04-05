from __future__ import annotations

import re
import sys
import time
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://tyac2.afmc.gov.tw"
SCHEDULE_URL = f"{BASE_URL}/Event_table"
CINEMA_NAME = "桃園光影文化館"


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


def _extract_date_from_href(href: str) -> Optional[str]:
    params = parse_qs(urlparse(href).query)
    raw_date = (params.get("bd") or [""])[0]
    match = re.match(r"(\d{4})/(\d{2})/(\d{2})", raw_date)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _extract_booking_url(soup: BeautifulSoup) -> Optional[str]:
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if "kktix" in href.lower() or "reurl.cc" in href.lower():
            return href
    return None


def _sanitize_runtime(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        runtime = int(str(value).strip())
    except ValueError:
        return None
    if runtime <= 0 or runtime > 400:
        return None
    return str(runtime)


def _extract_synopsis(lines: List[str]) -> str:
    try:
        start = lines.index("入場方式") + 2
    except ValueError:
        return ""

    synopsis_lines: List[str] = []
    stop_prefixes = ("每個月25號", "備註：", "請於KKTIX網站索取:", "返回列表")
    for line in lines[start:]:
        if line.startswith(stop_prefixes):
            break
        synopsis_lines.append(line)
    return " ".join(synopsis_lines).strip()


def _parse_detail(detail_url: str) -> Dict[str, Optional[str]]:
    soup = _fetch_soup(detail_url)
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]

    title = ""
    title_en = None
    heading = soup.select_one("h1")
    if heading:
        parts = [part.strip() for part in heading.get_text(" | ", strip=True).split("|") if part.strip()]
        if parts:
            title = parts[0]
        if len(parts) > 1 and re.search(r"[A-Za-z]", parts[1]):
            title_en = re.sub(r"\s+", " ", parts[1].replace("#", " ")).strip()

    metadata: Dict[str, Optional[str]] = {
        "movie_title": title,
        "movie_title_en": title_en,
        "director": None,
        "year": None,
        "country": None,
        "runtime_min": None,
        "synopsis": _extract_synopsis(lines),
        "booking_url": _extract_booking_url(soup),
    }

    for idx, line in enumerate(lines):
        if line == "導演：" and idx + 1 < len(lines):
            metadata["director"] = lines[idx + 1]
        elif line == "年份：" and idx + 1 < len(lines):
            metadata["year"] = lines[idx + 1]
        elif line == "國家：" and idx + 1 < len(lines):
            metadata["country"] = lines[idx + 1]
        elif re.match(r"^\d+\s*min$", line):
            metadata["runtime_min"] = _sanitize_runtime(re.search(r"\d+", line).group(0))

    return metadata


def scrape_taoyuan_arts_cinema_ii() -> List[Dict]:
    try:
        soup = _fetch_soup(SCHEDULE_URL)
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] schedule fetch failed: {exc}", file=sys.stderr)
        return []

    results: List[Dict] = []
    detail_cache: Dict[str, Dict[str, Optional[str]]] = {}

    for anchor in soup.select('a[href*="/Movie_detail/"]'):
        href = str(anchor.get("href") or "").strip()
        text = anchor.get_text(" ", strip=True)
        if not href or not text:
            continue

        match = re.match(r"(?P<showtime>\d{1,2}:\d{2})\s+(?P<runtime>\d+)min\s+\S+\s+(?P<title>.+)", text)
        if not match:
            continue

        date_text = _extract_date_from_href(href)
        if not date_text:
            continue

        detail_url = urljoin(BASE_URL, href.replace("&amp;", "&"))
        cache_key = urlparse(detail_url).path
        if cache_key not in detail_cache:
            try:
                detail_cache[cache_key] = _parse_detail(detail_url)
            except requests.RequestException as exc:
                print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {detail_url} {exc}", file=sys.stderr)
                continue

        detail = detail_cache[cache_key]
        results.append(
            {
                "cinema_name": CINEMA_NAME,
                "movie_title": detail.get("movie_title") or match.group("title").strip(),
                "movie_title_en": detail.get("movie_title_en"),
                "director": detail.get("director"),
                "director_en": "",
                "year": detail.get("year"),
                "country": detail.get("country"),
                "runtime_min": detail.get("runtime_min") or _sanitize_runtime(match.group("runtime")),
                "synopsis": detail.get("synopsis") or "",
                "date_text": date_text,
                "showtime": match.group("showtime"),
                "detail_page_url": detail_url,
                "booking_url": detail.get("booking_url"),
            }
        )

    return results
