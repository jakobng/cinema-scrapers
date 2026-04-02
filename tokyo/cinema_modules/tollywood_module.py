import sys
import time
import re
from datetime import datetime, date
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# -------------------------------------------------------------------
# Basic config
# -------------------------------------------------------------------

CINEMA_NAME = "下北沢トリウッド"
TOLLYWOOD_SCHEDULE_URL = "https://tollywood.jp/"

# eiga.com URL for Tollywood (theater code: 3277)
EIGA_COM_TOLLYWOOD_URL = "https://eiga.com/theater/13/130613/3277/"

# How long to wait for elements to appear (Selenium)
DEFAULT_SELENIUM_TIMEOUT = 15

# How many "pages" of the calendar to scrape (Selenium)
MAX_CALENDAR_PAGES = 3  # 3 * 7 = up to 21 days


# -------------------------------------------------------------------
# CSS selectors (eigaland widget structure for Selenium fallback)
# -------------------------------------------------------------------

DATE_ITEM_SELECTOR_CSS = ".calendar-head.component .calender-head-item"
DATE_VALUE_IN_ITEM_SELECTOR_CSS = ".date"
MOVIE_ITEM_BLOCK_SELECTOR_CSS = ".movie-schedule-body .movie-schedule-item"
MOVIE_TITLE_IN_ITEM_BLOCK_SELECTOR_CSS = "h2 span"
SHOWTIME_TABLE_ROWS_SELECTOR_CSS = ".schedule-table tbody tr"
SLOT_CELL_SELECTOR_CSS = "td.slot"
START_TIME_IN_SLOT_SELECTOR_CSS = "h2"
NEXT_BUTTON_SELECTOR_CSS = ".calendar-head.component button.next"


# -------------------------------------------------------------------
# Primary scraping via eiga.com (requests-based, more reliable)
# -------------------------------------------------------------------

def _scrape_from_eiga_com() -> List[Dict]:
    """
    Scrape Tollywood schedule from eiga.com using requests.
    This is faster and more reliable than Selenium-based scraping.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    }

    print(f"Tollywood: Fetching schedule from eiga.com...")
    resp = requests.get(EIGA_COM_TOLLYWOOD_URL, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'html.parser')
    results: List[Dict] = []
    today = date.today()

    # Find all theater-wrapper divs (each contains one movie's schedule)
    wrappers = soup.select('.theater-wrapper')

    for wrapper in wrappers:
        # Get parent section which contains the movie title
        section = wrapper.find_parent('section')
        if not section:
            continue

        # Find movie title (h2 or h3 in section)
        title_el = section.find(['h2', 'h3'])
        if not title_el:
            continue

        movie_title = title_el.get_text(strip=True)
        if not movie_title:
            continue

        # Find detail page link
        detail_url: Optional[str] = None
        movie_link = wrapper.select_one('.movie-image a[href*="/movie/"]')
        if movie_link:
            href = movie_link.get('href', '')
            if href:
                detail_url = 'https://eiga.com' + href

        # Find schedule table
        schedule = wrapper.select_one('.movie-schedule .weekly-schedule')
        if not schedule:
            continue

        # Extract times from table cells
        # Format: "1/7（水） 19:00"
        cells = schedule.select('td, th')
        for cell in cells:
            text = cell.get_text(strip=True)
            match = re.search(r'(\d{1,2})/(\d{1,2})[^0-9]+(\d{1,2}:\d{2})', text)
            if match:
                month, day, showtime = match.groups()
                month = int(month)
                day = int(day)

                # Determine year (handle year rollover)
                year = today.year
                if month < today.month and today.month > 6:
                    year += 1

                date_str = f'{year}-{month:02d}-{day:02d}'

                results.append({
                    "movie_title_uncleaned": movie_title,
                    "date_text": date_str,
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                })

    print(f"Tollywood: Found {len(results)} showings from eiga.com")
    return results


# -------------------------------------------------------------------
# Selenium-based fallback scraping (original approach)
# -------------------------------------------------------------------

def _init_selenium_driver() -> webdriver.Chrome:
    """Create a headless Chrome driver with sensible defaults."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver


def _parse_date_label_mmdd(mmdd_text: str, last_date: Optional[date]) -> date:
    """
    Convert an 'MM/DD' string from the calendar into a date object.
    Handles year rollover (Dec -> Jan) using last_date as reference.
    """
    mmdd_text = mmdd_text.strip()
    try:
        month_str, day_str = mmdd_text.split("/")
        month = int(month_str)
        day = int(day_str)
    except Exception:
        raise ValueError(f"Unexpected date label format: {mmdd_text!r}")

    today = date.today()
    if last_date is None:
        base_year = today.year
    else:
        base_year = last_date.year

    candidate = date(base_year, month, day)

    # If we already had a date and this new one is "earlier" in the calendar,
    # assume we crossed into the next year (e.g., Dec -> Jan).
    if last_date is not None and candidate < last_date:
        candidate = date(base_year + 1, month, day)

    return candidate


def _wait_for_schedule_loaded(driver: webdriver.Chrome) -> None:
    """Wait until the schedule widget is present."""
    WebDriverWait(driver, DEFAULT_SELENIUM_TIMEOUT).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, DATE_ITEM_SELECTOR_CSS)
        )
    )
    WebDriverWait(driver, DEFAULT_SELENIUM_TIMEOUT).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, MOVIE_ITEM_BLOCK_SELECTOR_CSS)
        )
    )


