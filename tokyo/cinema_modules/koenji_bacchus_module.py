from __future__ import annotations

import datetime as dt
import re
import sys
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

CINEMA_NAME = "高円寺シアターバッカス"
BASE_URL = "https://bacchus-tokyo.com/"
SCREENING_URLS = [BASE_URL]
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ja,en;q=0.8"}

# The schedule lives in one flat text block on the front page, between these markers.
_SCHEDULE_START = "上映スケジュール"
_SCHEDULE_END = "高円寺シアターバッカスとは"

_MAX_DAYS_AHEAD = 180

_FULLWIDTH_TRANS = str.maketrans(
    "０１２３４５６７８９：／－〜～　",
    "0123456789:/-~~ ",
)

_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
# "9月24・25日", "9月7日", "10月30・31日"
_JP_DATE_RE = re.compile(r"(\d{1,2})月((?:\d{1,2}[・,、])*\d{1,2})日")
# "9/7"
_SLASH_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d/)")
_TITLE_RE = re.compile(r"[『「]([^』」]+)[』」]")
_WEEKDAY_PAREN_RE = re.compile(r"[（(][月火水木金土日祝・,、\s]*[）)]")
# Circled numerals used as "screening 1 / 2 / 3" markers, not part of a title.
_CIRCLED_NUM_RE = re.compile(r"[①-⑳❶-❿➀-➉⓵-⓾]")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize(text: str) -> str:
    return _clean_text((text or "").translate(_FULLWIDTH_TRANS))


def _today_jst() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover - Python < 3.9
        from backports.zoneinfo import ZoneInfo  # type: ignore
    return dt.datetime.now(ZoneInfo("Asia/Tokyo")).date()


def _resolve_year(month: int, day: int, today: dt.date) -> int:
    """Pick the calendar year that puts month/day nearest to (and mostly after) today."""
    try:
        candidate = dt.date(today.year, month, day)
    except ValueError:
        return today.year
    if candidate < today - dt.timedelta(days=45):
        return today.year + 1
    return today.year


def _dates_in_line(line: str, today: dt.date) -> List[dt.date]:
    """Every explicit date mentioned in one line, in source order."""
    found: List[dt.date] = []
    seen = set()

    def add(month: int, day: int) -> None:
        year = _resolve_year(month, day, today)
        try:
            value = dt.date(year, month, day)
        except ValueError:
            return
        if value not in seen:
            seen.add(value)
            found.append(value)

    for match in _JP_DATE_RE.finditer(line):
        month = int(match.group(1))
        for day_raw in re.split(r"[・,、]", match.group(2)):
            add(month, int(day_raw))
    for match in _SLASH_DATE_RE.finditer(line):
        add(int(match.group(1)), int(match.group(2)))
    return found


def _times_in_line(line: str) -> List[str]:
    times: List[str] = []
    for hour, minute in _TIME_RE.findall(line):
        value = f"{int(hour):02d}:{minute}"
        if int(hour) <= 29 and value not in times:
            times.append(value)
    return times


def _lead_label(line: str) -> str:
    """Text before the first showtime, once dates and decoration are stripped."""
    match = _TIME_RE.search(line)
    lead = line[: match.start()] if match else line
    lead = _JP_DATE_RE.sub("", lead)
    lead = _SLASH_DATE_RE.sub("", lead)
    lead = _WEEKDAY_PAREN_RE.sub("", lead)
    lead = _CIRCLED_NUM_RE.sub("", lead)
    lead = lead.strip(" ●◆◇▶・~-/:")
    lead = _clean_text(lead)
    return lead if len(lead) <= 30 else ""


def _compose_title(program_title: Optional[str], line: str) -> Optional[str]:
    """Title for a showtime line: an explicit 『…』 wins, else programme + part label."""
    quoted = _TITLE_RE.search(line)
    if quoted:
        return _clean_text(quoted.group(1))
    if not program_title:
        return None
    lead = _lead_label(line)
    return _clean_text(f"{program_title} {lead}") if lead else program_title


def _schedule_lines(soup: BeautifulSoup) -> List[str]:
    text = soup.get_text("\n", strip=True)
    start = text.find(_SCHEDULE_START)
    if start < 0:
        return []
    end = text.find(_SCHEDULE_END, start)
    block = text[start : end if end > start else len(text)]
    return [_normalize(line) for line in block.splitlines()[1:]]


def _parse_schedule(lines: Iterable[str], today: dt.date) -> List[Tuple[dt.date, str, str]]:
    horizon = today + dt.timedelta(days=_MAX_DAYS_AHEAD)
    out: List[Tuple[dt.date, str, str]] = []
    seen = set()

    program_title: Optional[str] = None
    block_dates: List[dt.date] = []
    block_times: List[str] = []
    current_dates: List[dt.date] = []

    def emit(dates: List[dt.date], times: List[str], title: Optional[str]) -> None:
        if not (dates and times and title):
            return
        for date_value in dates:
            if not (today <= date_value <= horizon):
                continue
            for showtime in times:
                key = (date_value, showtime, title)
                if key in seen:
                    continue
                seen.add(key)
                out.append(key)

    for line in lines:
        if not line or line.startswith("http") or set(line) <= {"・", "◆", "◇", "●", " "}:
            continue

        if line.startswith("●"):
            # New programme block: header may carry its own dates and times.
            program_title = None
            block_dates = _dates_in_line(line, today)
            block_times = _times_in_line(line)
            current_dates = list(block_dates)
            quoted = _TITLE_RE.search(line)
            if quoted:
                program_title = _clean_text(quoted.group(1))
            continue

        if line.startswith("◆"):
            dates = _dates_in_line(line, today)
            if dates:
                current_dates = dates
                continue

        times = _times_in_line(line)
        if not times:
            quoted = _TITLE_RE.search(line)
            if quoted:
                program_title = _clean_text(quoted.group(1))
                # A ● header such as "9月28日（月）19:00～" states the time before the title.
                if block_times and block_dates:
                    emit(block_dates, block_times, program_title)
                    block_times = []
            continue

        line_dates = _dates_in_line(line, today)
        emit(line_dates or current_dates, times, _compose_title(program_title, line))

    return out


def scrape_koenji_bacchus() -> List[Dict[str, str]]:
    response = None
    for url in SCREENING_URLS:
        try:
            candidate = requests.get(url, headers=HEADERS, timeout=20)
            candidate.raise_for_status()
            candidate.encoding = candidate.apparent_encoding
            response = candidate
            break
        except requests.RequestException:
            continue
    if response is None:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch any screening index.", file=sys.stderr)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    rows = _parse_schedule(_schedule_lines(soup), _today_jst())

    listings = [
        {
            "cinema_name": CINEMA_NAME,
            "movie_title": title,
            "movie_title_en": "",
            "director": None,
            "year": None,
            "country": None,
            "runtime_min": None,
            "synopsis": None,
            "date_text": date_value.isoformat(),
            "showtime": showtime,
            "detail_page_url": BASE_URL,
            "purchase_url": None,
        }
        for date_value, showtime, title in sorted(rows)
    ]

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
    for row in data:
        print(row["date_text"], row["showtime"], row["movie_title"])
    print(f"Collected {len(data)} listings.")
