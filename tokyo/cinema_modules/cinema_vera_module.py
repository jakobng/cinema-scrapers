from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "http://www.cinemavera.com/schedule.html"
CINEMA_NAME = "シネマヴェーラ渋谷"


def clean_text(text: str) -> str:
    """Normalize whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup object, or None on error."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        # The site uses UTF-8 usually, but let's be safe
        resp.encoding = resp.apparent_encoding
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None

    return BeautifulSoup(resp.text, "html.parser")


def scrape_cinema_vera() -> List[Dict]:
    """
    Scrape Cinema Vera schedule.
    """
    results: List[Dict] = []
    soup = fetch_soup(BASE_URL)
    if soup is None:
        return results

    # Get the current program title and period if possible
    program_title = ""
    subject_tag = soup.select_one(".lineup .subject h2")
    if subject_tag:
        program_title = clean_text(subject_tag.get_text())

    period_tag = soup.select_one(".lineup .subject li.schedule h4")
    # Example: 2025/12/27 ～ 2026/01/23
    start_year = datetime.now().year
    start_month = None
    if period_tag:
        period_text = period_tag.get_text()
        m = re.search(r"(\d{4})/(\d{1,2})", period_text)
        if m:
            start_year = int(m.group(1))
            start_month = int(m.group(2))

    table = soup.select_one("table.pctime")
    if not table:
        return results

    current_month = start_month
    current_year = start_year

    for tr in table.find_all("tr"):
        date_td = tr.find("td", class_="date")
        if not date_td:
            continue

        day_tag = date_td.select_one(".day")
        day_text = clean_text(day_tag.get_text()) if day_tag else clean_text(date_td.get_text())
        # day_text can be "12/27" or just "28"
        if "/" in day_text:
            match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", day_text)
            if not match:
                continue
            new_month = int(match.group(1))
            # If month decreases (e.g. 12 -> 1), increment year
            if current_month is not None and new_month < current_month:
                current_year += 1
            current_month = new_month
            day = int(match.group(2))
        else:
            match = re.search(r"(\d{1,2})", day_text)
            if not match:
                continue
            day = int(match.group(1))
            if current_month is None:
                # Should not happen with current site structure
                current_month = datetime.now().month

        date_iso = f"{current_year:04d}-{current_month:02d}-{day:02d}"

        show_cells = tr.find_all("td", class_="cel7")
        if not show_cells:
            show_cells = [td for td in tr.find_all("td") if td is not date_td]

        # Showings are in subsequent cells
        for td in show_cells:
            time_tag = td.select_one(".time")
            film_tag = td.select_one(".film")

            if not time_tag or not film_tag:
                continue

            showtime = clean_text(time_tag.get_text())
            movie_title_raw = clean_text(film_tag.get_text())

            if not showtime or not movie_title_raw or movie_title_raw == "終日休館":
                continue

            # Remove runtime from title, e.g. "ジョルスン物語（129分）"
            movie_title = re.sub(r"（\d+\s*分）.*$", "", movie_title_raw).strip()
            # Also handle variations like (62 分)
            movie_title = re.sub(r"\(\d+\s*分\).*$", "", movie_title).strip()
            
            # Extract runtime if present
            runtime = None
            runtime_match = re.search(r"（(\d+)\s*分）", movie_title_raw)
            if not runtime_match:
                runtime_match = re.search(r"\((\d+)\s*分\)", movie_title_raw)
            
            if runtime_match:
                runtime = runtime_match.group(1)

            results.append({
                "cinema_name": CINEMA_NAME,
                "movie_title": movie_title,
                "movie_title_en": None,
                "director": None,
                "year": None,
                "country": None,
                "runtime_min": runtime,
                "date_text": date_iso,
                "showtime": showtime,
                "detail_page_url": BASE_URL,
                "program_title": program_title,
                "purchase_url": None,
            })

    return results


if __name__ == "__main__":
    data = scrape_cinema_vera()
    print(f"{len(data)} showings found")
    for d in data[:5]:
        print(d)
