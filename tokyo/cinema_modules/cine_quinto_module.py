"""
cine_quinto_module.py — 2025-06-23
Upgrades:
• Parses the JS-rendered schedule HTML (slider + panels) without a browser.
• Cross-links titles to the NOW SHOWING catalogue to fetch detail pages.
• Extracts director, year, country, runtime, synopsis, + optional English title.
• Outputs a list-of-dicts that matches our project’s standard schema.

Tested against:  
  – https://www.cinequinto-ticket.jp/theater/shibuya/schedule  
  – https://www.cinequinto.com/shibuya/movie/ + detail pages
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from bs4 import BeautifulSoup

# ───────────────────────── constants
CINEMA_NAME   = "シネクイント"
SCHEDULE_URL  = "https://www.cinequinto-ticket.jp/theater/shibuya/schedule"
LISTING_URL   = "https://www.cinequinto.com/shibuya/movie/"
HEADERS       = {"User-Agent": "CineQuintoScraper/1.0 (+https://github.com/your-org/project)"}

_RE_DATE_ID   = re.compile(r"^dateJouei(\d{8})$")
_RE_FW_NUM    = str.maketrans({chr(fw): str(d) for d, fw in enumerate(range(0xFF10, 0xFF1A))})
_RE_RUNTIME   = re.compile(r"(\d+)\s*分")
_RE_YEAR      = re.compile(r"(\d{4})年")
_RE_HTML_TAGS = re.compile(r"<[^>]+>")

# ───────────────────────── helpers
def _norm(s: str) -> str:
    """Aggressive normalisation so schedule titles match NOW SHOWING titles."""
    s = unicodedata.normalize("NFKC", s).translate(_RE_FW_NUM)
    return re.sub(r"\s+", "", s).lower()

def _get(session: requests.Session, url: str) -> str:
    return session.get(url, headers=HEADERS, timeout=30).text

# ───────────────────────── 1) schedule ─────────────────────────
def _parse_schedule(html: str,
                    today: _dt.date,
                    max_days: int = 7) -> Tuple[List[Dict], List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict] = []
    titles: List[str] = []

    for div in soup.select('div[id^="dateJouei"]'):
        m = _RE_DATE_ID.match(div.get("id", ""))
        if not m:
            continue
        date_obj = _dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        if date_obj < today or (date_obj - today).days > max_days:
            continue
        iso_date = date_obj.isoformat()

        for panel in div.select("div.panel.movie-panel"):
            jp_title = panel.select_one(".title-jp")
            if not jp_title:
                continue
            jp_title = jp_title.get_text(strip=True)
            titles.append(jp_title)

            en_title_el = panel.select_one(".title-eng")
            en_title = (en_title_el.get_text(strip=True) or None) if en_title_el else None

            runtime_el = panel.select_one(".total-time")
            runtime_min = None
            if runtime_el:
                rt_match = _RE_RUNTIME.search(runtime_el.get_text())
                if rt_match:
                    runtime_min = rt_match.group(1)

            # every individual show-time becomes its own record
            for ms in panel.select(".movie-schedule"):
                start_raw = ms.get("data-start") or ""
                if start_raw.isdigit():
                    start_raw = start_raw.zfill(4)
                    showtime = f"{start_raw[:2]}:{start_raw[2:]}"
                else:
                    b = ms.select_one(".movie-schedule-begin")
                    showtime = b.get_text(strip=True) if b else None
                if not showtime:
                    continue

                screen_el = ms.select_one(".screen-name")
                screen = screen_el.get_text(strip=True) if screen_el else None

                out.append(
                    dict(
                        cinema_name=CINEMA_NAME,
                        movie_title=jp_title,
                        date_text=iso_date,
                        showtime=showtime,
                        director=None,
                        year=None,
                        country=None,
                        runtime_min=runtime_min,
                        synopsis=None,
                        detail_page_url=None,
                        movie_title_en=en_title,
                        screen_name=screen,
                        purchase_url=None,
                    )
                )

    return out, titles

# ───────────────────────── 2) title → detail-URL map ───────────
def _map_titles(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    mapping: Dict[str, str] = {}
    for li in soup.select("ul.cmn-list01 li.item"):
        a = li.find("a")
        if not a:
            continue
        title_el = a.select_one(".txt01")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if "上映スケジュール" in title:  # skip the weekly schedule banner
            continue
        url = a["href"]
        if url.startswith("/"):
            url = "https://www.cinequinto.com" + url
        mapping[_norm(title)] = url
    return mapping

# ───────────────────────── 3) detail page scraper ──────────────
def _scrape_detail(session: requests.Session, url: str) -> Dict[str, str]:
    soup = BeautifulSoup(_get(session, url), "html.parser")

    # synopsis: the article text (strip tags, keep line-breaks)
    article = soup.select_one("article.article")
    synopsis = None
    if article:
        raw = article.decode()
        # replace <br> with newlines then strip the rest of the tags
        raw = re.sub(r"<br\s*/?>", "\n", raw)
        synopsis = _RE_HTML_TAGS.sub("", raw).strip()

    # credit table
    director = year = country = runtime_min = None
    for tr in soup.select(".cmn-tbl01 table tr"):
        th = tr.find("th")
        td = tr.find("td")
        if not th or not td:
            continue
        key = th.get_text(strip=True)
        val = td.get_text(" ", strip=True)
        if "監督" in key:
            director = val
        elif "作品データ" in key:
            y = _RE_YEAR.search(val)
            if y:
                year = y.group(1)
            rt = _RE_RUNTIME.search(val)
            if rt:
                runtime_min = rt.group(1)
            # attempt rudimentary country extraction (second chunk after '／')
            parts = [p.strip() for p in val.split("／") if p.strip()]
            for p in parts:
                if p != year and "分" not in p and not p.startswith("PG"):
                    country = p
                    break
        elif "上映時間" in key:
            rt = _RE_RUNTIME.search(val)
            if rt:
                runtime_min = rt.group(1)

    return dict(
        director=director or None,
        year=year or None,
        country=country or None,
        runtime_min=runtime_min or None,
        synopsis=synopsis or None,
    )

# ───────────────────────── main orchestrator ───────────────────
def scrape_cine_quinto(max_days: int = 7) -> List[Dict]:
    today = _dt.date.today()
    with requests.Session() as s:
        sched_html = _get(s, SCHEDULE_URL)
        schedule, titles = _parse_schedule(sched_html, today, max_days)

        mapping = _map_titles(_get(s, LISTING_URL))

        # fetch detail pages once per unique title
        cache: Dict[str, Dict] = {}
        for jp in titles:
            norm = _norm(jp)
            if norm in mapping and norm not in cache:
                cache[norm] = _scrape_detail(s, mapping[norm])

        # enrich rows
        for row in schedule:
            norm = _norm(row["movie_title"])
            if norm in cache:
                row.update(cache[norm])
                row["detail_page_url"] = mapping[norm]

    return schedule

# ───────────────────────── save helper (CLI convenience) ───────
def _save(data: List[Dict]):
    fp = Path(__file__).with_name("cine_quinto_showings.json")
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ Saved {len(data)} rows → {fp.name}\n")

# ───────────────────────── Run standalone ──────────────────────
if __name__ == "__main__":
    print("Running Cine Quinto scraper …")
    try:
        rows = scrape_cine_quinto()
    except Exception as e:
        print("ERROR:", e)
        raise
    print(f"Collected {len(rows)} rows; first 5 records:\n")
    for r in rows[:5]:
        print(r)
    _save(rows)
