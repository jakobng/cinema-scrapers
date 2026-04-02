#!/usr/bin/env python3
# olympic_studios_module.py
# Scraper for Olympic Studios (Barnes)
# https://www.olympiccinema.com/whats-on

import requests
import datetime
from bs4 import BeautifulSoup
import re

# Base URL
URL = "https://www.olympiccinema.com/whats-on"

def scrape_olympic_studios():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(URL, headers=headers)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching Olympic Studios: {e}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    
    final_data = []
    
    # Locate all date sections
    date_sections = soup.find_all('section', class_='date-section')
    
    current_year = datetime.datetime.now().year
    
    for section in date_sections:
        # Extract date: "Monday January 12"
        date_header = section.find('h3', class_='date-day')
        if not date_header:
            continue
            
        date_text = date_header.get_text(strip=True)
        # Parse date. Example: "Monday January 12"
        # We need to turn this into YYYY-MM-DD
        
        try:
            # Remove the day name (first word)
            # "Monday January 12" -> "January 12"
            day_month_part = " ".join(date_text.split()[1:])
            # Add year
            full_date_str = f"{day_month_part} {current_year}"
            dt_obj = datetime.datetime.strptime(full_date_str, "%B %d %Y")
            
            # adjustments for year boundary if needed (e.g. scraping in Dec for Jan)
            # If scraping date is Dec and show date is Jan, add 1 year
            now = datetime.datetime.now()
            if now.month == 12 and dt_obj.month == 1:
                dt_obj = dt_obj.replace(year=current_year + 1)
            # If scraping date is Jan and show date is Dec, subtract 1 year (unlikely but possible for cached/old pages)
            elif now.month == 1 and dt_obj.month == 12:
                dt_obj = dt_obj.replace(year=current_year - 1)
                
            formatted_date = dt_obj.strftime("%Y-%m-%d")
            
        except Exception as e:
            print(f"Error parsing date '{date_text}': {e}")
            continue

        # Find all movie rows in this section
        # The structure is:
        # <div class="row mb-5"> -> contains all movies for the day
        #   <div class="col-md-12"> -> one movie entry
        #     <div class="row ...">
        #       <div class="col-md-5 ..."> -> Title and Cert
        #       <div class="col ..."> -> Buttons
        
        movie_rows = section.find_all('div', class_='col-md-12')
        
        for row in movie_rows:
            # Title
            title_tag = row.find('h5', class_='h5-title')
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            
            # Find times and links
            buttons = row.find_all('a', class_='btn')
            
            for btn in buttons:
                if 'disabled' in btn.get('class', []):
                    # Check if sold out
                    # Sometimes sold out buttons are disabled but still have time
                    pass
                
                time_span = btn.find('span', class_='btn-times-fs')
                if not time_span:
                    continue
                    
                time_str = time_span.get_text(strip=True)
                booking_link = btn.get('href')
                
                # Handling "Sold Out" or other status
                is_sold_out = False
                status_span = btn.find('span', class_='opacity-7')
                if status_span and "Sold Out" in status_span.get_text():
                    is_sold_out = True
                
                # Check format tags (e.g. Babes in Arms)
                format_tags = []
                if status_span:
                   status_text = status_span.get_text(strip=True)
                   if "Babes in Arms" in status_text:
                       format_tags.append("Babes in Arms")
                   if "Preview" in status_text:
                       format_tags.append("Preview")
                   if "Q&A" in status_text:
                       format_tags.append("Q&A")

                final_data.append({
                    "cinema_name": "Olympic Studios (Barnes)",
                    "movie_title": title,
                    "date_text": formatted_date,
                    "showtime": time_str,
                    "booking_url": booking_link,
                    "is_sold_out": is_sold_out,
                    "format_tags": format_tags
                })

    return final_data

if __name__ == "__main__":
    data = scrape_olympic_studios()
    import json
    print(json.dumps(data, indent=2))
