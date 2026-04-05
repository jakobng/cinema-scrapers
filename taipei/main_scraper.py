#!/usr/bin/env python3
from __future__ import annotations

import difflib
import io
import json
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from cinema_modules import (
    eslite_arthouse_module,
    fuzhong15_module,
    spot_huashan_module,
    spot_taipei_module,
    wonderful_theatre_module,
)

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DATA_DIR = Path("data")
OUTPUT_JSON = DATA_DIR / "showtimes.json"
TMDB_CACHE_FILE = DATA_DIR / "tmdb_cache.json"
TAIPEI_TZ = timezone(timedelta(hours=8))


class ScrapeReport:
    def __init__(self) -> None:
        self.results: List[Dict[str, object]] = []
        self.total_showings = 0

    def add(self, cinema_name: str, status: str, count: int, error: Optional[Exception] = None) -> None:
        self.results.append(
            {
                "cinema": cinema_name,
                "status": status,
                "count": count,
                "error": str(error) if error else None,
            }
        )
        self.total_showings += count

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("TAIPEI SCRAPE HEALTH REPORT")
        print("=" * 60)
        print(f"{'STATUS':<8} {'VENUE':<28} {'COUNT':<6} NOTES")
        print("-" * 60)
        for item in self.results:
            notes = item["error"] or ""
            print(f"{item['status']:<8} {item['cinema']:<28} {item['count']:<6} {notes}")
        print("-" * 60)
        print(f"Total showings collected: {self.total_showings}")


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_tmdb_cache() -> Dict[str, Dict]:
    if TMDB_CACHE_FILE.exists():
        try:
            return json.loads(TMDB_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_tmdb_cache(cache: Dict[str, Dict]) -> None:
    TMDB_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_title_for_match(title: str) -> str:
    cleaned = (title or "").lower().strip()
    cleaned = re.sub(r"[【】\[\]（）()]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def clean_title_for_tmdb(title: str) -> str:
    cleaned = normalize_title_for_match(title)
    cleaned = re.sub(r"^(?:【[^】]+】\s*)+", "", cleaned)
    cleaned = re.sub(r"\s*(4k|數位修復版|數位修復|經典電影院|早安！周日經典電影院)\s*$", "", cleaned)
    return cleaned.strip()


def _score_tmdb_result(query: str, result: Dict, query_year: Optional[int]) -> float:
    query_norm = clean_title_for_tmdb(query)
    if not query_norm:
        return 0.0
    title_norm = normalize_title_for_match(result.get("title", ""))
    original_norm = normalize_title_for_match(result.get("original_title", ""))
    ratio = max(
        difflib.SequenceMatcher(None, query_norm, title_norm).ratio() if title_norm else 0.0,
        difflib.SequenceMatcher(None, query_norm, original_norm).ratio() if original_norm else 0.0,
    )
    score = ratio
    release_date = result.get("release_date") or ""
    if query_year and re.match(r"^\d{4}", release_date):
        result_year = int(release_date[:4])
        diff = abs(result_year - query_year)
        if diff == 0:
            score += 0.12
        elif diff == 1:
            score += 0.05
        elif diff > 8:
            score -= 0.12
    return score


def fetch_tmdb_details(item: Dict, session: requests.Session, api_key: str, cache: Dict[str, Dict]) -> Optional[Dict]:
    query = item.get("movie_title_en") or item.get("movie_title") or ""
    query = str(query).strip()
    if not query:
        return None

    query_year = None
    year_value = item.get("year")
    if year_value and re.search(r"\d{4}", str(year_value)):
        query_year = int(re.search(r"\d{4}", str(year_value)).group(0))

    cache_key = f"{clean_title_for_tmdb(query)}::{query_year or ''}"
    if cache_key in cache:
        return cache[cache_key]

    params = {
        "api_key": api_key,
        "query": query,
        "language": "zh-TW",
        "include_adult": "false",
    }
    if query_year:
        params["year"] = query_year

    try:
        response = session.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
        response.raise_for_status()
        results = response.json().get("results", [])
        if not results and query_year:
            params.pop("year", None)
            response = session.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
            response.raise_for_status()
            results = response.json().get("results", [])
        if not results:
            return None

        scored = sorted(results, key=lambda result: _score_tmdb_result(query, result, query_year), reverse=True)
        best = scored[0]
        if _score_tmdb_result(query, best, query_year) < 0.58:
            return None

        detail_response = session.get(
            f"https://api.themoviedb.org/3/movie/{best['id']}",
            params={"api_key": api_key, "language": "en-US", "append_to_response": "credits"},
            timeout=10,
        )
        detail_response.raise_for_status()
        detail = detail_response.json()

        director = ""
        for crew in detail.get("credits", {}).get("crew", []):
            if crew.get("job") == "Director":
                director = crew.get("name") or ""
                break

        payload = {
            "tmdb_id": detail.get("id"),
            "tmdb_title": detail.get("title"),
            "tmdb_original_title": detail.get("original_title"),
            "tmdb_poster_path": detail.get("poster_path"),
            "tmdb_backdrop_path": detail.get("backdrop_path"),
            "tmdb_overview": detail.get("overview"),
            "runtime": detail.get("runtime"),
            "genres": [genre.get("name") for genre in detail.get("genres", []) if genre.get("name")],
            "director_en": director,
            "release_date": detail.get("release_date") or "",
        }
        cache[cache_key] = payload
        return payload
    except Exception:
        return None


def enrich_listings_with_tmdb(listings: List[Dict], api_key: str) -> List[Dict]:
    cache = load_tmdb_cache()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    for item in listings:
        details = fetch_tmdb_details(item, session, api_key, cache)
        if not details:
            continue
        item.setdefault("director_en", details.get("director_en") or "")
        if not item.get("director") and details.get("director_en"):
            item["director"] = details["director_en"]
        if not item.get("runtime_min") and details.get("runtime"):
            item["runtime_min"] = str(details["runtime"])
        item["tmdb_id"] = details.get("tmdb_id")
        item["tmdb_title"] = details.get("tmdb_title")
        item["tmdb_original_title"] = details.get("tmdb_original_title")
        item["tmdb_poster_path"] = details.get("tmdb_poster_path")
        item["tmdb_backdrop_path"] = details.get("tmdb_backdrop_path")
        item["tmdb_overview"] = details.get("tmdb_overview")
        item["genres"] = details.get("genres", [])
        if not item.get("movie_title_en") and details.get("tmdb_title"):
            item["movie_title_en"] = details["tmdb_title"]
    save_tmdb_cache(cache)
    return listings


def dedupe_listings(listings: List[Dict]) -> List[Dict]:
    deduped: Dict[tuple, Dict] = {}
    for item in listings:
        key = (
            item.get("cinema_name"),
            item.get("movie_title"),
            item.get("date_text"),
            item.get("showtime"),
        )
        deduped[key] = item
    return sorted(
        deduped.values(),
        key=lambda row: (
            row.get("date_text", ""),
            row.get("showtime", ""),
            row.get("cinema_name", ""),
            row.get("movie_title", ""),
        ),
    )


def run() -> int:
    ensure_data_dir()
    report = ScrapeReport()

    scrapers = [
        ("SPOT Taipei", spot_taipei_module.scrape_spot_taipei),
        ("SPOT-Huashan", spot_huashan_module.scrape_spot_huashan),
        ("Eslite Art House Songyan", eslite_arthouse_module.scrape_eslite_arthouse),
        ("Wonderful Theatre", wonderful_theatre_module.scrape_wonderful_theatre),
        ("Fuzhong 15", fuzhong15_module.scrape_fuzhong15),
    ]

    listings: List[Dict] = []
    for name, func in scrapers:
        try:
            rows = func()
            listings.extend(rows)
            report.add(name, "SUCCESS", len(rows))
            print(f"Collected {len(rows)} showings from {name}")
        except Exception as exc:
            report.add(name, "FAILURE", 0, exc)
            print(f"ERROR in {name}: {exc}")
            traceback.print_exc()

    listings = dedupe_listings(listings)
    tmdb_key = os.environ.get("TMDB_API_KEY")
    if tmdb_key:
        listings = enrich_listings_with_tmdb(listings, tmdb_key)

    OUTPUT_JSON.write_text(json.dumps(listings, ensure_ascii=False, indent=2), encoding="utf-8")
    report.print_summary()

    today = datetime.now(TAIPEI_TZ).date().isoformat()
    future_count = sum(1 for item in listings if item.get("date_text", "") >= today)
    print(f"Saved {len(listings)} total showings to {OUTPUT_JSON}")
    print(f"Current/future showings from {today}: {future_count}")
    return 0 if listings else 1


if __name__ == "__main__":
    raise SystemExit(run())
