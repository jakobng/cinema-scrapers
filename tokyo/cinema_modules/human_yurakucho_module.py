from __future__ import annotations

"""
Scraper for ヒューマントラストシネマ有楽町 (Optimized)
-------------------------------------------------
* Fetches the theatre’s public JSON schedule feed.
* Uses concurrent requests for details (Massive speedup).
* Removes Selenium dependency to fix timeout/performance issues.
* Improved parsing logic for Year/Country.
"""

import datetime as dt
import json
import re
import sys
import concurrent.futures
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# ─────────────────────────── Constants ────────────────────────────
BASE_URL            = "https://ttcg.jp"
THEATER_CODE        = "human_yurakucho"
CINEMA_NAME         = "ヒューマントラストシネマ有楽町"
SCHEDULE_URL        = f"{BASE_URL}/data/{THEATER_CODE}.js"
PURCHASABLE_URL     = f"{BASE_URL}/data/purchasable.js"
DETAIL_URL_TEMPLATE = f"{BASE_URL}/{THEATER_CODE}/movie/{{movie_id}}.html"

# ─────────────────────── Helper functions ─────────────────────────

def _fetch_json(url: str) -> Optional[Any]:
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        # Cleanup JS variable assignment if present
        text = response.text.strip().rstrip(";")
        if text.startswith(("var", "let", "const")) and "=" in text:
            text = text.split("=", 1)[1].strip()
        return json.loads(text)
    except Exception as e:
        print(f"[ERROR] Fetching JSON {url}: {e}", file=sys.stderr)
        return None

def _zfill(num: Any) -> str:
    return str(num).zfill(2)

def _fmt_hm(h: Any, m: Any) -> str:
    return f"{_zfill(h)}:{_zfill(m)}" if h is not None and m is not None else ""

def _normalize_screen_name(raw: str) -> str:
    return raw.translate(str.maketrans("１２３４", "1234"))

# ──────────────────── Detail-page scraping ───────────────────────

def _fetch_and_parse_detail(movie_id: str) -> Dict[str, Optional[str]]:
    """
    Fetches the detail page using standard requests (no Selenium).
    Parses Year/Country/Director more aggressively.
    """
    url = DETAIL_URL_TEMPLATE.format(movie_id=movie_id)
    
    # Default empty details
    details = {
        "movie_title": None,
        "movie_title_en": None, 
        "director": None,
        "year": None, 
        "country": None, 
        "runtime_min": None, 
        "synopsis": None,
        "detail_page_url": url
    }

    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return details # Return empties if page missing
            
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 1. Title
        h2 = soup.select_one("h2.movie-title")
        if h2:
            details["movie_title"] = h2.get_text("|", strip=True).split("|", 1)[0]
            sub = h2.select_one("span.sub")
            details["movie_title_en"] = sub.get_text(strip=True) if sub else None

        # 2. Metadata Bar (Year / Country / Runtime)
        # Typically looks like: <b>2023年</b><b>日本</b><b>110分</b>
        label = soup.select_one("p.schedule-nowShowing-label")
        if label:
            bs = label.select("b")
            for b in bs:
                txt = b.get_text(strip=True)
                
                # Runtime
                if "分" in txt and txt[:-1].isdigit():
                    details["runtime_min"] = txt[:-1]
                
                # Year (Look for 4 digits + '年' or just 4 digits)
                # Prioritize this over copyright text
                elif re.search(r'^\d{4}年?$', txt):
                    details["year"] = txt.replace("年", "")
                
                # Country (Heuristic: Not minutes, not year, not empty)
                elif "分" not in txt and not re.search(r'\d{4}', txt):
                    details["country"] = txt

        # 3. Director
        for dt_tag in soup.select("dl.movie-staff dt"):
            if "監督" in dt_tag.text:
                dd = dt_tag.find_next_sibling("dd")
                if dd:
                    details["director"] = dd.get_text(" ", strip=True).lstrip("：:").split('『')[0].strip()
                break

        # 4. Year Fallback (Copyright / Text Search)
        if not details["year"]:
            # Look in copyright tag
            copyright_tag = soup.select_one("p.title-copyright")
            if copyright_tag:
                m = re.search(r'(\d{4})', copyright_tag.text)
                if m: details["year"] = m.group(1)
            
            # Last resort: Search whole text for patterns like "製作：2024年"
            if not details["year"]:
                full_text = soup.get_text()
                m = re.search(r'製作[^\d]*(\d{4})', full_text)
                if m: details["year"] = m.group(1)

        # 5. Synopsis
        synopsis_parts = [p.get_text(" ", strip=True) for p in soup.select("div.mod-imageText-a-text p, div.mod-field p")]
        details["synopsis"] = "\n".join(synopsis_parts) or None

    except Exception as e:
        print(f"[WARN] Error parsing {url}: {e}", file=sys.stderr)
        
    return details

