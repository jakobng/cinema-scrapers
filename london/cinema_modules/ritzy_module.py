#!/usr/bin/env python3
# ritzy_module.py
# Scraper for Ritzy Cinema (Brixton)
# https://www.picturehouses.com/cinema/ritzy-picturehouse

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List
from urllib.parse import unquote

import requests

BASE_URL = "https://www.picturehouses.com"
CINEMA_LIST_URL = f"{BASE_URL}/ajax-cinema-list"
SCHEDULE_API_URL = f"{BASE_URL}/api/scheduled-movies-ajax"
CINEMA_NAME = "Ritzy Cinema"
# We target 'Ritzy' but will search dynamically to be safe
TARGET_SLUG_PART = "ritzy" 

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

def scrape_ritzy() -> List[Dict]:
    """Scrape Ritzy Cinema showtimes."""
    shows: List[Dict] = []
    
    session = requests.Session()
    session.trust_env = False
    
    try:
        # Step 1: Get XSRF token and cookies
        # Accessing the cinema page initializes the session
        init_resp = session.get(f"{BASE_URL}/cinema/ritzy-picturehouse", headers=HEADERS, timeout=30)
        init_resp.raise_for_status()
        
        xsrf_token = session.cookies.get("XSRF-TOKEN")
        if not xsrf_token:
            match = re.search(r'var token = "(.*?)";', init_resp.text)
            if match:
                xsrf_token = match.group(1)
        
        if not xsrf_token:
            print(f"[{CINEMA_NAME}] Warning: XSRF token not found. Request might fail.", file=sys.stderr)
            return []

        # Prepare headers for POST requests
        post_headers = HEADERS.copy()
        post_headers["X-XSRF-TOKEN"] = unquote(xsrf_token)

        # Step 2: Get Cinema ID dynamically
        # This is more robust than hardcoding "004"
        cinema_id = None
        
        list_resp = session.post(CINEMA_LIST_URL, headers=post_headers, timeout=30)
        list_resp.raise_for_status()
        
        list_data = list_resp.json()
        if isinstance(list_data, str):
            list_data = json.loads(list_data)
            
        cinema_list = list_data.get("cinema_list", [])
        for cinema in cinema_list:
            slug = cinema.get("slug", "").lower()
            name = cinema.get("name", "").lower()
            if TARGET_SLUG_PART in slug or TARGET_SLUG_PART in name:
                cinema_id = cinema.get("cinema_id")
                # print(f"[{CINEMA_NAME}] Found Cinema ID: {cinema_id} ({cinema.get('name')})")
                break
        
        if not cinema_id:
            print(f"[{CINEMA_NAME}] Could not find cinema ID for Ritzy.", file=sys.stderr)
            return []

        # Step 3: Request scheduled movies
        payload = {
            "cinema_id": cinema_id
        }
        
        resp = session.post(SCHEDULE_API_URL, data=payload, headers=post_headers, timeout=30)
        resp.raise_for_status()
        
        data = resp.json()
        if isinstance(data, str):
            data = json.loads(data)

        if data.get("response") != "success":
            # Sometimes it might just be empty or have a different status
            pass

        movies = data.get("movies", [])
        for movie in movies:
            title = movie.get("Title", "").strip()
            # movie_id = movie.get("ScheduledFilmId") 
            
            show_times = movie.get("show_times", [])
            for st in show_times:
                # Ensure it matches our cinema ID (API usually filters, but good to double check)
                if str(st.get("CinemaId")) != str(cinema_id):
                    continue
                
                date_str = st.get("date_f") # e.g. "2026-01-09"
                
                # 'show_time' from API might be a timestamp or HH:MM string
                raw_time = st.get("show_time")
                if isinstance(raw_time, (int, float)) or (isinstance(raw_time, str) and raw_time.isdigit()):
                    # Convert timestamp to HH:MM
                    try:
                        dt_obj = dt.datetime.fromtimestamp(int(raw_time))
                        time_str = dt_obj.strftime("%H:%M")
                    except ValueError:
                        time_str = str(raw_time)
                else:
                    time_str = str(raw_time) 
                
                # Booking URL
                session_id = st.get("ScheduledSessionId")
                booking_url = f"{BASE_URL}/api/movies/checkout/{cinema_id}/{session_id}"
                
                # Detail Page URL
                # Best guess construction
                detail_url = f"{BASE_URL}/movie-details/{cinema_id}/{st.get('ScheduledFilmId')}/{movie.get('slug', '')}"

                listing = {
                    "cinema_name": CINEMA_NAME,
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
                }
                
                shows.append(listing)

    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        return []

    return sorted(shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))

if __name__ == "__main__":
    data = scrape_ritzy()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\nTotal: {len(data)} showings")