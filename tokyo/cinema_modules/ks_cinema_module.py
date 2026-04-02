from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# --- Constants ---
CINEMA_NAME_KC = "K's Cinema (ケイズシネマ)"
BASE_URL = "https://www.ks-cinema.com/"
IFRAME_SRC_URL_KC = urljoin(BASE_URL, "/calendar/index.html")
SAMPLE_DATA_DIR = Path(__file__).resolve().parents[1] / "sample_data"
SAMPLE_CALENDAR_PATH = SAMPLE_DATA_DIR / "ks_cinema_calendar_sample.html"
EIGALAND_URL_RE = re.compile(r"https?://schedule\\.eigaland\\.com/schedule\\?webKey=[^\\s'\"<>]+")

# --- Helper Functions ---

def _clean_text(element_or_string) -> str:
    """A helper to normalize whitespace."""
    if element_or_string is None:
        return ""
    if hasattr(element_or_string, 'get_text'):
        raw_text = element_or_string.get_text(separator=' ', strip=True)
    else:
        raw_text = str(element_or_string)
    return ' '.join(raw_text.strip().split())


def _fetch_soup(url: str, *, for_calendar: bool = False) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser', from_encoding='shift_jis')
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME_KC}] Could not fetch {url}: {e}", file=sys.stderr)
        if for_calendar and SAMPLE_CALENDAR_PATH.exists():
            try:
                print(f"INFO: [{CINEMA_NAME_KC}] Falling back to local sample calendar HTML.", file=sys.stderr)
                html = SAMPLE_CALENDAR_PATH.read_text(encoding="utf-8")
                return BeautifulSoup(html, 'html.parser')
            except Exception as read_err:
                print(f"ERROR: [{CINEMA_NAME_KC}] Could not read fallback calendar: {read_err}", file=sys.stderr)
        return None


def _select_title_candidates(cell: Tag) -> Iterable[Tag]:
    """Yield potential title nodes from a calendar cell."""
    selectors = [
        'span.title_s',
        '[class*="title"]',
        '.program-title',
        '.movie-title',
        '.title',
        'a'
    ]
    seen = set()
    for selector in selectors:
        for node in cell.select(selector):
            if not isinstance(node, Tag):
                continue
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            yield node


# --- Eigaland Schedule Support ---

def _discover_eigaland_schedule_url() -> str:
    try:
        response = requests.get(BASE_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"INFO: [{CINEMA_NAME_KC}] Could not fetch homepage for Eigaland discovery: {e}", file=sys.stderr)
        return ""

    html = response.text or ""
    match = EIGALAND_URL_RE.search(html)
    if match:
        return match.group(0)

    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href*='schedule.eigaland.com']"):
        href = link.get("href") or ""
        if "webKey=" in href:
            return href
    return ""


