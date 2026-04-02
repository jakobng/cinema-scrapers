from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

# --- Constants ---
CINEMA_NAME_SB = "新文芸坐"
SCHEDULE_PAGE_URL = "https://www.shin-bungeiza.com/schedule"

# Regex for parsing details from the <small> tag
# Now includes an optional director field
DETAILS_RE = re.compile(
    r"（(?P<year>\d{4})(?!/).*?/(?P<runtime>\d+)分.*?）"
    r"(?:監督：(?P<director>[^　\s]+))?"
)

# Regex to find a director listed for an entire program
PROGRAM_DIRECTOR_RE = re.compile(r"(?:監督|全作品監督)：(?P<director>[^　\s]+)")


def _clean_text(text: str) -> str:
    """Normalize whitespace and clean up text."""
    return " ".join(text.strip().split())


def _parse_film_details_from_program(content_div: BeautifulSoup) -> Dict[str, Dict]:
    """
    Parses the film details for a program, handling shared directors.
    """
    details_cache: Dict[str, Dict] = {}
    details_p = content_div.select_one("p.nihon-date")
    if not details_p:
        return details_cache

    # First, find a potential shared director for the whole program
    program_director = ""
    program_director_match = PROGRAM_DIRECTOR_RE.search(details_p.get_text())
    if program_director_match:
        program_director = program_director_match.group("director")

    # Go through each line item (separated by <br>) to get movie details
    for segment in details_p.decode_contents().split('<br>'):
        segment = segment.strip()
        if not segment:
            continue

        segment_soup = BeautifulSoup(segment, 'html.parser')
        
        # Clean the title by removing the details part
        raw_text = segment_soup.get_text(strip=True)
        title = _clean_text(raw_text.split('（')[0])
        
        if not title or "監督：" in title or "全作品監督" in title:
            continue

        small = segment_soup.find('small')
        if not small:
            details_cache[title] = {"director": program_director, "year": "", "country": "", "runtime_min": ""}
            continue
        
        match = DETAILS_RE.search(small.get_text())
        if not match:
            details_cache[title] = {"director": program_director, "year": "", "country": "", "runtime_min": ""}
            continue
        
        info = match.groupdict()
        
        # Prefer director listed on the line, otherwise use the program's shared director
        director = info.get("director") or program_director
        
        details_cache[title] = {
            "director": director,
            "year": info.get("year", ""),
            "country": info.get("country", ""),
            "runtime_min": info.get("runtime", ""),
        }
        
    return details_cache


def scrape_shin_bungeiza() -> List[Dict]:
    """
    Scrapes showtimes for Shin-Bungeiza for today and the next 7 days.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        # Fallback for Python < 3.9
        from backports.zoneinfo import ZoneInfo

    print(f"INFO: [{CINEMA_NAME_SB}] Fetching schedule page: {SCHEDULE_PAGE_URL}")
    try:
        response = requests.get(SCHEDULE_PAGE_URL, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME_SB}] Could not fetch page: {e}", file=sys.stderr)
        return []

    program_blocks = soup.select("div.schedule-box")
    print(f"INFO: [{CINEMA_NAME_SB}] Found {len(program_blocks)} film programs on the page.")

    all_showings: List[Dict] = []

    # Define the date range using Japan Standard Time (JST) for accuracy.
    try:
        jst_tz = ZoneInfo("Asia/Tokyo")
        today = _dt.datetime.now(jst_tz).date()
    except Exception:
        today = _dt.date.today()
    
    end_date = today + _dt.timedelta(days=7)
    print(f"INFO: [{CINEMA_NAME_SB}] Filtering for dates between {today} and {end_date} (JST).")

    for box in program_blocks:
        program_id = box.get('id', '')
        detail_url = f"{SCHEDULE_PAGE_URL}#{program_id}" if program_id else SCHEDULE_PAGE_URL
        content_div = box.find_next_sibling('div', class_='schedule-content')
        if not content_div:
            continue
        
        details_cache = _parse_film_details_from_program(content_div)
        
        last_month = None
        for date_header in content_div.select('h2'):
            date_raw = date_header.get_text(strip=True)
            
            month_day_match = re.search(r"(\d{1,2})/(\d{1,2})", date_raw)
            day_only_match = re.search(r"^(\d{1,2})", date_raw)

            if month_day_match:
                month, day = map(int, month_day_match.groups())
                last_month = month
            elif day_only_match and last_month:
                month = last_month
                day = int(day_only_match.group(1))
            else:
                continue

            try:
                year_candidates = [today.year, today.year + 1, today.year - 1]
                date_candidates = [_dt.date(y, month, day) for y in year_candidates if _dt.MINYEAR <= y <= _dt.MAXYEAR]
                show_date = min(date_candidates, key=lambda d: abs(d - today))
            except ValueError:
                continue

            if not (today <= show_date <= end_date):
                continue
            
            date_text = show_date.strftime("%Y-%m-%d")

            for sib in date_header.find_next_siblings():
                if sib.name == 'h2':
                    break
                if sib.name == 'div' and 'schedule-program' in sib.get('class', []):
                    title_p = sib.find('p')
                    if not title_p:
                        continue
                    
                    # Extract tags (e.g., "All-Night", "With Talk")
                    tags = [_clean_text(tag.get_text()) for tag in title_p.find_all('span')]
                    
                    # Clone the tag to get text without the spans
                    title_p_clone = BeautifulSoup(str(title_p), 'html.parser')
                    for s in title_p_clone.find_all('span'):
                        s.decompose()
                    title = _clean_text(title_p_clone.get_text())

                    info = details_cache.get(title, {})
                    
                    time_list_items = sib.select('ul li')
                    for li in time_list_items:
                        time_a = li.find('a')
                        if not time_a:
                            continue

                        showtime = _clean_text(time_a.get_text())
                        if not re.match(r"^\d{1,2}:\d{2}$", showtime):
                            continue
                        
                        booking_url = time_a.get('href', '')
                        
                        # Find end time if it exists in the next sibling
                        end_time = ""
                        next_li = li.find_next_sibling('li')
                        if next_li and "〜" in next_li.get_text():
                            end_time = _clean_text(next_li.get_text().replace("〜", ""))

                        all_showings.append({
                            "cinema_name": CINEMA_NAME_SB,
                            "movie_title": title,
                            "date_text": date_text,
                            "showtime": showtime,
                            "end_time": end_time,
                            "tags": ", ".join(tags),
                            "director": info.get("director", ""),
                            "year": info.get("year", ""),
                            "runtime_min": info.get("runtime_min", ""),
                            "booking_url": booking_url,
                            "detail_page_url": detail_url
                        })

    print(f"INFO: [{CINEMA_NAME_SB}] Collected {len(all_showings)} total showings for the specified date range.")
    return all_showings


if __name__ == '__main__':
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
            
    print(f"Testing {CINEMA_NAME_SB} scraper module...")
    showings = scrape_shin_bungeiza()
    
    if showings:
        showings.sort(key=lambda x: (x['date_text'], x['showtime']))
        fname = 'shin_bungeiza_showtimes.json'
        with open(fname, 'w', encoding='utf-8') as f:
            json.dump(showings, f, ensure_ascii=False, indent=2)
        print(f"INFO: Successfully wrote {len(showings)} records to {fname}.")
        
        # Pretty print the first record as an example
        from pprint import pprint
        print("\n--- Example Record ---")
        pprint(showings[0])
        print("--------------------")
    else:
        print("No showings found by Shin-Bungeiza scraper for the specified date range.")