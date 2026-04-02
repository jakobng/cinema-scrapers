from __future__ import annotations

"""Laputa Asagaya programme scraper – **rev-N 2026-01-01**
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
✅ Use html5lib parser to handle malformed HTML on Laputa website
   (their HTML has broken tags like '</font<' missing closing '>').
✅ Added bounds checking for colspan/rowspan to prevent overflow errors.
✅ Main grid parser checks all cells in a row for headers.
"""

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urldefrag

import requests
from bs4 import BeautifulSoup, Tag

# ──────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────
CINEMA_NAME    = "ラピュタ阿佐ヶ谷"
SCHEDULE_URL   = "https://www.laputa-jp.com/laputa/main/index.html"
BASE_URL       = "https://www.laputa-jp.com/"
LOOKAHEAD_DAYS = 7

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}
TIMEOUT = 20
JUNK_KEYWORDS = ["スケジュール", "会場", "特集", "休映"]

_soup_cache: Dict[str, BeautifulSoup] = {}

# ──────────────────────────────────────────────────────────
# Generic Helpers
# ──────────────────────────────────────────────────────────

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    base_url = urldefrag(url).url
    if base_url in _soup_cache:
        return _soup_cache[base_url]
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html5lib")
        _soup_cache[base_url] = soup
        return soup
    except requests.RequestException as exc:
        print(f"ERROR fetching {base_url}: {exc}", file=sys.stderr)
        return None

def _is_junk(text: str) -> bool:
    if not text or len(text) < 2:
        return True
    if any(keyword in text for keyword in JUNK_KEYWORDS):
        return True
    if text.startswith("＜") or text.endswith("＞"):
        return True
    return False

def _clean_text(text: str) -> str:
    return text.strip().replace(' ', '').replace('　', '').strip("、・") if text else ""

def _parse_time(raw: str) -> str:
    match = re.search(r"(\d{1,2}):(\d{2})", raw)
    if not match: return ""
    h, m = map(int, match.groups())
    if ("午後" in raw or "pm" in raw.lower()) and h != 12: h += 12
    if ("午前" in raw or "am" in raw.lower()) and h == 12: h = 0
    return f"{h:02d}:{m:02d}"

_date_pat = re.compile(r"(\d{1,2})")
def _expand_date_range(text: str, month: int, year: int) -> List[dt.date]:
    nums = list(map(int, _date_pat.findall(text)))
    if not nums: return []
    dates = []
    if ("～" in text or "・" in text or "〜" in text) and len(nums) >= 2:
        start_day, end_day = nums[0], nums[-1]
        try:
            start_date = dt.date(year, month, start_day)
            end_date = dt.date(year, month, end_day)
            if end_date < start_date:
                 end_date = dt.date(year, month + 1, end_day) if month < 12 else dt.date(year + 1, 1, end_day)
        except ValueError: return []
        current_date = start_date
        while current_date <= end_date:
            dates.append(current_date)
            current_date += dt.timedelta(days=1)
    else:
        for day in nums:
            try: dates.append(dt.date(year, month, day))
            except ValueError: continue
    return dates

def _iter_rowspan(table: Tag):
    rowspans: List[int] = [0] * 64
    for tr in table.find_all("tr"):
        cells_info: List[Tuple[Tag, int, int, int]] = []
        col = 0
        for td in tr.find_all(["td", "th"], recursive=False):
            while col < len(rowspans) and rowspans[col] > 0: col += 1
            colspan_match = re.search(r'\d+', str(td.get("colspan", "1")))
            colspan = int(colspan_match.group(0)) if colspan_match else 1
            rowspan_match = re.search(r'\d+', str(td.get("rowspan", "1")))
            rowspan = int(rowspan_match.group(0)) if rowspan_match else 1
            # Clamp to reasonable bounds to prevent integer overflow errors
            colspan = max(1, min(colspan, 100))
            rowspan = max(1, min(rowspan, 100))
            cells_info.append((td, col, colspan, rowspan))
            for c in range(col, col + colspan): rowspans[c] = rowspan
            col += colspan
        rowspans = [max(0, x - 1) for x in rowspans]
        yield tr, cells_info

