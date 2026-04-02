from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://cinema1900.shop-pro.jp/"
CINEMA_NAME = "シネマ・ノヴェチェント"


def clean_text(text: str) -> str:
    """Normalize whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def fetch_soup(url: str, encoding: str = "euc-jp") -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup object, or None on error."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        resp.encoding = encoding
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def parse_item_title(title: str) -> Optional[Dict]:
    """
    Parse title like '1/21 13時45分〜「帰ってきたあぶない刑事」応援上映'
    Returns {month, day, time, title} or None
    """
    # Regex to match M/D HH:MM or M/D H:MM
    # Handles spaces, wide characters etc.
    # Updated regex to be more robust
    match = re.search(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2})時(\d{1,2})分", title)
    if not match:
        return None
    
    month, day, hour, minute = match.groups()
    
    # Extract movie title - usually inside 「」 or after the time
    title_match = re.search(r"「(.*?)」", title)
    if title_match:
        movie_title = title_match.group(1)
    else:
        # Fallback: take everything after the time part
        # Removing the date/time prefix
        movie_title = re.sub(r"^\d{1,2}/\d{1,2}\s+\d{1,2}時\d{1,2}分[〜~]?", "", title).strip()
    
    # Clean up common suffixes like 上映会, 応援上映 etc. if they are not part of the core title
    # but for now we'll keep them as they are useful context
    
    current_year = datetime.now().year
    # Handle year wrap
    if int(month) < datetime.now().month and datetime.now().month > 10:
        year = current_year + 1
    else:
        year = current_year
        
    date_iso = f"{year}-{int(month):02d}-{int(day):02d}"
    time_str = f"{int(hour):02d}:{int(minute):02d}"
    
    return {
        "date_iso": date_iso,
        "time": time_str,
        "movie_title": movie_title
    }


def scrape_category(cbid: str) -> List[Dict]:
    """Scrape all items in a category (month)."""
    showings = []
    page = 1
    while True:
        url = f"{BASE_URL}?mode=cate&cbid={cbid}&csid=0&page={page}"
        soup = fetch_soup(url)
        if not soup:
            break
            
        # Items are usually in div.product_item or similar
        items = soup.select(".product_item")
        if not items:
            break
            
        for item in items:
            name_tag = item.select_one(".name a")
            if not name_tag:
                continue
                
            raw_title = clean_text(name_tag.get_text())
            detail_url = urljoin(BASE_URL, name_tag.get("href", ""))
            
            # Check if SOLD OUT
            sold_out = "SOLD OUT" in item.get_text()
            
            parsed = parse_item_title(raw_title)
            if parsed:
                showings.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": parsed["movie_title"],
                    "movie_title_en": None,
                    "director": None,
                    "year": None,
                    "country": None,
                    "runtime_min": None,
                    "date_text": parsed["date_iso"],
                    "showtime": parsed["time"],
                    "detail_page_url": detail_url,
                    "purchase_url": detail_url if not sold_out else None,
                })
        
        # Check for next page
        next_link = soup.find("a", string=re.compile(r"次へ"))
        if not next_link:
            break
            
        page += 1
        if page > 10: # safety
            break
            
    return showings


def scrape_cinema_novecento() -> List[Dict]:
    """
    Scrape Cinema Novecento showings from shop-pro.
    """
    # 1. Get Category IDs from home page
    soup = fetch_soup(BASE_URL)
    if not soup:
        return []
        
    category_options = soup.select("select[name='cid'] option")
    relevant_cbids = []
    
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    # Months to look for: current and next
    months_to_look = [
        (current_year, current_month),
        (current_year if current_month < 12 else current_year + 1, (current_month % 12) + 1)
    ]
    
    month_patterns = [f"{y}年{m}月上映" for y, m in months_to_look]
    
    for opt in category_options:
        text = opt.get_text().strip()
        val = opt.get("value", "")
        if not val or "," not in val:
            continue
            
        cbid = val.split(",")[0]
        
        # Match "2026年1月上映" etc.
        if any(p in text for p in month_patterns):
            relevant_cbids.append(cbid)
            
    all_showings = []
    for cbid in relevant_cbids:
        all_showings.extend(scrape_category(cbid))
        
    # Deduplicate
    seen = set()
    unique_showings = []
    for s in all_showings:
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_showings.append(s)
            
    return unique_showings


if __name__ == "__main__":
    data = scrape_cinema_novecento()
    print(f"{len(data)} showings found")
    for d in data[:10]:
        print(f"{d['date_text']} {d['showtime']} - {d['movie_title']}")
