#!/usr/bin/env python3
# yokohama_cinemarine_module.py
# Scraper for Yokohama Cinemarine via Eigaland schedule page.

from __future__ import annotations
import datetime as dt
import re
import sys
import time
from typing import Dict, List

# Selenium
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

CINEMA_NAME = "横浜シネマリン"
SCHEDULE_URL = "https://schedule.eigaland.com/schedule?webKey=4d6c9e5f-bcca-4635-abe4-6f0db498a8bc"

def _init_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)
    return driver

def scrape_yokohama_cinemarine(days_limit: int = 7) -> List[Dict]:
    if not SELENIUM_AVAILABLE:
        print("Selenium not available, skipping Yokohama Cinemarine.", file=sys.stderr)
        return []

    driver = None
    all_shows = []
    
    try:
        driver = _init_driver()
        driver.get(SCHEDULE_URL)
        
        # Wait for the date list to appear
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".calender-head-item")))
        time.sleep(3) 
        
        # Find date buttons
        date_items = driver.find_elements(By.CSS_SELECTOR, ".calender-head-item")
        target_limit = min(len(date_items), days_limit)

        for i in range(target_limit):
            # Re-find items to avoid stale element reference
            date_items = driver.find_elements(By.CSS_SELECTOR, ".calender-head-item")
            if i >= len(date_items): break
            
            item = date_items[i]
            
            # Extract date info
            date_str = ""
            try:
                date_text = item.find_element(By.CSS_SELECTOR, ".date").text.strip()
                month, day = map(int, date_text.split('/'))
                
                today = dt.date.today()
                year = today.year
                if month < today.month: year += 1
                elif month == 12 and today.month == 1: year -= 1
                
                current_date = dt.date(year, month, day)
                date_str = current_date.isoformat()
                
                # Click if not active
                if "active" not in item.get_attribute("class"):
                    driver.execute_script("arguments[0].click();", item)
                    time.sleep(2)
                    
            except Exception:
                continue
            
            # Parse movies list for this date
            # Each movie is in a .movie-schedule-item block
            movie_items = driver.find_elements(By.CSS_SELECTOR, ".movie-schedule-item")
            
            for m_item in movie_items:
                try:
                    # Title is usually in the first span
                    title = m_item.find_element(By.TAG_NAME, "span").text.strip()
                    if not title or title == "NEW": # "NEW" might be a separate span or part of text
                        # Try to find a span with actual title text
                        spans = m_item.find_elements(By.TAG_NAME, "span")
                        for s in spans:
                            t = s.text.strip()
                            if t and t != "NEW":
                                title = t
                                break
                    
                    if not title or title == "NEW": continue

                    # Times are in .slot h2
                    time_els = m_item.find_elements(By.CSS_SELECTOR, ".slot h2")
                    for te in time_els:
                        st = te.text.strip()
                        if st:
                            all_shows.append({
                                "cinema_name": CINEMA_NAME,
                                "movie_title": title,
                                "date_text": date_str,
                                "showtime": st,
                                "detail_page_url": SCHEDULE_URL,
                                "director": "",
                                "year": "",
                                "runtime_min": None
                            })
                except Exception:
                    continue

    except Exception as e:
        print(f"Error scraping {CINEMA_NAME}: {e}", file=sys.stderr)
    finally:
        if driver:
            driver.quit()
            
    # Deduplicate
    unique = []
    seen = set()
    for s in all_shows:
        k = (s['movie_title'], s['date_text'], s['showtime'])
        if k not in seen:
            seen.add(k)
            unique.append(s)
            
    return unique

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except: pass
    
    data = scrape_yokohama_cinemarine()
    print(f"Found {len(data)} shows.")
    import json
    if data:
        print(json.dumps(data[:5], indent=2, ensure_ascii=False)) # Print sample