# --- Schedule Table Helpers ---

def _find_main_schedule_table(soup: BeautifulSoup) -> Optional[Tag]:
    anchor = soup.find("a", attrs={"name": "2"})
    if anchor:
        table = anchor.find_next("table", class_="px12")
        if table:
            return table

    for table in soup.find_all("table"):
        if table.find("a", href=re.compile("sc\\.html")) or table.find("a", href=re.compile(r"sakuhin.*\\.html")):
            return table

    return soup.find("table", class_="px12")


def _find_header_row(table: Tag) -> Optional[Tag]:
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        date_like = sum(1 for c in cells if re.search(r"\d{1,2}(?:[\\/／]\d{1,2})?", c.get_text()))
        if date_like >= 3:
            return tr
    return table.find("tr")

def _extract_page_title(soup: BeautifulSoup) -> str:
    for selector in ("h1", "h2.title", "h2", "h3.title"):
        node = soup.select_one(selector)
        if node:
            title_text = _clean_text(node.get_text(strip=True))
            if title_text:
                return title_text
    title_tag = soup.find("title")
    if title_tag:
        title_text = _clean_text(title_tag.get_text(strip=True))
        if title_text:
            return title_text
    return ""

def _find_date_time_table(soup: BeautifulSoup) -> Optional[Tag]:
    best_table = None
    best_score = 0
    for table in soup.find_all("table"):
        score = 0
        for tr in table.find_all("tr"):
            text = tr.get_text(" ", strip=True)
            if re.search(r"\d{1,2}[\\/／]\d{1,2}", text) or re.search(r"\d{1,2}月\d{1,2}日", text):
                score += 1
            if re.search(r"\d{1,2}:\d{2}", text):
                score += 1
        if score > best_score:
            best_score = score
            best_table = table
    return best_table

def _parse_simple_schedule_table(table: Tag, today: dt.date, page_title: str, source_url: str = "") -> List[Dict]:
    shows: List[Dict] = []
    current_year = today.year
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        row_text = tr.get_text(" ", strip=True)
        if not re.search(r"\d{1,2}[\\/／]\d{1,2}", row_text) and not re.search(r"\d{1,2}月\d{1,2}日", row_text):
            continue

        date_text = cells[0].get_text(" ", strip=True)
        date_match = re.search(r"(\d{1,2})[\\/／](\d{1,2})", date_text)
        if date_match:
            month, day = map(int, date_match.groups())
            year = current_year
            if month < today.month and (today.month - month) > 6:
                year += 1
            elif month > today.month and (month - today.month) > 6:
                year -= 1
            try:
                show_date = dt.date(year, month, day)
            except ValueError:
                continue
        else:
            date_match = re.search(r"(\d{1,2})月(\d{1,2})日", date_text)
            if not date_match:
                continue
            month, day = map(int, date_match.groups())
            show_date = dt.date(current_year, month, day)

        times = re.findall(r"\d{1,2}:\d{2}", row_text)
        if not times:
            continue

        title_text = ""
        if len(cells) >= 2:
            title_text = _clean_text(cells[1].get_text(" ", strip=True))
        title_text = re.sub(r"\d{1,2}:\d{2}", "", title_text).strip()
        title_text = title_text or page_title or "ラピュタ阿佐ヶ谷"

        for time_str in times:
            shows.append({
                "movie_title": title_text,
                "date_text": show_date.isoformat(),
                "showtime": time_str,
                "director": "",
                "year": "",
                "country": None,
                "runtime_min": None,
                "synopsis": None,
                "detail_page_url": source_url,
            })
    return shows

