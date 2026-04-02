#!/usr/bin/env python3
# eurospace_module.py — Rev-12 (2025-11-23)
#
#  • IMPROVED: Year extraction now falls back to searching the full text
#    if not found in the slash-delimited line.
#  • ADDED: Extraction of "Original Title" (原題) for movie_title_en.
#  • REFINED: Director parsing handles more variations.
# ---------------------------------------------------------------------

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import bs4
import requests

BASE_URL = "http://www.eurospace.co.jp"
SCHEDULE_URL = f"{BASE_URL}/schedule/"
OUTPUT = Path(__file__).with_name("eurospace_showtimes.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (EurospaceScraper/2025)"}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 7

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_SUB_TITLE_RE = re.compile(r"『(.+?)』")
_RUNTIME_RE = re.compile(r"(\d+)\s*分")
# Robust year regex: 1900-2099, standalone
_YEAR_RE = re.compile(r'\b(19\d{2}|20\d{2})\b')


def _clean(text: str) -> str:
    """Collapse whitespace, trim, and normalize characters."""
    if not text:
        return ""
    normalized_text = unicodedata.normalize("NFKC", text).strip()
    return re.sub(r"\s+", " ", normalized_text)


def _parse_date(h3_tag: bs4.Tag) -> dt.date | None:
    m = DATE_RE.search(h3_tag.get_text())
    if not m:
        return None
    y, mth, d = map(int, m.groups())
    # Validate month/day are in reasonable ranges
    if not (1 <= mth <= 12) or not (1 <= d <= 31):
        print(f"[Eurospace] Invalid date components: year={y}, month={mth}, day={d}", file=sys.stderr)
        return None
    try:
        return dt.date(y, mth, d)
    except ValueError as e:
        print(f"[Eurospace] Date construction failed: {y}-{mth}-{d}: {e}", file=sys.stderr)
        return None


def _scrape_detail(url: str) -> Dict[str, str | int | None]:
    """
    Pull director, runtime, country, year, and clean English/Original titles.
    """
    defaults = {
        "director": None, 
        "runtime": None, 
        "country": None, 
        "year": None,
        "movie_title_en": None
    }
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
    except Exception:
        return defaults

    soup = bs4.BeautifulSoup(resp.text, "html.parser")
    caption_p = soup.select_one("p.work-caption")
    if not caption_p:
        return defaults

    full_text = caption_p.get_text(separator="\n")
    lines = [line.strip() for line in full_text.split("\n") if line.strip()]

    meta = defaults.copy()
    
    # 1. Parse Director
    for line in lines:
        if "監督" in line and ("：" in line or ":" in line):
            parts = re.split(r'[:：]', line, 1)
            if len(parts) > 1:
                d_text = parts[1]
                # Stop at slash or parentheses
                d_text = d_text.split("/")[0].split("（")[0].split("(")[0]
                meta["director"] = _clean(d_text)
            break
            
    # 2. Parse English/Original Title (Prioritize English)
    # We loop twice: first to find explicit English Title (英題), then fallback to Original (原題)
    for target_label in ["英題", "原題"]:
        if meta["movie_title_en"]: break # Stop if we found a better one already
        
        for line in lines:
            if target_label in line and ("：" in line or ":" in line):
                # Split specifically on the label (e.g. split on "英題：")
                # This fixes lines like "原題: AAA / 英題: BBB"
                parts = re.split(f'{target_label}[:：]', line, 1)
                
                if len(parts) > 1:
                    raw_title = parts[1]
                    # Cut at the next delimiter (slash, parens, or next label like 字幕)
                    # We accept " " (space) as part of the title, but cut at " / "
                    clean_title = re.split(r'[/／(（<＜]|字幕|配給|原題|英題', raw_title)[0]
                    
                    cleaned = _clean(clean_title)
                    if cleaned:
                        meta["movie_title_en"] = cleaned
                        break

    # 3. Parse Metadata Line (Slash delimited)
    for line in lines:
        if "／" in line:
            parts = [p.strip() for p in line.split("／")]
            countries = []
            for part in parts:
                runtime_match = _RUNTIME_RE.search(part)
                year_match = _YEAR_RE.search(part)

                if runtime_match and not meta["runtime"]:
                    meta["runtime"] = int(runtime_match.group(1))
                elif year_match and not meta["year"]:
                    meta["year"] = year_match.group(0)
                else:
                    # Country heuristic
                    noise_keywords = ["日本語", "カラー", "モノクロ", "DCP", "分", "年", "サイズ", "ヴィンテージ", "提供", "配給", "原題", "英題", "字幕", "ステレオ"]
                    if not any(noise in part for noise in noise_keywords):
                        cleaned_part = _clean(part)
                        if cleaned_part and len(cleaned_part) < 15: # Countries are usually short
                             countries.append(cleaned_part)
            
            if countries and not meta["country"]:
                meta["country"] = ", ".join(countries)
    
    # 4. Fallback Year
    if not meta["year"]:
        fallback_match = _YEAR_RE.search(full_text)
        if fallback_match:
            meta["year"] = fallback_match.group(0)

    return meta


# ---------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------

def scrape() -> List[Dict[str, str | int | None]]:
    try:
        resp = requests.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
    except Exception as e:
        sys.exit(f"Failed to GET schedule page: {e}")

    soup = bs4.BeautifulSoup(resp.text, "html.parser")
    schedule_sec = soup.find("section", id="schedule")
    if not schedule_sec:
        sys.exit("Schedule section not found in HTML")

    shows: List[Dict[str, str | int | None]] = []
    meta_cache: Dict[str, Dict[str, str | int | None]] = {}

    for art in schedule_sec.find_all("article"):
        h3 = art.find("h3")
        if not h3: continue
        d = _parse_date(h3)
        if not d or not (TODAY <= d < TODAY + dt.timedelta(days=WINDOW_DAYS)):
            continue

        for table in art.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2: continue
            
            times_row, titles_row = rows[0], rows[1]
            times = [_clean(td.get_text()) for td in times_row.find_all("td")]
            cells = titles_row.find_all("td")
            
            for idx, cell in enumerate(cells):
                a_tag = cell.find("a")
                if not a_tag: continue

                cell_text = cell.get_text(separator=" ")
                sub_title_match = _SUB_TITLE_RE.search(cell_text)

                title = _clean(sub_title_match.group(1)) if sub_title_match else _clean(a_tag.get_text())
                
                url = urljoin(BASE_URL, a_tag.get("href", ""))
                time_str = times[idx] if idx < len(times) else ""
                if not title or not url or not time_str: continue

                if url not in meta_cache:
                    meta_cache[url] = _scrape_detail(url)

                shows.append({
                    "cinema": "ユーロスペース",
                    "title": title,
                    "date": d.isoformat(),
                    "time": time_str,
                    "url": url,
                    **meta_cache[url],
                })

    seen = set()
    uniq_shows = []
    for s in shows:
        key = (s["title"], s["date"], s["time"])
        if key not in seen:
            seen.add(key)
            uniq_shows.append(s)

    return sorted(uniq_shows, key=lambda x: (x.get("date", ""), x.get("time", ""), x.get("title", "")))


# ---------------------------------------------------------------------
# CLI entry‑point
# ---------------------------------------------------------------------

if __name__ == "__main__":
    data = scrape()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"Wrote {len(data)} showtime records → {OUTPUT}")