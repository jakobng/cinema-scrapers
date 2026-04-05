from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE_PAGE_URL = "https://www.in89.com.tw/index.aspx"
BASE_FILM_LIST_URL = "https://www.in89.com.tw/film_list.aspx"
TAIPEI_TZ = timezone(timedelta(hours=8))


def _fetch(url: str) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {url}")


def _fetch_page_config(theater_id: str) -> Optional[Dict[str, str]]:
    soup = BeautifulSoup(_fetch(f"{BASE_PAGE_URL}?TheaterId={theater_id}").text, "html.parser")
    values = {tag.get("name"): str(tag.get("value") or "").strip() for tag in soup.find_all("input") if tag.get("name")}
    theater_api = values.get("theater_api") or ""
    theater_name = values.get("TheaterName") or ""
    page_theater_id = values.get("theater_id") or theater_id
    if not theater_api or not theater_name:
        return None
    return {"theater_api": theater_api, "theater_name": theater_name, "theater_id": page_theater_id}


def _build_detail_url(theater_id: str, theater_name: str, movie: Dict[str, str]) -> str:
    select_movie = f"{movie.get('movie_group_name', '')}-{movie.get('movie_play_desc', '')}-{movie.get('movie_lang_desc', '')}"
    return (
        "https://www.in89.com.tw/film_detail.aspx?"
        f"TheaterId={quote(theater_id)}&TheaterName={quote(theater_name)}&select_movie={quote(select_movie)}"
        f"&movie_id={quote(str(movie.get('movie_id') or ''))}"
    )


def _image_url(movie: Dict[str, str]) -> Optional[str]:
    path = str(movie.get("253_img_path") or movie.get("125_img_path") or "").strip()
    if not path:
        return None
    return f"https://img.in89cinemax.com{path}"


def _start_session(base_api_url: str) -> Optional[requests.Session]:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        response = session.post(
            f"{base_api_url}api_member.php?method=getSessionID",
            data={"method": "getSessionID"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "0000":
            return None
        return session
    except (requests.RequestException, ValueError):
        return None


def _fetch_stages_by_date(session: requests.Session, base_api_url: str, date_text: str) -> Optional[Dict]:
    session_id = session.cookies.get("PHPSESSID")
    payload = {"method": "getStagesByDate", "date": date_text, "session_id": session_id or ""}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.post(
                f"{base_api_url}api_movie.php?method=getStagesByDate",
                data=payload,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch stages for {date_text}")


def scrape_in89_branch(*, theater_id: str, cinema_name: str) -> List[Dict]:
    try:
        config = _fetch_page_config(theater_id)
    except requests.RequestException as exc:
        print(f"ERROR: [{cinema_name}] page fetch failed: {exc}", file=sys.stderr)
        return []

    if not config:
        print(f"ERROR: [{cinema_name}] unable to resolve theater API configuration", file=sys.stderr)
        return []

    base_api_url = f"https://{config['theater_api']}/api/"
    session = _start_session(base_api_url)
    if not session:
        print(f"ERROR: [{cinema_name}] failed to establish API session", file=sys.stderr)
        return []

    today = datetime.now(TAIPEI_TZ).date()
    results: List[Dict] = []
    empty_days = 0

    for offset in range(10):
        date_text = (today + timedelta(days=offset)).isoformat()
        try:
            payload = _fetch_stages_by_date(session, base_api_url, date_text)
        except Exception as exc:
            print(f"ERROR: [{cinema_name}] stage fetch failed: {date_text} {exc}", file=sys.stderr)
            break

        stage_root = (payload.get("stages") or {}).get(date_text)
        if not isinstance(stage_root, dict) or not stage_root:
            empty_days += 1
            if empty_days >= 3:
                break
            continue
        empty_days = 0

        movies = payload.get("movies") or {}
        for _start_date, timegroup in stage_root.items():
            if not isinstance(timegroup, dict):
                continue
            for _movie_cn_name, group in timegroup.items():
                if not isinstance(group, dict):
                    continue
                for movie_id, stages in group.items():
                    movie = movies.get(str(movie_id)) or {}
                    if not isinstance(stages, list):
                        continue
                    detail_url = _build_detail_url(config["theater_id"], config["theater_name"], movie)
                    for stage in stages:
                        show_dt = str(stage.get("movie_show_time") or "").strip()
                        match = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", show_dt)
                        if not match:
                            continue
                        results.append(
                            {
                                "cinema_name": cinema_name,
                                "movie_title": movie.get("movie_group_name") or "",
                                "movie_title_en": movie.get("en_name") or None,
                                "director": None,
                                "director_en": "",
                                "year": None,
                                "country": None,
                                "runtime_min": str(movie.get("play_duration") or "").strip() or None,
                                "synopsis": "",
                                "date_text": match.group(1),
                                "showtime": match.group(2),
                                "screen_name": stage.get("theater_film_name") or "",
                                "detail_page_url": detail_url,
                                "booking_url": f"{BASE_FILM_LIST_URL}?TheaterId={quote(config['theater_id'])}",
                                "image_url": _image_url(movie),
                            }
                        )

    return results
