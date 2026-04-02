"""polepole_module.py — scraper for ポレポレ東中野 (Pole‑Pole Higashi‑Nakano)

Scrapes Official Site (Selenium) as primary source, falls back to Eiga.com, then Jorudan.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# Selenium imports
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

# --- Constants ---
CINEMA_NAME = "ポレポレ東中野"
OFFICIAL_URL = "https://pole2.co.jp/"
EIGA_URL = "https://eiga.com/theater/13/130612/3292/"
JORUDAN_SCHEDULE_URL = "https://movie.jorudan.co.jp/theater/1000506/schedule/"
JORUDAN_BASE_URL = "https://movie.jorudan.co.jp"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}
TIMEOUT = 15

# --- Helper Functions ---

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return BeautifulSoup(r.content, "html.parser")
    except requests.RequestException as e:
        print(f"ERROR [{CINEMA_NAME}]: Could not fetch {url}. Reason: {e}", file=sys.stderr)
        return None

def _clean_text(element: Optional[Tag]) -> str:
    """Extracts and normalizes whitespace from a BeautifulSoup Tag."""
    if not element:
        return ""
    return " ".join(element.get_text(strip=True).split())

def _init_driver():
    """Initializes a headless Chrome driver with anti-detection."""
    if not HAS_SELENIUM:
        raise ImportError("Selenium not installed")
        
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(options=options)
    # Hide selenium property
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
        """
    })
    return driver

# --- Official Site Scraping (Selenium - Primary) ---

def _scrape_from_official_site(max_days: int = 7) -> List[Dict]:
    """Scrape schedule from official site using Selenium."""
    if not HAS_SELENIUM:
        return []
        
    print(f"INFO [{CINEMA_NAME}]: Fetching schedule from official site (Selenium)...")
    driver = None
    results = []
    
    try:
        driver = _init_driver()
        driver.get(OFFICIAL_URL)
        
        wait = WebDriverWait(driver, 20)
        
        # Wait for calendar header
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".calendar-head")))
        
        # Scroll to schedule (often required for triggering content load in Nuxt)
        try:
            schedule_el = driver.find_element(By.ID, "schedule")
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", schedule_el)
            time.sleep(2)
        except Exception:
            pass

        # Get Date Tabs
        date_items = driver.find_elements(By.CSS_SELECTOR, ".calender-head-item")
        
        # Extract current year for date parsing
        today = dt.date.today()
        current_year = today.year
        
        # Iterate and scrape
        for i in range(min(max_days, len(date_items))):
            # Re-fetch items to avoid stale element errors
            date_items = driver.find_elements(By.CSS_SELECTOR, ".calender-head-item")
            if i >= len(date_items): break
            
            item = date_items[i]
            
            # Extract date from tab: "水 01/14"
            date_text_raw = item.text.replace("\n", " ").strip()
            # Parse date: 01/14 -> 2026-01-14
            match = re.search(r"(\d{1,2})/(\d{1,2})", date_text_raw)
            if not match:
                continue
                
            month, day = map(int, match.groups())
            # Handle year rollover
            year = current_year
            if month < today.month and today.month > 6:
                year += 1
            
            try:
                date_obj = dt.date(year, month, day)
                date_iso = date_obj.isoformat()
            except ValueError:
                continue

            # Click to activate date
            driver.execute_script("arguments[0].click();", item)
            
            # Wait for movies to update/load
            time.sleep(1.5)
            
            movies = driver.find_elements(By.CSS_SELECTOR, ".movie-schedule-item")
            
            for m in movies:
                try:
                    # Title
                    title_el = m.find_element(By.CSS_SELECTOR, "h2")
                    # Remove "More" text if present
                    full_text = title_el.text
                    movie_title = full_text.split("\n")[0].replace("もっとみる", "").strip()
                    
                    # Detail URL
                    detail_url = None
                    try:
                        link_el = title_el.find_element(By.TAG_NAME, "a")
                        detail_url = link_el.get_attribute("href")
                    except Exception:
                        pass

                    # Times
                    slots = m.find_elements(By.CSS_SELECTOR, ".slot")
                    for s in slots:
                        # Time is usually in h2 inside slot
                        t_els = s.find_elements(By.CSS_SELECTOR, "h2")
                        if t_els:
                            showtime = t_els[0].text.strip()
                            if re.match(r"\d{1,2}:\d{2}", showtime):
                                results.append({
                                    "cinema_name": CINEMA_NAME,
                                    "movie_title": movie_title,
                                    "movie_title_en": None,
                                    "date_text": date_iso,
                                    "showtime": showtime,
                                    "detail_page_url": detail_url,
                                    "director": None,
                                    "year": None,
                                    "country": None,
                                    "runtime_min": None,
                                    "synopsis": None,
                                })
                except Exception as e:
                    # print(f"DEBUG: Error parsing movie item: {e}")
                    continue
                    
    except Exception as e:
        print(f"WARN [{CINEMA_NAME}]: Selenium scrape failed: {e}", file=sys.stderr)
    finally:
        if driver:
            driver.quit()
            
    print(f"INFO [{CINEMA_NAME}]: Found {len(results)} showings via Selenium.")
    return results

