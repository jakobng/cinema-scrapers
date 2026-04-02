#!/usr/bin/env python3
# cinemalice_module.py — Rev-2 (2026-01-08)
#
# Scraper for シネマリス (CineMalice) - https://cinemalice.theater/
# A new mini-theater in Tokyo that opened December 2025.
#
# This scraper uses Selenium to render the JavaScript-based schedule page
# and extract actual showtimes. Falls back to date-range extraction if
# Selenium is not available.
# ---------------------------------------------------------------------

from __future__ import annotations

import datetime as dt
import re
import sys
import time
from typing import Dict, List, Optional

import requests

# Selenium imports (optional - graceful fallback if not available)
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        NoSuchElementException,
        TimeoutException,
        WebDriverException
    )
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

CINEMA_NAME = "シネマリス"
BASE_URL = "https://cinemalice.theater"
SCHEDULE_URL = f"{BASE_URL}/schedules"
HEADERS = {"User-Agent": "Mozilla/5.0 (CineMaliceScraper/2026)"}
TIMEOUT = 30
SELENIUM_TIMEOUT = 15
MAX_RETRIES = 3

TODAY = dt.date.today()
WINDOW_DAYS = 7


# ---------------------------------------------------------------------
# Selenium-based scraping (primary method)
# ---------------------------------------------------------------------

