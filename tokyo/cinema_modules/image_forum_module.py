import json, re, sys, pathlib, datetime, requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.imageforum.co.jp/theatre"
SCHEDULE_URL = f"{BASE_URL}/schedule/"
CINEMA_NAME = "シアター・イメージフォーラム"
HEADERS = {"User-Agent": "Mozilla/5.0"}
THIS_YEAR = datetime.date.today().year

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def full_url(href: str) -> str:
    """Return absolute URL for a relative link."""
    if href.startswith("http"):
        return href
    return BASE_URL + href if href.startswith("/") else f"{BASE_URL}/{href}"


def iso_date(month_day: str) -> str:
    """Convert '6/23' → 'YYYY-06-23' using the current year."""
    m, d = map(int, month_day.split("/"))
    year = THIS_YEAR + (1 if datetime.date.today().month == 12 and m == 1 else 0)
    return datetime.date(year, m, d).isoformat()


def split_title(raw: str):
    """Return (jp, en) by detecting ASCII in the string."""
    parts = re.split(r"[ \u3000]+", raw.strip())
    jp_parts, en_parts = [], []
    for p in parts:
        (en_parts if re.search(r"[A-Za-z]", p) else jp_parts).append(p)
    jp = " ".join(jp_parts) if jp_parts else raw.strip()
    en = " ".join(en_parts) or None
    return jp, en


def fetch(url: str) -> BeautifulSoup:
    """GET a page and parse with the built‑in html.parser."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = 'utf-8'
    return BeautifulSoup(resp.text, "html.parser")

# ------------------------------------------------------------
# Detail‑page scraping utilities (with in‑memory cache)
# ------------------------------------------------------------

detail_cache: dict[str, dict] = {}

DIRECTOR_RE = re.compile(r"監督[^:：｜|\n]*[:：｜|]\s*([^\n／｜|]+)")
YEAR_RE = re.compile(r'(19\d{2}|20\d{2})')
RUNTIME_RE = re.compile(r'(\d{2,3})分')

def parse_detail(detail_url: str):
    """
    Final, robust version. Intelligently parses the detail page by looking
    for year, runtime, and country patterns across ALL lines of text.
    """
    if detail_url in detail_cache:
        return detail_cache[detail_url]

    soup = fetch(detail_url)
    text_block = soup.select_one("div.movie-right p.text")

    defaults = {"director": None, "year": None, "country": None, "runtime_min": None, "synopsis": None}
    if not text_block:
        detail_cache[detail_url] = defaults
        return defaults

    raw_text = text_block.get_text("\n", strip=True)
    lines = raw_text.split('\n')

    meta = {"synopsis": raw_text, **defaults}

    # Find director
    # Improved regex to avoid capturing original titles or other metadata
    if (m_dir := re.search(r"監督[^:：｜|]*[:：｜|]\s*([^\n／｜|]+)", raw_text)):
        candidate = m_dir.group(1).strip()
        # If candidate looks like an enclosed title (e.g. 「Title」), ignore it
        if not re.match(r"^「.*」$", candidate) and "原題" not in candidate:
             meta["director"] = candidate.split("、")[0]

    # Find the best possible metadata line that contains delimiters AND runtime
    best_meta_line = ""
    for line in lines:
        if ('／' in line or '｜' in line or '/' in line) and "分" in line:
            best_meta_line = line
            break

    # If a good line is found, parse it first
    if best_meta_line:
        normalized_line = best_meta_line.replace('｜', '／').replace('/', '／')
        parts = [p.strip() for p in normalized_line.split('／')]
        
        countries = []
        for part in parts:
            year_match = YEAR_RE.search(part)
            runtime_match = RUNTIME_RE.search(part)

            if year_match and not meta["year"]:
                meta["year"] = year_match.group(1)
            elif runtime_match and not meta["runtime_min"]:
                meta["runtime_min"] = runtime_match.group(1)
            else:
                # Add to country list if it's not noise
                if not any(noise in part for noise in ["分", "年", "監督", "配給", "カラー", "英語", "DCP", "ドキュメンタリー", "ビスタ", "5.1ch"]):
                    # Also check it has non-numeric characters to avoid things like "2.39:1"
                     if re.search(r'\D', part):
                        countries.append(part)
        
        if countries:
            meta["country"] = ", ".join(countries)
    
    # As a final fallback, if year is still missing, scan the entire text block again
    if not meta["year"]:
        if (year_match := YEAR_RE.search(raw_text)):
            meta["year"] = year_match.group(1)
            
    detail_cache[detail_url] = meta
    return meta

# ------------------------------------------------------------
# Main routine
# ------------------------------------------------------------

def scrape():
    soup = fetch(SCHEDULE_URL)
    results: list[dict] = []

    for day_box in soup.select("div.schedule-day-box"):
        h2 = day_box.select_one("h2.schedule-day-title2")
        if not h2: continue
        
        md_match = re.search(r"(\d{1,2}/\d{1,2})", h2.get_text())
        if not md_match: continue
        date_iso = iso_date(md_match.group(1))

        for table in day_box.select("table.schedule-table"):
            caption = table.caption.img["alt"] if table.caption and table.caption.img else ""
            screen_match = re.search(r"シアター.?.\d", caption)
            screen_name = screen_match.group(0) if screen_match else None

            for td in table.select("td.schebox"):
                a_tag = td.select_one("a")
                if not a_tag: continue
                
                href = full_url(a_tag["href"])
                showtime = td.select_one("div").get_text(strip=True)
                raw_title = td.select_one("p").get_text(strip=True)
                movie_title_jp, movie_title_en = split_title(raw_title)

                meta = parse_detail(href)

                results.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title_jp,
                    "movie_title_en": movie_title_en,
                    "date_text": date_iso,
                    "showtime": showtime,
                    "screen_name": screen_name,
                    "detail_page_url": href,
                    **meta,
                })

    results.sort(key=lambda r: (r["date_text"], r["showtime"]))
    return results

if __name__ == "__main__":
    showings = scrape()
    if showings:
        out_path = pathlib.Path(__file__).with_name("image_forum_schedule_TEST.json")
        out_path.write_text(json.dumps(showings, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Test run successful. Saved {len(showings)} showtimes → {out_path}")