from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

TAIPEI_TZ = timezone(timedelta(hours=8))
BASE_URL = "https://clab.org.tw"
# C-LAB tags every event with its own category, and the events index accepts that
# category as a server-side filter. "screening" is the slug behind the 放映 label
# (see the ul.tab-list links on any event detail page), so the listing itself is
# the single source of truth for "is this a screening" — no keyword guessing, and
# talks / workshops / exhibitions / guided tours never enter the pipeline.
LISTING_URL_TEMPLATE = f"{BASE_URL}/events/type/screening?page={{page}}"
MAX_LISTING_PAGES = 12
SCREENING_TYPE_SLUG = "screening"
SCREENING_TYPE_LABEL = "放映"
CINEMA_NAME = "臺灣當代文化實驗場 C-LAB"


def _fetch_soup(url: str) -> BeautifulSoup:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _node_text(node: Optional[BeautifulSoup]) -> str:
    return _clean_text(node.get_text(" ", strip=True)) if node else ""


def _iso_date(value: str) -> Optional[str]:
    match = re.search(r"(20\d{2})/(\d{1,2})/(\d{1,2})", value or "")
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _first_time(value: str) -> Optional[str]:
    # The detail page states a range, e.g. "19:30 - 21:30"; the start is the showtime.
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", value or "")
    if not match:
        return None
    hour = int(match.group(1))
    return f"{hour:02d}:{match.group(2)}" if hour <= 23 else None


def _unwrap_next_image(url: str) -> str:
    # Tile images are proxied through /_next/image?url=<encoded original>.
    if "/_next/image" not in url:
        return url
    original = parse_qs(urlparse(url).query).get("url", [])
    return original[0] if original else url


def _parse_tile(tile: BeautifulSoup) -> Optional[Dict[str, Optional[str]]]:
    link = tile.select_one('a[href*="/events/"]')
    title = _node_text(tile.select_one(".lower .title"))
    if not link or not title:
        return None
    image = tile.select_one("img[src]")
    start = _iso_date(_node_text(tile.select_one(".startDate")))
    if not start:
        return None
    return {
        "movie_title": title,
        "start_date": start,
        "end_date": _iso_date(_node_text(tile.select_one(".endDate"))) or start,
        "screen_name": _node_text(tile.select_one(".location")) or None,
        "detail_page_url": urljoin(BASE_URL, str(link.get("href") or "")),
        "image_url": _unwrap_next_image(str(image.get("src"))) if image else None,
    }


def _detail_fields(soup: BeautifulSoup) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for item in soup.select("ul.detail-list li.list-item"):
        label = _node_text(item.select_one(".title"))
        value = _node_text(item.select_one(".text"))
        if label and value:
            fields[label] = value
    return fields


def _detail_categories(soup: BeautifulSoup) -> List[str]:
    slugs: List[str] = []
    for anchor in soup.select('ul.tab-list a[href*="type="]'):
        slug = parse_qs(urlparse(str(anchor.get("href") or "")).query).get("type", [])
        slugs.extend(slug)
        label = _node_text(anchor)
        if label:
            slugs.append(label)
    return slugs


def _booking_url(soup: BeautifulSoup) -> Optional[str]:
    for item in soup.select("ul.detail-list li.list-item"):
        if _node_text(item.select_one(".title")) != "報名連結":
            continue
        anchor = item.select_one("a[href^=http]")
        if anchor:
            return str(anchor.get("href"))
    return None


def _tags(soup: BeautifulSoup) -> List[str]:
    return [t for t in (_node_text(a).lstrip("#").strip() for a in soup.select('a[href*="/events?tag="]')) if t]


def scrape_clab() -> List[Dict]:
    today = datetime.now(TAIPEI_TZ).date().isoformat()

    tiles: List[Dict[str, Optional[str]]] = []
    seen_urls: Set[str] = set()
    for page in range(1, MAX_LISTING_PAGES + 1):
        listing_url = LISTING_URL_TEMPLATE.format(page=page)
        try:
            soup = _fetch_soup(listing_url)
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] listing fetch failed: {listing_url} {exc}", file=sys.stderr)
            break

        page_tiles = soup.select("div.EventTileItem")
        if not page_tiles:
            break
        for node in page_tiles:
            tile = _parse_tile(node)
            if not tile:
                continue
            detail_url = str(tile["detail_page_url"])
            if detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)
            # The index is an all-time archive; keep anything still running today.
            if str(tile["end_date"]) < today:
                continue
            tiles.append(tile)

    results: List[Dict] = []
    for tile in tiles:
        detail_url = str(tile["detail_page_url"])
        try:
            soup = _fetch_soup(detail_url)
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {detail_url} {exc}", file=sys.stderr)
            continue

        categories = _detail_categories(soup)
        # Belt and braces: the listing filter already restricted us to 放映, but an
        # event may carry several categories and the filter could silently change.
        if SCREENING_TYPE_SLUG not in categories and SCREENING_TYPE_LABEL not in categories:
            continue

        fields = _detail_fields(soup)
        start_date = str(tile["start_date"])
        # A multi-day programme that already started surfaces under today rather
        # than leaking a stale past date into the feed (same rule as Treasure Hill).
        display_date = start_date if start_date >= today else today

        results.append(
            {
                "cinema_name": CINEMA_NAME,
                "movie_title": tile["movie_title"],
                "movie_title_en": None,
                "director": None,
                "director_en": "",
                "year": None,
                "country": None,
                "runtime_min": None,
                "synopsis": _node_text(soup.select_one("article.article-base")),
                "date_text": display_date,
                "showtime": _first_time(fields.get("時間", "")),
                "screen_name": fields.get("地點") or tile["screen_name"],
                "detail_page_url": detail_url,
                "booking_url": _booking_url(soup),
                "image_url": tile["image_url"],
                "tags": [SCREENING_TYPE_LABEL, *_tags(soup)],
            }
        )

    return results


if __name__ == "__main__":
    import json

    rows = scrape_clab()
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"{len(rows)} rows", file=sys.stderr)