# --- Eiga.com Scraping (Secondary) ---

def _scrape_from_eiga_com() -> List[Dict]:
    """Scrape schedule from eiga.com."""
    print(f"INFO [{CINEMA_NAME}]: Fetching schedule from eiga.com...")
    soup = _fetch_soup(EIGA_URL)
    if not soup:
        return []

    results: List[Dict] = []
    
    # Find all theater-wrapper divs
    wrappers = soup.select('.theater-wrapper')

    for wrapper in wrappers:
        section = wrapper.find_parent('section')
        if not section: continue

        title_el = section.find(['h2', 'h3'])
        if not title_el: continue

        movie_title = title_el.get_text(strip=True)
        
        movie_link = wrapper.select_one('.movie-image a[href*="/movie/"]')
        detail_url = 'https://eiga.com' + movie_link.get('href', '') if movie_link else None

        schedule = wrapper.select_one('.movie-schedule .weekly-schedule')
        if not schedule: continue

        cells = schedule.select('td, th')
        for cell in cells:
            data_date = cell.get("data-date")
            if data_date and len(data_date) == 8:
                try:
                    date_obj = dt.datetime.strptime(data_date, "%Y%m%d").date()
                    date_str = date_obj.isoformat()
                    
                    for span in cell.select('span'):
                        time_text = span.get_text(strip=True)
                        if re.match(r'^\d{1,2}:\d{2}$', time_text):
                            results.append({
                                "cinema_name": CINEMA_NAME,
                                "movie_title": movie_title,
                                "movie_title_en": None,
                                "date_text": date_str,
                                "showtime": time_text,
                                "detail_page_url": detail_url,
                                "director": None,
                                "year": None,
                                "country": None,
                                "runtime_min": None,
                                "synopsis": None,
                            })
                except ValueError:
                    continue

    print(f"INFO [{CINEMA_NAME}]: Found {len(results)} showings from eiga.com")
    return results

# --- Jorudan Scraping (Tertiary) ---

def _parse_jorudan_detail_page(soup: BeautifulSoup) -> Dict:
    """Parses a film's detail page on Jorudan for rich information."""
    details = {
        "director": None, "year": None, "runtime_min": None,
        "country": None, "synopsis": None
    }
    
    commentary = soup.select_one("section#commentary p.text")
    if commentary:
        details["synopsis"] = _clean_text(commentary)

    info_table = soup.select_one("section#information table")
    if info_table:
        for row in info_table.find_all("tr"):
            th = _clean_text(row.find("th"))
            td = _clean_text(row.find("td"))
            
            if "監督" in th or ("キャスト" in th and "監督" in td):
                director_text = re.sub(r".*監督：", "", td).strip()
                details["director"] = director_text.split(" ")[0]
            
            elif "制作国" in th:
                details["country"] = td.split('（')[0]
                year_match = re.search(r"（(\d{4})）", td)
                if year_match:
                    details["year"] = year_match.group(1)
            
            elif "上映時間" in th:
                runtime_match = re.search(r"(\d+)分", td)
                if runtime_match:
                    details["runtime_min"] = runtime_match.group(1)
    
    return details

