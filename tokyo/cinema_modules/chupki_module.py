# -*- coding: utf-8 -*-
"""
chupki_module.py
Scraper for Cinema Chupki Tabata, conforming to the standard format. (Final Version)

This version adds splitting of combined Japanese and English titles.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# --- Constants ---
CINEMA_NAME = "CINEMA Chupki TABATA"
BASE_URL = "https://chupki.jpn.org/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}
THIS_YEAR = dt.date.today().year

# --- Helper Functions ---

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch page {url}: {e}", file=sys.stderr)
        return None

def _parse_and_split_title(text: Optional[str]) -> tuple[str, str]:
    """
    Parses a movie title and splits it into Japanese and English parts if combined.
    Removes brackets and trailing notes.
    e.g. "『Movie（US）』 ＊Note" -> "Movie", ""
    e.g. "Underground アンダーグラウンド" -> "アンダーグラウンド", "Underground"
    """
    if not text:
        return "", ""

    # Remove content in full-width parentheses, e.g.（アメリカ）
    text = re.sub(r'（[^）]+）', '', text)
    # Remove special brackets
    text = text.replace("『", "").replace("』", "")
    # Remove notes like *6/26のみ 17:10-
    text = re.sub(r'\s*[＊✳︎].*$', '', text.strip())
    # Standard whitespace normalization
    text = " ".join(text.strip().split())

    # Attempt to split English and Japanese titles
    # Assuming English title often comes first or is separated by a space/full-width space
    # Look for a pattern like "English Title Japanese Title"
    match = re.match(r"([a-zA-Z0-9\s.,'&:-]+?)\s+([\u3000-\u9FFF\u3040-\u309F\u30A0-\u30FF\s]+)", text)
    if match:
        english_title = match.group(1).strip()
        japanese_title = match.group(2).strip()
        return japanese_title, english_title
    else:
        # If no clear split, assume the whole thing is the Japanese title, and English is empty
        return text, ""


# --- Scraping Logic ---

def _parse_movie_details(soup: BeautifulSoup) -> Dict[str, Dict]:
    """
    Parses all movie detail boxes on the page to build a cache.
    Keyed by cleaned movie title.
    """
    details_cache = {}
    movie_boxes = soup.select("section.movie .movie__box")
    print(f"INFO: [{CINEMA_NAME}] Found {len(movie_boxes)} movie detail boxes.", file=sys.stderr)

    for box in movie_boxes:
        title_tag = box.select_one("h4.movie__ttl")
        if not title_tag:
            continue

        full_title_text = title_tag.get_text()
        japanese_title, english_title = _parse_and_split_title(full_title_text)
        
        # Use the Japanese title as the key for the cache
        title_key = japanese_title 
        if not title_key or title_key in details_cache:
            continue

        details = {
            "movie_title": japanese_title,
            "movie_title_en": english_title,
            "director": None, "year": None, "runtime_min": None,
            "country": None, "synopsis": None, "purchase_url": None,
            "detail_page_url": BASE_URL
        }

        # Parse year, runtime, country from "2024年／131分／日本／ドキュメンタリー"
        if etc_tag := box.select_one("div.movie_etc"):
            etc_text = etc_tag.get_text(strip=True)
            parts = re.split(r'[／/]', etc_text)
            
            if m := re.search(r"(\d{4})", etc_text): details["year"] = m.group(1)
            # Ensure runtime is a number only
            if m := re.search(r"(\d+)\s*分", etc_text): details["runtime_min"] = m.group(1)
            elif m := re.search(r"(\d+)", etc_text): details["runtime_min"] = m.group(1)


            # Find country by excluding known non-country terms
            for part in parts:
                part = part.strip()
                # Check for specific patterns that indicate it's not a country name
                if not any(x in part for x in ['年', '分', '製作', 'ドキュメンタリー', 'カラー', 'モノクロ']) and not part.isdigit() and len(part) > 1:
                     # It's likely the country name
                    details["country"] = part.replace('合作','').strip()
                    break

        if info_tag := box.select_one("div.movie_info"):
            synopsis_text = " ".join(info_tag.get_text(separator="\n", strip=True).split())
            details["synopsis"] = synopsis_text
            # More precise regex for director: captures Japanese name, avoiding leading descriptive text
            # Looks for "氏名監督" or "監督 氏名" or "氏名 監督"
            director_match = re.search(r"(?:監督\s*|)([\u3040-\u30FF\u4E00-\u9FFF\s\・\ー\(\)「」『』]{2,20})\s*監督", synopsis_text)
            if director_match:
                # Take the captured group, clean up extra spaces and specific characters often found near names
                director_name = director_match.group(1).strip()
                # Remove common descriptive terms that might get caught
                director_name = re.sub(r"に真摯に向き合う|陶を受けた|初監督作品|による", "", director_name).strip()
                details["director"] = director_name
            else: # Fallback to a broader search for "監督" followed by a name if the primary regex fails
                 # This might still catch extra text if not carefully crafted
                if fallback_dir_match := re.search(r"監督[：:]*\s*([^\s／/・|,\n]+)", synopsis_text):
                    details["director"] = fallback_dir_match.group(1).strip()


        if btn_tag := box.select_one("a.movie__btn"):
            details["purchase_url"] = btn_tag.get("href")

        details_cache[title_key] = details
        print(f"  ... Cached details for '{title_key}'", file=sys.stderr)

    return details_cache

# Day numbers named by a closure note. The site writes these as
# "＊10(木)〜13(日)休映" (this row is cancelled on 10-13) or, less often, as a
# 休館 note meaning the whole venue is shut.
_CLOSURE_WORDS = ("休映", "休館")
_TIME_RE = re.compile(r"\d{1,2}\s*[:：]\s*\d{2}")
_NOTE_TAIL_RE = re.compile(r"[＊✳].*$", re.S)


def _resolve_date(month: int, day: int, today: dt.date) -> Optional[dt.date]:
    """Pick the year that puts month/day nearest to today (handles Dec -> Jan)."""
    for year in (today.year, today.year + 1, today.year - 1):
        try:
            candidate = dt.date(year, month, day)
        except ValueError:
            continue
        if abs((candidate - today).days) <= 185:
            return candidate
    return None


def _closure_days(text: str) -> tuple[set[int], bool]:
    """
    Read a 休映/休館 note into the day numbers it cancels.

    Returns (days, unreadable). `unreadable` is True when a closure word is
    present but no day number could be recovered - the caller must then drop
    the affected rows rather than publish them, because a wrong showtime sends
    someone to a shut cinema. A note whose range wraps a month end
    ("＊30(火)〜2(木)休映") yields no days and so reads as unreadable, which
    drops the rows: under-reporting, never a screening on a shut day.
    """
    if not any(word in text for word in _CLOSURE_WORDS):
        return set(), False

    days: set[int] = set()
    for match in re.finditer("|".join(_CLOSURE_WORDS), text):
        segment = text[: match.start()]
        # A note starts at its own marker; anything before it is the film title.
        segment = re.split(r"[＊✳、。\n]", segment)[-1]
        segment = _TIME_RE.sub(" ", segment)              # 18:30 is not day 18
        segment = re.sub(r"[（(][^）)]*[）)]", "", segment)  # drop (木) weekday tags
        segment = re.sub(r"\d{1,2}\s*月", "", segment)     # drop the month number
        compact = re.sub(r"[^0-9〜～\-–—,、，]", "", segment)
        for part in re.split(r"[,、，]", compact):
            if span := re.fullmatch(r"(\d{1,2})[〜～\-–—](\d{1,2})", part):
                days.update(range(int(span.group(1)), int(span.group(2)) + 1))
            elif part.isdigit():
                days.add(int(part))
    days = {d for d in days if 1 <= d <= 31}
    return days, not days


def _block_notes(block, table) -> tuple[set[int], bool]:
    """
    Closure days that apply to every row of a block: notes written outside the
    table, plus any 休館 (whole venue shut) note wherever it sits.
    """
    outside = " ".join(
        s for s in block.find_all(string=True) if not s.find_parent("table")
    )
    days, unreadable = _closure_days(outside)
    table_text = table.get_text(" ", strip=True) if table else ""
    if "休館" in table_text:
        venue_days, venue_unreadable = _closure_days(table_text)
        days |= venue_days
        unreadable = unreadable or venue_unreadable
    return days, unreadable


def _window(today: dt.date, max_days: int) -> tuple[dt.date, dt.date]:
    """Inclusive first date and exclusive cutoff of the publishing window."""
    return today, today + dt.timedelta(days=max_days)


def _range_block_dates(header_text: str, today: dt.date, max_days: int) -> List[dt.date]:
    """Dates covered by a "9月10日(木)〜9月15日(火)" style block header."""
    match = re.search(
        r"(\d{1,2})月(\d{1,2})日.*?[～〜]\s*(?:(\d{1,2})月)?(\d{1,2})日", header_text
    )
    if not match:
        return []
    start_month, start_day, end_month_str, end_day = match.groups()
    start = _resolve_date(int(start_month), int(start_day), today)
    end = _resolve_date(int(end_month_str or start_month), int(end_day), today)
    if not start or not end:
        return []
    if end < start:  # range crosses into the next year
        end = dt.date(end.year + 1, end.month, end.day)

    window_start, cutoff = _window(today, max_days)
    dates, current = [], max(start, window_start)
    while current <= end and current < cutoff:
        dates.append(current)
        current += dt.timedelta(days=1)
    return dates


def _row_cells(table) -> List[tuple[str, str]]:
    """(th text, td text) for each row, with tags separated so appended notes
    do not fuse onto the end of a title."""
    cells = []
    for row in table.find_all("tr"):
        th, td = row.find("th"), row.find("td")
        if not (th and td):
            continue
        cells.append(
            (
                " ".join(th.get_text(" ").split()),
                " ".join(td.get_text(" ").split()),
            )
        )
    return cells


def _showing(details: Dict, title_key: str, date: dt.date, showtime: str) -> Dict:
    return {
        "cinema_name": CINEMA_NAME,
        "movie_title": details.get("movie_title", title_key),
        "movie_title_en": details.get("movie_title_en", ""),
        "date_text": date.isoformat(),
        "showtime": showtime,
        **{k: v for k, v in details.items() if k not in ("movie_title", "movie_title_en")},
    }


def _parse_range_block(
    block, table, details_cache: Dict, today: dt.date, max_days: int
) -> List[Dict]:
    """Weekly block: header carries the date range, each row is time + title."""
    header = block.find("h3", class_="timetable__ttl")
    dates = _range_block_dates(
        header.get_text(" ", strip=True) if header else "", today, max_days
    )
    if not dates:
        return []

    block_closed, block_unreadable = _block_notes(block, table)
    if block_unreadable:
        print(
            f"WARN: [{CINEMA_NAME}] Block-level closure note could not be read; "
            f"skipping block '{header.get_text(' ', strip=True) if header else ''}'.",
            file=sys.stderr,
        )
        return []

    showings = []
    for th_text, td_text in _row_cells(table):
        time_match = re.search(r"(\d{1,2}:\d{2})", th_text)
        if not time_match:
            continue
        showtime = time_match.group(1)

        row_closed, row_unreadable = _closure_days(td_text)
        if row_unreadable:
            print(
                f"WARN: [{CINEMA_NAME}] Unreadable closure note on row "
                f"'{td_text}'; dropping the row.",
                file=sys.stderr,
            )
            continue
        closed = block_closed | row_closed

        title_key, _ = _parse_and_split_title(_NOTE_TAIL_RE.sub("", td_text))
        if not title_key:
            continue
        details = details_cache.get(title_key)
        if details is None:
            print(
                f"WARN: [{CINEMA_NAME}] No details found in cache for title: '{title_key}'",
                file=sys.stderr,
            )
            details = {}

        for date in dates:
            if date.day in closed:
                continue
            showings.append(_showing(details, title_key, date, showtime))
    return showings


def _parse_dated_rows_block(
    block, table, details_cache: Dict, today: dt.date, max_days: int
) -> List[Dict]:
    """Event block: header carries one title, each row is a date + its time."""
    header = block.find("h3", class_="timetable__ttl")
    header_text = header.get_text(" ", strip=True) if header else ""
    title_match = re.search(r"[「『](.+?)[」』]", header_text)
    if not title_match:
        return []
    title_key, _ = _parse_and_split_title(title_match.group(1))
    if not title_key:
        return []
    details = details_cache.get(title_key, {})

    block_closed, block_unreadable = _block_notes(block, table)
    if block_unreadable:
        print(
            f"WARN: [{CINEMA_NAME}] Block-level closure note could not be read; "
            f"skipping block '{header_text}'.",
            file=sys.stderr,
        )
        return []

    window_start, cutoff = _window(today, max_days)
    showings = []
    for th_text, td_text in _row_cells(table):
        date_match = re.search(r"(\d{1,2})月(\d{1,2})日", th_text)
        time_match = re.search(r"(\d{1,2}:\d{2})", td_text)
        if not (date_match and time_match):
            continue
        date = _resolve_date(int(date_match.group(1)), int(date_match.group(2)), today)
        if not date or not (window_start <= date < cutoff):
            continue

        row_closed, row_unreadable = _closure_days(td_text)
        if row_unreadable:
            print(
                f"WARN: [{CINEMA_NAME}] Unreadable closure note on row "
                f"'{th_text} {td_text}'; dropping the row.",
                file=sys.stderr,
            )
            continue
        if date.day in (block_closed | row_closed):
            continue

        showings.append(_showing(details, title_key, date, time_match.group(1)))
    return showings


def _parse_schedule(
    soup: BeautifulSoup,
    details_cache: Dict,
    max_days: int,
    today: Optional[dt.date] = None,
) -> List[Dict]:
    """
    Parse every div.timetable on the page.

    Chupki publishes several blocks side by side (the current week, the next
    week, plus one-off event blocks), in two shapes: a weekly grid whose header
    holds the date range, and an event grid whose rows hold the dates. Reading
    only the first block loses most of the week - but each block may also carry
    a 休映 note cancelling specific days, so blocks and rows are only expanded
    after those notes have been applied.
    """
    today = today or dt.date.today()
    showings: List[Dict] = []
    for block in soup.find_all("div", class_="timetable"):
        table = block.find("table")
        if not table:
            continue
        rows = _row_cells(table)
        if any(re.search(r"\d{1,2}:\d{2}", th) for th, _ in rows):
            showings.extend(_parse_range_block(block, table, details_cache, today, max_days))
        elif any(re.search(r"\d{1,2}月\d{1,2}日", th) for th, _ in rows):
            showings.extend(
                _parse_dated_rows_block(block, table, details_cache, today, max_days)
            )

    seen, unique = set(), []
    for showing in showings:
        key = (showing["date_text"], showing["showtime"], showing["movie_title"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(showing)
    return unique


def scrape_chupki(max_days: int = 14) -> List[Dict]:
    """
    Scrapes all movie showings and details from Cinema Chupki Tabata.
    """
    print(f"INFO: [{CINEMA_NAME}] Starting scrape...", file=sys.stderr) #
    soup = _fetch_soup(BASE_URL) #
    if not soup: return [] #

    details_cache = _parse_movie_details(soup) #
    showings = _parse_schedule(soup, details_cache, max_days) #
    
    showings.sort(key=lambda x: (x.get("date_text", ""), x.get("showtime", ""))) #

    print(f"INFO: [{CINEMA_NAME}] Scrape complete. Found {len(showings)} showings.", file=sys.stderr) #
    return showings #

# --- Main Execution ---

if __name__ == '__main__':
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8')

    all_showings = scrape_chupki() #

    if all_showings: #
        output_filename = f"chupki_showtimes.json" #
        output_path = Path(__file__).parent / output_filename #
        
        print(f"\nINFO: Writing {len(all_showings)} records to {output_path}...", file=sys.stderr) #
        with open(output_path, "w", encoding="utf-8") as f: #
            json.dump(all_showings, f, ensure_ascii=False, indent=2) #
        print(f"INFO: Successfully created {output_path}.", file=sys.stderr) #
        
        print("\n--- Sample of First Showing ---") #
        from pprint import pprint
        pprint(all_showings[0])
    else: #
        print(f"\nNo showings found for {CINEMA_NAME}.") #