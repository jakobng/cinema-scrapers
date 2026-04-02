#!/usr/bin/env python3
"""waseda_shochiku_scraper.py
=================================
Scraper for **早稲田松竹** (Waseda Shochiku) that mirrors the JSON‑file
behaviour of the other cinema modules in this repo.

It fetches the theatre's home page (http://www.wasedashochiku.co.jp/),
crawls the linked schedule detail pages, resolves show‑times for the
next *N* days (default = 21), and dumps everything to a JSON file on
disk so it’s easy to diff / debug.

Run it:
```
$python waseda_shochiku_scraper.py              # → waseda_shochiku_showings.json$ python waseda_shochiku_scraper.py -o ws.json   # custom output name
```

The output file is a **list of objects**; each record looks like this:
```json
{
  "cinema_name": "早稲田松竹",
  "movie_title": "君の名は。",            # Japanese title as shown in schedule
  "movie_title_en": "Your Name.",        # English title (may be blank)
  "date_text": "2025-07-04",            # ISO‑8601 calendar date
  "showtime": "18:40",                 # HH:MM (24‑hour clock)
  "director": "新海 誠",
  "year": "2016",
  "country": "日本",                    # if available
  "runtime_min": "106",
  "synopsis": "…",
  "detail_page_url": "http://…"
}
```

Dependencies: `requests`, `beautifulsoup4` and Python ≥3.8.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ───────────────────── constants ───────────────────────────────
CINEMA_NAME = "早稲田松竹"
BASE_URL = "http://www.wasedashochiku.co.jp/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}
TIMEOUT = 20
_YEAR_RE = re.compile(r"(\d{4})年")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_RUNTIME_RE = re.compile(r"(\d+)分")

# ─────────────────── film‑detail extraction ────────────────────

def _parse_film_details(detail_soup: BeautifulSoup, schedule_page_url: str) -> Dict[str, Dict]:
    """Return a mapping *Japanese title* → info‑dict from one schedule page."""
    film_details: Dict[str, Dict] = {}
    # Iterate through each film's info block on the single schedule page.
    for block in detail_soup.select("div.sakuhinjoho-box[id^='film']"):
        title_tag = block.select_one("h3.sakuhin-title")
        if not title_tag:
            continue

        # The URL for all films on this page is the schedule page's URL.
        actual_detail_url = schedule_page_url

        # Cleanly extract the Japanese title by removing any nested tags.
        title_tmp = BeautifulSoup(str(title_tag), "html.parser").h3
        if title_tmp.span:
            title_tmp.span.decompose()
        title_ja = title_tmp.get_text(" ", strip=True)

        # Extract the English title if it exists.
        title_en_tag = title_tag.select_one("span")
        title_en = title_en_tag.get_text(strip=True) if title_en_tag else ""

        details = {
            "director": "", "year": "", "country": "", "runtime_min": "", "synopsis": "",
        }

        # Parse the metadata from the description box.
        desc_box = block.select_one(".sakuhin-desc-box")
        if desc_box:
            text_content = desc_box.get_text("\n", strip=True)
            meta_line = text_content.split("\n")[0] if text_content else ""
            if "監督" in meta_line:
                details["director"] = meta_line.split("監督")[0].replace("■", "").strip()
            if year_match := _YEAR_RE.search(meta_line):
                details["year"] = year_match.group(1)
            if runtime_match := _RUNTIME_RE.search(meta_line):
                details["runtime_min"] = runtime_match.group(1)
            segs = meta_line.split("／")
            if len(segs) >= 3 and "年" in segs[1] and "分" not in segs[2]:
                 details["country"] = segs[2].strip()

        # Extract synopsis.
        synopsis_box = block.select_one(".sakuhin-text-box p.page-text2")
        if synopsis_box:
            details["synopsis"] = synopsis_box.get_text(" ", strip=True)

        # Store all collected details, keyed by the Japanese title.
        film_details[title_ja] = {
            "title_ja": title_ja,
            "title_en": title_en,
            "detail_page_url": actual_detail_url,
            **details,
        }
    return film_details

# ─────────────────────── schedule scraping ─────────────────────

def scrape_waseda_shochiku(max_days: int = 21) -> List[Dict[str, str]]:
    """Return a list of showing-records covering *max_days* ahead."""
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
    except requests.RequestException as e:
        print(f"ERROR: Could not fetch the main page at {BASE_URL}: {e}", file=sys.stderr)
        return []

    # Crawl schedule detail pages to build a cache of film metadata.
    details_cache: Dict[str, Dict] = {}
    detail_urls = {
        urljoin(BASE_URL, a["href"].split("#")[0])
        for a in soup.select(".top-sakuhin-area a[href*='archives/schedule/']")
    }

    for url in detail_urls:
        try:
            dresp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            dresp.raise_for_status()
            # The URL of the schedule page itself is passed to the parser.
            details_cache.update(_parse_film_details(BeautifulSoup(dresp.content, "html.parser"), url))
        except requests.RequestException as e:
            print(f"WARNING: Failed to scrape details from {url}: {e}", file=sys.stderr)

    today = _dt.date.today()
    window_end = today + _dt.timedelta(days=max_days)
    showings: List[Dict] = []

    # Iterate through the schedule tables on the main page.
    for tbl in soup.select("table.top-schedule-area"):
        header_txt = tbl.find("thead").get_text(" ", strip=True)
        # Extract date range from the table header.
        dates: List[_dt.date] = []
        md_pairs = re.findall(r"(\d{1,2})/(\d{1,2})", header_txt)
        if len(md_pairs) == 2:
            m1, d1 = map(int, md_pairs[0])
            m2, d2 = map(int, md_pairs[1])
            # Validate month/day are in reasonable ranges
            if not (1 <= m1 <= 12 and 1 <= d1 <= 31 and 1 <= m2 <= 12 and 1 <= d2 <= 31):
                continue
            year_start = today.year
            # Handle year boundary: if start month is before current month,
            # the schedule is likely for next year (e.g., in Dec showing Jan dates)
            if m1 < today.month and today.month >= 10:
                year_start += 1
            try:
                start_date = _dt.date(year_start, m1, d1)
                end_date = _dt.date(year_start if m2 >= m1 else year_start + 1, m2, d2)
            except ValueError:
                continue
            current_date = start_date
            while current_date <= end_date:
                dates.append(current_date)
                current_date += _dt.timedelta(days=1)

        # Process each film row within this table's date range.
        for row in tbl.select("tr.schedule-item"):
            title_header = row.find("th")
            if not title_header:
                continue
            title_tab = title_header.get_text(strip=True).replace("【ﾚｲﾄｼｮｰ】", "").strip()
            # Look up the film's details from the cache using its title.
            details = details_cache.get(title_tab)
            if not details: 
                print(f"WARNING: Title '{title_tab}' found in schedule table but not in detail blocks. Skipping.", file=sys.stderr)
                continue
            
            for td in row.select("td"):
                # --- [FINAL TWEAK] PROBLEM: End times (e.g., "～22:05") were parsed as start times.
                # --- SOLUTION: Split the cell text on '～' and only parse the first part.
                cell_text = td.get_text()
                start_time_text = cell_text.split("～")[0]
                
                for showtime in _TIME_RE.findall(start_time_text):
                    for date_obj in dates:
                        if today <= date_obj <= window_end:
                            showings.append({
                                "cinema_name": CINEMA_NAME,
                                "movie_title": details.get("title_ja", title_tab),
                                "movie_title_en": details.get("title_en", ""),
                                "date_text": date_obj.isoformat(),
                                "showtime": showtime,
                                "director": details.get("director", ""),
                                "year": details.get("year", ""),
                                "country": details.get("country", ""),
                                "runtime_min": details.get("runtime_min", ""),
                                "synopsis": details.get("synopsis", ""),
                                "detail_page_url": details.get("detail_page_url", ""),
                            })

    # Deduplicate records.
    unique_showings = { (r["date_text"], r["movie_title"], r["showtime"]): r for r in showings }
    return list(unique_showings.values())

# ─────────────────────────── CLI glue ──────────────────────────

def _cli(argv: List[str] | None = None) -> None:
    """Command-line interface for the scraper."""
    parser = argparse.ArgumentParser(description="Scrape Waseda Shochiku and write a JSON file.")
    parser.add_argument("--days", type=int, default=21, help="How many days ahead to include (default 21)")
    parser.add_argument("-o", "--outfile", default="waseda_shochiku_showings.json", help="Output JSON filename")
    parser.add_argument("--quiet", action="store_true", help="Suppress INFO logs (errors still show)")
    args = parser.parse_args(argv)

    if not args.quiet:
        print(f"INFO: Fetching {BASE_URL}…")
    data = scrape_waseda_shochiku(max_days=args.days)
    if not data:
        print("ERROR: No data was scraped. Exiting.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.outfile)
    if not args.quiet:
        print(f"INFO: Writing {len(data)} showing record(s) to {out_path}…")
    try:
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=4)
        if not args.quiet:
            print("INFO: Finished successfully.")
    except IOError as e:
        print(f"ERROR: Could not write to output file {out_path}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    _cli()
