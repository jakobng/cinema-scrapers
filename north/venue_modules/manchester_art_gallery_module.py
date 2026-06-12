#!/usr/bin/env python3
# Manchester Art Gallery - exhibitions/events scraper
# Source: https://manchesterartgallery.org/event/
# The site is behind Cloudflare. We try, in order: (1) WordPress REST API via curl_cffi,
# (2) event page HTML via curl_cffi, (3) requests, (4) Playwright, (5) JSON export file
# (data/manchester_events_export.json from browser script), (6) curated fallback list.

import json
import os
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, norm

BASE_URL = "https://manchesterartgallery.org"
EVENTS_URL = f"{BASE_URL}/event/"
EXHIBITIONS_URL = f"{BASE_URL}/exhibitions/"
WP_EVENTS_API = f"{BASE_URL}/wp-json/wp/v2/event?per_page=100&_embed"
EXPORT_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "manchester_events_export.json")

VENUE_NAME = "Manchester Art Gallery"
VENUE_CITY = "Manchester"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.google.com/",
}
TIMEOUT = 20

# Fallback when the site returns 403 (Cloudflare). Update periodically from manchesterartgallery.org/event/
FALLBACK_EXHIBITIONS = [
    {"title": "Holly Graham: The Warp / The Weft / The Wake", "slug": "holly-graham", "end_date": "2026-09-06"},
    {"title": "Splendours of the Sikh Raj: Arms and Armour", "slug": "splendours-of-the-sikh-raj", "end_date": "2026-11-29"},
    {"title": "Won't Sit Still", "slug": "wont-sit-still", "start_date": "2026-03-26", "end_date": "2027-03-28"},
    {"title": "WORN: the life within clothes", "slug": "worn-the-life-within-clothes", "start_date": "2026-03-26", "end_date": "2028-02-13"},
    {"title": "Room to Breathe", "slug": "room-to-breathe", "start_date": "2022-04-02", "end_date": "2026-04-06"},
    {"title": "What's New? Collecting for Manchester", "slug": "whats-new", "start_date": "2023-02-07", "end_date": "2025-12-31"},
    {"title": "Out of the Crate", "slug": "out-of-the-crate", "start_date": "2019-11-07", "end_date": "2025-12-31"},
    {"title": "Rethinking the Grand Tour", "slug": "rethinking-the-grand-tour", "start_date": "2022-11-24", "end_date": "2025-12-31"},
    {"title": "Unpicking Couture", "slug": "unpicking-couture", "start_date": "2023-07-21", "end_date": "2025-01-12"},
]

# Optional image URLs for fallback exhibitions (slug -> url). Add more as you find them on the site.
FALLBACK_IMAGES = {
    "room-to-breathe": "https://manchesterartgallery.org/wp-content/uploads/2022/03/View-from-Hampstead-Heath-looking-towards-Harrow-copy.jpg",
}


def _fetch_with_curl_cffi(url, timeout=20):
    """Fetch URL using curl_cffi (browser TLS fingerprint). Returns response text or None."""
    try:
        from curl_cffi import requests as curl_requests
        r = curl_requests.get(url, impersonate="chrome120", timeout=timeout)
        if r.status_code == 200 and "Just a moment" not in (r.text or ""):
            return r.text
    except Exception:
        pass
    return None


