from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.fuzhong15.ntpc.gov.tw/xcmovie?xsmsid=0m361641875264878260"
BASE_ORIGIN = "https://www.fuzhong15.ntpc.gov.tw"
CINEMA_NAME = "府中15放映院"


def scrape_fuzhong15() -> List[Dict]:
    try:
        response = requests.get(BASE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] schedule fetch failed: {exc}", file=sys.stderr)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.select_one("table.ListTable")
    if not table:
        return []

    current_year = datetime.now().year
    results: List[Dict] = []

    for row in table.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        date_raw = cells[0].get_text(" ", strip=True)
        time_raw = cells[1].get_text(" ", strip=True)
        title_cell = cells[2]
        runtime_raw = cells[3].get_text(" ", strip=True)

        date_match = re.search(r"(\d{2})/(\d{2})", date_raw)
        time_match = re.search(r"(\d{1,2}:\d{2})", time_raw)
        runtime_match = re.search(r"(\d+)\s*min", runtime_raw, re.IGNORECASE)
        if not date_match or not time_match:
            continue

        detail_link = title_cell.find("a")
        detail_url = urljoin(BASE_ORIGIN, detail_link["href"]) if detail_link and detail_link.get("href") else BASE_URL

        movie_title = re.sub(r"\s+[報售]$", "", title_cell.get_text(" ", strip=True)).strip()

        results.append(
            {
                "cinema_name": CINEMA_NAME,
                "movie_title": movie_title,
                "movie_title_en": None,
                "director": None,
                "director_en": "",
                "year": None,
                "country": None,
                "runtime_min": runtime_match.group(1) if runtime_match else None,
                "synopsis": "",
                "date_text": f"{current_year:04d}-{int(date_match.group(1)):02d}-{int(date_match.group(2)):02d}",
                "showtime": time_match.group(1),
                "detail_page_url": detail_url,
                "booking_url": None,
            }
        )

    return results