# ──────────────────────────────────────────────────────────
# Stage 3: Scrape sakuhin.html for Rich Metadata
# ──────────────────────────────────────────────────────────
def _fetch_rich_metadata(url: str) -> Dict:
    soup = _fetch_soup(url)
    if not soup: return {}
    fragment = urldefrag(url).fragment
    if not fragment: return {}

    anchor_tag = soup.find("a", attrs={"name": fragment})
    if not anchor_tag: return {}
    
    work_div = anchor_tag.find_next("div", class_="works")
    if not work_div: return {}

    metadata = {}
    title_tag = work_div.find("h3", class_="title")
    metadata["movie_title"] = _clean_text(title_tag.get_text(strip=True)) if title_tag else ""

    data_p = work_div.find("p", class_="data")
    if data_p:
        raw_data = data_p.get_text(" ", strip=True)
        year_m = re.search(r"(\d{4})年", raw_data)
        runtime_m = re.search(r"(\d+)分", raw_data)
        metadata["year"] = year_m.group(1) if year_m else ""
        metadata["runtime_min"] = int(runtime_m.group(1)) if runtime_m else None
    
    staff_p = work_div.find("p", class_="staff")
    if staff_p:
        raw_staff = staff_p.get_text(" ", strip=True)
        director_m = re.search(r"監督：([^／\s]+)", raw_staff)
        if director_m:
            metadata["director"] = _clean_text(director_m.group(1))
        else:
            script_m = re.search(r"脚本：([^／\s]+)", raw_staff)
            metadata["director"] = _clean_text(script_m.group(1)) if script_m else ""
    return metadata

# ──────────────────────────────────────────────────────────
# Stage 2: Scrape sc.html for Schedules and Links to Stage 3
# ──────────────────────────────────────────────────────────
def _scrape_program_schedule_page(url: str, today: dt.date) -> List[Dict]:
    soup = _fetch_soup(url)
    if not soup: return []

    shows = []
    page_title = _extract_page_title(soup)
    
    # Try to find the specific table for Laputa Asagaya
    # Sometimes header text varies, so fallback to finding the first sc_table if URL implies Laputa
    schedule_table = None
    laputa_header = soup.find(lambda tag: "ラピュタ阿佐ヶ谷" in tag.get_text() and "h2subText" in tag.get("class", []))
    
    if laputa_header:
        schedule_table = laputa_header.find_next("table", class_="sc_table")
    
    if not schedule_table:
        # Fallback: Just take the first sc_table
        schedule_table = soup.find("table", class_="sc_table")
        
    if not schedule_table:
        fallback_table = _find_date_time_table(soup)
        if not fallback_table:
            return []
        return _parse_simple_schedule_table(fallback_table, today, page_title, url)

    current_month, current_year = today.month, today.year
    month_initialized = False
    for tr, cells in _iter_rowspan(schedule_table):
        if not cells: continue

        if "item2" in cells[0][0].get("class", []):
            month_m = _date_pat.search(cells[0][0].get_text())
            if month_m:
                new_month = int(month_m.group(1))
                if not month_initialized:
                    month_initialized = True
                    if new_month > today.month + 1:
                        current_year = today.year - 1
                    else:
                        current_year = today.year
                elif new_month < current_month:
                    current_year += 1
                elif new_month > current_month and (new_month - current_month) > 10:
                    current_year -= 1
                current_month = new_month
            cells.pop(0)

        if not cells or "item1" not in cells[0][0].get("class", []): continue
        date_text = cells[0][0].get_text(" ", strip=True)
        dates = _expand_date_range(date_text, current_month, current_year)
        
        for cell_info in cells[1:]:
            td = cell_info[0]
            if not td.get_text(strip=True): continue
            
            time_raw, *_ = td.get_text("\n", strip=True).split("\n")
            showtime = _parse_time(time_raw)
            
            link_tag = td.find("a", href=re.compile(r"sakuhin\d+\.html"))
            
            movie_data = {}
            detail_url = ""
            
            if link_tag:
                detail_url = urljoin(url, link_tag['href'])
                movie_data = _fetch_rich_metadata(detail_url)
            
            # Fallback if no link or metadata failed
            if not movie_data or not movie_data.get("movie_title"):
                # Parse text: "12:50-14:28 Title (98min)"
                text = td.get_text(strip=True)
                # Remove time range pattern: 12:50-14:28 or 12:50 (handling hyphens and tildes)
                clean_text = re.sub(r'\d{1,2}:\d{2}(?:[ \-〜～]\d{1,2}:\d{2})?', '', text)
                # Remove runtime pattern: (99分 or (99分)
                clean_text = re.sub(r'[(（]\d+分[)）]?', '', clean_text)
                
                title = _clean_text(clean_text)
                if not title: continue
                
                movie_data = {"movie_title": title}
                
                # Try to extract runtime from original text
                rt_match = re.search(r'[(（](\d+)分[)）]?', text)
                if rt_match:
                    movie_data["runtime_min"] = int(rt_match.group(1))

            if not movie_data.get("movie_title"): continue

            for d in dates:
                shows.append({
                    "movie_title": movie_data.get("movie_title"), "date_text": d.isoformat(),
                    "showtime": showtime, "director": movie_data.get("director", ""),
                    "year": movie_data.get("year", ""), "country": None,
                    "runtime_min": movie_data.get("runtime_min"), "synopsis": None,
                    "detail_page_url": detail_url,
                })
    if shows:
        return shows

    fallback_table = _find_date_time_table(soup)
    if fallback_table:
        return _parse_simple_schedule_table(fallback_table, today, page_title, url)
    return shows

