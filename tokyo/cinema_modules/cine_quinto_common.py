from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
}

_DATE_RANGE_RE = re.compile(
    r"^(?P<m1>\d{1,2})/(?P<d1>\d{1,2})\([^)]+\)"
    r"(?:\s*[～〜~\-]\s*(?:(?P<m2>\d{1,2})/)?(?P<d2>\d{1,2})\([^)]+\))?$"
)
_TITLE_LINE_RE = re.compile(r"^『?(?P<title>.+?)』?$")
_COMBINED_LINE_RE = re.compile(r"^『?(?P<title>.+?)』?\s*▶\s*(?P<times>.+)$")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").replace("\u3000", " ").strip()


def _fetch(session: requests.Session, url: str) -> str:
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def _parse_date(month: int, day: int, anchor: _dt.date) -> _dt.date:
    year = anchor.year
    if month < anchor.month - 6:
        year += 1
    elif month > anchor.month + 6:
        year -= 1
    return _dt.date(year, month, day)


def _expand_date_line(line: str, anchor: _dt.date) -> List[_dt.date]:
    normalized = _normalize(line)
    match = _DATE_RANGE_RE.match(normalized)
    if not match:
        return []

    start = _parse_date(int(match.group("m1")), int(match.group("d1")), anchor)
    if match.group("d2"):
        end_month = int(match.group("m2") or match.group("m1"))
        end = _parse_date(end_month, int(match.group("d2")), anchor)
        if end < start and end.year == start.year:
            end = _dt.date(end.year + 1, end.month, end.day)
        days: List[_dt.date] = []
        cursor = start
        while cursor <= end:
            days.append(cursor)
            cursor += _dt.timedelta(days=1)
        return days
    return [start]


def _find_weekly_schedule_url(listing_url: str, session: requests.Session) -> str:
    soup = BeautifulSoup(_fetch(session, listing_url), "html.parser")
    candidates = soup.select("ul.cmn-list01 li.item a[href*='/movie/detail.php?id=']")
    for anchor in candidates:
        href = anchor.get("href", "")
        title = anchor.select_one(".txt01")
        date = anchor.select_one(".date")
        title_text = title.get_text(" ", strip=True) if title else ""
        date_text = date.get_text(" ", strip=True) if date else ""
        if "上映スケジュール" in title_text or re.fullmatch(r"\d{4}/\d{2}/\d{2}-\d{4}/\d{2}/\d{2}", date_text):
            return urljoin(listing_url, href)

    # Fallback: first detail link on the page.
    if candidates:
        return urljoin(listing_url, candidates[0].get("href", ""))
    return ""


def _extract_schedule_text(detail_url: str, session: requests.Session) -> str:
    soup = BeautifulSoup(_fetch(session, detail_url), "html.parser")
    article = soup.select_one("article.article")
    if not article:
        return ""
    return article.get_text("\n", strip=True)


def _parse_showtimes(times_text: str) -> List[str]:
    times: List[str] = []
    for token in re.split(r"\s*/\s*", times_text):
        match = _TIME_RE.search(token)
        if match:
            times.append(f"{int(match.group(1)):02d}:{match.group(2)}")
    return times


def _strip_title(title: str) -> str:
    title = _normalize(title)
    title = title.strip("『』「」【】")
    return title.strip()


def scrape_cine_quinto_weekly_schedule(
    listing_url: str,
    cinema_name: str,
    ticket_url: str,
) -> List[Dict[str, str]]:
    session = requests.Session()
    session.headers.update(HEADERS)

    detail_url = _find_weekly_schedule_url(listing_url, session)
    if not detail_url:
        return []

    article_text = _extract_schedule_text(detail_url, session)
    if not article_text:
        return []

    today = _dt.date.today()
    rows: List[Dict[str, str]] = []
    current_dates: List[_dt.date] = []
    pending_title: Optional[str] = None

    for raw_line in article_text.splitlines():
        line = _normalize(raw_line)
        if not line:
            continue
        if "上映スケジュール" in line and line.startswith("【"):
            continue
        if "チケットのご購入" in line or "画面上部" in line:
            continue

        date_block = _expand_date_line(line, today)
        if date_block:
            current_dates = date_block
            pending_title = None
            continue

        combined = _COMBINED_LINE_RE.match(line)
        if combined and current_dates:
            title = _strip_title(combined.group("title"))
            times = _parse_showtimes(combined.group("times"))
            for dt_obj in current_dates:
                for showtime in times:
                    rows.append(
                        {
                            "cinema_name": cinema_name,
                            "movie_title": title,
                            "movie_title_en": "",
                            "director": None,
                            "year": None,
                            "country": None,
                            "runtime_min": None,
                            "synopsis": None,
                            "date_text": dt_obj.isoformat(),
                            "showtime": showtime,
                            "detail_page_url": detail_url,
                            "purchase_url": ticket_url,
                        }
                    )
            pending_title = None
            continue

        if line.startswith("『") or line.startswith("【"):
            pending_title = _strip_title(line)
            continue

        if line.startswith("▶") and current_dates and pending_title:
            times = _parse_showtimes(line.lstrip("▶").strip())
            for dt_obj in current_dates:
                for showtime in times:
                    rows.append(
                        {
                            "cinema_name": cinema_name,
                            "movie_title": pending_title,
                            "movie_title_en": "",
                            "director": None,
                            "year": None,
                            "country": None,
                            "runtime_min": None,
                            "synopsis": None,
                            "date_text": dt_obj.isoformat(),
                            "showtime": showtime,
                            "detail_page_url": detail_url,
                            "purchase_url": ticket_url,
                        }
                    )
            pending_title = None

    rows.sort(key=lambda row: (row.get("date_text", ""), row.get("showtime", ""), row.get("movie_title", "")))
    return rows
