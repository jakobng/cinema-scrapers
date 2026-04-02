import requests
import json
import re
from bs4 import BeautifulSoup, NavigableString
from urllib.parse import urljoin
from datetime import date, timedelta, datetime
from typing import List, Dict, Optional, Tuple

BASE_URL = "https://www.morc-asagaya.com"
LIST_URL = f"{BASE_URL}/film_date/film_now/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    )
}

def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[Morc阿佐ヶ谷] Error fetching {url}: {e}")
        return None

def clean_title(text: str) -> str:
    """
    Removes event prefixes like 〈第4回クロアチア映画祭〉
    """
    # Remove text inside angle brackets <...> or 〈...〉
    text = re.sub(r'[〈<].*?[〉>]', '', text)
    return text.strip()

def parse_meta_from_text(text: str) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[str]]:
    """
    Extracts Year, Runtime, Country, Director from a blob of text.
    """
    year, runtime, country, director = None, None, None, None

    # 1. Year / Runtime / Country pattern: "2025年／61分／日本"
    m_specs = re.search(r"(\d{4})年\s*[／/]\s*(\d+)分\s*[／/]\s*([^\n]+)", text)
    if m_specs:
        year = m_specs.group(1)
        runtime = int(m_specs.group(2))
        # Clean country (stop at newlines or block chars)
        c_raw = m_specs.group(3)
        country = re.split(r'[■◼︎\n]', c_raw)[0].strip()

    # 2. Director pattern: "■監督：Name" or just "監督：Name"
    m_dir = re.search(r"[■◼︎]?\s*監督[：:]\s*([^\n■◼︎]+)", text)
    if m_dir:
        director = m_dir.group(1).strip()

    return year, runtime, country, director

def expand_date_text(text: str) -> List[date]:
    """
    Parses complex date strings found in Morc text.
    Examples: "11/17(月)〜11/20(木)", "11/25(火)、11/26(水)"
    """
    today = date.today()
    current_year = today.year
    dates = []

    # Normalize separators
    text = text.replace("～", "〜").replace("-", "〜")
    
    date_pattern = re.compile(r"(\d{1,2})/(\d{1,2})")

    def make_date(m, d):
        # Validate month is in valid range (1-12)
        # This catches cases where regex matches year parts like "2025/1" -> m=25
        if not (1 <= m <= 12) or not (1 <= d <= 31):
            return None
        y = current_year
        # Handle year boundaries
        if today.month >= 10 and m <= 3:
            y += 1
        elif today.month <= 3 and m >= 10:
            y -= 1
        try:
            return date(y, m, d)
        except ValueError:
            return None

    # Split by commas first
    parts = re.split(r'[、,]', text)

    for part in parts:
        part = part.strip()
        if not part: continue

        if "〜" in part:
            range_sides = part.split("〜")
            start_match = date_pattern.search(range_sides[0])
            if start_match:
                start_m, start_d = map(int, start_match.groups())
                start_date = make_date(start_m, start_d)
                if start_date is None:
                    continue

                end_match = date_pattern.search(range_sides[1]) if len(range_sides) > 1 else None

                if end_match:
                    end_m, end_d = map(int, end_match.groups())
                    end_date = make_date(end_m, end_d)
                    if end_date is None:
                        continue
                else:
                    # If "End TBD", assume 1 week
                    end_date = start_date + timedelta(days=7)

                # Fill range
                curr = start_date
                while curr <= end_date:
                    dates.append(curr)
                    curr += timedelta(days=1)
        else:
            match = date_pattern.search(part)
            if match:
                m, d = map(int, match.groups())
                parsed_date = make_date(m, d)
                if parsed_date is not None:
                    dates.append(parsed_date)

    return sorted(list(set(dates)))

