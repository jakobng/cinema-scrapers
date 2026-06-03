# -*- coding: utf-8 -*-
import sys
import os
import time
import re
from datetime import datetime, date, timedelta, timezone

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# --- Start: Configure stdout and stderr for UTF-8 on Windows ---
if __name__ == "__main__" and sys.platform == "win32":
    try:
        if sys.stdout.encoding != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
# --- End: Configure stdout and stderr ---

CINEMA_NAME_KY = "Kadokawa Cinema Yurakucho (角川シネマ有楽町)"
URL_KY = "https://www.kadokawa-cinema.jp/theaters/yurakucho/"
BASE_URL_KY = "https://www.kadokawa-cinema.jp"
THEATER_CODE_KY = "017"
JST = timezone(timedelta(hours=9))

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()

def _request_json(path):
    url = path if path.startswith("http") else f"{BASE_URL_KY}{path}"
    response = requests.get(
        url,
        headers={'User-Agent': 'Mozilla/5.0'},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()

def _parse_iso_to_jst(value):
    if not value:
        return None
    normalized = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).astimezone(JST)
    except ValueError:
        return None

def _duration_to_minutes(value):
    if not value:
        return ""
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", str(value))
    if not match:
        return ""
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    total = hours * 60 + minutes
    return str(total) if total else ""

def _localized_name(value):
    if isinstance(value, dict):
        return clean_text(value.get("ja") or value.get("en") or "")
    return clean_text(value)

def _entry_to_showing(entry, fallback_date, fallback_time):
    title = _localized_name(entry.get("name"))
    if not title:
        return None

    start = _parse_iso_to_jst(entry.get("startDate"))
    date_text = start.date().isoformat() if start else fallback_date
    showtime = start.strftime("%H:%M") if start else f"{fallback_time[:2]}:{fallback_time[2:]}"
    runtime_min = _duration_to_minutes((entry.get("workPerformed") or {}).get("duration"))

    return {
        "cinema_name": CINEMA_NAME_KY,
        "date_text": date_text,
        "movie_title": title,
        "showtime": showtime,
        "year": date_text.split("-")[0] if date_text else "",
        "runtime_min": runtime_min,
        "detail_page_url": URL_KY,
    }

def _scrape_kadokawa_json(max_days=7):
    today = date.today()
    end_date = today + timedelta(days=max_days - 1)
    schedule_index = _request_json("/schedule/data/schedule.json")
    showings = []

    for movie_id, theaters in schedule_index.items():
        dates = theaters.get(THEATER_CODE_KY, {})
        for yyyymmdd, times in dates.items():
            try:
                show_date = datetime.strptime(yyyymmdd, "%Y%m%d").date()
            except ValueError:
                continue
            if not (today <= show_date <= end_date):
                continue

            detail_path = f"/schedule/data/{movie_id}/{THEATER_CODE_KY}/{yyyymmdd}.json"
            try:
                detail_data = _request_json(detail_path)
            except requests.RequestException as e:
                print(f"Error fetching Kadokawa schedule detail {detail_path}: {e}", file=sys.stderr)
                detail_data = times

            for time_key, rooms in detail_data.items():
                if isinstance(rooms, list):
                    entries = rooms
                elif isinstance(rooms, dict):
                    entries = list(rooms.values())
                else:
                    continue
                for entry in entries:
                    showing = _entry_to_showing(entry, show_date.isoformat(), str(time_key))
                    if showing:
                        showings.append(showing)

    return _dedupe_showings(showings)

def get_headless_driver():
    cache_dir = os.path.join(os.getcwd(), ".selenium-cache")
    os.makedirs(cache_dir, exist_ok=True)
    os.environ.setdefault("SE_CACHE_PATH", cache_dir)

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--remote-debugging-port=0")
    chrome_options.add_argument("--window-size=1280,1000")
    chrome_options.add_argument(f"--user-data-dir={os.path.join(cache_dir, 'chrome-profile')}")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

