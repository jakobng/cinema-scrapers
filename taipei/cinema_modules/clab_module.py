from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://clab.org.tw"
LISTING_URLS = (
    f"{BASE_URL}/events/",
    f"{BASE_URL}/events/page/2/",
)
CINEMA_NAME = "臺灣當代文化實驗場 C-LAB"
KEYWORDS = (
    "放映",
    "播映",
    "影片",
    "影展",
    "膠卷",
    "16mm",
    "8mm",
    "錄像",
    "投影",
    "實驗電影",
    "screening",
    "projection",
)


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


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _parse_card_date(card: BeautifulSoup) -> Optional[str]:
    for wrapper in card.select(".a-base-card__footer .a-dateTime__wrapper"):
        classes = wrapper.get("class") or []
        if "-time" in classes:
            continue
        month_day = wrapper.select_one(".a-dateTime__text")
        year = wrapper.select_one(".a-dateTime__year")
        if not month_day or not year:
            continue
        md_match = re.search(r"(\d{2})\.(\d{2})", month_day.get_text(" ", strip=True))
        year_match = re.search(r"(20\d{2})", year.get_text(" ", strip=True))
        if not md_match or not year_match:
            continue
        return f"{year_match.group(1)}-{md_match.group(1)}-{md_match.group(2)}"
    return None


def _parse_card_time(card: BeautifulSoup) -> Optional[str]:
    for wrapper in card.select(".a-base-card__footer .a-dateTime__wrapper"):
        classes = wrapper.get("class") or []
        if "-time" not in classes:
            continue
        match = re.search(r"(\d{1,2}):(\d{2})", wrapper.get_text(" ", strip=True))
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"
    return None


def _extract_image_url(card: BeautifulSoup) -> Optional[str]:
    thumb = card.select_one(".a-base-card__thumbnail")
    style = str(thumb.get("style") or "") if thumb else ""
    match = re.search(r"url\((https?://[^)]+)\)", style)
    return match.group(1) if match else None


def _extract_booking_url(soup: BeautifulSoup) -> Optional[str]:
    for anchor in soup.select(".m-single-side__registration a[href]"):
        href = str(anchor.get("href") or "").strip()
        if href.startswith("http"):
            return href
    return None


def _extract_tags(soup: BeautifulSoup) -> List[str]:
    tags = [_clean_text(node.get_text(" ", strip=True)) for node in soup.select(".m-single-side__hashtag a")]
    return [tag for tag in tags if tag]


def _is_screening_candidate(*values: object) -> bool:
    haystack = " ".join(_clean_text(str(value or "")) for value in values).lower()
    return any(keyword.lower() in haystack for keyword in KEYWORDS)


def _parse_card(card: BeautifulSoup) -> Optional[Dict[str, Optional[str]]]:
    title_node = card.select_one(".a-base-card__title")
    content_link = card.select_one('.a-base-card__content[href*="/events/"]')
    if not title_node or not content_link:
        return None

    detail_url = str(content_link.get("href") or "").strip()
    if not detail_url:
        return None

    return {
        "movie_title": _clean_text(title_node.get_text(" ", strip=True)),
        "category": _clean_text(card.select_one(".a-base-card__category").get_text(" ", strip=True))
        if card.select_one(".a-base-card__category")
        else None,
        "screen_name": _clean_text(card.select_one(".a-base-card__location").get_text(" ", strip=True))
        if card.select_one(".a-base-card__location")
        else None,
        "date_text": _parse_card_date(card),
        "showtime": _parse_card_time(card),
        "detail_page_url": detail_url,
        "image_url": _extract_image_url(card),
    }


def scrape_clab() -> List[Dict]:
    today = datetime.now().date().isoformat()
    cards: List[Dict[str, Optional[str]]] = []
    seen_urls: Set[str] = set()

    for listing_url in LISTING_URLS:
        try:
            soup = _fetch_soup(listing_url)
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] listing fetch failed: {listing_url} {exc}", file=sys.stderr)
            continue

        for card_node in soup.select(".a-base-card.-event"):
            card = _parse_card(card_node)
            if not card:
                continue
            detail_url = str(card.get("detail_page_url") or "")
            if not detail_url or detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)
            date_text = str(card.get("date_text") or "")
            if not date_text or date_text < today:
                continue
            cards.append(card)

    results: List[Dict] = []
    for card in cards:
        detail_url = str(card.get("detail_page_url") or "")
        try:
            soup = _fetch_soup(detail_url)
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {detail_url} {exc}", file=sys.stderr)
            continue

        content_node = soup.select_one(".m-single-main__content-main")
        synopsis = _clean_text((content_node or soup).get_text(" ", strip=True))
        synopsis_focus = synopsis[:900]
        if not _is_screening_candidate(
            card.get("movie_title"),
            card.get("screen_name"),
            synopsis_focus,
            " ".join(_extract_tags(soup)),
        ):
            continue

        results.append(
            {
                "cinema_name": CINEMA_NAME,
                "movie_title": card.get("movie_title") or "",
                "movie_title_en": None,
                "director": None,
                "director_en": "",
                "year": None,
                "country": None,
                "runtime_min": None,
                "synopsis": synopsis,
                "date_text": card.get("date_text"),
                "showtime": card.get("showtime"),
                "screen_name": card.get("screen_name"),
                "detail_page_url": detail_url,
                "booking_url": _extract_booking_url(soup),
                "image_url": card.get("image_url"),
                "tags": [tag for tag in [card.get("category"), *_extract_tags(soup)] if tag],
            }
        )

    return results
