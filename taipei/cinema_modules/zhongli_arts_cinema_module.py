from __future__ import annotations

import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://www.taoyuan.arts-cinema.com/"
API_BASE = f"{BASE_URL}api/"
CINEMA_NAME = "中壢光影電影館"


def _request_json(path: str, *, method: str = "GET", data: Optional[Dict[str, str]] = None) -> Dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.request(
                method,
                f"{API_BASE}{path}",
                data=data,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
                verify=False,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"Unexpected JSON payload from {path}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to fetch {path}")


def _extract_booking_url(html: str) -> Optional[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if href.startswith("http"):
            return href
    return None


def _clean_synopsis(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    cleaned: List[str] = []
    for line in lines:
        if line.startswith("索取票券"):
            continue
        cleaned.append(line)
    return " ".join(cleaned).strip()


def _sanitize_runtime(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        runtime = int(str(value).strip())
    except ValueError:
        return None
    if runtime <= 0 or runtime > 400:
        return None
    return str(runtime)


def _target_years() -> List[str]:
    today = datetime.now().date()
    years: Set[int] = {today.year}
    if today.month <= 2:
        years.add(today.year - 1)
    if today.month >= 11:
        years.add(today.year + 1)
    return [str(year) for year in sorted(years, reverse=True)]


def scrape_zhongli_arts_cinema() -> List[Dict]:
    today = datetime.now().date()

    try:
        year_payload = _request_json("GetExpoYear.php", method="POST")
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] expo year fetch failed: {exc}", file=sys.stderr)
        return []

    available_years = {
        str(item.get("expoYear"))
        for item in (year_payload.get("data") or [])
        if isinstance(item, dict) and item.get("expoYear")
    }
    years = [year for year in _target_years() if year in available_years] or sorted(available_years, reverse=True)[:1]

    results: List[Dict] = []
    seen_showings: Set[Tuple[str, str, str]] = set()
    detail_cache: Dict[Tuple[str, str], Dict] = {}

    for year in years:
        try:
            expo_payload = _request_json("GetExpoList.php", method="POST", data={"year": year})
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] expo list fetch failed for {year}: {exc}", file=sys.stderr)
            continue

        for expo in expo_payload.get("data") or []:
            expo_id = str(expo.get("id") or "").strip()
            expo_title = str(expo.get("title") or "").strip()
            if not expo_id:
                continue

            try:
                subexpo_payload = _request_json("GetSubExpoList.php", method="POST", data={"eId": expo_id})
            except requests.RequestException as exc:
                print(f"ERROR: [{CINEMA_NAME}] sub-expo fetch failed: {expo_id} {exc}", file=sys.stderr)
                continue

            for subexpo in subexpo_payload.get("data") or []:
                subexpo_id = str(subexpo.get("id") or "").strip()
                subexpo_title = str(subexpo.get("title") or "").strip()
                if not subexpo_id:
                    continue

                try:
                    movie_payload = _request_json(
                        "GetMovieList.php",
                        method="POST",
                        data={"seId": subexpo_id, "showType": "0"},
                    )
                except requests.RequestException as exc:
                    print(f"ERROR: [{CINEMA_NAME}] movie list fetch failed: {subexpo_id} {exc}", file=sys.stderr)
                    continue

                for movie in movie_payload.get("data") or []:
                    movie_id = str(movie.get("id") or "").strip()
                    expo_movie_id = str(movie.get("emid") or "").strip()
                    show_dt = str(movie.get("showDate") or "").strip()
                    if not movie_id or not expo_movie_id or not show_dt:
                        continue

                    try:
                        start_dt = datetime.strptime(show_dt, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                    if start_dt.date() < today:
                        continue

                    show_key = (movie_id, expo_movie_id, show_dt)
                    if show_key in seen_showings:
                        continue
                    seen_showings.add(show_key)

                    cache_key = (movie_id, expo_movie_id)
                    if cache_key not in detail_cache:
                        try:
                            detail_cache[cache_key] = _request_json(f"ShowMovie.php?id={movie_id}&emid={expo_movie_id}")
                        except requests.RequestException as exc:
                            print(f"ERROR: [{CINEMA_NAME}] movie detail fetch failed: {movie_id}/{expo_movie_id} {exc}", file=sys.stderr)
                            continue

                    detail_rows = detail_cache[cache_key].get("data") or []
                    if not detail_rows:
                        continue
                    detail = detail_rows[0]

                    detail_endpoint = f"{API_BASE}ShowMovie.php?id={movie_id}&emid={expo_movie_id}"
                    tags = [tag for tag in [expo_title, subexpo_title, detail.get("movieType")] if tag]

                    results.append(
                        {
                            "cinema_name": CINEMA_NAME,
                            "movie_title": detail.get("title") or movie.get("title") or "",
                            "movie_title_en": detail.get("engTitle") or None,
                            "director": detail.get("director") or None,
                            "director_en": "",
                            "year": detail.get("showYear") or None,
                            "country": detail.get("country") or None,
                            "runtime_min": _sanitize_runtime(detail.get("movieTime")),
                            "synopsis": _clean_synopsis(str(detail.get("description") or "")),
                            "date_text": start_dt.date().isoformat(),
                            "showtime": start_dt.strftime("%H:%M"),
                            "detail_page_url": detail_endpoint,
                            "booking_url": _extract_booking_url(str(detail.get("description") or "")),
                            "image_url": f"{BASE_URL}image/newmovie/{detail.get('bigImage')}" if detail.get("bigImage") else None,
                            "tags": tags,
                        }
                    )

    return results
