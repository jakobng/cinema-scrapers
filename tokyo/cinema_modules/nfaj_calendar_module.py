"""
nfaj_calendar_module.py — scraper for 国立映画アーカイブ (National Film Archive of Japan)
- Updated 2026-01 for new calendar page structure (row-based tables)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --- Constants ---
CINEMA_NAME = "国立映画アーカイブ"
CALENDAR_URL = "https://www.nfaj.go.jp/calendar/"
BASE_URL = "https://www.nfaj.go.jp/"

# --- Helper Functions ---

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return BeautifulSoup(response.text, 'html.parser')
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None

def _clean_text(element) -> str:
    """Extracts and normalizes whitespace from a BeautifulSoup Tag."""
    if not element: return ""
    return " ".join(element.get_text(strip=True).split())

def _parse_detail_page(detail_url: str, detail_cache: dict) -> dict:
    """Scrapes a movie detail page for rich information."""
    if detail_url in detail_cache:
        return detail_cache[detail_url]

    print(f"INFO: Scraping detail page: {detail_url}")
    soup = _fetch_soup(detail_url)
    if not soup:
        detail_cache[detail_url] = {}
        return {}

    details = {
        "movie_title": None, "director": None, "year": None,
        "country": None, "synopsis": None, "runtime_min": None
    }

    # Extract title from h1
    if title_h1 := soup.find('h1'):
        title_text = _clean_text(title_h1)
        # Remove English title if present (keep only Japanese)
        if title_text:
            parts = title_text.split()
            japanese_title = ""
            for part in parts:
                # Stop when we hit a mostly-Latin alphabet word
                if re.search(r'[a-zA-Z]{3,}', part):
                    break
                japanese_title += part + " "
            details['movie_title'] = japanese_title.strip() if japanese_title else title_text

    # Find main content area
    main_content = soup.find('main') or soup.find('article') or soup.body
    if main_content:
        # Look for synopsis (main paragraph text)
        paragraphs = main_content.find_all('p')
        for p in paragraphs:
            text = _clean_text(p)
            # Look for year and director in format: "1966-67（監）スタン・ブラッケージ"
            year_dir_match = re.search(r'(\d{4})(?:-\d{2,4})?\s*(?:（監）|監督：)([^）\n]+)', text)
            if year_dir_match:
                details['year'] = year_dir_match.group(1)
                details['director'] = year_dir_match.group(2).strip()

            # If this paragraph has substantial content, use as synopsis
            if len(text) > 50 and not details['synopsis']:
                # Remove the year/director line if it's part of this paragraph
                synopsis_text = re.sub(r'\d{4}(?:-\d{2,4})?\s*(?:（監）|監督：)[^）\n]+', '', text)
                details['synopsis'] = synopsis_text.strip()

        # Look for runtime in format "64分"
        full_text = main_content.get_text()
        runtime_match = re.search(r'(\d+)分', full_text)
        if runtime_match:
            details['runtime_min'] = runtime_match.group(1)

    detail_cache[detail_url] = details
    return details

# --- Main Scraping Logic ---

def scrape_nfaj_calendar() -> List[Dict]:
    """
    Scrapes the NFAJ calendar page for all film screenings at 長瀬記念ホール OZU.
    """
    print(f"INFO: [{CINEMA_NAME}] Fetching calendar: {CALENDAR_URL}")
    soup = _fetch_soup(CALENDAR_URL)
    if not soup: return []

    all_showings = []
    detail_cache = {}
    today = datetime.now().date()

    # Find all calendar tables
    calendar_tables = soup.find_all('table')
    print(f"INFO: Found {len(calendar_tables)} calendar tables")

    for table_idx, table in enumerate(calendar_tables):
        # Find the header row to extract dates
        header_row = table.find('tr', class_='num')
        if not header_row:
            continue

        # Extract dates from header cells (skip first column which is venue label)
        date_cells = header_row.find_all('th')[1:]  # Skip first th (venue column)
        dates = []

        for cell in date_cells:
            cell_text = _clean_text(cell)
            # Parse date format like "8日(木)" or "10日(土)11:00開館"
            date_match = re.search(r'(\d+)日\([月火水木金土日]\)', cell_text)
            if date_match:
                day = int(date_match.group(1))
                # Determine year and month from current context
                # For simplicity, use current month/year (adjust for month boundaries)
                month = today.month
                year = today.year
                try:
                    date_obj = datetime(year, month, day).date()
                    # If the date is in the past, it's probably next month
                    if date_obj < today:
                        if month == 12:
                            month, year = 1, year + 1
                        else:
                            month += 1
                        date_obj = datetime(year, month, day).date()
                    dates.append(date_obj)
                except ValueError:
                    dates.append(None)
            else:
                dates.append(None)

        print(f"INFO: Table {table_idx} has {len(dates)} date columns")

        # Find rows with OZU venue and process them + following rows
        all_rows = table.find_all('tr')
        for row_idx, row in enumerate(all_rows):
            # Check if this row is for OZU venue
            venue_header = row.find('th', scope='row')
            if not venue_header:
                continue

            venue_text = _clean_text(venue_header)
            if 'OZU' not in venue_text:
                continue

            print(f"INFO: Found OZU header in table {table_idx}, row {row_idx}")

            # Get rowspan to know how many rows this venue covers
            rowspan = int(venue_header.get('rowspan', 1))
            print(f"INFO: OZU rowspan = {rowspan}")

            # Process this row and the next (rowspan-1) rows
            rows_to_process = [row] + all_rows[row_idx+1:row_idx+rowspan]

            for sub_row in rows_to_process:
                # Get all td cells in this row
                data_cells = sub_row.find_all('td')

                # Calculate column offset based on cells with colspan in this row
                col_offset = 0

                for cell_idx, cell in enumerate(data_cells):
                    # Skip cells that are marked as closed
                    if cell.get('class') and 'close' in cell.get('class'):
                        colspan = int(cell.get('colspan', 1))
                        rowspan_val = int(cell.get('rowspan', 1))
                        col_offset += colspan
                        continue

                    # Skip cells with colspan > 1 (these are headers/series info)
                    colspan = int(cell.get('colspan', 1))
                    if colspan > 1:
                        col_offset += colspan
                        continue

                    # Find screenings in this cell
                    times = cell.find_all('time')
                    links = cell.find_all('a', href=re.compile(r'/program/'))

                    if times and links:
                        # Match times with links
                        for time_tag, link_tag in zip(times, links):
                            showtime = time_tag.get('datetime', time_tag.get_text(strip=True))

                            # Skip talks/events
                            link_text = _clean_text(link_tag)
                            if re.search(r'トーク|talk|講演|ギャラリー', link_text, re.I):
                                continue

                            # Get detail page URL
                            detail_page_url = urljoin(BASE_URL, link_tag['href'])

                            # Determine date for this cell
                            # The date index = col_offset + cell_idx
                            date_idx = col_offset + cell_idx
                            if date_idx < len(dates) and dates[date_idx]:
                                date_obj = dates[date_idx]

                                # Fetch metadata from detail page
                                details = _parse_detail_page(detail_page_url, detail_cache)

                                # Only add if we got a title
                                if details.get("movie_title"):
                                    all_showings.append({
                                        "cinema_name": CINEMA_NAME,
                                        "movie_title": details.get("movie_title"),
                                        "date_text": date_obj.isoformat(),
                                        "showtime": showtime,
                                        "director": details.get("director"),
                                        "year": details.get("year"),
                                        "country": details.get("country"),
                                        "runtime_min": details.get("runtime_min"),
                                        "synopsis": details.get("synopsis"),
                                        "detail_page_url": detail_page_url,
                                        "screen_name": "長瀬記念ホール OZU"
                                    })

                    col_offset += 1

    # Deduplicate and sort
    unique_showings = list({(s["date_text"], s["movie_title"], s["showtime"]): s for s in all_showings}.values())
    unique_showings.sort(key=lambda x: (x.get('date_text', ''), x.get('showtime', '')))

    print(f"INFO: [{CINEMA_NAME}] Collected {len(unique_showings)} unique showings.")
    return unique_showings

if __name__ == '__main__':
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    showings = scrape_nfaj_calendar()

    if showings:
        output_filename = "nfaj_showtimes.json"
        print(f"\nINFO: Writing {len(showings)} records to {output_filename}...")
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(showings, f, ensure_ascii=False, indent=2)
        print(f"INFO: Successfully created {output_filename}.")

        print("\n--- Sample of First Showing ---")
        from pprint import pprint
        pprint(showings[0])
    else:
        print(f"\nNo showings found by {CINEMA_NAME} scraper.")
