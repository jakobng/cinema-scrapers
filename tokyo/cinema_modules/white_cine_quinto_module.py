from __future__ import annotations
import datetime as _dt
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple
import requests
from bs4 import BeautifulSoup

CINEMA_NAME   = "ホワイト シネクイント"
SCHEDULE_URL  = "https://www.cinequinto-ticket.jp/cq02/theater/white/schedule"
LISTING_URL   = "https://www.cinequinto.com/white/movie/"
HEADERS       = {"User-Agent": "CineQuintoScraper/1.0"}

_RE_DATE_ID   = re.compile(r"^dateJouei(\d{8})$")
_RE_FW_NUM    = str.maketrans({chr(fw): str(d) for d, fw in enumerate(range(0xFF10, 0xFF1A))})
_RE_RUNTIME   = re.compile(r"(\d+)\s*分")
_RE_YEAR      = re.compile(r"(\d{4})年")
_RE_HTML_TAGS = re.compile(r"<[^>]+>")

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_RE_FW_NUM)
    return re.sub(r"\s+", "", s).lower()

def _get(session: requests.Session, url: str) -> str:
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text

def _parse_schedule(html: str, today: _dt.date, max_days: int = 7) -> Tuple[List[Dict], List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict] = []
    titles: List[str] = []
    for div in soup.select('div[id^="dateJouei"]'):
        m = _RE_DATE_ID.match(div.get("id", ""))
        if not m: continue
        date_obj = _dt.datetime.strptime(m.group(1), "%Y%m%d").date()
        if date_obj < today or (date_obj - today).days > max_days: continue
        iso_date = date_obj.isoformat()
        for panel in div.select("div.panel.movie-panel"):
            jp_title_el = panel.select_one(".title-jp")
            if not jp_title_el: continue
            jp_title = jp_title_el.get_text(strip=True)
            if "上映スケジュール" in jp_title: continue
            titles.append(jp_title)
            en_title_el = panel.select_one(".title-eng")
            en_title = (en_title_el.get_text(strip=True) or None) if en_title_el else None
            runtime_el = panel.select_one(".total-time")
            runtime_min = None
            if runtime_el:
                rt_match = _RE_RUNTIME.search(runtime_el.get_text())
                if rt_match: runtime_min = rt_match.group(1)
            for ms in panel.select(".movie-schedule"):
                start_raw = ms.get("data-start") or ""
                if start_raw.isdigit():
                    start_raw = start_raw.zfill(4)
                    showtime = f"{start_raw[:2]}:{start_raw[2:]}"
                else:
                    b = ms.select_one(".movie-schedule-begin")
                    showtime = b.get_text(strip=True) if b else None
                if not showtime: continue
                screen_el = ms.select_one(".screen-name")
                screen = screen_el.get_text(strip=True) if screen_el else None
                out.append(dict(cinema_name=CINEMA_NAME, movie_title=jp_title, date_text=iso_date, showtime=showtime, director=None, year=None, country=None, runtime_min=runtime_min, synopsis=None, detail_page_url=None, movie_title_en=en_title, screen_name=screen, purchase_url=None))
    return out, titles

def _map_titles(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    mapping: Dict[str, str] = {}
    for li in soup.select("ul.cmn-list01 li.item"):
        a = li.find("a")
        if not a: continue
        title_el = a.select_one(".txt01")
        if not title_el: continue
        title = title_el.get_text(strip=True)
        if "上映スケジュール" in title: continue
        url = a["href"]
        if url.startswith("/"): url = "https://www.cinequinto.com" + url
        mapping[_norm(title)] = url
    return mapping

def _scrape_detail(session: requests.Session, url: str) -> Dict[str, str]:
    try:
        html = _get(session, url)
        soup = BeautifulSoup(html, "html.parser")
    except Exception: return {}
    article = soup.select_one("article.article")
    synopsis = None
    if article:
        raw = article.decode()
        raw = re.sub(r"<br\s*/?>", "\n", raw)
        synopsis = _RE_HTML_TAGS.sub("", raw).strip()
    director = year = country = runtime_min = None
    for tr in soup.select(".cmn-tbl01 table tr"):
        th = tr.find("th")
        td = tr.find("td")
        if not th or not td: continue
        key = th.get_text(strip=True)
        val = td.get_text(" ", strip=True)
        if "監督" in key: director = val
        elif "作品データ" in key:
            y = _RE_YEAR.search(val)
            if y: year = y.group(1)
            rt = _RE_RUNTIME.search(val)
            if rt: runtime_min = rt.group(1)
            parts = [p.strip() for p in val.split("／") if p.strip()]
            for p in parts:
                if p != year and "分" not in p and not p.startswith("PG"):
                    country = p
                    break
        elif "上映時間" in key:
            rt = _RE_RUNTIME.search(val)
            if rt: runtime_min = rt.group(1)
    return dict(director=director, year=year, country=country, runtime_min=runtime_min, synopsis=synopsis)

def scrape_white_cine_quinto(max_days: int = 7) -> List[Dict]:
    today = _dt.date.today()
    with requests.Session() as s:
        sched_html = _get(s, SCHEDULE_URL)
        schedule, titles = _parse_schedule(sched_html, today, max_days)
        mapping = _map_titles(_get(s, LISTING_URL))
        cache: Dict[str, Dict] = {}
        for jp in set(titles):
            norm = _norm(jp)
            if norm in mapping and norm not in cache: cache[norm] = _scrape_detail(s, mapping[norm])
        for row in schedule:
            norm = _norm(row["movie_title"])
            if norm in cache:
                row.update(cache[norm])
                row["detail_page_url"] = mapping[norm]
    return schedule

if __name__ == "__main__":
    print(f"Running {CINEMA_NAME} scraper …")
    rows = scrape_white_cine_quinto()
    print(f"Collected {len(rows)} rows.")
    for r in rows[:2]: print(json.dumps(r, ensure_ascii=False, indent=2))
