from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

TAIPEI_TZ = timezone(timedelta(hours=8))

BASE_URL = "https://wonderful.movie.com.tw/time"
BASE_ORIGIN = "https://wonderful.movie.com.tw"
CINEMA_NAME = "真善美劇院"


def _fetch_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def _fetch_detail(movie_id: str) -> Dict[str, str]:
    soup = _fetch_soup(f"{BASE_ORIGIN}/movie/inner?id={movie_id}")
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]

    title = ""
    director = ""
    year = ""
    runtime = ""
    synopsis = ""

    skip = {"真善美劇院 | 中影", "關於影城", "時刻查詢", "影片介紹"}
    for idx, line in enumerate(lines):
        if not title and line not in skip:
            title = line
        if line == "導　　演：" and idx + 1 < len(lines):
            director = lines[idx + 1]
        if line == "上映日期：" and idx + 1 < len(lines):
            year_match = re.search(r"\b(19|20)\d{2}\b", lines[idx + 1])
            if year_match:
                year = year_match.group(0)
        if line == "片　　長：" and idx + 1 < len(lines):
            runtime_match = re.search(r"(?:(\d+)時)?(\d+)分", lines[idx + 1])
            if runtime_match:
                hours = int(runtime_match.group(1) or 0)
                minutes = int(runtime_match.group(2))
                runtime = str(hours * 60 + minutes)
        if line == "立即購票" and idx + 1 < len(lines):
            synopsis = " ".join(lines[idx + 1 : idx + 6]).strip()
            break

    return {
        "movie_title": title,
        "director": director or None,
        "year": year or None,
        "runtime_min": runtime or None,
        "synopsis": synopsis,
        "detail_page_url": f"{BASE_ORIGIN}/movie/inner?id={movie_id}",
    }


def scrape_wonderful_theatre() -> List[Dict]:
    try:
        soup = _fetch_soup(BASE_URL)
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] schedule fetch failed: {exc}", file=sys.stderr)
        return []

    results: List[Dict] = []
    today = datetime.now(TAIPEI_TZ).date()
    movie_items = soup.select(".movie_list > li > a.link_lb")

    for item in movie_items:
        href = item.get("href", "")
        movie_id_match = re.search(r"id=(\d+)", href)
        if not movie_id_match:
            continue
        movie_id = movie_id_match.group(1)

        try:
            detail_info = _fetch_detail(movie_id)
            lightbox = _fetch_soup(f"{BASE_ORIGIN}/lightbox/index?id={movie_id}")
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] movie fetch failed: {movie_id} {exc}", file=sys.stderr)
            continue

        for group in lightbox.select(".time_list"):
            date_bits = group.select("li.time div")
            if not date_bits:
                continue
            month_day = date_bits[0].get_text(" ", strip=True)
            match = re.search(r"(\d{2})\s*/\s*(\d{2})", month_day)
            if not match:
                continue
            month = int(match.group(1))
            day = int(match.group(2))
            year = today.year
            if month < today.month - 6:
                year += 1
            elif month > today.month + 6:
                year -= 1
            date_text = f"{year:04d}-{month:02d}-{day:02d}"
            for slot in group.select("li:not(.time)"):
                showtime = slot.get_text(" ", strip=True)
                if not re.match(r"^\d{1,2}:\d{2}$", showtime):
                    continue
                results.append(
                    {
                        "cinema_name": CINEMA_NAME,
                        "movie_title": detail_info["movie_title"],
                        "movie_title_en": None,
                        "director": detail_info["director"],
                        "director_en": "",
                        "year": detail_info["year"],
                        "country": None,
                        "runtime_min": detail_info["runtime_min"],
                        "synopsis": detail_info["synopsis"],
                        "date_text": date_text,
                        "showtime": showtime,
                        "detail_page_url": detail_info["detail_page_url"],
                        "booking_url": "https://www.ezding.com.tw/cinemabooking?cinemaid=f644412efbb811e58858f2128151146f",
                    }
                )

    return results