# ─────────────────────── Main scraping ───────────────────────────

def scrape_human_yurakucho(max_days: int = 7) -> List[Dict]:
    schedule_js = _fetch_json(SCHEDULE_URL)
    purchasable_js = _fetch_json(PURCHASABLE_URL)
    
    if not schedule_js: 
        return []

    if isinstance(schedule_js, list):
        schedule_js = next((x for x in schedule_js if isinstance(x, dict)), {})

    dates = schedule_js.get("dates", [])[:max_days]
    movies_map = schedule_js.get("movies", {})
    screens = schedule_js.get("screens", {})
    purchasable_flag = bool(purchasable_js.get(THEATER_CODE)) if purchasable_js else False
    
    # 1. Identify all Unique Movie IDs needed
    movie_ids_to_fetch = set()
    for d in dates:
        for mid in d.get("movie", []):
            movie_ids_to_fetch.add(str(mid))

    # 2. Fetch Details Concurrently (Fast!)
    # Using a ThreadPool to fetch multiple pages at once
    detail_cache = {}
    print(f"   [Human Yurakucho] Fetching details for {len(movie_ids_to_fetch)} movies...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_id = {executor.submit(_fetch_and_parse_detail, mid): mid for mid in movie_ids_to_fetch}
        for future in concurrent.futures.as_completed(future_to_id):
            mid = future_to_id[future]
            try:
                detail_cache[mid] = future.result()
            except Exception as e:
                print(f"[ERROR] Failed to fetch details for {mid}: {e}", file=sys.stderr)
                detail_cache[mid] = {} # Empty fallback

    # 3. Build Schedule
    result: List[Dict] = []
    
    for d in dates:
        y, m, day = map(str, (d["date_year"], d["date_month"], d["date_day"]))
        iso_date = f"{y}-{_zfill(m)}-{_zfill(day)}"
        
        for mid in map(str, d.get("movie", [])):
            # Use cached details
            meta = detail_cache.get(mid, {})
            
            # Fallback title from JSON if scraping failed
            if not meta.get("movie_title"):
                mv_list = movies_map.get(mid, [])
                mv = mv_list[0] if mv_list else {}
                meta["movie_title"] = mv.get("name") or mv.get("cname") or mv.get("title")

            for scr in screens.get(f"{mid}-{y}-{m}-{day}", []):
                for t in scr.get("time", []):
                    sh, sm = t.get("start_time_hour"), t.get("start_time_minute")
                    if sh is None or sm is None: continue

                    result.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": meta.get("movie_title"),
                        "movie_title_en": meta.get("movie_title_en"),
                        "date_text": iso_date, 
                        "showtime": _fmt_hm(sh, sm),
                        "screen_name": _normalize_screen_name(scr.get("name", "スクリーン")),
                        "director": meta.get("director"),
                        "year": meta.get("year"),
                        "country": meta.get("country"),
                        "runtime_min": meta.get("runtime_min"),
                        "synopsis": meta.get("synopsis"),
                        "detail_page_url": meta.get("detail_page_url"),
                        "purchase_url": t.get("url") if purchasable_flag and str(t.get("url", "")).startswith("http") else None,
                    })

    unique = [dict(t) for t in {tuple(sorted(d.items(), key=lambda item: str(item))) for d in result}]
    return sorted(unique, key=lambda x: (x["date_text"], x["showtime"], x.get("movie_title") or ""))

if __name__ == "__main__":
    shows = scrape_human_yurakucho()
    
    # Save to a local file for testing
    filename = "human_yurakucho_test.json"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(shows, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Saved {len(shows)} showings to '{filename}'")
    except Exception as e:
        print(f"Error saving test file: {e}", file=sys.stderr)
