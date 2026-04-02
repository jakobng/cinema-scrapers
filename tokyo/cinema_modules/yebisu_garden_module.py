# yebisu_garden_module.py (Enhanced Title Cleaning)

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import time
from typing import Dict, List

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ──────────────────────────────────────────────────────────────
CINEMA_NAME = "YEBISU GARDEN CINEMA"
BASE_URL = "https://www.unitedcinemas.jp/ygc"
DAILY_URL = BASE_URL + "/daily.php?date={}"
DAYS_AHEAD = 5

_SCREEN_RE = re.compile(r"(\d)screen")
_YEAR_RE = re.compile(r"(\d{4})")
# IMPROVEMENT: Regex to find year in synopsis as a fallback.
_YEAR_IN_SYNOPSIS_RE = re.compile(r"(\d{4})年製作")

# ──────────────────────────────────────────────────────────────
def _clean_title(text: str) -> str:
    """
    Cleans Yebisu titles by removing quotes, parentheses, and technical suffixes.
    FIXED: Now removes suffixes FIRST so wrapping quotes can be detected.
    """
    if not text: return ""
    
    # 1. Strip Technical Suffixes (Aggressive) - ORDER CHANGED to First
    # This ensures "『Title』 4K" becomes "『Title』" so step 4 catches it.
    patterns = [
        r"\s*4K.*$",               # Matches "4K", "4K レストア", "4K Restored"
        r"\s*デジタル.?リマスター.*$", # Matches "デジタルリマスター", "デジタル・リマスター版"
        r"\s*レストア.*$",           # Matches "レストア版"
        r"\s*完全版.*$",
        r"\s*ディレクターズ.?カット.*$"
    ]
    
    for pat in patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    
    # 2. Remove parentheses content (e.g. (字幕), (吹替))
    text = re.sub(r"\s*[（(].*?[)）]\s*", "", text)
    
    # 3. Clean up whitespace
    text = text.strip()
    
    # 4. Remove wrapping Japanese quotes
    # Now that suffixes are gone, this will correctly match "『Title』"
    if text.startswith("『") and text.endswith("』"):
        text = text[1:-1]
    
    # Remove standard double quotes just in case
    text = text.replace('"', '').strip()
        
    return text.strip()
# ──────────────────────────────────────────────────────────────
def _parse_film_details(html: str) -> Dict:
    soup = BeautifulSoup(html, "html.parser")
    details = { "director": None, "synopsis": None, "year": None, "official_site": None }

    director_dt = soup.find("dt", string=re.compile("監督"))
    if director_dt and director_dt.find_next_sibling("dd"):
        details["director"] = director_dt.find_next_sibling("dd").get_text(strip=True)

    synopsis_tag = soup.select_one("div.movieDetailInfoFilm > p:not([class])")
    if synopsis_tag:
        details["synopsis"] = synopsis_tag.get_text(strip=True)

    # --- YEAR EXTRACTION LOGIC ---
    # Method 1: Check the copyright tag first (preferred method).
    copyright_tag = soup.select_one("span.copy")
    if copyright_tag:
        match = _YEAR_RE.search(copyright_tag.get_text())
        if match:
            details["year"] = match.group(1)

    # Method 2 (FALLBACK): If year not found, check the synopsis text.
    if not details["year"] and details["synopsis"]:
        match = _YEAR_IN_SYNOPSIS_RE.search(details["synopsis"])
        if match:
            details["year"] = match.group(1)
            print(f"INFO   : Found year '{details['year']}' in synopsis as fallback.")

    site_link_tag = soup.select_one("div#movieSubInfo a.btn.bt_s")
    if site_link_tag and site_link_tag.has_attr("href"):
        details["official_site"] = site_link_tag["href"]

    return details