def _parse_date_mmdd(text, today):
    if not text:
        return ""
    normalized = clean_text(str(text))
    normalized = normalized.translate(str.maketrans("０１２３４５６７８９", "0123456789")).replace("／", "/")

    iso_match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', normalized)
    if iso_match:
        year, month, day_val = map(int, iso_match.groups())
        return f"{year:04d}-{month:02d}-{day_val:02d}"

    match = re.search(r'(\d{1,2})/(\d{1,2})', normalized)
    if not match:
        return ""

    month, day_val = int(match.group(1)), int(match.group(2))
    year = today.year
    if month < today.month and (today.month - month) > 6:
        year += 1
    elif month > today.month and (month - today.month) > 6:
        year -= 1
    return f"{year}-{month:02d}-{day_val:02d}"

def _collect_date_tabs(driver):
    selectors = [".schedule-swiper__item", ".schedule-date-item", ".schedule-tab__item", ".schedule-tab li", "[data-date]", "[data-day]"]
    for selector in selectors:
        items = driver.find_elements(By.CSS_SELECTOR, selector)
        dated_items = [item for item in items if _parse_date_mmdd(item.text, date.today())]
        if dated_items:
            return dated_items
    return driver.find_elements(By.XPATH, "//*[contains(@class,'date') and contains(text(),'/')]")

def _extract_title_from_block(block):
    for selector in ["a.title", ".item-title", ".item-title .title", ".title", "h3", "h4", "a[href*='/movie/']"]:
        title_tag = block.select_one(selector)
        if not title_tag:
            continue
        title = clean_text(title_tag.get_text())
        if title:
            return title
    return ""

def _extract_times_from_block(block):
    times = []
    for selector in [".schedule-item .time span", ".schedule-item .time", ".time span", ".time", "time"]:
        for node in block.select(selector):
            text = clean_text(node.get_text()).replace("：", ":").translate(str.maketrans("０１２３４５６７８９", "0123456789"))
            for h, m in re.findall(r"(\d{1,2}):(\d{2})", text):
                t = f"{int(h):02d}:{m}"
                if t not in times:
                    times.append(t)
    if times:
        return times
    text = clean_text(block.get_text(" ", strip=True)).replace("：", ":").translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    for h, m in re.findall(r"(\d{1,2}):(\d{2})", text):
        t = f"{int(h):02d}:{m}"
        if t not in times:
            times.append(t)
    return times

def _find_movie_blocks(root):
    block_selectors = [
        ".tab_content-wrap > .content-item[data-order]",
        ".tab-content-wrap > .content-item[data-order]",
        ".content-item",
        ".movie-schedule-item",
        ".schedule-item",
        ".movie-item",
        "li.movie",
        "article.movie",
    ]
    for selector in block_selectors:
        blocks = root.select(selector)
        if blocks:
            return blocks
    return []

def _build_showings_from_blocks(blocks, date_str):
    showings = []
    year_val = date_str.split("-")[0] if date_str else ""
    for block in blocks:
        title = _extract_title_from_block(block)
        if not title:
            continue
        for showtime in _extract_times_from_block(block):
            showings.append({
                "cinema_name": CINEMA_NAME_KY,
                "date_text": date_str,
                "movie_title": title,
                "showtime": showtime,
                "year": year_val,
                "detail_page_url": URL_KY
            })
    return showings

def _parse_showings_from_soup(soup, date_str, today):
    if date_str:
        return _build_showings_from_blocks(_find_movie_blocks(soup), date_str)

    showings = []
    date_sections = soup.select("[data-date], [data-day]")
    for section in date_sections:
        section_date = _parse_date_mmdd(
            " ".join(
                [
                    section.get("data-date") or "",
                    section.get("data-day") or "",
                    section.get_text(" ", strip=True),
                ]
            ),
            today,
        )
        if not section_date:
            continue
        blocks = _find_movie_blocks(section)
        if blocks:
            showings.extend(_build_showings_from_blocks(blocks, section_date))

    if showings:
        return showings

    fallback_date = _parse_date_mmdd(soup.get_text(" ", strip=True), today)
    if fallback_date:
        return _build_showings_from_blocks(_find_movie_blocks(soup), fallback_date)
    return []