def _parse_wp_api_events(api_text):
    """Parse WordPress REST API event list. Yield (title, detail_url, start_str, end_str, image_url)."""
    try:
        data = json.loads(api_text)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(data, list):
        return
    for post in data:
        title = (post.get("title") or {}).get("rendered") or post.get("title")
        if not title or not isinstance(title, str):
            continue
        # Strip HTML from title
        soup = BeautifulSoup(title, "html.parser")
        title = norm(soup.get_text())
        if not title or len(title) < 2:
            continue
        link = (post.get("link") or "").strip()
        if not link or BASE_URL not in link:
            continue
        start_str = end_str = None
        # Try meta / ACF-style dates
        meta = post.get("meta") or post.get("acf") or {}
        for key in ("event_start_date", "start_date", "event_end_date", "end_date", "event_date"):
            val = meta.get(key)
            if val and isinstance(val, str):
                parsed = parse_date_range(val)
                if parsed[0]:
                    if "start" in key or "event_date" in key:
                        start_str = parsed[0]
                        if not end_str:
                            end_str = parsed[1]
                    else:
                        end_str = parsed[1] or parsed[0]
                        if not start_str:
                            start_str = parsed[0]
        if not start_str and not end_str:
            # Fallback: post date
            date_str = post.get("date") or post.get("modified")
            if date_str:
                start_str, end_str = date_str[:10], date_str[:10]
        # Featured image from _embedded
        image_url = None
        embedded = post.get("_embedded") or {}
        for media in (embedded.get("wp:featuredmedia") or [])[:1]:
            if isinstance(media, dict):
                image_url = (media.get("source_url") or media.get("media_details", {}).get("source_url"))
            break
        yield title, link, start_str, end_str, image_url


def _load_export_json():
    """Load events from browser-exported JSON file. Returns list of dicts or None."""
    path = os.path.normpath(EXPORT_JSON_PATH)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, list):
        return None
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("exhibition_title") or "").strip()
        url = (item.get("url") or item.get("detail_page_url") or item.get("link") or "").strip()
        if not title or not url or BASE_URL not in url:
            continue
        start_str = item.get("start_date")
        end_str = item.get("end_date")
        if (not start_str or not end_str) and item.get("date_text"):
            start_str, end_str = parse_date_range(item.get("date_text"))
        out.append({
            "venue_name": VENUE_NAME,
            "venue_city": VENUE_CITY,
            "exhibition_title": title[:500],
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": url,
            "description": None,
            "image_url": item.get("image_url") or item.get("image"),
        })
    return out if out else None


def _fetch_with_playwright(url):
    """Fetch page HTML using Playwright (bypasses Cloudflare). Returns HTML or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            html = page.content()
            browser.close()
        return html
    except Exception:
        return None


def _date_text_for_link(link):
    """Get date text from the closest ancestor that contains a parseable date."""
    parent = link.parent
    for _ in range(12):
        if not parent:
            break
        text = parent.get_text(separator=" ")
        start, end = parse_date_range(text)
        if start or end:
            return text
        parent = parent.parent
    return ""


def _image_for_link(link, base_url):
    """Get first image URL from the closest ancestor that contains an img (same card as link)."""
    parent = link.parent
    for _ in range(10):
        if not parent:
            break
        img = parent.find("img", src=True)
        if img:
            src = (img.get("src") or "").strip()
            if src and not src.startswith("data:"):
                return src if src.startswith("http") else urljoin(base_url, src)
        parent = parent.parent
    return None


def _parse_listing_html(html, page_url):
    """Parse event/exhibition listing HTML; yield (title, detail_url, date_text, image_url)."""
    if not html:
        return
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href.startswith("/event/") and not href.startswith("/exhibitions/"):
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url.rstrip("/") in (EVENTS_URL.rstrip("/"), EXHIBITIONS_URL.rstrip("/"), BASE_URL.rstrip("/")):
            continue
        if href.strip() in ("/event/", "/event", "/exhibitions/", "/exhibitions"):
            continue
        title = norm(a.get_text())
        if not title or len(title) < 3:
            continue
        if title.lower() in ("read more", "book now", "more info", "events", "exhibitions", "what's on", "view all"):
            continue
        date_text = _date_text_for_link(a)
        image_url = _image_for_link(a, BASE_URL)
        yield title, full_url, date_text or a.get_text(separator=" "), image_url


def _og_image_from_html(html):
    """Extract og:image content from page HTML. Returns None if not found."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta", property=True):
        if (meta.get("property") or "").lower() == "og:image":
            c = (meta.get("content") or "").strip()
            return c if c else None
    return None


