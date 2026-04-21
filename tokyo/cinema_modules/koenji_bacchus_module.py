from __future__ import annotations

import datetime as dt
import re
import sys
from typing import Dict, Iterable, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

CINEMA_NAME = "高円寺シアターバッカス"
BASE_URL = "https://bacchus-tokyo.com/"
SCREENING_URL = urljoin(BASE_URL, "/screening/")
SCREENING_URLS = [
    BASE_URL,
    SCREENING_URL,
    urljoin(BASE_URL, "/category/%E4%B8%8A%E6%98%A0/"),
    urljoin(BASE_URL, "/category/%E7%89%B9%E9%9B%86%E4%B8%8A%E6%98%A0/"),
]
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ja,en;q=0.8"}

_FULLWIDTH_TRANS = str.maketrans(
    "０１２３４５６７８９：／－〜～",
    "0123456789:/-~~",
)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize(text: str) -> str:
    return _clean_text(text.translate(_FULLWIDTH_TRANS))


def _today_jst() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("Asia/Tokyo")).date()


def _resolve_year(month: int, day: int, base_year: int, today: dt.date) -> int:
    candidate = dt.date(base_year, month, day)
    if candidate < today - dt.timedelta(days=45):
        return base_year + 1
    return base_year


def _iter_dates(text: str, today: dt.date) -> Iterable[dt.date]:
    normalized = _normalize(text)
    seen = set()

    range_patterns = [
        re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日.{0,20}[~/\-](?:(\d{1,2})月)?(\d{1,2})日"),
        re.compile(r"(?:(\d{4})/)?(\d{1,2})/(\d{1,2}).{0,20}[~/\-](?:(\d{1,2})/)?(\d{1,2})"),
    ]
    for pattern in range_patterns:
        for match in pattern.finditer(normalized):
            year_raw, start_month, start_day, end_month, end_day = match.groups()
            year = int(year_raw) if year_raw else today.year
            sm = int(start_month)
            sd = int(start_day)
            em = int(end_month) if end_month else sm
            ed = int(end_day)
            year = _resolve_year(sm, sd, year, today)
            try:
                current = dt.date(year, sm, sd)
                end = dt.date(year + (1 if em < sm else 0), em, ed)
            except ValueError:
                continue
            emitted = 0
            while current <= end and emitted <= 31:
                if current not in seen:
                    seen.add(current)
                    yield current
                current += dt.timedelta(days=1)
                emitted += 1

    single_patterns = [
        re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日"),
        re.compile(r"(?:(\d{4})/)?(\d{1,2})/(\d{1,2})"),
    ]
    for pattern in single_patterns:
        for match in pattern.finditer(normalized):
            year_raw, month_raw, day_raw = match.groups()
            month = int(month_raw)
            day = int(day_raw)
            year = int(year_raw) if year_raw else _resolve_year(month, day, today.year, today)
            try:
                value = dt.date(year, month, day)
            except ValueError:
                continue
            if value not in seen:
                seen.add(value)
                yield value


def _iter_times(text: str) -> Iterable[str]:
    for hour, minute in re.findall(r"\b(\d{1,2}):(\d{2})\b", _normalize(text)):
        yield f"{int(hour):02d}:{minute}"


def _entry_text(anchor: Tag) -> str:
    article = anchor.find_parent("article")
    if article:
        return article.get_text(" ", strip=True)
    parent = anchor.find_parent()
    return parent.get_text(" ", strip=True) if parent else anchor.get_text(" ", strip=True)


def scrape_koenji_bacchus() -> List[Dict[str, str]]:
    response = None
    for url in SCREENING_URLS:
        try:
            candidate = requests.get(url, headers=HEADERS, timeout=20)
            candidate.raise_for_status()
            response = candidate
            break
        except requests.RequestException:
            continue
    if response is None:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch any screening index.", file=sys.stderr)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    today = _today_jst()
    listings: List[Dict[str, str]] = []
    seen = set()

    for anchor in soup.select("h3 a[href], .entry-title a[href], article a[href]"):
        title = _clean_text(anchor.get_text(" ", strip=True))
        if not title or title in {"READ MORE", "上映", "TOPICS"}:
            continue
        detail_url = urljoin(BASE_URL, anchor.get("href", ""))
        text = _entry_text(anchor)
        dates = [value for value in _iter_dates(text, today) if value >= today]
        times = list(dict.fromkeys(_iter_times(text)))
        if not dates or not times:
            continue
        for date_value in dates:
            for showtime in times:
                key = (title, date_value.isoformat(), showtime)
                if key in seen:
                    continue
                seen.add(key)
                listings.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "date_text": date_value.isoformat(),
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                    "synopsis": _clean_text(text),
                })

    if not listings:
        print(f"INFO: [{CINEMA_NAME}] No future public screenings with explicit times found.")
    return listings


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    data = scrape_koenji_bacchus()
    print(f"Collected {len(data)} listings.")