def _dedupe_showings(showings):
    unique_showings = []
    seen = set()
    for s in showings:
        tup = (s.get('date_text'), s.get('movie_title'), s.get('showtime'))
        if tup not in seen:
            unique_showings.append(s)
            seen.add(tup)
    return unique_showings

def scrape_kadokawa_yurakucho(max_days=7):
    try:
        json_showings = _scrape_kadokawa_json(max_days=max_days)
        if json_showings:
            print(f"Using Kadokawa JSON schedule: {len(json_showings)} showings.")
            return json_showings
        print("Kadokawa JSON schedule returned no showings; falling back to Selenium.")
    except Exception as e:
        print(f"Error in Kadokawa JSON schedule scrape: {e}; falling back to Selenium.")

    showings = []
    driver = None
    try:
        driver = get_headless_driver()
        driver.get(URL_KY)
        
        wait = WebDriverWait(driver, 20)
        # Wait for schedule swiper and content to appear
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".schedule-swiper__item, .schedule-swiper .swiper-slide, .tab_content-wrap, .tab-content-wrap, .content-item, .movie-schedule-item")
            )
        )
        
        # 1. Find Date Tabs
        date_tabs = _collect_date_tabs(driver)
        print(f"Found {len(date_tabs)} date tabs.")
        
        today = date.today()
        if not date_tabs:
            soup = BeautifulSoup(driver.page_source, "html.parser")
            showings.extend(_parse_showings_from_soup(soup, "", today))
            date_tabs = []
        
        for i in range(min(len(date_tabs), max_days)):
            # Re-find tabs to avoid stale element exception
            tabs = _collect_date_tabs(driver)
            if i >= len(tabs):
                break
            tab = tabs[i]
            
            # Extract date from tab
            try:
                tab_date_attr = " ".join(
                    [
                        tab.get_attribute("data-date") or "",
                        tab.get_attribute("data-day") or "",
                        tab.get_attribute("aria-label") or "",
                    ]
                )
                try:
                    day_text = tab.find_element(By.CLASS_NAME, "day").text.strip() # "01/14"
                except Exception:
                    day_text = tab.text.strip()
                date_str = _parse_date_mmdd(f"{tab_date_attr} {day_text}", today)
                if not date_str:
                    date_str = _parse_date_mmdd(tab.text.strip(), today)

                print(f"Processing {date_str or 'unknown date tab'}...")

                # Click the tab
                driver.execute_script("arguments[0].click();", tab)
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".tab_content-wrap, .tab-content-wrap, .content-item, .movie-schedule-item"))
                    )
                except Exception:
                    pass
                time.sleep(1) # Allow any lazy content to settle

                # Parse current page content
                soup = BeautifulSoup(driver.page_source, "html.parser")
                showings.extend(_parse_showings_from_soup(soup, date_str or "", today))
            except Exception as e:
                print(f"Error processing tab {i}: {e}")
                continue

        if not showings:
            soup = BeautifulSoup(driver.page_source, "html.parser")
            showings.extend(_parse_showings_from_soup(soup, "", today))
                
    except Exception as e:
        print(f"Error in scrape_kadokawa_yurakucho: {e}")
    finally:
        if driver:
            driver.quit()
            
    return _dedupe_showings(showings)

if __name__ == "__main__":
    results = scrape_kadokawa_yurakucho()
    for s in sorted(results, key=lambda x: (x['date_text'], x['showtime'])):
        print(f"{s['date_text']} | {s['showtime']} | {s['movie_title']}")