def scrape_manchester_art_gallery():
    """Return list of exhibition/event dicts for Manchester Art Gallery. Tries WP API, curl_cffi, requests, Playwright, export file, then fallback list."""
    out = []

    # 1) WordPress REST API (often less protected than HTML pages)
    api_text = _fetch_with_curl_cffi(WP_EVENTS_API)
    if api_text:
        for title, link, start_str, end_str, image_url in _parse_wp_api_events(api_text):
            out.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": title[:500],
                "start_date": start_str,
                "end_date": end_str,
                "detail_page_url": link,
                "description": None,
                "image_url": image_url,
            })

    # 2) Event listing page via curl_cffi
    if not out:
        html = _fetch_with_curl_cffi(EVENTS_URL)
        if html:
            for title, full_url, date_text, image_url in _parse_listing_html(html, EVENTS_URL):
                start_str, end_str = parse_date_range(date_text)
                out.append({
                    "venue_name": VENUE_NAME,
                    "venue_city": VENUE_CITY,
                    "exhibition_title": title[:500],
                    "start_date": start_str,
                    "end_date": end_str,
                    "detail_page_url": full_url,
                    "description": None,
                    "image_url": image_url,
                })

    # 3) Browser-exported JSON (run script on event page when you can load it)
    if not out:
        export_list = _load_export_json()
        if export_list:
            out = export_list

    # 4) requests then Playwright for HTML
    if not out:
        urls_to_try = [EVENTS_URL, EXHIBITIONS_URL]
        html_used = None
        for page_url in urls_to_try:
            try:
                r = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
                if r.status_code == 403 or (r.status_code == 200 and "Just a moment" in (r.text or "")):
                    html_used = _fetch_with_playwright(page_url)
                    if html_used and "Just a moment" not in html_used:
                        for title, full_url, date_text, image_url in _parse_listing_html(html_used, page_url):
                            start_str, end_str = parse_date_range(date_text)
                            out.append({
                                "venue_name": VENUE_NAME,
                                "venue_city": VENUE_CITY,
                                "exhibition_title": title[:500],
                                "start_date": start_str,
                                "end_date": end_str,
                                "detail_page_url": full_url,
                                "description": None,
                                "image_url": image_url,
                            })
                    if out:
                        break
                    break
                r.raise_for_status()
                r.encoding = r.apparent_encoding or "utf-8"
                if "Just a moment" not in (r.text or ""):
                    for title, full_url, date_text, image_url in _parse_listing_html(r.text, page_url):
                        start_str, end_str = parse_date_range(date_text)
                        out.append({
                            "venue_name": VENUE_NAME,
                            "venue_city": VENUE_CITY,
                            "exhibition_title": title[:500],
                            "start_date": start_str,
                            "end_date": end_str,
                            "detail_page_url": full_url,
                            "description": None,
                            "image_url": image_url,
                        })
                    if out:
                        break
            except Exception:
                if html_used is None:
                    html_used = _fetch_with_playwright(page_url)
                    if html_used and "Just a moment" not in html_used:
                        for title, full_url, date_text, image_url in _parse_listing_html(html_used, page_url):
                            start_str, end_str = parse_date_range(date_text)
                            out.append({
                                "venue_name": VENUE_NAME,
                                "venue_city": VENUE_CITY,
                                "exhibition_title": title[:500],
                                "start_date": start_str,
                                "end_date": end_str,
                                "detail_page_url": full_url,
                                "description": None,
                                "image_url": image_url,
                            })
                        if out:
                            break
                continue

    seen = set()
    unique = []
    for item in out:
        key = item["detail_page_url"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    if not unique:
        for fb in FALLBACK_EXHIBITIONS:
            url = f"{BASE_URL}/event/{fb['slug']}/"
            unique.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": fb["title"],
                "start_date": fb.get("start_date"),
                "end_date": fb.get("end_date"),
                "detail_page_url": url,
                "description": None,
                "image_url": FALLBACK_IMAGES.get(fb["slug"]),
            })

    # For items missing image_url, try fetching og:image from event detail page (Playwright, short timeout)
    need_image = [item for item in unique if not item.get("image_url") and item.get("detail_page_url")]
    if need_image:
        for item in need_image[:8]:
            try:
                detail_html = _fetch_with_playwright(item["detail_page_url"])
                img = _og_image_from_html(detail_html)
                if img:
                    item["image_url"] = img if img.startswith("http") else urljoin(BASE_URL, img)
            except Exception:
                pass

    return unique
