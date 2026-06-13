#!/usr/bin/env python3
# Shared headless-browser renderer for venues whose listings are built by
# JavaScript (so a plain requests fetch returns an empty shell). Uses Playwright
# if it is installed; returns None otherwise so callers degrade gracefully and
# the rest of the scrape is unaffected. NB: this does NOT defeat Cloudflare's
# bot challenge (e.g. Manchester Art Gallery) - that blocks automated browsers
# headless and headed alike; it only renders ordinary client-side pages.

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def render_html(url, wait_ms=3000, timeout_ms=45000):
    """Return the fully-rendered HTML of url, or None if rendering is unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=_UA, locale="en-GB")
                page = ctx.new_page()
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                page.wait_for_timeout(wait_ms)
                return page.content()
            finally:
                browser.close()
    except Exception:
        return None
