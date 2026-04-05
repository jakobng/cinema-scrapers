from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://arthouse.eslite.com/visAgreement.aspx"
BASE_ORIGIN = "https://arthouse.eslite.com/"
CINEMA_NAME = "誠品電影院（松菸）"
CINEMA_ID = "1001"


def _get_session() -> requests.Session:
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0"}
    response = session.get(BASE_URL, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    payload = {
        "__VIEWSTATE": soup.select_one("#__VIEWSTATE")["value"],
        "__EVENTVALIDATION": soup.select_one("#__EVENTVALIDATION")["value"],
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$lbtAgree",
        "__EVENTARGUMENT": "",
    }
    agreed = session.post(BASE_URL, data=payload, headers=headers, timeout=30)
    agreed.raise_for_status()
    return session


def _split_title(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    match = re.match(r"^(?P<jp>.+?)\s+(?P<en>[A-Za-z0-9][A-Za-z0-9 .:'!&,\-]+)$", cleaned)
    if match:
        return match.group("jp").strip(), match.group("en").strip()
    return cleaned, ""


def _parse_date(text: str) -> str:
    match = re.search(r"(\d+)月(\d+)日", text)
    if not match:
        return ""
    month = int(match.group(1))
    day = int(match.group(2))
    year = datetime.now().year
    return f"{year:04d}-{month:02d}-{day:02d}"


def scrape_eslite_arthouse() -> List[Dict]:
    try:
        session = _get_session()
    except Exception as exc:
        print(f"ERROR: [{CINEMA_NAME}] agreement flow failed: {exc}", file=sys.stderr)
        return []

    headers = {"User-Agent": "Mozilla/5.0"}
    listing_url = f"{BASE_ORIGIN}visSelect.aspx?visSearchBy=cin&visCinID={CINEMA_ID}"
    response = session.get(listing_url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    movie_links = soup.select("a[id^='ctl00_ContentPlaceHolder1_lnkMovie']")
    results: List[Dict] = []

    for link in movie_links:
        href = link.get("href")
        if not href:
            continue
        detail_url = urljoin(BASE_ORIGIN, href)
        try:
            detail_response = session.get(detail_url, headers=headers, timeout=30)
            detail_response.raise_for_status()
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] movie page failed: {detail_url} {exc}", file=sys.stderr)
            continue

        detail_soup = BeautifulSoup(detail_response.text, "html.parser")
        title_node = detail_soup.select_one("#ctl00_ContentPlaceHolder1_lblStep2Selection")
        if not title_node:
            continue
        title_jp, title_en = _split_title(title_node.get_text(" ", strip=True))

        session_rows = detail_soup.select("#ctl00_ContentPlaceHolder1_tblSessions tr")
        current_date = ""
        for row in session_rows:
            anchors = row.select("a")
            text = row.get_text(" ", strip=True)
            if "星期" in text:
                current_date = _parse_date(text)
                continue
            if not current_date or not anchors:
                continue
            for anchor in anchors:
                showtime = anchor.get("title") or anchor.get_text(" ", strip=True).split()[0]
                booking_url = urljoin(BASE_ORIGIN, anchor.get("href", ""))
                results.append(
                    {
                        "cinema_name": CINEMA_NAME,
                        "movie_title": title_jp,
                        "movie_title_en": title_en or None,
                        "director": None,
                        "director_en": "",
                        "year": None,
                        "country": None,
                        "runtime_min": None,
                        "synopsis": "",
                        "date_text": current_date,
                        "showtime": showtime,
                        "detail_page_url": detail_url,
                        "booking_url": booking_url,
                    }
                )

    return results