def parse_schedule_from_detail_soup(soup: BeautifulSoup) -> List[Tuple[date, str]]:
    """
    Scans the detail page text to pair Dates with Times.
    """
    showings = []

    def extract_showtimes_from_line(line: str) -> List[str]:
        """Return start times while ignoring end/door times.

        The site sometimes lists ranges like "19:00〜20:30" or door-open
        times such as "開場18:00/開映18:30". When a start and end time are
        present, we only keep the first (start) time. We also drop times
        labelled as door open to avoid treating them as screenings.
        """

        # Collapse whitespace for simpler regex checks
        normalized = re.sub(r"\s+", "", line)

        # If the line explicitly shows a start-end range, only keep the start.
        range_match = re.search(r"(\d{1,2}:\d{2})[〜～-](\d{1,2}:\d{2})", normalized)
        if range_match:
            return [range_match.group(1)]

        times = []
        for match in re.finditer(r"(\d{1,2}:\d{2})", normalized):
            time_str = match.group(1)

            # Skip door-open style times (開場/オープン/Open) to avoid
            # interpreting them as showtimes.
            pre_context = normalized[max(0, match.start() - 4):match.start()]
            if re.search(r"開場|open", pre_context, re.IGNORECASE):
                continue

            # Skip times immediately followed by an end marker.
            post_context = normalized[match.end():match.end() + 2]
            if re.search(r"終", post_context):
                continue

            times.append(time_str)

        return times
    
    # Find the header "上映日時"
    header = soup.find(lambda tag: tag.name in ['h2', 'h3', 'h4', 'p'] and '上映日時' in tag.get_text())
    
    if not header:
        text_source = soup.get_text("\n")
    else:
        lines = []
        for sibling in header.next_siblings:
            s_text = sibling.get_text()
            if "料金" in s_text or "Ticket" in s_text or "TICKET" in s_text:
                break
            lines.append(s_text)
        text_source = "\n".join(lines)

    raw_lines = [l.strip() for l in text_source.split('\n') if l.strip()]
    active_dates = []
    
    for line in raw_lines:
        # 1. Extract potential dates from this line
        line_dates = expand_date_text(line)

        # 2. Extract potential times from this line (ignore end/door times)
        time_matches = extract_showtimes_from_line(line)
        
        if line_dates and time_matches:
            # Date and Time on same line
            for d in line_dates:
                for t in time_matches:
                    showings.append((d, t))
            active_dates = line_dates
            
        elif line_dates and not time_matches:
            # Just dates, set context for next lines
            active_dates = line_dates
            
        elif time_matches and not line_dates:
            # Just times, apply to active dates
            if active_dates:
                for d in active_dates:
                    for t in time_matches:
                        showings.append((d, t))

    return showings

def fetch_morc_asagaya_showings() -> List[Dict]:
    """
    Main scraper function.
    """
    soup = fetch_soup(LIST_URL)
    if not soup:
        return []

    all_showings = []
    today = date.today()
    end_date = today + timedelta(days=7) # Today + 7 days

    # Parse list
    film_blocks = soup.select("#pg_film_now li.tpf_list")
    print(f"[Morc阿佐ヶ谷] Found {len(film_blocks)} films in listing.")

    for li in film_blocks:
        a_tag = li.find("a")
        if not a_tag: continue
        
        href = a_tag.get("href")
        full_url = urljoin(BASE_URL, href)
        
        # Extract Title
        h2 = li.find("h2")
        raw_title = h2.get_text(strip=True) if h2 else ""
        title = clean_title(raw_title)
        
        # Fetch Detail Page
        detail_soup = fetch_soup(full_url)
        if not detail_soup: continue
        
        # Parse Meta & Schedule
        page_text = detail_soup.get_text("\n")
        year, runtime, country, director = parse_meta_from_text(page_text)
        scraped_showings = parse_schedule_from_detail_soup(detail_soup)
        
        for d, t_str in scraped_showings:
            # --- DATE FILTERING ---
            if not (today <= d <= end_date):
                continue

            all_showings.append({
                "cinema_name": "Morc阿佐ヶ谷",
                "movie_title": title,
                "movie_title_en": None, 
                "director": director,
                "year": year,
                "country": country,
                "runtime_min": runtime,
                "date_text": d.isoformat(),
                "showtime": t_str,
                "detail_page_url": full_url,
                "purchase_url": None
            })

    # --- DEDUPLICATION ---
    # Sometimes the parser captures the same showtime twice if text layout is messy.
    unique_showings = {}
    for s in all_showings:
        # Key: Date + Title + Time
        key = (s['date_text'], s['movie_title'], s['showtime'])
        unique_showings[key] = s

    # Convert back to list and sort
    final_list = list(unique_showings.values())
    final_list.sort(key=lambda x: (x['date_text'], x['showtime']))
    
    return final_list

if __name__ == "__main__":
    # Run scraper
    data = fetch_morc_asagaya_showings()
    
    # Save to JSON
    filename = "morc_asagaya_showtimes.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\nSuccess! Scraped {len(data)} unique showings.")
    print(f"Results saved to: {filename}")