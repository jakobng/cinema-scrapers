# cinemart_shinjuku_module.py
# v3: Added a third regex pattern to handle pipe-separated metadata (e.g., 2023|韓国|124分).

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# --- Constants ---
CINEMA_NAME = "シネマート新宿"
SCHEDULE_URL = "https://cinemart.cineticket.jp/theater/shinjuku/schedule"
MOVIE_LIST_URL = "https://www.cinemart.co.jp/theater/shinjuku/movie/"
BASE_DETAIL_URL = "https://www.cinemart.co.jp/theater/shinjuku/movie/"

# --- Helper Functions ---

def _init_driver() -> webdriver.Chrome:
    """Initializes a headless Chrome WebDriver."""
    chrome_options = ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception:
        driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(40)
    return driver

def _clean_text(text: Optional[str]) -> str:
    """Normalizes whitespace for display text."""
    if not text: return ""
    return " ".join(text.strip().split())

def _get_title_key(raw_title: str) -> str:
    """Creates a consistent key from a movie title by cleaning it."""
    if not raw_title:
        return ""

    title = str(raw_title)

    # Normalise some punctuation and whitespace
    title = title.replace("／", "/")  # full-width slash → ASCII
    title = title.replace("　", " ")  # full-width space → normal space

    # Drop bracketed notes like 【4K上映】, 『…』, 《…》, （…）
    # (The content itself is almost never part of the "base" film title.)
    title = re.sub(r'[【《「『〈(（][^】》」』〉)）]*[】》」』〉)）]', '', title)

    # Remove common suffix-style annotations (formats, events, etc.)
    suffix_patterns = [
        r"(4K|４Ｋ)[^/]*$",                       # any trailing 4K annotation
        r"(デジタル・?リマスター版?)$",          # digital remaster / remastered
        r"(レストア版)$",
        r"(字幕版|吹替版|日本語吹替版)$",
        r"(上映後トークショー.*)$",
        r"(舞台挨拶.*)$",
        r"(特別上映.*)$",
        r"(先行上映.*)$",
    ]
    for pat in suffix_patterns:
        title = re.sub(pat, "", title)

    # Preserve your existing specific cleanups
    suffixes_to_remove = [
        "※HDリマスター版", "※HDリマスター版上映", "4Kレストア版",
        "/ポイント・ブランク", "上映後トークショー"
    ]
    for suffix in suffixes_to_remove:
        title = title.replace(suffix, "")

    return _clean_text(title)


