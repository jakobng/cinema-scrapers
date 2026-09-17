from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_ORIGIN = "https://culture.institutfrancais.jp"
# Restrict the listing at source.  The unscoped cinema feed also contains
# events in Fukuoka, Kyoto, Yokohama, and other Institut francais venues.
BASE_URL = f"{BASE_ORIGIN}/event?taxonomy=cinema&host=tokyo"
CINEMA_NAME = "アンスティチュ・フランセ東京"
EVENT_URL_RE = re.compile(r"/event/[^/?#]+")
DATE_TIME_RE = re.compile(
    r"(?:(?P<year>20\d{2})\s*年\s*)?"
    r"(?P<month>\d{1,2})\s*(?:月|[./])\s*"
    r"(?P<day>\d{1,2})\s*(?:日)?"
    r"(?:\s*[（(][^）)]*[）)])?"
    r"[^\d]{0,20}"
    r"(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{2}|[oO]0)"
)


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


def _event_year(text: str) -> int:
    """Return the event year printed on the page, falling back to this year."""
    match = re.search(r"(20\d{2})\s*年\s*\d{1,2}\s*月", text or "")
    return int(match.group(1)) if match else datetime.now().year


def _date_time_matches(
    text: str, reference_year: Optional[int] = None
) -> List[tuple[str, str]]:
    """Parse the date formats currently used by Institut francais event pages."""
    results: List[tuple[str, str]] = []
    current = datetime.now()
    for match in DATE_TIME_RE.finditer(text or ""):
        parts = match.groupdict()
        month = int(parts["month"])
        day = int(parts["day"])
        hour = int(parts["hour"])
        minute = int(parts["minute"].lower().replace("o", "0"))
        if parts["year"]:
            year = int(parts["year"])
        elif reference_year is not None:
            year = reference_year
        elif month < current.month and current.month > 10:
            year = current.year + 1
        else:
            year = current.year

        try:
            date_value = datetime(year, month, day)
        except ValueError:
            continue
        if hour > 23 or minute > 59:
            continue
        results.append((date_value.date().isoformat(), f"{hour:02d}:{minute:02d}"))
    return results


def parse_peatix_link_text(
    text: str, reference_year: Optional[int] = None
) -> Optional[tuple[str, str]]:
    """
    Parse text like '1月16日(金) 16:00'
    Returns (date_iso, time_str)
    """
    matches = _date_time_matches(text, reference_year=reference_year)
    return matches[0] if matches else None


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


def _page_mentions_tokyo(soup: BeautifulSoup) -> bool:
    """Check the structured venue field, avoiding the site's global footer text."""
    for wrap in soup.select(".event-box .wrap"):
        label = wrap.select_one(".title-box")
        if not label or clean_text(label.get_text()) not in {"場所", "会場"}:
            continue
        venue = wrap.select_one(".text-box")
        venue_text = clean_text(venue.get_text()) if venue else ""
        return any(marker in venue_text for marker in ("東京日仏学院", "エスパス・イマージュ"))
    # The source listing is already host-filtered, so events without a venue
    # field are safer to keep than to silently discard.
    return True


def _extract_datetimes_from_text(
    text: str, reference_year: Optional[int] = None
) -> List[tuple[str, str]]:
    return _date_time_matches(text, reference_year=reference_year)


def _is_schedule_heading(text: str) -> bool:
    normalized = clean_text(text).strip("：: 　")
    return not normalized or normalized in {"上映日時", "上映時間", "日時", "スケジュール"}


def _screening_title(node, event_title: str) -> str:
    """Find the film or programme heading associated with a showtime node."""
    container = node.find_parent("div", class_="text-box")
    h3_fallback = ""
    for heading in node.find_all_previous(["h2", "h3"]):
        if container is not None and heading.find_parent("div", class_="text-box") is not container:
            continue
        heading_text = clean_text(heading.get_text())
        if _is_schedule_heading(heading_text):
            continue
        if heading.name == "h2":
            if "プログラム" in heading_text and event_title:
                return f"{event_title} — {heading_text}"
            return heading_text
        if not h3_fallback:
            h3_fallback = heading_text
    return h3_fallback or event_title


def _listing(
    *,
    title: str,
    date_iso: str,
    time_str: str,
    detail_url: str,
    event_title: str,
    purchase_url: Optional[str],
) -> Dict:
    return {
        "cinema_name": CINEMA_NAME,
        "movie_title": title,
        "movie_title_en": None,
        "director": None,
        "year": None,
        "country": None,
        "runtime_min": None,
        "date_text": date_iso,
        "showtime": time_str,
        "detail_page_url": detail_url,
        "program_title": event_title,
        "purchase_url": purchase_url,
    }


def scrape_event_page(url: str, event_title: str) -> List[Dict]:
    """
    Extract specific screenings from an event detail page.
    """
    results = []
    soup = fetch_soup(url)
    if not soup:
        return results

    page_text = soup.get_text(" ", strip=True)
    if not _page_mentions_tokyo(soup):
        return results

    event_title = _extract_event_title(soup, event_title)
    reference_year = _event_year(page_text)
    seen = set()

    # Specific screenings are often in 'text-box' or 'detail-box'
    # and usually linked to Peatix.
    peatix_links = soup.find_all("a", href=lambda h: h and "peatix.com" in h)
    
    for link in peatix_links:
        link_text = clean_text(link.get_text())
        parsed = parse_peatix_link_text(link_text, reference_year=reference_year)
        if not parsed:
            continue
        
        date_iso, time_str = parsed
        
        movie_title = _screening_title(link, event_title)
        key = (date_iso, time_str, movie_title)
        if key not in seen:
            seen.add(key)
            results.append(
                _listing(
                    title=movie_title,
                    date_iso=date_iso,
                    time_str=time_str,
                    detail_url=url,
                    event_title=event_title,
                    purchase_url=link["href"],
                )
            )

    # Some programmes publish their schedule before individual Peatix tickets
    # go on sale. Parse dated paragraphs as well, but skip Peatix paragraphs
    # already handled above.
    for node in soup.select(".detail-box p, .detail-box li"):
        if node.find("a", href=lambda h: h and "peatix.com" in h):
            continue
        node_text = clean_text(node.get_text(" ", strip=True))
        for date_iso, time_str in _extract_datetimes_from_text(
            node_text, reference_year=reference_year
        ):
            movie_title = _screening_title(node, event_title)
            key = (date_iso, time_str, movie_title)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                _listing(
                    title=movie_title,
                    date_iso=date_iso,
                    time_str=time_str,
                    detail_url=url,
                    event_title=event_title,
                    purchase_url=None,
                )
            )

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
        if urlparse(event_url).netloc != urlparse(BASE_ORIGIN).netloc:
            continue
        if not EVENT_URL_RE.search(urlparse(event_url).path):
            continue
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
