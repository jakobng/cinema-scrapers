"""
theatre_shinjuku_module.py — scraper for テアトル新宿 (Theatre Shinjuku)

Robust handling of encoding and common UTF-8/Latin-1 mojibake.
Attempts to repair double-encoded Japanese text.
Drops remaining mojibake festival blocks that cannot be meaningfully used.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --- Constants ---
CINEMA_NAME = "テアトル新宿"
BASE_URL = "https://ttcg.jp"
SCHEDULE_DATA_URL = f"{BASE_URL}/data/theatre_shinjuku.js"


# --- Encoding / mojibake helpers ---


def _fetch_content(url: str, is_json: bool) -> Optional[str]:
    """
    Fetch content from a URL with explicit encoding handling.

    - For the JS schedule data we use cp932, since that is what TTCG uses.
    - For HTML we force UTF-8 and then rely on downstream mojibake repair
      if the server has double-encoded some fields.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        request_url = f"{url}?t={datetime.now().timestamp()}"
        print(f"INFO: Fetching {'JSON' if is_json else 'HTML'} from {request_url}")

        response = requests.get(request_url, timeout=20, headers=headers)
        response.raise_for_status()

        if is_json:
            return response.content.decode("cp932", errors="replace")
        else:
            response.encoding = "utf-8"
            return response.text
    except requests.RequestException as e:
        print(f"ERROR: Could not fetch {url}: {e}", file=sys.stderr)
        return None


def _has_japanese(text: str) -> bool:
    """Return True if the string contains any typical Japanese characters."""
    if not text:
        return False
    for ch in text:
        code = ord(ch)
        # Hiragana, Katakana, CJK Unified Ideographs
        if 0x3040 <= code <= 0x30FF or 0x4E00 <= code <= 0x9FFF:
            return True
    return False


def _fix_mojibake(text: Optional[str]) -> Optional[str]:
    """
    Attempt to repair common UTF-8→Latin-1 mojibake such as 'ãã¼ãã...'.

    Strategy:
      - If the string already has Japanese characters, return as-is.
      - If it contains 'ã' or 'Ã', try Latin-1→UTF-8 re-decode.
      - If that result has Japanese, return it; otherwise keep the original.
    """
    if text is None:
        return None

    if _has_japanese(text):
        return text

    if "ã" in text or "Ã" in text:
        try:
            repaired = text.encode("latin1", errors="ignore").decode(
                "utf-8", errors="ignore"
            )
            if _has_japanese(repaired):
                return repaired
        except Exception:
            pass

    return text


# Typical Shift-JIS→UTF-8 mojibake characters (kanji-ish and half-width kana etc.)
MOJIBAKE_MARKERS = (
    "縺", "繧", "譌", "遘", "邏", "螳", "蟾", "鬮", "縲", "逕", "濶",
    "ｧ", "ｨ", "ｩ", "ｪ", "ｫ",
    "ｶ", "ｷ", "ｸ", "ｹ", "ｺ",
    "ｻ", "ｼ", "ｽ", "ｾ", "ｿ",
    "ﾀ", "ﾁ", "ﾂ", "ﾃ", "ﾄ",
    "ﾅ", "ﾆ", "ﾇ", "ﾈ", "ﾉ",
    "ﾊ", "ﾋ", "ﾌ", "ﾍ", "ﾎ",
    "ﾏ", "ﾐ", "ﾑ", "ﾒ", "ﾓ",
    "ﾔ", "ﾕ", "ﾖ",
    "ﾗ", "ﾘ", "ﾙ", "ﾚ", "ﾛ",
    "ﾜ", "ｦ", "ﾝ",
    " ",  # replacement character
)


def _looks_shiftjis_mojibake(text: Optional[str]) -> bool:
    """
    Return True if the string still looks like Shift-JIS→UTF-8 mojibake.

    Heuristic: if it contains any of the typical mojibake markers above,
    we treat it as unusable and drop it.
    """
    if not text:
        return False
    return any(marker in text for marker in MOJIBAKE_MARKERS)


# --- Parsing helpers ---