def _init_selenium_driver() -> "webdriver.Chrome":
    """Create a headless Chrome driver with sensible defaults."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver


def _scrape_with_selenium() -> List[Dict]:
    """
    Scrape CineMalice schedule using Selenium to render the React page.
    Iterates through date buttons to load each day's schedule.
    Returns list of showtime dictionaries.
    """
    if not SELENIUM_AVAILABLE:
        print(f"WARNING: [{CINEMA_NAME}] Selenium not available, skipping browser-based scraping",
              file=sys.stderr)
        return []

    driver = None
    results: List[Dict] = []

    try:
        print(f"{CINEMA_NAME}: Initializing Selenium driver...")
        driver = _init_selenium_driver()

        print(f"{CINEMA_NAME}: Loading schedule page...")
        driver.get(SCHEDULE_URL)

        # Wait for the page to load
        wait = WebDriverWait(driver, SELENIUM_TIMEOUT)
        time.sleep(5)  # Allow ample time for React hydration and content rendering

        # Find the container for date buttons (grid with 7 columns)
        try:
            date_grid = driver.find_element(By.XPATH, "//div[contains(@class, 'grid') and contains(@class, 'grid-cols-7')]")
            # Get the number of buttons to iterate
            buttons = date_grid.find_elements(By.TAG_NAME, "button")
            button_count = len(buttons)
            print(f"{CINEMA_NAME}: Found {button_count} date buttons")
        except NoSuchElementException:
            print(f"{CINEMA_NAME}: Could not find date button grid, scraping current view only")
            button_count = 0

        # If no buttons found, we run the loop once (index -1) to scrape whatever is visible
        loop_range = range(button_count) if button_count > 0 else [-1]

        for i in loop_range:
            # If we are iterating buttons, click the next one
            if i >= 0:
                try:
                    # Re-find grid and buttons to avoid stale elements
                    date_grid = driver.find_element(By.XPATH, "//div[contains(@class, 'grid') and contains(@class, 'grid-cols-7')]")
                    buttons = date_grid.find_elements(By.TAG_NAME, "button")
                    
                    if i < len(buttons):
                        button = buttons[i]
                        # Scroll into view just in case
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                        button.click()
                        time.sleep(1.5) # Wait for React state update
                except Exception as e:
                    print(f"{CINEMA_NAME}: Error clicking button {i}: {e}")
                    continue

            # Find all date blocks (usually only one visible after clicking)
            # Structure: <div class="overflow-hidden rounded-[20px]"> ... </div>
            date_blocks = driver.find_elements(By.XPATH, 
                "//div[contains(@class, 'overflow-hidden') and contains(@class, 'rounded-[20px]')]")
            
            for block in date_blocks:
                try:
                    # Extract Date from Header
                    # Header: <div class="bg-beige-600 ...">
                    header = block.find_element(By.XPATH, ".//div[contains(@class, 'bg-beige-600')]")
                    
                    # The date parts are in child divs. 
                    month_text = header.find_element(By.XPATH, "./div[1]").text.strip()
                    day_text = header.find_element(By.XPATH, "./div[3]").text.strip()
                    
                    if not month_text.isdigit() or not day_text.isdigit():
                        continue
                        
                    month = int(month_text)
                    day = int(day_text)

                    # Determine year
                    year = TODAY.year
                    if month < TODAY.month and (TODAY.month - month) > 6:
                         year += 1
                    if TODAY.month == 12 and month == 1:
                        year += 1
                    
                    date_str = f"{year}-{month:02d}-{day:02d}"

                    # Extract Movies from Content
                    content = block.find_element(By.XPATH, ".//div[contains(@class, 'bg-white')]")
                    
                    # Target desktop container
                    movie_containers = content.find_elements(By.CSS_SELECTOR, "div.hidden.md\\:block")
                    
                    for container in movie_containers:
                        try:
                            title_el = container.find_element(By.TAG_NAME, "h3")
                            title = title_el.text.strip()
                            
                            if not title:
                                continue

                            # Showtimes
                            time_els = container.find_elements(By.CSS_SELECTOR, "div.text-\\[20px\\]")
                            
                            for time_el in time_els:
                                time_text = time_el.text.strip()
                                if not re.match(r'^\d{1,2}:\d{2}$', time_text):
                                    continue
                                
                                results.append({
                                    "cinema_name": CINEMA_NAME,
                                    "movie_title": title,
                                    "movie_title_en": "",
                                    "date_text": date_str,
                                    "showtime": time_text,
                                    "director": "",
                                    "year": "",
                                    "country": "",
                                    "runtime_min": None,
                                    "synopsis": "",
                                    "detail_page_url": SCHEDULE_URL,
                                })
                                
                        except NoSuchElementException:
                            continue
                            
                except (NoSuchElementException, ValueError, IndexError) as e:
                    continue

        print(f"{CINEMA_NAME}: Selenium scraping found {len(results)} showings")
        return results

    except TimeoutException:
        print(f"ERROR: [{CINEMA_NAME}] Selenium timed out loading page", file=sys.stderr)
        return []
    except WebDriverException as e:
        print(f"ERROR: [{CINEMA_NAME}] Selenium WebDriver error: {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"ERROR: [{CINEMA_NAME}] Selenium scraping failed: {e}", file=sys.stderr)
        return []
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------
# Fallback: RSC payload extraction (date ranges only)
# ---------------------------------------------------------------------

def _fetch_page(url: str) -> Optional[str]:
    """Fetch page HTML content."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        return resp.text
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def _extract_screenings_data(html: str) -> List[Dict]:
    """
    Extract movie data from the React Server Component payload.
    The data is embedded as escaped JSON in the page.
    """
    idx = html.find('cmsScreeningsData')
    if idx == -1:
        print(f"ERROR: [{CINEMA_NAME}] Could not find cmsScreeningsData in page", file=sys.stderr)
        return []

    chunk = html[idx:idx+100000]
    movies = []

    # Pattern for escaped JSON
    escaped_pattern = '\\"title\\"' in chunk

    if escaped_pattern:
        title_matches = re.findall(r'\\"title\\":\\"([^\\]+)\\"', chunk)
        director_matches = re.findall(r'\\"director\\":\\"([^\\]*)\\"', chunk)
        runtime_matches = re.findall(r'\\"screeningTimes\\":\\"([^\\]*)\\"', chunk)
        date_from_matches = re.findall(r'\\"releaseDateFrom\\":\\"([^\\]+)\\"', chunk)
        date_to_matches = re.findall(r'\\"releaseDateTo\\":\\"([^\\]+)\\"', chunk)
        website_matches = re.findall(r'\\"website\\":\\"([^\\]*)\\"', chunk)
        slug_matches = re.findall(r'\\"slug\\":\\"([^\\]+)\\"', chunk)
    else:
        title_matches = re.findall(r'"title":"([^"]+)"', chunk)
        director_matches = re.findall(r'"director":"([^"]*)"', chunk)
        runtime_matches = re.findall(r'"screeningTimes":"([^"]*)"', chunk)
        date_from_matches = re.findall(r'"releaseDateFrom":"([^"]+)"', chunk)
        date_to_matches = re.findall(r'"releaseDateTo":"([^"]+)"', chunk)
        website_matches = re.findall(r'"website":"([^"]*)"', chunk)
        slug_matches = re.findall(r'"slug":"([^"]+)"', chunk)

    for i, title in enumerate(title_matches):
        movie = {'title': title}
        if i < len(director_matches):
            movie['director'] = director_matches[i]
        if i < len(runtime_matches):
            movie['runtime'] = runtime_matches[i]
        if i < len(date_from_matches):
            movie['date_from'] = date_from_matches[i]
        if i < len(date_to_matches):
            movie['date_to'] = date_to_matches[i]
        if i < len(website_matches):
            movie['website'] = website_matches[i]
        if i < len(slug_matches):
            movie['slug'] = slug_matches[i]
        movies.append(movie)

    return movies


