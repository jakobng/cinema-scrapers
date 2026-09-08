#!/usr/bin/env python3
# curzon_chain_module.py
# Scraper for all London Curzon Cinemas
# https://www.curzon.com
#
# Data source: Curzon's Vista Cloud "OCAPI" JSON API at https://digital-api.curzon.com.
#
# Why not scrape the HTML?  www.curzon.com sits behind a Cloudflare managed
# challenge ("Just a moment...") that headless Chromium never clears, so the old
# Playwright implementation timed out on 11/11 venues both in CI and locally.
# The showtime picker on those pages is a Vista web component that reads the JSON
# API below, and that API host is NOT behind Cloudflare -- plain `requests` works
# against it.  The only thing we still need from www.curzon.com is the short-lived
# bearer token the page embeds in its bootstrap config, and cloudscraper can fetch
# that page.

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional, Tuple

import requests

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:  # pragma: no cover - cloudscraper is in requirements.txt
    HAS_CLOUDSCRAPER = False

BASE_URL = "https://www.curzon.com"
CONFIG_URL = f"{BASE_URL}/"

# Vista site id -> (display name, website slug).
# Curzon Sea Containers is gone: it is absent from the API's site list and
# https://www.curzon.com/venues/sea-containers/ returns 404.
LONDON_SITES: Dict[str, Tuple[str, str]] = {
    "ALD1": ("Curzon Aldgate", "aldgate"),
    "BLO1": ("Curzon Bloomsbury", "bloomsbury"),
    "CAM1": ("Curzon Camden", "camden"),
    "HOX1": ("Curzon Hoxton", "hoxton"),
    "KIN1": ("Curzon Kingston", "kingston"),
    "MAY1": ("Curzon Mayfair", "mayfair"),
    "RIC1": ("Curzon Richmond", "richmond"),
    "SOH1": ("Curzon Soho", "soho"),
    "VIC1": ("Curzon Victoria", "victoria"),
    "WIM1": ("Curzon Wimbledon", "wimbledon"),
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
TIMEOUT = 45
TODAY = dt.date.today()
WINDOW_DAYS = 14

# {"apiUrl":"https://digital-api.curzon.com","authToken":"<jwt>"}
_CONFIG_RE = re.compile(r'"apiUrl"\s*:\s*"(https://[^"]+)"\s*,\s*"authToken"\s*:\s*"([A-Za-z0-9._\-]+)"')


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _text_of(node) -> str:
    """Vista wraps localisable strings as {"text": ..., "translations": [...]}."""
    if isinstance(node, dict):
        return _clean(node.get("text") or "")
    return _clean(node or "")


def _fetch_api_config() -> Optional[Tuple[str, str]]:
    """Pull (api_url, bearer_token) out of the Curzon homepage bootstrap config.

    The token is a JWT that lives for about 12 hours, so it has to be fetched on
    every run rather than hard-coded.
    """
    fetchers = []
    if HAS_CLOUDSCRAPER:
        fetchers.append(("cloudscraper", lambda: cloudscraper.create_scraper().get(CONFIG_URL, timeout=TIMEOUT)))
    fetchers.append(
        ("requests", lambda: requests.get(CONFIG_URL, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT))
    )

    for label, fetch in fetchers:
        try:
            resp = fetch()
        except Exception as exc:
            print(f"[Curzon Chain] Config fetch via {label} failed: {exc}", file=sys.stderr)
            continue

        if resp.status_code != 200:
            print(f"[Curzon Chain] Config fetch via {label} returned HTTP {resp.status_code}", file=sys.stderr)
            continue
        if "Just a moment" in resp.text:
            print(f"[Curzon Chain] Config fetch via {label} hit the Cloudflare challenge", file=sys.stderr)
            continue

        match = _CONFIG_RE.search(resp.text)
        if match:
            return match.group(1), match.group(2)
        print(f"[Curzon Chain] Config fetch via {label} succeeded but no api config found", file=sys.stderr)

    return None


def _director_name(member: Dict) -> str:
    name = member.get("name") or {}
    parts = [name.get("givenName"), name.get("middleName"), name.get("familyName")]
    return _clean(" ".join(p for p in parts if p))


def _showtime_rows(payload: Dict, film_cache: Dict, crew_cache: Dict, attr_cache: Dict) -> List[Dict]:
    related = payload.get("relatedData") or {}

    for film in related.get("films") or []:
        film_cache[film["id"]] = film
    for member in related.get("castAndCrew") or []:
        crew_cache[member["id"]] = member
    for attr in related.get("attributes") or []:
        attr_cache[attr["id"]] = _text_of(attr.get("name"))

    rows: List[Dict] = []
    for st in payload.get("showtimes") or []:
        site_id = st.get("siteId")
        venue = LONDON_SITES.get(site_id)
        if not venue:
            continue
        cinema_name, slug = venue

        film = film_cache.get(st.get("filmId")) or {}
        title = _text_of(film.get("title"))
        if not title:
            continue

        schedule = st.get("schedule") or {}
        starts_at = schedule.get("startsAt") or ""
        business_date = schedule.get("businessDate") or ""
        # startsAt is a full offset-aware local timestamp, e.g. 2026-09-08T11:30:00+01:00
        time_match = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", starts_at)
        if not time_match:
            continue
        calendar_date, hour, minute = time_match.group(1), time_match.group(2), time_match.group(3)

        try:
            show_date = dt.date.fromisoformat(calendar_date)
        except ValueError:
            continue
        if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
            continue

        director = ""
        for credit in film.get("castAndCrew") or []:
            if "Director" in (credit.get("roles") or []):
                member = crew_cache.get(credit.get("castAndCrewMemberId"))
                if member:
                    director = _director_name(member)
                    break

        release_date = film.get("releaseDate") or ""
        year = release_date[:4] if len(release_date) >= 4 and release_date[:4].isdigit() else ""

        runtime = film.get("runtimeInMinutes")
        runtime_min = str(runtime) if isinstance(runtime, int) and runtime > 0 else ""

        synopsis = _text_of(film.get("synopsis")) or _text_of(film.get("shortSynopsis"))

        format_tags = [attr_cache[a] for a in (st.get("attributeIds") or []) if attr_cache.get(a)]

        # Mirrors the site's own deep link: allocated-seating showtimes go straight
        # to the seat picker, the rest start at the ticketing login step.
        seat_page = "seats" if st.get("isAllocatedSeating") else "ticketing-login"
        booking_url = f"{BASE_URL}/ticketing/{seat_page}/?showtimeId={st.get('id')}"

        rows.append({
            "cinema_name": cinema_name,
            "movie_title": title,
            "movie_title_en": title,
            "date_text": (business_date or calendar_date),
            "showtime": f"{hour}:{minute}",
            "detail_page_url": f"{BASE_URL}/venues/{slug}/",
            "booking_url": booking_url,
            "director": director,
            "year": year,
            "country": "",
            "runtime_min": runtime_min,
            "synopsis": synopsis[:500],
            "format_tags": format_tags,
        })

    return rows


def scrape_all_curzon() -> List[Dict]:
    """Scrape all London Curzon venues via the Vista Cloud JSON API."""
    print(f"[Curzon Chain] Starting scrape for {len(LONDON_SITES)} venues...", file=sys.stderr)

    config = _fetch_api_config()
    if not config:
        print("[Curzon Chain] Could not obtain API config from www.curzon.com - aborting", file=sys.stderr)
        return []
    api_url, token = config
    api_url = api_url.rstrip("/")

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
    })

    site_params = [("siteIds", sid) for sid in LONDON_SITES]
    film_cache: Dict[str, Dict] = {}
    crew_cache: Dict[str, Dict] = {}
    attr_cache: Dict[str, str] = {}

    all_shows: List[Dict] = []
    failed_dates: List[str] = []

    for offset in range(WINDOW_DAYS):
        business_date = (TODAY + dt.timedelta(days=offset)).isoformat()
        url = f"{api_url}/ocapi/v1/showtimes/by-business-date/{business_date}"
        try:
            resp = session.get(url, params=site_params, timeout=TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            print(f"[Curzon Chain] {business_date}: request failed: {exc}", file=sys.stderr)
            failed_dates.append(business_date)
            continue

        all_shows.extend(_showtime_rows(payload, film_cache, crew_cache, attr_cache))

    # Deduplicate
    seen = set()
    unique_shows = []
    for s in all_shows:
        key = (s["cinema_name"], s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    per_venue: Dict[str, int] = {name: 0 for name, _ in LONDON_SITES.values()}
    for s in unique_shows:
        per_venue[s["cinema_name"]] = per_venue.get(s["cinema_name"], 0) + 1
    empty_venues = [name for name, count in per_venue.items() if count == 0]

    if failed_dates:
        print(f"[Curzon Chain] WARNING: {len(failed_dates)} date(s) failed: {', '.join(failed_dates)}", file=sys.stderr)
    if empty_venues:
        print(
            f"[Curzon Chain] WARNING: {len(empty_venues)}/{len(LONDON_SITES)} venues "
            f"returned 0 showings: {', '.join(empty_venues)}",
            file=sys.stderr,
        )
    print(
        "[Curzon Chain] "
        + ", ".join(f"{name}={count}" for name, count in sorted(per_venue.items())),
        file=sys.stderr,
    )

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_all_curzon()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
