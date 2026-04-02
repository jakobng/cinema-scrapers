#!/usr/bin/env python3
# david_lean_module.py
# Scraper for David Lean Cinema (Croydon)
# Uses Ticketsolve XML feed

import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import re
import html

CINEMA_NAME = "David Lean Cinema"
FEED_URL = "https://davidleancinema.ticketsolve.com/shows.xml"

def clean_html(raw_html):
    """Remove HTML tags and clean whitespace."""
    if not raw_html:
        return ""
    # Decode HTML entities
    text = html.unescape(raw_html)
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', text)
    return cleantext.strip()

def scrape_david_lean():
    print(f"Scraping {CINEMA_NAME}...")
    try:
        response = requests.get(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        
        # Parse XML
        root = ET.fromstring(response.content)
        
        listings = []
        
        # Structure: <venues><venue><shows><show>...</show></shows></venue></venues>
        # We can find all 'show' elements directly if they are unique enough, or traverse.
        
        for show in root.findall(".//show"):
            title_elem = show.find("name")
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Unknown Title"
            
            # Extract description
            desc_elem = show.find("description")
            raw_desc = desc_elem.text if desc_elem is not None else ""
            synopsis = clean_html(raw_desc)
            
            # Extract events
            events_elem = show.find("events")
            if events_elem is None:
                continue
                
            for event in events_elem.findall("event"):
                # Date Time
                iso_elem = event.find("date_time_iso")
                if iso_elem is None or not iso_elem.text:
                    continue
                
                dt_str = iso_elem.text.strip()
                try:
                    # Python's fromisoformat supports +00:00 in newer versions, 
                    # but to be safe with older python (though 3.7+ is fine):
                    dt_obj = datetime.fromisoformat(dt_str)
                    date_text = dt_obj.strftime("%Y-%m-%d")
                    showtime = dt_obj.strftime("%H:%M")
                except ValueError:
                    print(f"Skipping invalid date: {dt_str}")
                    continue
                
                # Url
                url_elem = event.find("url")
                booking_url = url_elem.text.strip() if url_elem is not None else ""
                
                listing = {
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": date_text,
                    "showtime": showtime,
                    "detail_page_url": booking_url,
                    "booking_url": booking_url,
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": synopsis,
                }
                listings.append(listing)
                
        return listings

    except Exception as e:
        print(f"Error scraping {CINEMA_NAME}: {e}")
        return []

if __name__ == "__main__":
    data = scrape_david_lean()
    import json
    print(json.dumps(data, indent=2, default=str))