def _scrape_active_day(
    driver: webdriver.Chrome,
    date_iso: str,
) -> List[Dict]:
    """
    Scrape all movie blocks and showtimes for the currently active day
    in the schedule widget, and return a list of raw showtime dicts.
    """
    results: List[Dict] = []

    movie_blocks = driver.find_elements(By.CSS_SELECTOR, MOVIE_ITEM_BLOCK_SELECTOR_CSS)
    for block in movie_blocks:
        try:
            title_el = block.find_element(By.CSS_SELECTOR, MOVIE_TITLE_IN_ITEM_BLOCK_SELECTOR_CSS)
            movie_title = title_el.text.strip()
        except NoSuchElementException:
            continue

        detail_page_url = None
        try:
            link_el = block.find_element(By.CSS_SELECTOR, "h2 a[href]")
            href = link_el.get_attribute("href")
            if href:
                detail_page_url = href
        except NoSuchElementException:
            pass

        rows = block.find_elements(By.CSS_SELECTOR, SHOWTIME_TABLE_ROWS_SELECTOR_CSS)
        for row in rows:
            slot_cells = row.find_elements(By.CSS_SELECTOR, SLOT_CELL_SELECTOR_CSS)
            for slot in slot_cells:
                try:
                    start_el = slot.find_element(By.CSS_SELECTOR, START_TIME_IN_SLOT_SELECTOR_CSS)
                except NoSuchElementException:
                    continue

                showtime = start_el.text.strip()
                if not showtime:
                    continue

                results.append(
                    {
                        "movie_title_uncleaned": movie_title,
                        "date_text": date_iso,
                        "showtime": showtime,
                        "detail_page_url": detail_page_url,
                    }
                )

    return results


def _scrape_tollywood_selenium_once() -> List[Dict]:
    """
    Single attempt to scrape Tollywood via Selenium. May raise exceptions.
    """
    driver = _init_selenium_driver()
    all_results: List[Dict] = []

    try:
        driver.get(TOLLYWOOD_SCHEDULE_URL)
        _wait_for_schedule_loaded(driver)

        last_date: Optional[date] = None

        for page_index in range(MAX_CALENDAR_PAGES):
            date_items = driver.find_elements(By.CSS_SELECTOR, DATE_ITEM_SELECTOR_CSS)
            if not date_items:
                break

            for idx in range(len(date_items)):
                date_items = driver.find_elements(By.CSS_SELECTOR, DATE_ITEM_SELECTOR_CSS)
                if idx >= len(date_items):
                    break

                item = date_items[idx]

                try:
                    date_label_el = item.find_element(By.CSS_SELECTOR, DATE_VALUE_IN_ITEM_SELECTOR_CSS)
                    mmdd_text = date_label_el.text.strip()
                except NoSuchElementException:
                    continue

                current_date = _parse_date_label_mmdd(mmdd_text, last_date)
                last_date = current_date
                date_iso = current_date.isoformat()

                driver.execute_script("arguments[0].click();", item)
                time.sleep(1.0)

                day_results = _scrape_active_day(driver, date_iso)
                all_results.extend(day_results)

            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, NEXT_BUTTON_SELECTOR_CSS)
                if not next_btn.is_enabled():
                    break
                driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(1.5)
            except NoSuchElementException:
                break

    finally:
        driver.quit()

    return all_results


# Maximum number of retry attempts
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def _scrape_tollywood_selenium() -> List[Dict]:
    """
    Drive the Tollywood schedule widget with Selenium (fallback method).
    Includes retry logic to handle transient Selenium/Chrome crashes.
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"Tollywood Selenium scrape attempt {attempt}/{MAX_RETRIES}")
            results = _scrape_tollywood_selenium_once()
            return results
        except Exception as e:
            last_error = e
            print(f"Tollywood Selenium attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                print(f"Retrying in {RETRY_DELAY_SECONDS} seconds...")
                time.sleep(RETRY_DELAY_SECONDS)

    raise last_error  # type: ignore


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def scrape_tollywood_raw() -> List[Dict]:
    """
    Scrape Tollywood schedule data using the best available method.

    Primary: eiga.com (fast, reliable, uses requests)
    Fallback: tollywood.jp via Selenium (if eiga.com fails)

    Returns raw showtime dicts with:
        movie_title_uncleaned, date_text, showtime, detail_page_url
    """
    # Try eiga.com first (primary method)
    try:
        results = _scrape_from_eiga_com()
        if results:
            return results
        print("Tollywood: eiga.com returned no results, trying Selenium fallback...")
    except Exception as e:
        print(f"Tollywood: eiga.com scrape failed ({e}), trying Selenium fallback...")

    # Fallback to Selenium-based scraping
    return _scrape_tollywood_selenium()


def scrape_tollywood() -> List[Dict]:
    """
    Return Tollywood showtimes in the same schema as other cinema modules:
        cinema_name, movie_title, movie_title_en, director, year,
        country, runtime_min, date_text, showtime, detail_page_url,
        program_title, purchase_url
    """
    raw = scrape_tollywood_raw()
    result: List[Dict] = []

    for r in raw:
        result.append(
            {
                "cinema_name": CINEMA_NAME,
                "movie_title": r.get("movie_title_uncleaned", "").strip() or None,
                "movie_title_en": None,
                "director": None,
                "year": None,
                "country": None,
                "runtime_min": None,
                "date_text": r.get("date_text"),
                "showtime": r.get("showtime"),
                "detail_page_url": r.get("detail_page_url"),
                "program_title": None,
                "purchase_url": None,
            }
        )

    return result


# -------------------------------------------------------------------
# CLI test
# -------------------------------------------------------------------

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    showtimes = scrape_tollywood()
    print(f"\nFound {len(showtimes)} showings for {CINEMA_NAME}:")
    for row in showtimes:
        print(f"  {row['date_text']} {row['showtime']} - {row['movie_title']}")