def _parse_js_variable(js_content: str) -> Optional[Any]:
    """
    Extract and parse a JSON object/array from a JavaScript variable assignment.

    Accepts forms like:
        var SCHEDULE = {...};
        SCHEDULE = {...};
        {...}
        [...]
    """
    if not js_content:
        return None
    try:
        match = re.search(r"=\s*(\{.*\}|\[.*\]);?", js_content, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        stripped = js_content.strip()
        if stripped.startswith(("{", "[")):
            return json.loads(stripped)
        return None
    except (json.JSONDecodeError, IndexError) as e:
        print(f"ERROR: Could not parse JSON from JS content: {e}", file=sys.stderr)
        return None


def _parse_detail_page(detail_url: str, detail_cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Scrape a movie detail page for richer information.

    - Repairs mojibake in title, synopsis, and overview-related fields.
    - Extracts director, year, country, and synopsis when possible.
    """
    if detail_url in detail_cache:
        return detail_cache[detail_url]

    print(f"INFO: Scraping new detail page: {detail_url}")
    html_content = _fetch_content(detail_url, is_json=False)
    if not html_content:
        detail_cache[detail_url] = {}
        return {}

    soup = BeautifulSoup(html_content, "html.parser")
    details: Dict[str, Optional[str]] = {
        "movie_title": None,
        "director": None,
        "year": None,
        "country": None,
        "synopsis": None,
    }

    # --- Title ---
    title_tag = soup.select_one("h2.movie-title")
    if title_tag:
        if title_tag.find("span"):
            title_tag.find("span").decompose()
        title_text = title_tag.get_text(strip=True)
        title_text = _fix_mojibake(title_text) or title_text
        details["movie_title"] = re.sub(r"[【\[(].*?[)\]】]", "", title_text).strip()

    # --- Director ---
    staff_dl = soup.find("dl", class_="movie-staff")
    if staff_dl:
        for dt in staff_dl.find_all("dt"):
            if "監督" in dt.get_text():
                dd = dt.find_next_sibling("dd")
                if dd:
                    director_text = dd.get_text(strip=True).lstrip("：").strip()
                    director_text = re.sub(
                        r"[（(].*?[)）]", "", director_text
                    ).strip()
                    details["director"] = director_text.split("/")[0].strip()
                    break

    # --- Synopsis ---
    synopsis_tag = soup.select_one(".mod-imageText-a-text p")
    if synopsis_tag:
        synopsis_text = synopsis_tag.get_text(strip=True)
        synopsis_text = _fix_mojibake(synopsis_text) or synopsis_text
        details["synopsis"] = synopsis_text

    # --- Year & country from overview section ---
    overview_div = soup.select_one(".movie-overview")
    if overview_div:
        overview_raw = overview_div.get_text()
        overview_raw = _fix_mojibake(overview_raw) or overview_raw
        overview_text = unicodedata.normalize("NFKC", overview_raw)

        # Priority 1: structured "movie-data" paragraph.
        meta_tag = overview_div.select_one("p.movie-data")
        if meta_tag:
            meta_text_raw = meta_tag.get_text(strip=True)
            meta_text_raw = _fix_mojibake(meta_text_raw) or meta_text_raw
            meta_text = unicodedata.normalize("NFKC", meta_text_raw)

            year_match = re.search(r"\(?(\d{4})[年/]", meta_text)
            if year_match:
                details["year"] = year_match.group(1)

            parts = re.split(r"[／/]", meta_text)
            if len(parts) > 1 and details["year"]:
                country_candidate = parts[1].strip()
                if "分" not in country_candidate and not country_candidate.isdigit():
                    details["country"] = country_candidate

        # Priority 2: copyright notice.
        if not details["year"]:
            copyright_tag = overview_div.find("p", class_="title-copyright")
            if copyright_tag:
                copyright_text_raw = copyright_tag.get_text()
                copyright_text_raw = _fix_mojibake(copyright_text_raw) or copyright_text_raw
                copyright_text = unicodedata.normalize("NFKC", copyright_text_raw)
                year_match = re.search(r"[©Ⓒ]\s*(\d{4})", copyright_text)
                if year_match:
                    details["year"] = year_match.group(1)

        # Priority 3: generic "YYYY年...公開" pattern.
        if not details["year"]:
            year_match = re.search(r"(\d{4})年.*?公開", overview_text)
            if year_match:
                details["year"] = year_match.group(1)

        # Priority 4: award section fallback.
        if not details["year"]:
            award_div = overview_div.select_one(".movie-award")
            if award_div:
                award_text_raw = award_div.get_text()
                award_text_raw = _fix_mojibake(award_text_raw) or award_text_raw
                award_text = unicodedata.normalize("NFKC", award_text_raw)
                year_match = re.search(r"(\d{4})年", award_text)
                if year_match:
                    details["year"] = year_match.group(1)

    # Fallback for country from small label area.
    if not details["country"]:
        country_label = soup.select_one(".schedule-nowShowing-label .label-type-b")
        if country_label:
            country_text = country_label.get_text(strip=True)
            country_text = _fix_mojibake(country_text) or country_text
            if "不可" not in country_text:
                details["country"] = country_text

    detail_cache[detail_url] = details
    return details


# --- Main scraping function ---


def scrape_theatre_shinjuku(max_days: int = 7) -> List[Dict[str, Any]]:
    """
    Scrape the Theatre Shinjuku schedule.

    Returns a list of normalised showtime dicts.
    """
    js_content = _fetch_content(SCHEDULE_DATA_URL, is_json=True)
    schedule_data = _parse_js_variable(js_content)

    if not schedule_data:
        print("ERROR: Failed to fetch or parse schedule data. Aborting.")
        return []

    detail_cache: Dict[str, Dict[str, Any]] = {}
    all_showings: List[Dict[str, Any]] = []

    dates_to_process = schedule_data.get("dates", [])[:max_days]
    movies_map = schedule_data.get("movies", {})
    screens_map = schedule_data.get("screens", {})

    for date_info in dates_to_process:
        date_str = (
            f"{date_info['date_year']}-"
            f"{str(date_info['date_month']).zfill(2)}-"
            f"{str(date_info['date_day']).zfill(2)}"
        )

        for movie_id in date_info.get("movie", []):
            movie_id_str = str(movie_id)

            if movie_id_str not in movies_map or not movies_map[movie_id_str]:
                continue
            movie_details_json = movies_map[movie_id_str][0]

            json_title = movie_details_json.get("name", "").strip()
            json_title = _fix_mojibake(json_title) or json_title
            runtime_min = movie_details_json.get("running_time")

            # Skip blank titles or obviously short items (trailers, etc.)
            if not json_title or (runtime_min is not None and int(runtime_min) < 30):
                continue

            # Skip talk events etc. explicitly labelled as such.
            if re.search(r"トーク|舞台挨拶|予告編", json_title):
                print(f"INFO: Skipping likely event based on title: '{json_title}'")
                continue

            detail_page_url = urljoin(
                BASE_URL, f"theatre_shinjuku/movie/{movie_id_str}.html"
            )
            details = _parse_detail_page(detail_page_url, detail_cache)

            clean_title = details.get("movie_title")
            if not clean_title:
                clean_title = re.sub(r"[【\[(].*?[)\]】]", "", json_title).strip()

            # Drop remaining mojibake festival blocks that cannot be repaired.
            if _looks_shiftjis_mojibake(clean_title):
                print(
                    f"INFO: Skipping likely mojibake festival block at {CINEMA_NAME}: "
                    f"raw='{json_title}' → '{clean_title}'"
                )
                continue

            screen_key = (
                f"{movie_id_str}-"
                f"{date_info['date_year']}-"
                f"{str(date_info['date_month']).zfill(2)}-"
                f"{str(date_info['date_day']).zfill(2)}"
            )
            screen_schedules = screens_map.get(screen_key, [])

            for screen in screen_schedules:
                for time_info in screen.get("time", []):
                    showtime = (
                        f"{str(time_info['start_time_hour']).zfill(2)}:"
                        f"{str(time_info['start_time_minute']).zfill(2)}"
                    )

                    all_showings.append(
                        {
                            "cinema_name": CINEMA_NAME,
                            "movie_title": clean_title,
                            "date_text": date_str,
                            "showtime": showtime,
                            "director": details.get("director"),
                            "year": details.get("year"),
                            "country": details.get("country"),
                            "runtime_min": str(runtime_min)
                            if runtime_min is not None
                            else None,
                            "synopsis": details.get("synopsis"),
                            "detail_page_url": detail_page_url,
                        }
                    )

    # Deduplicate by (date, title, time) and sort.
    unique_showings = list(
        {
            (s["date_text"], s["movie_title"], s["showtime"]): s
            for s in all_showings
        }.values()
    )
    unique_showings.sort(key=lambda x: (x.get("date_text", ""), x.get("showtime", "")))

    print(f"INFO: Collected {len(unique_showings)} unique showings for {CINEMA_NAME}.")
    return unique_showings


if __name__ == "__main__":
    # Ensure UTF-8 output on Windows when testing locally.
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    showings = scrape_theatre_shinjuku(max_days=7)

    if showings:
        output_filename = "theatre_shinjuku_showtimes_final.json"
        print(f"\nINFO: Writing {len(showings)} records to {output_filename}...")
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(showings, f, ensure_ascii=False, indent=2)
        print(f"INFO: Successfully created {output_filename}.")

        print("\n--- Sample of First Showing ---")
        from pprint import pprint

        pprint(showings[0])
    else:
        print(f"\nNo showings found for {CINEMA_NAME}.")
