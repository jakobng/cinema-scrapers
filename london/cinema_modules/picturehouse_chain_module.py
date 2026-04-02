#!/usr/bin/env python3
# picturehouse_chain_module.py
# Scraper for all London Picturehouse Cinemas
# https://www.picturehouses.com

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from typing import Dict, List, Optional
from urllib.parse import unquote

import requests

BASE_URL = "https://www.picturehouses.com"
CINEMA_LIST_URL = f"{BASE_URL}/ajax-cinema-list"
SCHEDULE_API_URL = f"{BASE_URL}/api/scheduled-movies-ajax"

# Map of Cinema ID (string format used in API) to Display Name
# Based on inspection of ajax-cinema-list
LONDON_CINEMAS = {
    "020": "Clapham Picturehouse",
    "024": "Crouch End Picturehouse",
    "031": "Ealing Picturehouse",
    "009": "East Dulwich Picturehouse",
    "029": "Finsbury Park Picturehouse",
    "021": "Greenwich Picturehouse",
    "010": "Hackney Picturehouse",
    "022": "Picturehouse Central",
    "004": "Ritzy Cinema",
    "016": "The Gate",
    "023": "West Norwood Picturehouse",
    # "030": "Epsom Picturehouse", # Outside London Zone usually, but could include if requested
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

def get_session_and_token():
    """Initializes session and gets XSRF token."""
    session = requests.Session()
    try:
        # Accessing the base page initializes the session and cookies
        init_resp = session.get(BASE_URL, headers=HEADERS, timeout=30)
        init_resp.raise_for_status()
        
        xsrf_token = session.cookies.get("XSRF-TOKEN")
        if not xsrf_token:
            match = re.search(r'var token = "(.*?)";', init_resp.text)
            if match:
                xsrf_token = match.group(1)
        
        return session, unquote(xsrf_token) if xsrf_token else None
    except Exception as e:
        print(f"[Picturehouse Chain] Error initializing session: {e}", file=sys.stderr)
        return None, None

def scrape_picturehouse_site(session, cinema_id, cinema_name, xsrf_token) -> List[Dict]:
    """Scrapes a single Picturehouse cinema."""
    shows = []
    
    post_headers = HEADERS.copy()
    if xsrf_token:
        post_headers["X-XSRF-TOKEN"] = xsrf_token

    payload = {
        "cinema_id": cinema_id
    }
    
    try:
        resp = session.post(SCHEDULE_API_URL, data=payload, headers=post_headers, timeout=30)
        resp.raise_for_status()
        
        data = resp.json()
        if isinstance(data, str):
            data = json.loads(data)

        if data.get("response") != "success":
            return []

        movies = data.get("movies", [])
        for movie in movies:
            title = movie.get("Title", "").strip()
            movie_slug = movie.get("slug", "")
            scheduled_film_id = movie.get("ScheduledFilmId")

            show_times = movie.get("show_times", [])
            for st in show_times:
                # Ensure it matches our cinema ID
                if str(st.get("CinemaId")) != str(cinema_id):
                    continue
                
                date_str = st.get("date_f") # e.g. "2026-01-09"
                
                raw_time = st.get("show_time")
                if isinstance(raw_time, (int, float)) or (isinstance(raw_time, str) and raw_time.isdigit()):
                    try:
                        dt_obj = dt.datetime.fromtimestamp(int(raw_time))
                        time_str = dt_obj.strftime("%H:%M")
                    except ValueError:
                        time_str = str(raw_time)
                else:
                    time_str = str(raw_time)
                
                session_id = st.get("ScheduledSessionId")
                booking_url = f"{BASE_URL}/api/movies/checkout/{cinema_id}/{session_id}"
                detail_url = f"{BASE_URL}/movie-details/{cinema_id}/{scheduled_film_id}/{movie_slug}"

                shows.append({
                    "cinema_name": cinema_name,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": date_str,
                    "showtime": time_str,
                    "detail_page_url": detail_url,
                    "booking_url": booking_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
                    "format_tags": [] # Could extract 3D/IMAX from movie properties if available
                })
                
    except Exception as e:
        print(f"[{cinema_name}] Error scraping: {e}", file=sys.stderr)

    return shows

def scrape_all_picturehouse() -> List[Dict]:
    """Scrapes all configured London Picturehouse cinemas."""
    all_shows = []
    
    session, token = get_session_and_token()
    if not session or not token:
        print("[Picturehouse Chain] Failed to get session/token. Aborting.", file=sys.stderr)
        return []

    print(f"[Picturehouse Chain] Starting scrape for {len(LONDON_CINEMAS)} cinemas...", file=sys.stderr)

    for cinema_id, cinema_name in LONDON_CINEMAS.items():
        print(f"[Picturehouse Chain] Scraping {cinema_name}...", file=sys.stderr)
        site_shows = scrape_picturehouse_site(session, cinema_id, cinema_name, token)
        all_shows.extend(site_shows)
        time.sleep(0.5) # Be polite between requests

    return sorted(all_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))

if __name__ == "__main__":
    data = scrape_all_picturehouse()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