def _scrape_from_jorudan(max_days: int = 7) -> List[Dict]:
    """
    Scrapes the Jorudan schedule page.
    """
    print(f"INFO [{CINEMA_NAME}]: Fetching schedule from Jorudan: {JORUDAN_SCHEDULE_URL}")
    main_soup = _fetch_soup(JORUDAN_SCHEDULE_URL)
    if not main_soup:
        return []

    details_cache = {}
    film_sections = main_soup.select("main > section[id^='cnm']")
    
    print(f"INFO [{CINEMA_NAME}]: Found {len(film_sections)} films on Jorudan schedule page.")
    for section in film_sections:
        link_tag = section.select_one(".btn a[href*='/film/']")
        if link_tag:
            detail_url = urljoin(JORUDAN_BASE_URL, link_tag['href'])
            if detail_url not in details_cache:
                detail_soup = _fetch_soup(detail_url)
                if detail_soup:
                    details_cache[detail_url] = _parse_jorudan_detail_page(detail_soup)

    all_showings = []
    today = dt.date.today()
    end_date = today + dt.timedelta(days=max_days - 1)
    
    for section in film_sections:
        title = _clean_text(section.find("h2"))
        if not title: continue

        link_tag = section.select_one(".btn a[href*='/film/']")
        detail_url = urljoin(JORUDAN_BASE_URL, link_tag['href']) if link_tag else None
        details = details_cache.get(detail_url, {})

        table = section.find("table")
        if not table: continue
            
        headers = [th.get_text(strip=True) for th in table.select("tr:first-of-type th")]
        date_map = {}
        for i, header_text in enumerate(headers):
            match = re.search(r"(\d{1,2})/(\d{1,2})", header_text)
            if match:
                month, day = map(int, match.groups())
                year = today.year if month >= today.month else today.year + 1
                try:
                    show_date = dt.date(year, month, day)
                    if today <= show_date <= end_date:
                        date_map[i] = show_date.isoformat()
                except ValueError:
                    continue
        
        time_row = table.select("tr:nth-of-type(2)")
        if not time_row: continue

        for i, cell in enumerate(time_row[0].find_all("td")):
            if i in date_map:
                date_text = date_map[i]
                showtimes = re.findall(r"\d{1,2}:\d{2}", cell.get_text())
                for st in showtimes:
                    all_showings.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title":       title,
                        "movie_title_en":    None,
                        "date_text":         date_text,
                        "showtime":          st,
                        "director":          details.get("director"),
                        "year":              details.get("year"),
                        "country":           details.get("country"),
                        "runtime_min":       details.get("runtime_min"),
                        "synopsis":          details.get("synopsis"),
                        "detail_page_url":   detail_url,
                    })

    unique_showings = list({(s["date_text"], s["movie_title"], s["showtime"]): s for s in all_showings}.values())
    unique_showings.sort(key=lambda r: (r["date_text"], r["showtime"]))
    print(f"INFO [{CINEMA_NAME}]: Collected {len(unique_showings)} showings from Jorudan.")
    return unique_showings

# --- Main Scraper ---

def scrape_polepole(max_days: int = 7) -> List[Dict]:
    """
    Main entry point. 
    1. Selenium (Official Site) -> Best coverage (4+ days)
    2. Eiga.com -> Good coverage (3 days)
    3. Jorudan -> Minimal coverage (2 days)
    """
    # 1. Try Official Site (Selenium)
    try:
        results = _scrape_from_official_site(max_days)
        # Check if we got a reasonable number of days (at least 3 to beat Eiga.com)
        if results and len(set(r['date_text'] for r in results)) >= 3:
            return results
        if results:
            print(f"WARN [{CINEMA_NAME}]: Selenium returned few days ({len(set(r['date_text'] for r in results))}), trying fallbacks...")
    except Exception as e:
        print(f"WARN [{CINEMA_NAME}]: Selenium scrape failed ({e}), trying fallbacks...")

    # 2. Try Eiga.com
    try:
        eiga_results = _scrape_from_eiga_com()
        if eiga_results:
            return eiga_results
    except Exception as e:
        print(f"WARN [{CINEMA_NAME}]: Eiga.com scrape failed: {e}", file=sys.stderr)

    # 3. Fallback to Jorudan
    return _scrape_from_jorudan(max_days)


# --- CLI test harness ---
if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception: pass

    print(f"Testing {CINEMA_NAME} scraper...")
    data = scrape_polepole(max_days=7)
    
    if data:
        print(f"\nINFO: Collected {len(data)} showings total.")
        # Date breakdown
        dates = sorted(list(set(d['date_text'] for d in data)))
        print(f"Dates covered ({len(dates)}): {dates}")
        
        if len(data) > 0:
            print("\n--- Sample Showing ---")
            from pprint import pprint
            pprint(data[0])
    else:
        print("\nNo showings found.")