def _parse_runtime(runtime_str: str) -> Optional[str]:
    """Extract numeric runtime from string like '106分'."""
    if not runtime_str:
        return None
    match = re.search(r'(\d+)', runtime_str)
    return match.group(1) if match else None


def _generate_daily_entries(movie: Dict) -> List[Dict]:
    """
    Generate showtime entries for each day within the movie's screening period.
    Used as fallback when Selenium can't get actual showtimes.
    """
    entries = []

    if 'date_from' not in movie or 'date_to' not in movie:
        return entries

    try:
        date_from = dt.date.fromisoformat(movie['date_from'])
        date_to = dt.date.fromisoformat(movie['date_to'])
    except ValueError:
        return entries

    window_end = TODAY + dt.timedelta(days=WINDOW_DAYS)
    current_date = max(date_from, TODAY)
    end_date = min(date_to, window_end)

    while current_date <= end_date:
        entry = {
            "cinema_name": CINEMA_NAME,
            "movie_title": movie.get('title', ''),
            "movie_title_en": "",
            "date_text": current_date.isoformat(),
            "showtime": "スケジュール確認",  # Fallback: "Check schedule"
            "director": movie.get('director', ''),
            "year": "",
            "country": "",
            "runtime_min": _parse_runtime(movie.get('runtime', '')),
            "synopsis": "",
            "detail_page_url": movie.get('website', '') or f"{BASE_URL}/movie/{movie.get('slug', '')}",
        }
        entries.append(entry)
        current_date += dt.timedelta(days=1)

    return entries


def _scrape_fallback() -> List[Dict]:
    """Fallback scraper using RSC payload extraction (date ranges only)."""
    html = _fetch_page(SCHEDULE_URL)
    if not html:
        return []

    movies = _extract_screenings_data(html)
    if not movies:
        print(f"WARNING: [{CINEMA_NAME}] No movies found in schedule", file=sys.stderr)
        return []

    all_entries = []
    for movie in movies:
        entries = _generate_daily_entries(movie)
        all_entries.extend(entries)

    return all_entries


# ---------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------

def scrape_cinemalice(max_days: int = 7) -> List[Dict[str, str]]:
    """
    Scrape シネマリス (CineMalice) schedule.

    Primary: Uses Selenium to render JavaScript and extract actual showtimes.
    Fallback: Extracts date ranges from RSC payload if Selenium unavailable.

    Returns a list of showtime dictionaries with standard schema.
    """
    global WINDOW_DAYS, TODAY
    WINDOW_DAYS = max_days
    TODAY = dt.date.today()

    all_entries = []

    # Try Selenium first for actual showtimes
    if SELENIUM_AVAILABLE:
        for attempt in range(MAX_RETRIES):
            try:
                all_entries = _scrape_with_selenium()
                if all_entries:
                    break
            except Exception as e:
                print(f"WARNING: [{CINEMA_NAME}] Selenium attempt {attempt + 1} failed: {e}",
                      file=sys.stderr)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2)

    # Fall back to RSC payload extraction if Selenium didn't work
    if not all_entries:
        print(f"{CINEMA_NAME}: Falling back to date-range extraction...")
        all_entries = _scrape_fallback()

    # Deduplicate (same movie, same date, same time)
    seen = set()
    unique_entries = []
    for entry in all_entries:
        key = (entry["movie_title"], entry["date_text"], entry.get("showtime", ""))
        if key not in seen:
            seen.add(key)
            unique_entries.append(entry)

    # Sort by date, then time, then title
    unique_entries.sort(key=lambda x: (
        x.get("date_text", ""),
        x.get("showtime", "ZZZ"),  # Put "スケジュール確認" at end
        x.get("movie_title", "")
    ))

    print(f"{CINEMA_NAME}: Returning {len(unique_entries)} showings")
    return unique_entries


# ---------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------

if __name__ == "__main__":
    import json as json_module
    from pathlib import Path

    showings = scrape_cinemalice()
    if showings:
        out_path = Path(__file__).with_name("cinemalice_schedule_TEST.json")
        out_path.write_text(json_module.dumps(showings, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Test run successful. Saved {len(showings)} showtimes → {out_path}")
    else:
        print("No showtimes found.")
