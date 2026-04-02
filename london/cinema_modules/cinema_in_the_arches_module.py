#!/usr/bin/env python3
# cinema_in_the_arches_module.py
# Scraper for The Cinema in the Arches (Battersea Power Station)
# https://www.thecinemainthepowerstation.com/whats-on

import datetime as dt
import re
import requests
from bs4 import BeautifulSoup
import sys

# Constants
CINEMA_NAME = "The Cinema in the Arches"
BASE_URL = "https://www.thecinemainthepowerstation.com"
SCHEDULE_URL = f"{BASE_URL}/whats-on"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def get_year_for_date(show_date):
    """
    Heuristic to determine the year of a showtime.
    If the month is significantly earlier than the current month, assume it's next year.
    """
    today = dt.date.today()
    year = today.year
    # If show month is Jan (1) and current month is Dec (12), it's next year.
    if show_date.month < today.month and (today.month - show_date.month) > 6:
        year += 1
    # If show month is Dec (12) and current month is Jan (1), it was last year (unlikely for future listings but good for robustness)
    elif show_date.month > today.month and (show_date.month - today.month) > 6:
        year -= 1
    
    return show_date.replace(year=year)

def parse_date(date_text):
    """
    Parses date string like "Friday January 9".
    """
    try:
        # Strip day name
        parts = date_text.split()
        if len(parts) >= 3:
            # "January 9"
            month_day = " ".join(parts[1:]) 
            # Parse month day
            date_obj = dt.datetime.strptime(month_day, "%B %d").date()
            return get_year_for_date(date_obj)
    except Exception as e:
        print(f"Error parsing date '{date_text}': {e}", file=sys.stderr)
    return None

def scrape_cinema_in_the_arches():
    showings = []
    
    try:
        response = requests.get(SCHEDULE_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Iterate over date sections
        date_sections = soup.select(".date-section")
        
        for section in date_sections:
            date_header = section.select_one(".date-day")
            if not date_header:
                continue
                
            date_text = date_header.get_text(strip=True)
            show_date = parse_date(date_text)
            
            if not show_date:
                continue
                
            # Iterate over movie blocks within the date section
            # The structure seems to be: .row.mb-5 -> .col-md-12 (one per movie)
            movie_blocks = section.select(".col-md-12")
            
            for block in movie_blocks:
                title_el = block.select_one(".h5-title a")
                if not title_el:
                    # Try finding title directly if not in 'a' tag
                    title_el = block.select_one(".h5-title")
                    
                if not title_el:
                    continue
                    
                movie_title = title_el.get_text(strip=True)
                movie_link = title_el.get("href") if title_el.name == "a" else ""
                detail_url = f"{BASE_URL}{movie_link}" if movie_link else ""
                
                # Check for "The Cinema in the Arches" venue
                # The structure is: 
                # .col (right side) -> h6 "The Cinema in the Arches" -> div -> a.btn-arches
                
                # Find all venue headers in this block
                venue_headers = block.select("h6.text-muted.fw-semibold")
                
                for v_header in venue_headers:
                    venue_name = v_header.get_text(strip=True)
                    if "Arches" not in venue_name:
                        continue
                        
                    # The showtimes are in the div immediately following the header
                    # OR in the same column. Let's look for the next sibling div or parent's buttons
                    
                    # Based on HTML snippet:
                    # <h6 ...>The Cinema in the Arches</h6>
                    # <div class="d-flex flex-wrap">
                    #    <a class="btn btn-arches ...">
                    
                    times_container = v_header.find_next_sibling("div")
                    if not times_container:
                        continue
                        
                    buttons = times_container.select("a.btn-arches")
                    
                    for btn in buttons:
                        # Extract time
                        time_span = btn.select_one(".btn-times-fs")
                        if not time_span:
                            continue
                        time_text = time_span.get_text(strip=True)
                        
                        # Extract booking URL
                        booking_url = btn.get("data-booking-url") or btn.get("href")
                        if booking_url == "#":
                            booking_url = "" # Fallback if only hash is present
                            
                        # Extract Format (e.g. 3D, Subtitled)
                        # Snippet: <span class="ms-2 opacity-7" style="line-height: 1;">Subtitled</span>
                        # OR <i class="bi bi-badge-3d-fill fs-4"></i>
                        notes = []
                        if btn.select_one(".bi-badge-3d-fill"):
                            notes.append("3D")
                        
                        # Look for text spans that aren't the time
                        for span in btn.select("span"):
                            if "btn-times-fs" not in span.get("class", []):
                                txt = span.get_text(strip=True)
                                if txt and txt != "Sold Out":
                                    notes.append(txt)
                        
                        is_sold_out = False
                        if btn.select_one('[data-bs-title="Sold Out"]') or "disabled" in btn.get("class", []):
                             is_sold_out = True
                             # Sometimes "Sold Out" text is inside a span we captured in notes
                             if "Sold Out" in notes:
                                 notes.remove("Sold Out")

                        showings.append({
                            "cinema_name": CINEMA_NAME,
                            "movie_title": movie_title,
                            "date_text": show_date.isoformat(),
                            "showtime": time_text,
                            "booking_url": booking_url,
                            "detail_page_url": detail_url,
                            "is_sold_out": is_sold_out,
                            "notes": ", ".join(notes)
                        })

    except Exception as e:
        print(f"Error scraping {CINEMA_NAME}: {e}", file=sys.stderr)
        return []

    return showings

if __name__ == "__main__":
    import json
    data = scrape_cinema_in_the_arches()
    print(json.dumps(data, indent=2))
