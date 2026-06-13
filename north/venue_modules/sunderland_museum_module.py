# Sunderland Culture venues (Sunderland Museum & Winter Gardens, National Glass
# Centre, Northern Gallery for Contemporary Art, Arts Centre Washington).
#
# The /whats-on listing is client-rendered, so a plain requests fetch returns an
# empty shell - the old scraper fell back to grabbing nav links ("About Us",
# "See & Do"). We render the exhibitions filter with a headless browser
# (_js_render) and parse the c-event-card grid. Each card names its own venue, so
# rows are emitted under the real sub-venue rather than all under the museum.
# If the browser renderer is unavailable, returns [] (no junk).
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ._js_render import render_html
from ._utils import norm, parse_uk_date_text

BASE_URL = "https://www.sunderlandculture.org.uk"
LISTING_URL = "https://www.sunderlandculture.org.uk/whats-on/?type=exhibitions"
VENUE_CITY = "Sunderland"

_DATE_RE = re.compile(
    r"\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?\s*[–—-]\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}"
    r"|(?:from|until)\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}",
    re.IGNORECASE,
)


def _image(card):
    img = card.find("img")
    if not img:
        return None
    src = img.get("data-src") or img.get("src") or ""
    if not src and img.get("data-srcset"):
        src = img["data-srcset"].split(",")[0].strip().split(" ")[0]
    if not src:
        return None
    return urljoin(BASE_URL, src.split("?")[0])  # drop the tiny ?resize= crop


def scrape_sunderland_museum():
    html = render_html(LISTING_URL, wait_ms=3000)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    out = []
    seen = set()
    for card in soup.select("div.c-event-card"):
        type_el = card.select_one(".c-event-card__type")
        if type_el and "exhibition" not in type_el.get_text(strip=True).lower():
            continue
        a = card.select_one("a.c-event-card__permalink") or card.find("a", href=True)
        title_el = card.select_one(".c-event-card__title")
        if not a or not title_el:
            continue
        detail_url = urljoin(BASE_URL, a["href"].split("?")[0])
        if detail_url in seen:
            continue

        # The last <p> in the card is the clean venue name ("National Glass Centre").
        venue_ps = [norm(p.get_text()) for p in card.find_all("p") if norm(p.get_text())]
        venue_name = None
        for p in reversed(venue_ps):
            if not p.lower().startswith(("showing in", "exhibition")) and len(p) < 60:
                venue_name = p
                break
        if not venue_name:
            venue_name = "Sunderland Museum & Winter Gardens"

        m = _DATE_RE.search(norm(card.get_text(" ")))
        start_str, end_str = parse_uk_date_text(m.group(0)) if m else (None, None)

        seen.add(detail_url)
        out.append({
            "venue_name": venue_name,
            "venue_city": VENUE_CITY,
            "exhibition_title": norm(title_el.get_text())[:500],
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": detail_url,
            "description": None,
            "image_url": _image(card),
        })
    return out


if __name__ == "__main__":
    for r in scrape_sunderland_museum():
        print(f"{'IMG' if r['image_url'] else '---'} {str(r['start_date']):>10}..{str(r['end_date']):<10} | "
              f"{r['venue_name'][:28]:<28} | {r['exhibition_title'][:36]}")