# ──────────────────────────────────────────────────────────
# Stage 1: Scrape Main Grid for Direct Listings & Program Links
# ──────────────────────────────────────────────────────────
def scrape_laputa_asagaya() -> List[Dict]:
    main_soup = _fetch_soup(SCHEDULE_URL)
    if not main_soup: return []

    all_shows = []
    program_urls_to_visit = set()
    today = dt.date.today()
    
    table = _find_main_schedule_table(main_soup)
    if not table: return []

    header_tr = _find_header_row(table)
    if not header_tr: return []
    header_cells = header_tr.find_all(["td", "th"])
    if not header_cells: return []
    iso_dates: List[Optional[dt.date]] = []
    year, month, last_day = today.year, 0, 0
    for cell in header_cells:
        t = cell.get_text(strip=True)
        md_match = re.search(r"(\d{1,2})\s*[\\/／]\s*(\d{1,2})", t)
        if md_match:
            month, day = map(int, md_match.groups())
        else:
            day_match = re.search(r"(\d{1,2})", t)
            if not day_match:
                iso_dates.append(None); continue
            day = int(day_match.group(1))
            if month == 0:
                month = today.month
            if 0 < day < last_day:
                month += 1
                if month == 13:
                    month, year = 1, year + 1
        try:
            iso_dates.append(dt.date(year, month, day)); last_day = day
        except ValueError: iso_dates.append(None)

    active_showtime = ""
    for tr, cells in _iter_rowspan(table):
        is_movie_row = True
        
        # FIX: Check all cells in a row for a header, not just the first one.
        for cell, _, _, _ in cells:
            header_font = cell.find("font", color="#FFFFFF")
            if cell.get("colspan") and header_font:
                is_movie_row = False  # This row contains a header, so don't process for movies
                header_text = header_font.get_text(strip=True)
                
                # Reset time for new section (prevents stale time bleeding into program sections)
                active_showtime = ""
                
                parsed_time = _parse_time(header_text)
                if parsed_time:
                    active_showtime = parsed_time # Update showtime
        
        if is_movie_row:
            for cell, col_start, colspan, _ in cells:
                # 1. Check for Program Page Link
                link_sc = cell.find("a", href=re.compile("sc.html"))
                if link_sc:
                    program_urls_to_visit.add(urljoin(BASE_URL, link_sc["href"]))
                    continue

                raw_cell_text = cell.get_text(strip=True)
                if _is_junk(raw_cell_text): continue
                
                # 2. Check for Direct Movie Detail Link (sakuhinXX.html)
                link_sakuhin = cell.find("a", href=re.compile(r"sakuhin.*\.html"))
                detail_url = ""
                meta = {}
                if link_sakuhin:
                    detail_url = urljoin(BASE_URL, link_sakuhin["href"])
                    meta = _fetch_rich_metadata(detail_url)

                # 3. Extract Info
                title_p = cell.find("p")
                # If we have a detail link, we trust the metadata title. 
                # If no detail link, we require a <p> tag for the title to avoid junk.
                if not title_p and not meta.get("movie_title"): continue

                text_title = _clean_text(title_p.get_text(strip=True)) if title_p else ""
                title = meta.get("movie_title") or text_title
                
                if _is_junk(title): continue
                
                director = meta.get("director")
                if not director:
                    # Regex on plain text is safer and handles variants like "監督:" or "監督："
                    dm = re.search(r"監督[:：]([^<\n\r]+)", cell.get_text())
                    if dm: director = _clean_text(dm.group(1))
                
                year = meta.get("year")
                if not year:
                    ym = re.search(r"(\d{4})年", cell.get_text())
                    if ym: year = ym.group(1)
                
                runtime = meta.get("runtime_min")
                
                for i in range(colspan):
                    idx = col_start + i
                    if idx < len(iso_dates) and iso_dates[idx]:
                        all_shows.append({
                            "movie_title": title, "date_text": iso_dates[idx].isoformat(), 
                            "showtime": active_showtime,
                            "director": director or "",
                            "year": year or "", "country": None, 
                            "runtime_min": runtime, "synopsis": None, "detail_page_url": detail_url,
                        })
    
    for url in program_urls_to_visit:
        print(f"INFO: Scraping program page: {url}")
        all_shows.extend(_scrape_program_schedule_page(url, today))
        
    limit = today + dt.timedelta(days=LOOKAHEAD_DAYS)
    
    # Bucket by (Date, Title) to handle deduplication and merging
    grouped = {}
    for show in all_shows:
        if not show.get("date_text") or not show.get("movie_title"): continue
        try:
            show_date = dt.date.fromisoformat(show["date_text"])
        except ValueError: continue
        
        if not (today <= show_date <= limit): continue
        
        key = (show["date_text"], show["movie_title"])
        grouped.setdefault(key, []).append(show)
    
    final_shows = []
    for key, group in grouped.items():
        # Separately identify entries with specific times vs empty times
        specific_time_shows = [s for s in group if s.get("showtime")]
        empty_time_shows = [s for s in group if not s.get("showtime")]
        
        # If we have specific times, use them (they likely came from sc.html or Time Header)
        # We ignore empty_time_shows as they are likely duplicates from the grid without time headers
        target_shows = specific_time_shows if specific_time_shows else empty_time_shows
        
        # Deduplicate within target_shows (e.g. strict duplicates)
        seen_times = set()
        for s in target_shows:
            # If falling back to empty time, set a friendly message
            if not s.get("showtime"):
                s["showtime"] = "スケジュール確認"
            
            # Simple dedupe by showtime
            if s["showtime"] in seen_times: continue
            seen_times.add(s["showtime"])
            
            s["cinema_name"] = CINEMA_NAME
            final_shows.append(s)

    final_shows.sort(key=lambda x: (x.get("date_text", ""), x.get("showtime", ""), x.get("movie_title", "")))
    print(f"Wrote {len(final_shows)} unique showings → laputa_asagaya_showtimes.json")
    return final_shows

# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception: pass

    data = scrape_laputa_asagaya()
    if not data:
        sys.exit("No showings found :(")
    
    with open("laputa_asagaya_showtimes.json", "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
