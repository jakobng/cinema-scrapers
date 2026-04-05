from __future__ import annotations

import ast
import re
import sys
from typing import Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.spot-hs.org.tw/movie/nowplaying.html"
BASE_ORIGIN = "https://www.spot-hs.org.tw"
CINEMA_NAME = "光點華山電影館"
MOVIE_LINK_RE = re.compile(r"movie20\d{4}/movie20\d{6}\.html")


def _fetch_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.content.decode("utf-8", "ignore")


def _clean_lines(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]


def _extract_schedule(html: str) -> List[List[str]]:
    match = re.search(r"var\s+MovieSchedule\s*=\s*(\[[\s\S]*?\]);", html)
    if not match:
        return []
    return ast.literal_eval(match.group(1))


def _split_director(text: str) -> tuple[str, str]:
    director = text.replace("導演:", "", 1).strip()
    latin = re.search(r"([A-Z][A-Za-z.\-'\s]+)$", director)
    return director, (latin.group(1).strip() if latin else "")


def scrape_spot_huashan() -> List[Dict]:
    try:
        homepage = _fetch_text(BASE_URL)
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] homepage fetch failed: {exc}", file=sys.stderr)
        return []

    detail_urls = sorted({urljoin(BASE_URL, path) for path in MOVIE_LINK_RE.findall(homepage)})

    results: List[Dict] = []
    for detail_url in detail_urls:
        try:
            html = _fetch_text(detail_url)
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] detail fetch failed: {detail_url} {exc}", file=sys.stderr)
            continue

        lines = _clean_lines(html)
        if "放映場次 Schedule" not in lines:
            continue

        title_index = None
        for idx, line in enumerate(lines):
            if line == "首頁 / 現正放映 /" and idx + 3 < len(lines):
                title_index = idx + 1
                break
        if title_index is None:
            continue

        title_jp = lines[title_index]
        title_en = lines[title_index + 2] if re.search(r"[A-Za-z]", lines[title_index + 2]) else ""
        director_line = next((line for line in lines if line.startswith("導演:")), "")
        runtime_line = next((line for line in lines if line.startswith("片長:")), "")
        release_line = next((line for line in lines if re.match(r"^\d{4}/\d{1,2}/\d{1,2}起$", line)), "")
        director, director_en = _split_director(director_line)

        runtime_match = re.search(r"(\d+)\s*min", runtime_line, re.IGNORECASE)
        year_match = re.search(r"\b(19|20)\d{2}\b", release_line)

        synopsis = ""
        if "劇情介紹 Story" in lines and "放映場次 Schedule" in lines:
            start = lines.index("劇情介紹 Story") + 1
            end = lines.index("放映場次 Schedule")
            synopsis = " ".join(lines[start:end]).strip()

        listing = {
            "cinema_name": CINEMA_NAME,
            "movie_title": title_jp,
            "movie_title_en": title_en or None,
            "director": director or None,
            "director_en": director_en or "",
            "year": year_match.group(0) if year_match else None,
            "country": None,
            "runtime_min": runtime_match.group(1) if runtime_match else None,
            "synopsis": synopsis,
            "booking_url": "https://spot-hs.tixi.com.tw/",
        }

        for row in _extract_schedule(html):
            if not row:
                continue
            date_text = row[0].replace("/", "-")
            for session in row[1:]:
                time_match = re.match(r"(\d{1,2}:\d{2})", session)
                if not time_match:
                    continue
                item = dict(listing)
                item["date_text"] = date_text
                item["showtime"] = time_match.group(1)
                item["detail_page_url"] = detail_url
                results.append(item)

    return results
