#!/usr/bin/env python3
# Attempt to fetch Manchester Art Gallery event list via Playwright and save as
# data/manchester_events_export.json for the main scraper to use.
# Used by GitHub Actions (fortnightly). Often blocked by Cloudflare; when it
# succeeds, the file is committed so the main scraper gets fresh Manchester data.

import json
import os
import sys

# Run from north-art-exhibitions directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from venue_modules.manchester_art_gallery_module import (
    BASE_URL,
    EVENTS_URL,
    _parse_listing_html,
)
from venue_modules._utils import parse_date_range

OUTPUT_PATH = os.path.join(SCRIPT_DIR, "data", "manchester_events_export.json")


def fetch_with_playwright(url, wait_seconds=8):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # Wait for event links to appear (fails if Cloudflare challenge)
            try:
                page.wait_for_selector(
                    'a[href^="/event/"][href!="/event/"]',
                    timeout=wait_seconds * 1000,
                )
            except Exception:
                pass
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
        return html
    except Exception:
        return None


def main():
    html = fetch_with_playwright(EVENTS_URL)
    if not html or "Just a moment" in html:
        print("Manchester export: page blocked or challenge (no events extracted)")
        return 1

    out = []
    for title, full_url, date_text, image_url in _parse_listing_html(html, EVENTS_URL):
        start_str, end_str = (None, None)
        if date_text:
            start_str, end_str = parse_date_range(date_text)
        out.append({
            "title": title,
            "url": full_url,
            "date_text": date_text or None,
            "start_date": start_str,
            "end_date": end_str,
            "image_url": image_url,
        })

    if not out:
        print("Manchester export: no event links found in page")
        return 1

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Manchester export: saved {len(out)} events to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