# ──────────────────────────────────────────────────────────────
def _parse_daily_showtimes(html: str, date_obj: _dt.date) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict] = []

    for film_li in soup.select("ul#dailyList li.clearfix"):
        link_tag = film_li.select_one("h3 span.movieTitle a")
        if not link_tag: continue

        raw_title = link_tag.get_text(strip=True)
        # Apply the new cleaning function
        title = _clean_title(raw_title)

        detail_url = None
        if link_tag.has_attr("href"):
            href = link_tag['href']
            base_href = href.split('?')[0]
            film_param = next((part for part in href.split('?') if part.startswith("film=")), None)

            clean_href = f"{base_href}?{film_param}" if film_param else base_href
            detail_url = f"{BASE_URL}/{clean_href}" if 'film.php' in clean_href else clean_href

        screen_alt = (film_li.select_one("p.screenNumber img[alt*='screen']") or {}).get("alt", "")
        m = _SCREEN_RE.search(screen_alt)
        screen = f"スクリーン{m.group(1)}" if m else "スクリーン"

        for st in film_li.select("li.startTime"):
            showtime = st.get_text(strip=True)
            if showtime:
                rows.append(dict(movie_title=title, date_text=str(date_obj), screen_name=screen, showtime=showtime, detail_page_url=detail_url))
    return rows

# ───── Selenium helpers ───────────────────────────────────────
def _init_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_experimental_option('excludeSwitches', ['enable-logging'])

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(40)
    return driver

def _wait_for_schedule(drv: webdriver.Chrome, timeout: int = 15) -> None:
    sel = "ul#dailyList li.clearfix"
    WebDriverWait(drv, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))

# ───── public API ─────────────────────────────────────────────
def scrape_yebisu_garden_cinema(days_ahead: int = DAYS_AHEAD) -> List[Dict]:
    all_showings: List[Dict] = []
    film_details_cache: Dict[str, Dict] = {}
    today = _dt.date.today()
    driver = None

    try:
        driver = _init_driver()
        for offset in range(days_ahead):
            date_obj = today + _dt.timedelta(days=offset)
            url = DAILY_URL.format(date_obj.isoformat())
            print(f"INFO   : GET {url} for {CINEMA_NAME}")

            try:
                driver.get(url)
                _wait_for_schedule(driver)
            except TimeoutException:
                print(f"WARNING: Schedule not found or page timed out for {date_obj} at {CINEMA_NAME} – skipping day")
                continue

            daily_showings = _parse_daily_showtimes(driver.page_source, date_obj)

            urls_to_scrape = {s['detail_page_url'] for s in daily_showings if s.get('detail_page_url') and s['detail_page_url'] not in film_details_cache}

            if urls_to_scrape:
                print(f"INFO   : Found {len(urls_to_scrape)} new movie(s) to get details for.")
            for film_url in urls_to_scrape:
                print(f"INFO   : Scraping details from: {film_url}")
                try:
                    driver.get(film_url)
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "detailBox")))
                    details = _parse_film_details(driver.page_source)
                    film_details_cache[film_url] = details
                except TimeoutException:
                    print(f"WARNING: Could not load detail page {film_url} in time.")
                    film_details_cache[film_url] = {} # Cache failure to avoid retries
                time.sleep(0.5)

            for showing in daily_showings:
                if showing.get('detail_page_url') in film_details_cache:
                    showing.update(film_details_cache[showing['detail_page_url']])
                showing['cinema_name'] = CINEMA_NAME

            all_showings.extend(daily_showings)
            time.sleep(0.7)
    finally:
        if driver:
            driver.quit()

    print(f"INFO   : Collected {len(all_showings)} showings total from {CINEMA_NAME}.")
    return all_showings

if __name__ == "__main__":
    data = scrape_yebisu_garden_cinema()

    if not data:
        print(f"No data collected for {CINEMA_NAME}.")
        sys.exit(1)

    output_filename = "yebisu_showtimes.json"
    print(f"INFO   : Writing {len(data)} records to {output_filename}...")
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"INFO   : Successfully created {output_filename}.")