from __future__ import annotations

import re
import sys
import time
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.ambassador.com.tw"
SHOWTIME_URL = f"{BASE_URL}/home/Showtime"


def _fetch_soup(url: str, *, params: Optional[Dict[str, str]] = None) -> BeautifulSoup:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def _parse_runtime_minutes(value: str) -> Optional[str]:
    match = re.search(r"(?:(\d+)小時)?\s*(\d+)分", value or "")
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    return str(hours * 60 + minutes)


def _extract_date_links(index_soup: BeautifulSoup, theater_id: str) -> List[str]:
    links: List[str] = []
    seen = set()
    for anchor in index_soup.select(f'a[href*="/home/Showtime?ID={theater_id}"]'):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        parsed = urlparse(urljoin(BASE_URL, href))
        params = parse_qs(parsed.query)
        dt = (params.get("DT") or [""])[0]
        if not re.fullmatch(r"\d{4}/\d{2}/\d{2}", dt):
            continue
        url = urljoin(BASE_URL, parsed.path + "?" + parsed.query)
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def _parse_detail(detail_url: str) -> Dict[str, Optional[str]]:
    soup = _fetch_soup(detail_url)
    info_box = soup.select_one(".movie-info-box")
    if not info_box:
        return {"movie_title": "", "movie_title_en": None, "runtime_min": None, "synopsis": "", "year": None}

    title = info_box.select_one("h2")
    title_en = info_box.select_one("h6")
    synopsis = ""
    for paragraph in info_box.select("p"):
        if "note" in (paragraph.get("class") or []):
            continue
        text = paragraph.get_text(" ", strip=True)
        if text:
            synopsis = text
            break

    year = None
    for paragraph in info_box.select("p.note"):
        text = paragraph.get_text(" ", strip=True)
        match = re.search(r"上映日期[:：]\s*(\d{4})/\d{2}/\d{2}", text)
        if match:
            year = match.group(1)
            break

    runtime_text = ""
    rating_box = info_box.select_one(".rating-box")
    if rating_box:
        spans = rating_box.select("span")
        if len(spans) >= 2:
            runtime_text = spans[1].get_text(" ", strip=True)

    return {
        "movie_title": title.get_text(" ", strip=True) if title else "",
        "movie_title_en": title_en.get_text(" ", strip=True) if title_en else None,
        "runtime_min": _parse_runtime_minutes(runtime_text),
        "synopsis": synopsis,
        "year": year,
    }


def scrape_ambassador_branch(*, theater_id: str, cinema_name: str) -> List[Dict]:
    try:
        index_soup = _fetch_soup(SHOWTIME_URL, params={"ID": theater_id})
    except requests.RequestException as exc:
        print(f"ERROR: [{cinema_name}] showtime fetch failed: {exc}", file=sys.stderr)
        return []

    detail_cache: Dict[str, Dict[str, Optional[str]]] = {}
    results: List[Dict] = []

    for page_url in _extract_date_links(index_soup, theater_id):
        try:
            soup = _fetch_soup(page_url)
        except requests.RequestException as exc:
            print(f"ERROR: [{cinema_name}] dated showtime fetch failed: {page_url} {exc}", file=sys.stderr)
            continue

        params = parse_qs(urlparse(page_url).query)
        date_raw = (params.get("DT") or [""])[0]
        date_text = date_raw.replace("/", "-")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
            continue

        for item in soup.select(".showtime-item"):
            detail_anchor = item.select_one('h3 a[href], .poster-img a[href]')
            if not detail_anchor:
                continue

            detail_url = urljoin(BASE_URL, str(detail_anchor.get("href") or "").strip())
            if detail_url not in detail_cache:
                try:
                    detail_cache[detail_url] = _parse_detail(detail_url)
                except requests.RequestException as exc:
                    print(f"ERROR: [{cinema_name}] detail fetch failed: {detail_url} {exc}", file=sys.stderr)
                    continue

            detail = detail_cache[detail_url]
            image = item.select_one("img")
            image_url = image.get("src") if image else None

            for slot in item.select("ul.seat-list.theater > li"):
                showtime_node = slot.select_one("h6")
                info_node = slot.select_one(".info")
                showtime = showtime_node.get_text(" ", strip=True) if showtime_node else ""
                if not re.fullmatch(r"\d{1,2}:\d{2}", showtime):
                    continue

                screen_text = info_node.get_text(" ", strip=True) if info_node else ""
                screen_name = re.sub(r"\s+\d+席$", "", screen_text).strip()

                results.append(
                    {
                        "cinema_name": cinema_name,
                        "movie_title": detail.get("movie_title") or detail_anchor.get_text(" ", strip=True),
                        "movie_title_en": detail.get("movie_title_en"),
                        "director": None,
                        "director_en": "",
                        "year": detail.get("year"),
                        "country": None,
                        "runtime_min": detail.get("runtime_min"),
                        "synopsis": detail.get("synopsis") or "",
                        "date_text": date_text,
                        "showtime": showtime,
                        "screen_name": screen_name,
                        "detail_page_url": detail_url,
                        "booking_url": page_url,
                        "image_url": urljoin(BASE_URL, image_url) if image_url else None,
                    }
                )

    return results