def _parse_eigaland_date(date_str: str, today: date) -> Optional[date]:
    match = re.search(r"(\d{1,2})/(\d{1,2})", date_str)
    if not match:
        return None
    month, day = map(int, match.groups())
    year = today.year
    if month < today.month and (today.month - month) > 6:
        year += 1
    elif month > today.month and (month - today.month) > 6:
        year -= 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _scrape_eigaland_schedule(schedule_url: str, max_days: int = 7) -> List[Dict]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except Exception as e:
        print(f"INFO: [{CINEMA_NAME_KC}] Selenium not available for Eigaland scrape: {e}", file=sys.stderr)
        return []

    driver = None
    showings: List[Dict] = []
    today = date.today()
    end_date = today + timedelta(days=max_days - 1)

    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1280,1000")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        driver = webdriver.Chrome(options=options)
        driver.get(schedule_url)
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".calender-head-item")))
        time.sleep(1)

        date_items = driver.find_elements(By.CSS_SELECTOR, ".calender-head-item")
        for idx in range(min(len(date_items), max_days)):
            date_items = driver.find_elements(By.CSS_SELECTOR, ".calender-head-item")
            if idx >= len(date_items):
                break

            item = date_items[idx]
            date_text_elem = item.find_element(By.CSS_SELECTOR, ".date") if item.find_elements(By.CSS_SELECTOR, ".date") else None
            date_text = date_text_elem.text.strip() if date_text_elem else item.text.strip()
            show_date = _parse_eigaland_date(date_text, today)
            if not show_date or not (today <= show_date <= end_date):
                continue

            if "active" not in item.get_attribute("class"):
                driver.execute_script("arguments[0].click();", item)
                time.sleep(1.5)

            movie_items = driver.find_elements(By.CSS_SELECTOR, ".movie-schedule-item")
            for movie_item in movie_items:
                title = ""
                for selector in ["span[style*='font-weight']", ".movie-title", "span.title", "span"]:
                    try:
                        title_elem = movie_item.find_element(By.CSS_SELECTOR, selector)
                        title = title_elem.text.strip()
                        if title and title != "NEW":
                            break
                    except Exception:
                        continue

                if not title or title == "NEW":
                    continue

                time_elems = movie_item.find_elements(By.CSS_SELECTOR, ".slot h2")
                for time_elem in time_elems:
                    showtime = time_elem.text.strip()
                    if not showtime:
                        continue
                    showings.append({
                        "cinema_name": CINEMA_NAME_KC,
                        "movie_title": title,
                        "date_text": show_date.isoformat(),
                        "showtime": showtime,
                        "detail_page_url": schedule_url,
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": "",
                        "synopsis": "",
                        "movie_title_en": "",
                    })
    except Exception as e:
        print(f"ERROR: [{CINEMA_NAME_KC}] Eigaland scrape failed: {e}", file=sys.stderr)
    finally:
        if driver:
            driver.quit()

    # Deduplicate
    unique = []
    seen = set()
    for s in showings:
        key = (s["date_text"], s["movie_title"], s["showtime"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    return unique


# --- Detail Page Parsing ---

def _parse_detail_page(soup: BeautifulSoup) -> Dict[str, str]:
    """Parses a movie detail page for rich information."""
    details = {"director": "", "year": "", "runtime_min": "", "country": "", "synopsis": "", "original_title": ""}
    
    # Details Table Parsing
    for table in soup.select("#txt-area table"):
        table_text = table.get_text()
        if '監督' in table_text or '作品データ' in table_text:
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) != 2:
                    continue
                key, value = _clean_text(cells[0]), _clean_text(cells[1])

                if "監督" in key:
                    details["director"] = value
                elif "作品データ" in key:
                    year_match = re.search(r"(\d{4})年", value)
                    runtime_match = re.search(r"(\d+)分", value)
                    country_match = re.search(r"／\s*([^／]+?)\s*／", value)
                    # Extract Original Title
                    # Looks for "原題：" followed by text until next slash or end of string
                    original_title_match = re.search(r"原題[:：]\s*([^／/]+)", value)

                    if year_match:
                        details["year"] = year_match.group(1)
                    if runtime_match:
                        details["runtime_min"] = runtime_match.group(1)
                    if country_match:
                        details["country"] = country_match.group(1).strip()
                    if original_title_match:
                        details["original_title"] = original_title_match.group(1).strip()
            break

    # Synopsis Parsing
    synopsis_div = soup.select_one("div.wixui-rich-text")
    if synopsis_div:
        details["synopsis"] = _clean_text(synopsis_div)
    else:
        txt_area_div = soup.select_one("#txt-area")
        if txt_area_div:
            synopsis_parts = []
            start_node = txt_area_div.select_one("table.alignright") or txt_area_div.select_one("p > img")
            if start_node:
                for element in start_node.find_next_siblings():
                    if element.name == 'table' and ('監督' in element.get_text() or '作品データ' in element.get_text()):
                        break
                    if element.name == 'p':
                        p_text = _clean_text(element)
                        if p_text:
                            synopsis_parts.append(p_text)
                if synopsis_parts:
                    details["synopsis"] = " ".join(synopsis_parts)
    return details


# --- Main Scraping Logic ---
def _extract_times_from_elements(elements: Iterable[Tag]) -> List[str]:
    times: List[str] = []
    time_pattern = re.compile(r"\b\d{1,2}:\d{2}\b")
    for el in elements:
        text = el.get_text(separator=' ', strip=True)
        for match in time_pattern.findall(text):
            if match not in times:
                times.append(match)
    return times


def _extract_showtimes_from_cell(cell: Tag) -> List[str]:
    """Find showtime strings within a calendar cell."""
    time_nodes = list(cell.select('[class*="time"], [class*="schedule"], li, p'))
    if time_nodes:
        extracted = _extract_times_from_elements(time_nodes)
        if extracted:
            return extracted
    return _extract_times_from_elements([cell])


def _resolve_detail_url(cell: Tag) -> str:
    link = cell.select_one("a[href*='/movie/']")
    if link and link.has_attr('href'):
        return urljoin(BASE_URL, link['href'])
    data_link = cell.get('data-url') or cell.get('data-href')
    if data_link:
        return urljoin(BASE_URL, data_link)
    return ""


def scrape_ks_cinema(max_days: int = 7) -> List[Dict]:
    eigaland_url = _discover_eigaland_schedule_url()
    if eigaland_url:
        print(f"INFO: [{CINEMA_NAME_KC}] Found Eigaland schedule: {eigaland_url}")
        eigaland_showings = _scrape_eigaland_schedule(eigaland_url, max_days=max_days)
        if eigaland_showings:
            print(f"INFO: [{CINEMA_NAME_KC}] Using Eigaland showings: {len(eigaland_showings)}")
            return eigaland_showings
        print(f"INFO: [{CINEMA_NAME_KC}] Eigaland returned no showings, falling back to calendar.")

    print(f"INFO: [{CINEMA_NAME_KC}] Fetching calendar iframe: {IFRAME_SRC_URL_KC}")
    iframe_soup = _fetch_soup(IFRAME_SRC_URL_KC, for_calendar=True)
    if not iframe_soup:
        return []

    details_cache: Dict[str, Dict[str, str]] = {}
    unique_detail_urls = {
        urljoin(BASE_URL, a['href'])
        for a in iframe_soup.select("td a[href*='/movie/']")
        if a.has_attr('href')
    }
    for cell in iframe_soup.select("td[data-url], td[data-href]"):
        data_link = cell.get('data-url') or cell.get('data-href')
        if data_link:
            unique_detail_urls.add(urljoin(BASE_URL, data_link))
    
    print(f"INFO: [{CINEMA_NAME_KC}] Found {len(unique_detail_urls)} unique detail pages to scrape.")
    for url in unique_detail_urls:
        print(f"INFO: [{CINEMA_NAME_KC}] Scraping detail page: {url}")
        detail_soup = _fetch_soup(url)
        if detail_soup:
            details_cache[url] = _parse_detail_page(detail_soup)
    print(f"INFO: [{CINEMA_NAME_KC}] Finished scraping details. Parsing schedule...")

    all_showings: List[Dict] = []
    today = date.today()
    end_date = today + timedelta(days=max_days - 1)
    
    tables = iframe_soup.select("div.slide > table, div.swiper-slide table, table.calendar-table")
    if not tables:
        tables = iframe_soup.select("table")

    for table in tables:
        month_row = table.find('tr', class_='month')
        day_header_row = table.find('tr', class_='day')
        if not month_row or not day_header_row:
            continue

        column_dates: Dict[int, date] = {}
        day_ths = day_header_row.find_all('th', scope='col')
        current_col_index = 0
        last_month = 0
        current_year = today.year
        for month_th in month_row.find_all('th'):
            month_match = re.search(r'(\d{1,2})月', _clean_text(month_th))
            if not month_match:
                continue
            
            month = int(month_match.group(1))
            if last_month > 0 and month < last_month:
                current_year += 1
            last_month = month
            raw_colspan = str(month_th.get('colspan', '1'))
            clean_colspan = ''.join(filter(str.isdigit, raw_colspan))
            colspan = int(clean_colspan) if clean_colspan else 1
            for i in range(colspan):
                day_index = current_col_index + i
                if day_index < len(day_ths):
                    try:
                        day = int(_clean_text(day_ths[day_index]))
                        column_dates[day_index] = date(current_year, month, day)
                    except ValueError:
                        pass
            current_col_index += colspan
        
        row_candidates = table.select('tr.movie, tr[data-movie-id]')
        if not row_candidates:
            continue
        for row in row_candidates:
            current_cell_idx = 0
            for cell in row.find_all('td'):
                colspan = int(cell.get('colspan') or cell.get('data-colspan') or 1)
                title = ""
                for title_candidate in _select_title_candidates(cell):
                    title = _clean_text(title_candidate)
                    if title:
                        break
                if not title:
                    current_cell_idx += colspan
                    continue

                detail_url = _resolve_detail_url(cell)
                if detail_url and detail_url not in details_cache:
                    detail_soup = _fetch_soup(detail_url)
                    if detail_soup:
                        details_cache[detail_url] = _parse_detail_page(detail_soup)
                    else:
                        details_cache[detail_url] = {}
                details = details_cache.get(detail_url, {})
                showtimes = _extract_showtimes_from_cell(cell)

                for day_offset in range(colspan):
                    col_idx = current_cell_idx + day_offset
                    if col_idx in column_dates:
                        show_date = column_dates[col_idx]
                        if today <= show_date <= end_date:
                            for st in showtimes:
                                all_showings.append({
                                    "cinema_name": CINEMA_NAME_KC,
                                    "movie_title": title,
                                    "movie_title_en": details.get("original_title", ""),
                                    "date_text": show_date.isoformat(),
                                    "showtime": st,
                                    "director": details.get("director", ""),
                                    "year": details.get("year", ""),
                                    "country": details.get("country", ""),
                                    "runtime_min": details.get("runtime_min", ""),
                                    "synopsis": details.get("synopsis", ""),
                                    "detail_page_url": detail_url,
                                })
                current_cell_idx += colspan

    unique_showings = list({(s["date_text"], s["movie_title"], s["showtime"]): s for s in all_showings}.values())
    print(f"INFO: [{CINEMA_NAME_KC}] Collected {len(unique_showings)} unique showings.")
    return unique_showings


if __name__ == '__main__':
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
            
    print(f"Testing {CINEMA_NAME_KC} scraper module...")
    showings = scrape_ks_cinema(max_days=7)
    
    if showings:
        showings.sort(key=lambda x: (x.get('date_text', ''), x.get('showtime', '')))
        
        output_filename = "ks_cinema_showtimes.json"
        print(f"\nINFO: Writing {len(showings)} records to {output_filename}...")
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(showings, f, ensure_ascii=False, indent=2)
        print(f"INFO: Successfully created {output_filename}.")

        print("\n--- Sample of First Showing ---")
        from pprint import pprint
        pprint(showings[0])
    else:
        print(f"\nNo showings found by {CINEMA_NAME_KC} scraper.")


