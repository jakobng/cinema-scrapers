#!/usr/bin/env python3
# curzon_chain_module.py
# Scraper for all London Curzon Cinemas
# https://www.curzon.com

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from typing import Dict, List, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE_URL = "https://www.curzon.com"

# List of London venues: (Display Name, URL Slug)
LONDON_VENUES = [
    ("Curzon Soho", "soho"),
    ("Curzon Mayfair", "mayfair"),
    ("Curzon Bloomsbury", "bloomsbury"),
    ("Curzon Victoria", "victoria"),
    ("Curzon Camden", "camden"),
    ("Curzon Hoxton", "hoxton"),
    ("Curzon Aldgate", "aldgate"),
    ("Curzon Sea Containers", "sea-containers"),
    ("Curzon Wimbledon", "wimbledon"),
    ("Curzon Richmond", "richmond"),
    ("Curzon Kingston", "kingston"),
]

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _clean(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_runtime(runtime_str: str) -> str:
    if not runtime_str:
        return ""
    runtime_str = runtime_str.strip()
    hours = 0
    minutes = 0
    hour_match = re.search(r"(\d+)\s*h", runtime_str, re.I)
    min_match = re.search(r"(\d+)\s*m", runtime_str, re.I)
    if hour_match:
        hours = int(hour_match.group(1))
    if min_match:
        minutes = int(min_match.group(1))
    total_minutes = hours * 60 + minutes
    return str(total_minutes) if total_minutes > 0 else ""


def _parse_date_from_picker(day_str: str, day_num: str, month_str: str) -> Optional[dt.date]:
    if day_str.lower() == "today":
        return TODAY
    try:
        day = int(day_num)
        current_year = TODAY.year
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "may": 5, "jun": 6, "jul": 7, "aug": 8,
            "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        month = month_map.get(month_str.lower()[:3])
        if not month:
            return None
        try:
            parsed_date = dt.date(current_year, month, day)
        except ValueError:
            return None
        if parsed_date < TODAY - dt.timedelta(days=30):
            parsed_date = dt.date(current_year + 1, month, day)
        return parsed_date
    except (ValueError, AttributeError):
        return None


def _parse_iso_datetime(iso_str: str) -> Optional[dt.datetime]:
    if not iso_str:
        return None
    try:
        iso_str = iso_str.replace("Z", "+00:00")
        if "." in iso_str:
            iso_str = re.sub(r"\.\d+", "", iso_str)
        return dt.datetime.fromisoformat(iso_str)
    except ValueError:
        return None

def _is_maintenance_page(page) -> bool:
    """Detect Vista Digital maintenance or Cloudflare block page."""
    try:
        title = (page.title() or "").lower()
        if "maintenance" in title:
            return True
        # Vista maintenance page has this
        body = page.content()
        if "vista digital" in body.lower() and "maintenance" in body.lower():
            return True
        return False
    except Exception:
        return False


def _dismiss_yie_overlay(page) -> None:
    try:
        if not page.query_selector("[id^='yie-overlay-'], [id^='yie-backdrop-']"):
            return
        page.add_style_tag(
            content="[id^='yie-overlay-'], [id^='yie-backdrop-'] { display: none !important; }"
        )
        page.evaluate(
            "() => {"
            "document.querySelectorAll('[id^=\"yie-overlay-\"], [id^=\"yie-backdrop-\"]')"
            ".forEach(el => el.remove());"
            "}"
        )
        page.wait_for_timeout(100)
    except Exception:
        pass

def scrape_venue(page, cinema_name, slug) -> List[Dict]:
    """Scrapes a single venue using the provided Playwright page."""
    venue_url = f"{BASE_URL}/venues/{slug}/"
    print(f"[{cinema_name}] Loading {venue_url} ...", file=sys.stderr)
    
    shows = []
    try:
        page.goto(venue_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)  # Allow JS/Cloudflare to settle

        if _is_maintenance_page(page):
            print(f"[{cinema_name}] Site returned maintenance page - skipping", file=sys.stderr)
            return []

        # Wait for film list selector
        try:
            page.wait_for_selector(".v-showtime-picker-film-list", timeout=25000)
        except PlaywrightTimeout:
            if _is_maintenance_page(page):
                print(f"[{cinema_name}] Site in maintenance - skipping", file=sys.stderr)
                return []
            print(f"[{cinema_name}] Retrying with wait_until='load'...", file=sys.stderr)
            page.goto(venue_url, wait_until="load", timeout=60000)
            page.wait_for_timeout(2000)
            if _is_maintenance_page(page):
                return []
            try:
                page.wait_for_selector(".v-showtime-picker-film-list", timeout=15000)
            except PlaywrightTimeout:
                print(f"[{cinema_name}] Timeout waiting for film list", file=sys.stderr)
                return []

        _dismiss_yie_overlay(page)

        # Get all available dates
        date_elements = page.query_selector_all(".v-date-picker-date")
        dates_to_scrape = []

        for date_elem in date_elements:
            button = date_elem.query_selector(".v-date-picker-date__button")
            if button and "v-date-picker-date__button--inactive" in (button.get_attribute("class") or ""):
                continue

            spans = date_elem.query_selector_all(".v-display-text-part")
            if len(spans) >= 1:
                parsed_date = None
                if len(spans) == 1:
                    if spans[0].inner_text().strip().lower() == "today":
                        parsed_date = TODAY
                elif len(spans) >= 3:
                    day_str = spans[0].inner_text().strip()
                    day_num = spans[1].inner_text().strip()
                    month_str = spans[2].inner_text().strip()
                    parsed_date = _parse_date_from_picker(day_str, day_num, month_str)
                
                if parsed_date and TODAY <= parsed_date < TODAY + dt.timedelta(days=WINDOW_DAYS):
                    dates_to_scrape.append((parsed_date, date_elem))

        print(f"[{cinema_name}] Found {len(dates_to_scrape)} dates to scrape", file=sys.stderr)

        for show_date, date_elem in dates_to_scrape:
            try:
                # Re-query the button to avoid stale element handle if DOM updated
                # Note: This is tricky with simple loops if DOM refreshes. 
                # But Curzon usually keeps the date picker static.
                # However, safe approach is to just click the handle we have or query by text/index.
                # For simplicity, we use the handle.
                button = date_elem.query_selector(".v-date-picker-date__button")
                if button:
                    _dismiss_yie_overlay(page)
                    button.click(timeout=5000)
                    page.wait_for_timeout(1000) # Wait for films to filter
            except Exception as e:
                print(f"[{cinema_name}] Error clicking date {show_date}: {e}", file=sys.stderr)
                continue

            film_items = page.query_selector_all(".v-showtime-picker-film-list__item")
            for film_item in film_items:
                title_elem = film_item.query_selector(".v-film-title__text")
                if not title_elem:
                    continue
                film_title = _clean(title_elem.inner_text())
                if not film_title:
                    continue

                detail_url = ""
                detail_link = film_item.query_selector(".v-showtime-picker-film-details__film-link")
                if detail_link:
                    href = detail_link.get_attribute("href")
                    if href:
                        detail_url = BASE_URL + href if href.startswith("/") else href

                synopsis_elem = film_item.query_selector(".v-film-synopsis .v-detail__content")
                synopsis = _clean(synopsis_elem.inner_text()) if synopsis_elem else ""

                runtime_elem = film_item.query_selector(".v-film-runtime .v-detail__content")
                runtime_str = _clean(runtime_elem.inner_text()) if runtime_elem else ""
                runtime_min = _parse_runtime(runtime_str)

                showtime_buttons = film_item.query_selector_all(".v-showtime-button")
                for st_btn in showtime_buttons:
                    time_elem = st_btn.query_selector("time.v-showtime-button__detail-start-time")
                    if not time_elem:
                        continue
                    
                    datetime_attr = time_elem.get_attribute("datetime")
                    parsed_dt = _parse_iso_datetime(datetime_attr)
                    if not parsed_dt:
                        continue
                    
                    showtime = parsed_dt.strftime("%H:%M")
                    
                    booking_url = ""
                    href = st_btn.get_attribute("href")
                    if href:
                        booking_url = BASE_URL + href if href.startswith("/") else href

                    format_tags = []
                    attr_icons = st_btn.query_selector_all(".v-attribute__img img")
                    for icon in attr_icons:
                        alt = icon.get_attribute("alt")
                        if alt:
                            format_tags.append(alt)

                    shows.append({
                        "cinema_name": cinema_name,
                        "movie_title": film_title,
                        "movie_title_en": film_title,
                        "date_text": show_date.isoformat(),
                        "showtime": showtime,
                        "detail_page_url": detail_url,
                        "booking_url": booking_url,
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": runtime_min,
                        "synopsis": synopsis[:500],
                        "format_tags": format_tags,
                    })

    except Exception as e:
        print(f"[{cinema_name}] Scrape failed: {e}", file=sys.stderr)

    return shows


def scrape_all_curzon() -> List[Dict]:
    """Scrape all London Curzon venues."""
    all_shows = []
    
    print(f"[Curzon Chain] Starting scrape for {len(LONDON_VENUES)} venues...", file=sys.stderr)
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-GB",
                timezone_id="Europe/London",
            )
            page = context.new_page()

            for name, slug in LONDON_VENUES:
                shows = scrape_venue(page, name, slug)
                all_shows.extend(shows)
                time.sleep(1)

            browser.close()
            
    except Exception as e:
        print(f"[Curzon Chain] Critical Error: {e}", file=sys.stderr)

    # Deduplicate
    seen = set()
    unique_shows = []
    for s in all_shows:
        key = (s["cinema_name"], s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_all_curzon()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