def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a static URL and returns a BeautifulSoup object."""
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch static page {url}: {e}", file=sys.stderr)
        return None

# --- Scraping Logic ---

def _parse_detail_page(soup: BeautifulSoup) -> Dict[str, str | None]:
    """
    Parses a movie detail page from cinemart.co.jp.
    Extracts director, year, runtime, country, and synopsis.
    """
    details: Dict[str, Optional[str]] = {
        "director": None,
        "year": None,
        "runtime_min": None,
        "country": None,
        "synopsis": None,
    }

    # -----------------------
    # Synopsis
    # -----------------------
    summary_div = soup.find("div", class_="movieSummary")
    summary_text = None
    if summary_div:
        summary_text = summary_div.get_text(separator=" ")
        details["synopsis"] = _clean_text(summary_div.get_text(separator="\n"))

    # -----------------------
    # Helper: parse compact metadata
    # -----------------------
    def _apply_compact_meta_patterns(full_text: str) -> None:
        nonlocal details
        if not full_text:
            return

        text = full_text

        # ---- Pattern A ----
        # 2024/98分/アイルランド/...
        m = re.search(r"(\d{4})\s*/\s*(\d+)\s*分\s*/\s*([^/]+)", text)
        if m:
            year, runtime, country = m.groups()

            if not details["year"]:
                details["year"] = year

            if not details["runtime_min"]:
                details["runtime_min"] = runtime

            if not details["country"]:
                country_clean = country
                for junk in ["カラー", "モノクロ", "白黒", "製作", "合作"]:
                    country_clean = country_clean.replace(junk, "")
                country_clean = re.sub(r"\s+", " ", country_clean)
                country_clean = country_clean.strip(" /　|｜")
                if country_clean:
                    details["country"] = country_clean

        # ---- Pattern B ----
        # 1976年｜イタリア｜…｜111分
        if not (details["year"] and details["runtime_min"] and details["country"]):
            year_match = re.search(r"(\d{4})\s*年", text)

            # Runtime detection with guard (ignore "4分" etc.)
            runtime_match = None
            for mm in re.finditer(r"(\d+)\s*分", text):
                candidate = int(mm.group(1))
                if candidate >= 40:     # prevents picking up "ラスト4分"
                    runtime_match = mm

            # Extract country only when year+runtime are localised
            if year_match and runtime_match:
                # Only set year/runtime if we found a likely block pairing
                if not details["year"]:
                     # Check for date-like suffix (e.g. 2026年1月)
                     suffix_check = text[year_match.end():year_match.end()+2]
                     if not re.match(r"\s*\d+月", suffix_check):
                        details["year"] = year_match.group(1)

                if not details["runtime_min"]:
                    details["runtime_min"] = runtime_match.group(1)

                if not details["country"]:
                    span_start = year_match.end()
                    span_end = runtime_match.start()
                    between = text[span_start:span_end]

                    # Prevent grabbing entire paragraphs as country
                    if span_end - span_start < 120:
                        between = (between
                                .replace("／", "/")
                                .replace("｜", "/")
                                .replace("|", "/"))

                        tokens = [t.strip() for t in between.split("/")
                                if t.strip()]

                        # Filter non-country tokens
                        country_tokens = [
                            t for t in tokens
                            if not any(x in t for x in [
                                "語", "モノクロ", "モノラル", "カラー",
                                "ヴィスタ", "ビスタ", "DCP",
                                "上映時間", "サイズ", "レストア"
                            ])
                        ]

                        if country_tokens:
                            details["country"] = "・".join(country_tokens[:2])

    # -----------------------
    # 1st pass: summary
    # -----------------------
    if summary_text:
        _apply_compact_meta_patterns(summary_text)

    # -----------------------
    # 2nd pass: article blocks
    # -----------------------
    for article in soup.find_all("article", class_="article"):
        title_tag = article.find("h3", class_="entryTitle2")
        data_tag = article.find("p", class_="movieData")
        if not (title_tag and data_tag):
            continue

        title_text = _clean_text(title_tag.get_text())
        data_text = data_tag.get_text(separator=" ")

        # Director
        if "監督" in title_text and not details["director"]:
            director = data_text.split("『")[0].strip()
            details["director"] = _clean_text(director) if director else None

        # Staff
        if "スタッフ" in title_text:
            _apply_compact_meta_patterns(data_text)

    # -----------------------
    # 3rd pass: fallback — summary again
    # -----------------------
    if summary_text:
        _apply_compact_meta_patterns(summary_text)

    return details

def _build_details_cache() -> Dict[str, Dict]:
    """Builds a cache of movie details by scraping the main movie listing page."""
    print(f"INFO: [{CINEMA_NAME}] Building details cache from {MOVIE_LIST_URL}", file=sys.stderr)
    list_soup = _fetch_soup(MOVIE_LIST_URL)
    if not list_soup: return {}

    cache = {}
    for item in list_soup.select("li.lineupPost03_item"):
        title_tag = item.select_one("p.lineupPost03_title")
        link_tag = item.find("a")
        if not (title_tag and link_tag and link_tag.get("href")): continue
        
        title_key = _get_title_key(title_tag.text)
        if not title_key or title_key in cache: continue

        detail_url = urljoin(BASE_DETAIL_URL, link_tag["href"])
        detail_soup = _fetch_soup(detail_url)
        if detail_soup:
            print(f"  -> Scraping details for '{title_key}'", file=sys.stderr)
            details = _parse_detail_page(detail_soup)
            details["detail_page_url"] = detail_url
            cache[title_key] = details
    
    print(f"INFO: [{CINEMA_NAME}] Built cache for {len(cache)} movies.", file=sys.stderr)
    return cache

def scrape_cinemart_shinjuku(max_days: int = 7) -> List[Dict]:
    """Main function to scrape Cinemart Shinjuku."""
    details_cache = _build_details_cache()
    all_showings = []
    driver = _init_driver()

    try:
        print(f"INFO: [{CINEMA_NAME}] Navigating to schedule page...", file=sys.stderr)
        driver.get(SCHEDULE_URL)
        wait = WebDriverWait(driver, 25)
        date_tabs = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[id^='dateSlider']")))
        
        for i in range(min(len(date_tabs), max_days)):
            current_tab = driver.find_elements(By.CSS_SELECTOR, "div[id^='dateSlider']")[i]
            date_id = current_tab.get_attribute("id").replace("dateSlider", "")
            date_iso = f"{date_id[:4]}-{date_id[4:6]}-{date_id[6:]}"

            print(f"  -> Processing date: {date_iso}", file=sys.stderr)
            if i > 0:
                driver.execute_script("arguments[0].click();", current_tab)
                wait.until(EC.visibility_of_element_located((By.ID, f"dateJouei{date_id}")))
            time.sleep(1.5)

            page_soup = BeautifulSoup(driver.page_source, "html.parser")
            schedule_container = page_soup.find("div", id=f"dateJouei{date_id}")
            if not schedule_container: continue

            for panel in schedule_container.select("div.movie-panel"):
                title_jp_tag = panel.select_one(".title-jp")
                if not title_jp_tag: continue
                
                raw_title = _clean_text(title_jp_tag.text)
                title_key = _get_title_key(raw_title)
                details = details_cache.get(title_key, {})

                for schedule in panel.select("div.movie-schedule"):
                    showtime = _clean_text(schedule.select_one(".movie-schedule-begin").text)
                    screen = _clean_text(schedule.select_one(".screen-name").text)
                    all_showings.append({
                        "cinema_name": CINEMA_NAME, "movie_title": raw_title,
                        "date_text": date_iso, "showtime": showtime,
                        "screen_name": screen, **details
                    })
    except TimeoutException:
        print(f"ERROR: [{CINEMA_NAME}] A timeout occurred.", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: [{CINEMA_NAME}] An unexpected error occurred: {e}", file=sys.stderr)
    finally:
        if driver:
            driver.quit()

    unique = {(s["date_text"], s["movie_title"], s["showtime"]): s for s in all_showings}
    return sorted(list(unique.values()), key=lambda r: (r.get("date_text", ""), r.get("showtime", "")))

# --- Main Execution ---
if __name__ == '__main__':
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8')
    
    showings = scrape_cinemart_shinjuku()
    if showings:
        output_filename = "cinemart_shinjuku_showtimes.json"
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(showings, f, ensure_ascii=False, indent=2)
        print(f"\nINFO: Successfully created '{output_filename}' with {len(showings)} records.", file=sys.stderr)
    else:
        print(f"\nNo showings found for {CINEMA_NAME}.")
