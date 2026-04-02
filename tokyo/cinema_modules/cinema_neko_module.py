# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, date
import sys

# --- Start: Configure stdout and stderr for UTF-8 on Windows ---
if __name__ == "__main__" and sys.platform == "win32":
    try:
        if sys.stdout.encoding != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
# --- End: Configure stdout and stderr ---

CINEMA_NAME_NEKO = "Cinema Neko (シネマネコ)"
BASE_URL = "https://cinema-neko.com/"

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()

def scrape_cinema_neko():
    showings = []
    try:
        response = requests.get(BASE_URL, timeout=30)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Find all movie detail links
        movie_links = set()
        for a in soup.select('section.movieList a[href^="movie_detail.php"]'):
            movie_links.add(BASE_URL + a['href'])
            
        print(f"Found {len(movie_links)} unique movie pages at {CINEMA_NAME_NEKO}")
        
        today = date.today()
        
        # 2. Scrape each detail page
        for link in movie_links:
            try:
                res = requests.get(link, timeout=20)
                res.encoding = 'utf-8'
                m_soup = BeautifulSoup(res.text, 'html.parser')
                
                title_h3 = m_soup.select_one('.movieDetail .title h3')
                if not title_h3: continue
                title = clean_text(title_h3.get_text())
                
                # Schedule is in .week li
                schedule_items = m_soup.select('.week li')
                for item in schedule_items:
                    day_div = item.select_one('.day')
                    if not day_div: continue
                    
                    # day_div text is like "1/14（水）"
                    day_text_raw = clean_text(day_div.get_text())
                    match = re.search(r'(\d{1,2})/(\d{1,2})', day_text_raw)
                    if not match: continue
                    
                    month, day_val = int(match.group(1)), int(match.group(2))
                    
                    # Determine year
                    year = today.year
                    if month < today.month and (today.month - month) > 6: year += 1
                    elif month > today.month and (month - today.month) > 6: year -= 1
                    
                    date_str = f"{year}-{month:02d}-{day_val:02d}"
                    
                    # Times are in .cell
                    for cell in item.select('.cell'):
                        # Check if it has a time or "上映なし"
                        time_div = cell.select_one('.time strong')
                        if not time_div: continue
                        
                        start_time = clean_text(time_div.get_text())
                        # Format HH:MM
                        time_match = re.search(r'(\d{1,2}):(\d{2})', start_time)
                        if time_match:
                            start_time = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"
                        
                        showings.append({
                            "cinema_name": CINEMA_NAME_NEKO,
                            "date_text": date_str,
                            "movie_title": title,
                            "showtime": start_time,
                            "year": str(year),
                            "detail_page_url": link
                        })
            except Exception as e:
                print(f"Error scraping {link}: {e}")
                
    except Exception as e:
        print(f"Error in scrape_cinema_neko: {e}")
        
    return showings

if __name__ == "__main__":
    results = scrape_cinema_neko()
    for s in sorted(results, key=lambda x: (x['date_text'], x['showtime'])):
        print(f"{s['date_text']} | {s['showtime']} | {s['movie_title']}")
