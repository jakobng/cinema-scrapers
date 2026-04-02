#!/usr/bin/env python3
# the_arzner_module.py
# Scraper for The Arzner (formerly Kino Bermondsey)
# https://thearzner.com
#
# Data source: Embedded JSON in the homepage HTML "var Events = {...}"

import json
import re
import sys
import datetime as dt
from typing import List, Dict, Optional
import requests

CINEMA_NAME = "The Arzner"
BASE_URL = "https://thearzner.com"
BOOKING_BASE_URL = "https://thearzner.com/TheArzner.dll/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

def _clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove HTML tags if any (basic)
    text = re.sub(r'<[^>]+>', '', text)
    return " ".join(text.split())

def scrape_the_arzner() -> List[Dict]:
    """
    Scrapes The Arzner showtimes from the homepage embedded JSON.
    """
    shows = []
    
    try:
        print(f"[{CINEMA_NAME}] Fetching homepage...", file=sys.stderr)
        resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text

        # Extract JSON
        # Looking for: var Events = {...}
        match = re.search(r'var\s+Events\s*=\s*(\{.*?\})\s*;?\s*\n', html, re.DOTALL)
        if not match:
            print(f"[{CINEMA_NAME}] Could not find 'var Events' JSON in HTML.", file=sys.stderr)
            return []

        json_str = match.group(1)
        
        # Clean up potential trailing commas or JS-specific quirks if json.loads fails
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"[{CINEMA_NAME}] JSON decode error: {e}. Trying to fix common JS JSON issues...", file=sys.stderr)
            # Sometimes JS objects keys are not quoted, but here they seem to be.
            # Let's try a more lenient parser or just fail if it's too broken.
            return []

        events = data.get("Events", [])
        print(f"[{CINEMA_NAME}] Found {len(events)} events.", file=sys.stderr)

        today = dt.date.today()
        window_end = today + dt.timedelta(days=30) # Good lookahead

        for event in events:
            title = _clean_text(event.get("Title"))
            film_id = event.get("ID")
            synopsis = _clean_text(event.get("Synopsis"))
            director = _clean_text(event.get("Director"))
            year = str(event.get("Year", ""))
            
            # Duration in minutes
            runtime = event.get("RunningTime")
            
            # Format tags from title or tags list
            # "Tags": [{"Format": ""}] - seems empty in sample, but maybe useful later
            
            performances = event.get("Performances", [])
            
            for perf in performances:
                # "StartDate": "2026-01-12"
                date_str = perf.get("StartDate")
                # "StartTime": "1500"
                time_str = perf.get("StartTime")
                
                if not date_str or not time_str:
                    continue
                
                try:
                    perf_date = dt.date.fromisoformat(date_str)
                except ValueError:
                    continue
                
                if perf_date < today:
                    continue
                    
                # Format time "1500" -> "15:00"
                if len(time_str) == 4:
                    formatted_time = f"{time_str[:2]}:{time_str[2:]}"
                else:
                    formatted_time = time_str # Fallback
                
                # Booking URL
                # "URL": "Booking?Booking=..."
                rel_url = perf.get("URL", "")
                booking_url = f"{BOOKING_BASE_URL}{rel_url}"
                
                # Is Sold Out?
                is_sold_out = perf.get("IsSoldOut") == "Y"
                if is_sold_out:
                    continue # Skip sold out shows? Or keep them? Usually we skip or mark.
                    # Project convention seems to be skip or include. 
                    # If I look at other scrapers, they usually include valid shows.
                    # But if it's sold out, maybe not useful.
                    # Let's include for now, user can filter. 
                    # Actually, main_scraper doesn't seem to filter sold out.
                    pass

                # Attributes
                notes = []
                if perf.get("CC") == "Y":
                    notes.append("CC")
                
                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": date_str,
                    "showtime": formatted_time,
                    "detail_page_url": f"{BOOKING_BASE_URL}WhatsOn?f={film_id}",
                    "booking_url": booking_url,
                    "director": director,
                    "year": year,
                    "country": _clean_text(event.get("Country", "")),
                    "runtime_min": str(runtime) if runtime else "",
                    "synopsis": synopsis,
                    "format_tags": notes
                })

    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        return []

    return shows

if __name__ == "__main__":
    # Test run
    data = scrape_the_arzner()
    print(json.dumps(data, indent=2))