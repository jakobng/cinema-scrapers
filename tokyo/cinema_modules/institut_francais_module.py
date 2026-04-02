from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_ORIGIN = "https://culture.institutfrancais.jp"
BASE_URL = f"{BASE_ORIGIN}/event?taxonomy=cinema"
CINEMA_NAME = "アンスティチュ・フランセ東京"
EVENT_URL_RE = re.compile(r"/event/[^/?#]+")


def clean_text(text: str) -> str:
    """Normalize whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup object, or None on error."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def parse_peatix_link_text(text: str) -> Optional[tuple[str, str]]:
    """
    Parse text like '1月16日(金) 16:00'
    Returns (date_iso, time_str)
    """
    # Pattern: MM月DD日... HH:MM
    match = re.search(r"(\d+)月(\d+)日.*?(\d{1,2}:\d{2})", text)
    if not match:
        return None

    month, day, time_str = match.groups()
    current_year = datetime.now().year
    
    # Heuristic for year transition
    if int(month) < datetime.now().month and datetime.now().month > 10:
        year = current_year + 1
    else:
        year = current_year

    date_iso = f"{year:04d}-{int(month):02d}-{int(day):02d}"
    return date_iso, time_str


def _extract_event_title(soup: BeautifulSoup, fallback_title: str) -> str:
    if fallback_title and len(fallback_title) > 2:
        return fallback_title
    for selector in ("h1", ".title-main", ".entry-title", "h2"):
        title_tag = soup.select_one(selector)
        if title_tag:
            title_text = clean_text(title_tag.get_text())
            if title_text:
                return title_text
    return fallback_title


def _page_mentions_tokyo(page_text: str) -> bool:
    if not page_text:
        return False
    if "場所" not in page_text and "会場" not in page_text:
        return True
    return ("東京" in page_text) or ("Tokyo" in page_text)


def _extract_datetimes_from_text(text: str) -> List[tuple[str, str]]:
    results: List[tuple[str, str]] = []
    if not text:
        return results
    for match in re.findall(r"(\d{1,2})月(\d{1,2})日[^\d]{0,8}(\d{1,2}:\d{2})", text):
        month, day, time_str = match
        current_year = datetime.now().year
        if int(month) < datetime.now().month and datetime.now().month > 10:
            year = current_year + 1
        else:
            year = current_year
        date_iso = f"{year:04d}-{int(month):02d}-{int(day):02d}"
        results.append((date_iso, time_str))
    return results


def scrape_event_page(url: str, event_title: str) -> List[Dict]:
    """
    Extract specific screenings from an event detail page.
    """
    results = []
    soup = fetch_soup(url)
    if not soup:
        return results

    page_text = soup.get_text(" ", strip=True)
    if not _page_mentions_tokyo(page_text):
        return results

    event_title = _extract_event_title(soup, event_title)

    # Specific screenings are often in 'text-box' or 'detail-box'
    # and usually linked to Peatix.
    peatix_links = soup.find_all("a", href=lambda h: h and "peatix.com" in h)
    
    for link in peatix_links:
        link_text = clean_text(link.get_text())
        parsed = parse_peatix_link_text(link_text)
        if not parsed:
            continue
        
        date_iso, time_str = parsed
        
        # Try to find the movie title. It's often in the nearest preceding H3.
        movie_title = event_title # Default to event title
        
        # Look back for H3
        prev_h3 = link.find_previous("h3")
        if prev_h3:
            h3_text = clean_text(prev_h3.get_text())
            # Sometimes H3 is "【作品紹介】" or similar, ignore those
            if "作品紹介" not in h3_text and h3_text:
                movie_title = h3_text

        # Clean movie title (often has French title attached)
        # e.g. "気のいい女たち　Les Bonnes femmes"
        # We'll keep it as is or try to split if needed.
        
        results.append({
            "cinema_name": CINEMA_NAME,
            "movie_title": movie_title,
            "movie_title_en": None,
            "director": None,
            "year": None,
            "country": None,
            "runtime_min": None,
            "date_text": date_iso,
            "showtime": time_str,
            "detail_page_url": url,
            "program_title": event_title,
            "purchase_url": link["href"],
        })

    if results:
        return results

    for date_iso, time_str in _extract_datetimes_from_text(page_text):
        results.append({
            "cinema_name": CINEMA_NAME,
            "movie_title": event_title,
            "movie_title_en": None,
            "director": None,
            "year": None,
            "country": None,
            "runtime_min": None,
            "date_text": date_iso,
            "showtime": time_str,
            "detail_page_url": url,
            "program_title": event_title,
            "purchase_url": None,
        })

    return results


def scrape_institut_francais() -> List[Dict]:
    """
    Scrape Institut Français Tokyo screenings.
    """
    results: List[Dict] = []
    soup = fetch_soup(BASE_URL)
    if soup is None:
        return results

    events: Dict[str, str] = {}

    # Primary: article items (older markup)
    for article in soup.select(".article-item"):
        event_url = article.get("href")
        if not event_url:
            link_tag = article.select_one("a[href]")
            event_url = link_tag.get("href") if link_tag else None
        if not event_url:
            continue
        event_url = urljoin(BASE_ORIGIN, event_url)
        title_tag = article.select_one(".title-main, .title, h3, h2")
        event_title = clean_text(title_tag.get_text()) if title_tag else ""
        events[event_url] = event_title

    # Fallback: any /event/ links on the page
    if not events:
        for link in soup.select("a[href]"):
            href = link.get("href") or ""
            if not EVENT_URL_RE.search(href):
                continue
            event_url = urljoin(BASE_ORIGIN, href)
            title = clean_text(link.get_text())
            if not title:
                continue
            events.setdefault(event_url, title)

    for event_url, event_title in events.items():
        event_results = scrape_event_page(event_url, event_title)
        results.extend(event_results)
    return results


if __name__ == "__main__":
    data = scrape_institut_francais()
    print(f"{len(data)} showings found")
    for d in data[:5]:
        print(d)
