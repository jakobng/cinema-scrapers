"""
athenee_francais_module.py — Scraper for Athénée Français Cultural Center (Tokyo)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --- Constants ---
CINEMA_NAME = "アテネ・フランセ文化センター"
BASE_URL = "https://athenee.net/culturalcenter/"
SCHEDULE_INDEX_URL = urljoin(BASE_URL, "schedule/schedule.html")

# --- Helper Functions ---

def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        # Athénée Français site uses UTF-8 usually, but let's be safe
        response.encoding = response.apparent_encoding or 'utf-8'
        return BeautifulSoup(response.text, 'html.parser')
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None

def _clean_text(text: str) -> str:
    """Normalizes whitespace."""
    if not text: return ""
    return " ".join(text.split())

def _parse_program_page(url: str, year_context: int) -> List[Dict]:
    """Scrapes a specific program page for showtimes."""
    soup = _fetch_soup(url)
    if not soup: return []

    showings = []
    
    # Try to find the year in the page if context is shaky
    # Usually h2 has something like "2025年12月18日（木）―20日（土）"
    h2_text = ""
    h2_tag = soup.find('h2')
    if h2_tag:
        h2_text = _clean_text(h2_tag.get_text())
        year_match = re.search(r'(\d{4})年', h2_text)
        if year_match:
            year_context = int(year_match.group(1))

    # Find all date spans
    date_spans = soup.find_all('span', class_='date')
    for span in date_spans:
        date_text = _clean_text(span.get_text())
        # Format: "12月18日（木）"
        m = re.search(r'(\d{1,2})月(\d{1,2})日', date_text)
        if not m: continue
        
        month, day = int(m.group(1)), int(m.group(2))
        try:
            date_obj = datetime(year_context, month, day).date()
        except ValueError:
            continue

        # The schedule table usually follows the date span or its parent p
        table = span.find_next('table', class_='schedule')
        if not table:
            # Sometimes it's inside a p or after a br
            table = span.parent.find_next('table', class_='schedule')
            
        if table:
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 2: continue
                
                time_str = _clean_text(cols[0].get_text())
                # Validate time format HH:MM
                if not re.match(r'\d{1,2}:\d{2}', time_str):
                    continue
                
                # Title column
                title_col = cols[1]
                # Skip if it's a talk/lecture (usually contains 'トーク' or '対談')
                col_text = _clean_text(title_col.get_text())
                if re.search(r'トーク|対談|講演|講義|オンライントーク|シンポジウム', col_text):
                    continue
                
                # Title is often in span.futo or just text
                futo = title_col.find('span', class_='futo')
                if futo:
                    movie_title = _clean_text(futo.get_text())
                else:
                    movie_title = col_text
                
                # Strip brackets if present: 『タイトル』 -> タイトル
                movie_title = re.sub(r'^『(.*?)』$', r'\1', movie_title)
                
                # Additional metadata might be in div#informationad
                # For simplicity, we just take the title and basic info
                
                showings.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title,
                    "date_text": date_obj.isoformat(),
                    "showtime": time_str,
                    "detail_page_url": url,
                    "director": "", # Optional enrichment
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
                    "movie_title_en": ""
                })

    return showings

def scrape_athenee_francais() -> List[Dict]:
    """
    Main entry point for the Athénée Français scraper.
    """
    print(f"INFO: [{CINEMA_NAME}] Fetching index: {SCHEDULE_INDEX_URL}")
    soup = _fetch_soup(SCHEDULE_INDEX_URL)
    if not soup: return []

    all_showings = []
    
    # Determine the current JST time
    JST = timezone(timedelta(hours=9))
    now = datetime.now(timezone.utc).astimezone(JST)
    current_year = now.year
    current_month = now.month
    
    # Find links to quarterly schedules
    # They are in div#year blocks
    year_divs = soup.find_all('div', id='year')
    target_quarter_link = None
    target_year = current_year
    
    # Quarterly labels: "1月.2月.3月", "4月.5月.6月", "7月.8月.9月", "10月.11月.12月"
    if 1 <= current_month <= 3: quarter_pattern = "1月.2月.3月"
    elif 4 <= current_month <= 6: quarter_pattern = "4月.5月.6月"
    elif 7 <= current_month <= 9: quarter_pattern = "7月.8月.9月"
    else: quarter_pattern = "10月.11月.12月"

    for ydiv in year_divs:
        h1 = ydiv.find('h1')
        if not h1: continue
        year_text = _clean_text(h1.get_text())
        if str(current_year) in year_text:
            links = ydiv.find_all('a')
            for a in links:
                if quarter_pattern in _clean_text(a.get_text()):
                    target_quarter_link = urljoin(SCHEDULE_INDEX_URL, a['href'])
                    target_year = current_year
                    break
        if target_quarter_link: break

    # If not found for current year, check next year if it's late in the year? 
    # Or just fallback to the first one available in the first div.
    if not target_quarter_link and year_divs:
        # Fallback to the very first link in the first year div (most recent)
        first_a = year_divs[0].find('a')
        if first_a:
            target_quarter_link = urljoin(SCHEDULE_INDEX_URL, first_a['href'])
            year_h1 = year_divs[0].find('h1')
            if year_h1:
                m = re.search(r'(\d{4})', year_h1.get_text())
                if m: target_year = int(m.group(1))

    if not target_quarter_link:
        print(f"WARN: [{CINEMA_NAME}] No quarterly schedule link found.")
        return []

    print(f"INFO: [{CINEMA_NAME}] Fetching quarter: {target_quarter_link}")
    q_soup = _fetch_soup(target_quarter_link)
    if not q_soup: return []

    # Program pages are linked in div#headline div#article
    program_links = []
    headline = q_soup.find('div', id='headline')
    if headline:
        articles = headline.find_all('div', id='article')
        for art in articles:
            a = art.find('a', href=re.compile(r'/program/'))
            if a:
                program_links.append(urljoin(target_quarter_link, a['href']))

    # Also check the schedule.html page itself as it sometimes lists upcoming events
    articles_index = soup.find_all('div', id='article')
    for art in articles_index:
        a = art.find('a', href=re.compile(r'/program/'))
        if a:
            program_links.append(urljoin(SCHEDULE_INDEX_URL, a['href']))

    # Deduplicate program links
    program_links = list(set(program_links))
    
    for p_url in program_links:
        print(f"INFO: [{CINEMA_NAME}] Scoping program: {p_url}")
        showings = _parse_program_page(p_url, target_year)
        all_showings.extend(showings)

    # Filter for future dates (optional, but good for keeping it clean)
    # The main scraper handles filtering usually, but we want to be relevant.
    today = now.date()
    # Keep showtimes from today onwards
    future_showings = [s for s in all_showings if s['date_text'] >= today.isoformat()]

    # Sort and deduplicate
    unique_showings = list({(s["date_text"], s["movie_title"], s["showtime"]): s for s in future_showings}.values())
    unique_showings.sort(key=lambda x: (x.get('date_text', ''), x.get('showtime', '')))

    print(f"INFO: [{CINEMA_NAME}] Collected {len(unique_showings)} unique showings.")
    return unique_showings

if __name__ == '__main__':
    # Test execution
    data = scrape_athenee_francais()
    print(json.dumps(data, ensure_ascii=False, indent=2))
