from __future__ import annotations

import json
import re
import sys
from datetime import date
from typing import Dict, List, Optional
from urllib.parse import urljoin

try:
    from playwright.sync_api import (
        sync_playwright,
        Page,
        Error,
        Playwright,
        TimeoutError,
    )
except ImportError:
    sys.exit(
        "ERROR: Playwright not installed. Please run 'pip install playwright' and 'playwright install chromium'."
    )

from bs4 import BeautifulSoup, Tag

# --- Constants ---

CINEMA_NAME = "K2 Cinema"
BASE_URL = "https://k2-cinema.com/"
EVENT_LIST_URL = urljoin(BASE_URL, "/event/")
MAIN_PAGE_URL = urljoin(BASE_URL, "/")
TIMEOUT = 45

# Known tricky cases where the text mentions multiple filmmakers
# and we want to enforce the correct director.
DIRECTOR_OVERRIDES: Dict[str, Optional[str]] = {
    "嬉々な生活": "谷口慈彦",
    "グランドツアー": "ミゲル・ゴメス",
    "キムズビデオ": None,
}


# --- Helper Functions ---


def _fetch_page_content(page: Page, url: str, selector: str) -> Optional[str]:
    """
    Navigates to a URL, waits for a selector, and returns the page content.
    """
    try:
        page.goto(url, timeout=TIMEOUT * 1000, wait_until="domcontentloaded")
        page.wait_for_selector(selector, timeout=15000)
        return page.content()
    except Error as e:
        print(
            f"ERROR [{CINEMA_NAME}]: Could not process page '{url}'. Reason: {e}",
            file=sys.stderr,
        )
        return None


def _clean_text(element: Optional[Tag | str]) -> str:
    """
    Extracts visible text and normalizes whitespace.
    """
    if element is None:
        return ""
    if hasattr(element, "get_text"):
        text = element.get_text(separator=" ", strip=True)
    else:
        text = str(element)
    return " ".join(text.strip().split())


def _clean_title(text: str) -> str:
    """
    Cleans a raw title string from the site by removing decorative quotes
    and obvious suffix annotations, but keeping the inner title.

    Examples:
      『YOYOGI』／Yoyogi         -> YOYOGI
      『リンダ リンダ リンダ 4K』 -> リンダ リンダ リンダ 4K
      タイトル【舞台挨拶付き】      -> タイトル
      タイトル ※トークイベントあり  -> タイトル
    """
    if not text:
        return ""

    # Normalize punctuation and spaces
    text = text.replace("　", " ")
    text = text.strip()

    # Remove decorative JP quotes but keep their contents
    for ch in ["『", "』", "「", "」", "〈", "〉", "《", "》", "＜", "＞"]:
        text = text.replace(ch, "")

    # Remove annotations in 【】 (tags like "4Kレストア版", "舞台挨拶付き")
    text = re.sub(r"【[^】]*】", "", text)

    # Remove generic "※..." suffix notes
    text = re.sub(r"※.*$", "", text)

    # Remove some generic format / event suffixes at the end if they remain
    suffix_patterns = [
        r"(IMAX.*)$",
        r"(先行上映.*)$",
        r"(特別上映.*)$",
        r"(舞台挨拶.*)$",
    ]
    for pat in suffix_patterns:
        text = re.sub(pat, "", text)

    # Collapse remaining whitespace
    text = " ".join(text.split())
    return text.strip()


def _extract_year_runtime_country(info_text: str) -> Dict[str, Optional[str]]:
    """
    Tries several patterns to extract year, runtime (minutes), and country
    from a meta block if present.
    """
    result: Dict[str, Optional[str]] = {
        "year": None,
        "runtime_min": None,
        "country": None,
    }

    if not info_text:
        return result

    text = info_text.replace("：", ":")
    text = text.replace("／", "/").replace("｜", "/").replace("|", "/")

    # Pattern A: "2024/125分/Japan/..."
    m = re.search(r"(\d{4})\s*/\s*(\d+)\s*(?:分|min)\s*/\s*([^/]+)", text)
    if m:
        y, r, c = m.groups()
        result["year"] = y
        result["runtime_min"] = r
        country = c.strip()
        for junk in ["カラー", "モノクロ", "白黒", "製作", "合作"]:
            country = country.replace(junk, "")
        country = re.sub(r"\s+", " ", country).strip(" /")
        if country:
            result["country"] = country
        return result

    # Pattern B: "2024年 日本 125分" or "2024年 / 日本 / 125分"
    year_match = re.search(r"(\d{4})\s*年", text)
    if year_match:
        # Check for date-like suffix (e.g. 2026年1月)
        suffix_check = text[year_match.end() : year_match.end() + 2]
        if re.match(r"\s*\d+月", suffix_check):
            year_match = None

    runtime_match = None
    for mm in re.finditer(r"(\d+)\s*(?:分|min)", text):
        candidate = int(mm.group(1))
        if candidate >= 40:  # avoid e.g. "ラスト4分"
            runtime_match = mm

    if year_match:
        result["year"] = year_match.group(1)
    if runtime_match:
        result["runtime_min"] = runtime_match.group(1)

    if year_match and runtime_match:
        span_start = year_match.end()
        span_end = runtime_match.start()
        between = text[span_start:span_end]
        if span_end - span_start < 120:
            tokens = [t.strip() for t in between.split("/") if t.strip()]
            country_tokens = [
                t
                for t in tokens
                if not any(
                    x in t
                    for x in [
                        "語",
                        "モノクロ",
                        "モノラル",
                        "カラー",
                        "ヴィスタ",
                        "ビスタ",
                        "DCP",
                        "上映時間",
                        "サイズ",
                        "レストア",
                        "分",
                    ]
                )
            ]
            if country_tokens:
                result["country"] = "・".join(country_tokens[:2])

    return result


def _extract_original_title(text: str) -> Optional[str]:
    """
    Extracts an English/original title from text if present.

    Looks for:
      - 原題: ...
      - Original title: ...
      - 英題: ...
    """
    if not text:
        return None

    t = text.replace("：", ":")

    patterns = [
        r"原題[:：]\s*([^\n■◼︎]+)",
        r"Original title[:：]\s*([^\n■◼︎]+)",
        r"英題[:：]\s*([^\n■◼︎]+)",
    ]
    for pat in patterns:
        m = re.search(pat, t, flags=re.IGNORECASE)
        if m:
            return _clean_text(m.group(1))

    return None


def _extract_director_with_title(
    info_text: str, movie_title_jp: Optional[str]
) -> Optional[str]:
    """
    Try to extract a director *using the film's Japanese title* for context.
    This is to handle patterns like:
      - 「谷口慈彦監督の『嬉々な生活』」
      - 「ミゲル・ゴメスの新作『グランドツアー』」
    and avoid grabbing directors of other films mentioned in the blurb.
    """
    if not info_text or not movie_title_jp:
        return None

    text = info_text
    title_variants = [
        movie_title_jp,
        f"『{movie_title_jp}』",
        f"「{movie_title_jp}」",
    ]

    def sentence_has_title(s: str) -> bool:
        return any(t in s for t in title_variants)

    # Very rough sentence split
    sentences = re.split(r"[。！？!?]\s*", text)

    non_name_tokens = {"帰国", "来日", "在住", "出身", "生まれ", "育ち", "年カンヌ国際映画祭"}

    # 1) 「◯◯監督の『タイトル』」
    for s in sentences:
        if not sentence_has_title(s):
            continue
        m = re.search(r"([A-Za-zァ-ヺ一-龯ー・]+)\s*監督", s)
        if m:
            candidate = m.group(1).strip()
            if candidate and candidate not in non_name_tokens:
                return candidate

    # 2) 「ミゲル・ゴメスの新作『グランドツアー』」
    for s in sentences:
        if not sentence_has_title(s):
            continue
        m = re.search(r"([A-Za-zァ-ヺ一-龯ー・]+)の新作", s)
        if m:
            candidate = m.group(1).strip()
            if candidate and candidate not in non_name_tokens:
                return candidate

    # 3) 「監督は◯◯◯。『タイトル』…」 style, if any
    for s in sentences:
        if not sentence_has_title(s):
            continue
        m = re.search(r"監督は[^。！!?]*?([A-Za-zァ-ヺ一-龯ー・]+)", s)
        if m:
            candidate = m.group(1).strip()
            if candidate and candidate not in non_name_tokens:
                return candidate

    # 4) 「◯◯がメガホンを握り…『タイトル』」 style
    for s in sentences:
        if not sentence_has_title(s):
            continue
        m = re.search(r"([A-Za-zァ-ヺ一-龯ー・]+)がメガホンを握り", s)
        if m:
            candidate = m.group(1).strip()
            if candidate and candidate not in non_name_tokens:
                return candidate

    return None


def _extract_director(info_text: str) -> Optional[str]:
    """
    Generic director extractor *without* using the title.
    Kept conservative to avoid pulling in directors of other films.
    """
    if not info_text:
        return None

    text = info_text.replace("：", ":")

    non_name_tokens = {"帰国", "来日", "在住", "出身", "生まれ", "育ち", "年カンヌ国際映画祭"}

    # 1) Japanese colon style: 監督:◯◯◯ / 監督・脚本:◯◯◯
    m = re.search(r"監督[・\s\w]*:\s*([^\n／/,]+)", text)
    if m:
        candidate = m.group(1).strip()
        if candidate and candidate not in non_name_tokens:
            return candidate

    # 2) English style: Director: John Smith
    m = re.search(r"Director:\s*([^\n／/,]+)", text, flags=re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        if candidate and candidate not in non_name_tokens:
            return candidate

    # 3) English style: Directed by John Smith
    m = re.search(r"Directed by\s+([^\n／/,]+)", text, flags=re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        if candidate and candidate not in non_name_tokens:
            return candidate

    # 4) 「監督を担当したのは、『市子』の戸田彬弘。」など
    m = re.search(r"監督[^。!?]*?([A-Za-zァ-ヺ一-龯ー・]+)\s*。", text)
    if m:
        candidate = m.group(1).strip()
        if candidate and candidate not in non_name_tokens:
            return candidate

    # 5) Narrative Japanese: 「監督は……マックス・ゴロミゾフ。」など
    m = re.search(r"監督は([^。！!?]+)", text)
    if m:
        sent = m.group(1)
        sent = re.sub(r"[『「（(【].*?[』」）)】]", "", sent)
        m2 = re.search(r"([A-Za-zァ-ヺ一-龯ー・]+)\s*監督", sent)
        if m2:
            candidate = m2.group(1).strip()
            if candidate and candidate not in non_name_tokens:
                return candidate
        m3 = re.search(r"([A-Za-zァ-ヺ一-龯ー・]+)\s*$", sent)
        if m3:
            candidate = m3.group(1).strip()
            if candidate and candidate not in non_name_tokens:
                return candidate

    # 6) 「◯◯がメガホンを握り」
    m = re.search(r"([A-Za-zァ-ヺ一-龯ー・]+)がメガホンを握り", text)
    if m:
        candidate = m.group(1).strip()
        if candidate and candidate not in non_name_tokens:
            return candidate

    # 7) 最後の手段として「◯◯監督」を見るが、最初ではなく最後の一致を優先
    all_matches = re.findall(r"([A-Za-zァ-ヺ一-龯ー・]+)\s*監督", text)
    if all_matches:
        candidate = all_matches[-1].strip()
        if candidate and candidate not in non_name_tokens:
            return candidate

    return None


def _parse_detail_page(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """
    Parses a film's detail page for rich information.
    Handles missing elements gracefully.
    """
    details: Dict[str, Optional[str]] = {
        "director": None,
        "year": None,
        "country": None,
        "runtime_min": None,
        "synopsis": None,
        "movie_title_en": None,
    }

    # ---- Title / English title (from event detail header, if present)
    jp_title_raw = None
    jp_title_clean = None

    if title_tag := soup.select_one(".eventTitle"):
        raw_title = _clean_text(title_tag)
        parts = re.split(r"[／/]", raw_title, maxsplit=1)
        jp_title_raw = parts[0].strip()
        jp_title_clean = _clean_title(jp_title_raw)
        en_raw = parts[1].strip() if len(parts) > 1 else None

        if en_raw:
            en_clean = _clean_title(en_raw)
            if en_clean:
                details["movie_title_en"] = en_clean

    # ---- Synopsis (INTRODUCTION/STORY block)
    if desc_div := soup.select_one(".eventDescription"):
        intro_header = desc_div.find("h2", string=re.compile("INTRODUCTION|STORY"))
        if intro_header:
            p_tags: List[Tag] = []
            for sibling in intro_header.find_next_siblings():
                if sibling.name == "h2":
                    break
                if sibling.name == "p":
                    p_tags.append(sibling)
            synopsis_parts = [_clean_text(p) for p in p_tags if _clean_text(p)]
            if synopsis_parts:
                details["synopsis"] = " ".join(synopsis_parts)

    # Collect a generic info_text from staff-info / meta block (if present)
    staff_text = ""
    if staff_info := soup.select_one(".staffInfo"):
        staff_text = _clean_text(staff_info)
    else:
        # Fallback: sometimes meta may sit inside eventDescription
        if desc_div := soup.select_one(".eventDescription"):
            staff_text = _clean_text(desc_div)

    # ---- Year / runtime / country (fallback / supplement)
    if staff_text:
        yrc = _extract_year_runtime_country(staff_text)
        # Only set year from text if we did NOT get it from the header
        if not details["year"] and yrc.get("year"):
            details["year"] = yrc.get("year")
        if yrc.get("runtime_min"):
            details["runtime_min"] = yrc.get("runtime_min")
        if yrc.get("country"):
            details["country"] = yrc.get("country")

    # ---- Director (title-aware first, then generic, then overrides)
    director: Optional[str] = None
    if staff_text:
        director = _extract_director_with_title(staff_text, jp_title_clean)
        if not director:
            director = _extract_director(staff_text)

    # Apply overrides if this title is known to be tricky
    override_key = jp_title_clean or jp_title_raw
    if override_key and override_key in DIRECTOR_OVERRIDES:
        director = DIRECTOR_OVERRIDES[override_key]

    if director:
        details["director"] = director

    # ---- English/original title fallback from text
    if not details["movie_title_en"]:
        orig = _extract_original_title(staff_text)
        if not orig and (desc_div := soup.select_one(".eventDescription")):
            orig = _extract_original_title(_clean_text(desc_div))
        if orig:
            details["movie_title_en"] = orig

    return details


# --- Main Scraper ---


def scrape_k2_cinema() -> List[Dict]:
    """
    Scrapes K2 Cinema's event list and daily schedule, returning a list of showings.
    Each showing includes basic info plus metadata from the detail page where possible.
    """
    pw_instance: Playwright = sync_playwright().start()
    browser = pw_instance.chromium.launch()
    page = browser.new_page()

    try:
        # 1. Build a cache of movie details from the /event/ page
        print(f"INFO [{CINEMA_NAME}]: Fetching all movie detail links from event page...")
        _fetch_page_content(page, EVENT_LIST_URL, "section.eventList")

        # Click "more" if present to load all events
        while page.locator("button#moreButton").is_visible():
            try:
                page.locator("button#moreButton").click(timeout=5000)
                page.wait_for_timeout(1000)
            except (Error, TimeoutError):
                break

        event_list_html = page.content()
        event_soup = BeautifulSoup(event_list_html, "html.parser")
        details_cache: Dict[str, Dict[str, Optional[str]]] = {}

        event_links = event_soup.select('div.eventCard a[href*="/event/title/"]')
        print(f"INFO [{CINEMA_NAME}]: Found {len(event_links)} unique movie links.")

        for link in event_links:
            detail_url = urljoin(BASE_URL, link["href"])
            # The card heading usually has the JP title; sometimes JP／EN.
            heading_tag = link.find_previous("h3", class_="eventCardHeading")
            title_jp_raw = _clean_text(heading_tag) if heading_tag else ""
            if not title_jp_raw:
                continue

            # Split JP／EN and clean only the JP part for the key
            parts = re.split(r"[／/]", title_jp_raw, maxsplit=1)
            jp_raw = parts[0].strip()
            title_jp = _clean_title(jp_raw)

            if not title_jp:
                continue

            if title_jp in details_cache:
                continue

            print(f"INFO [{CINEMA_NAME}]: Caching details for '{title_jp}'...")
            detail_html = _fetch_page_content(page, detail_url, ".eventDetailHeader")

            if detail_html:
                detail_soup = BeautifulSoup(detail_html, "html.parser")
                movie_details = _parse_detail_page(detail_soup)
                movie_details["detail_page_url"] = detail_url
                details_cache[title_jp] = movie_details
            else:
                print(
                    f"WARN [{CINEMA_NAME}]: Failed to fetch detail page for '{title_jp}'.",
                    file=sys.stderr,
                )
                details_cache[title_jp] = {"detail_page_url": detail_url}

        # 2. Scrape the main page for the daily schedule
        print(f"\nINFO [{CINEMA_NAME}]: Fetching schedule from the main page...")
        _fetch_page_content(page, MAIN_PAGE_URL, "section.homeScheduleContainer")

        # Again click "more" for additional days if available
        while page.locator("button#moreButton").is_visible():
            try:
                page.locator("button#moreButton").click(timeout=5000)
                page.wait_for_timeout(1000)
            except (Error, TimeoutError):
                break

        main_html = page.content()
        main_soup = BeautifulSoup(main_html, "html.parser")

        all_showings: List[Dict] = []
        today = date.today()

        for date_cont in main_soup.select("div.dateContainer"):
            date_div = date_cont.select_one("div.date")
            if not date_div:
                continue

            match = re.search(r"(\d{1,2})\.(\d{1,2})", _clean_text(date_div))
            if not match:
                continue

            month, day_ = map(int, match.groups())
            # Handle year rollover: if the month is early (e.g. Jan–May)
            # but today is late in the year, assume it's next year.
            year = today.year
            if month < today.month and month < 6:
                year = today.year + 1

            show_date = date(year, month, day_)

            for card in date_cont.select("div.scheduleCard"):
                title_tag = card.select_one("h3.scheduleCardHeading")
                time_tag = card.select_one("span.startTime")
                if not (title_tag and time_tag):
                    continue

                raw_title = _clean_text(title_tag)

                # Example: 『YOYOGI』／Yoyogi
                parts = re.split(r"[／/]", raw_title, maxsplit=1)
                jp_raw = parts[0].strip()
                en_raw = parts[1].strip() if len(parts) > 1 else None

                title_jp = _clean_title(jp_raw)
                movie_title_en = _clean_title(en_raw) if en_raw else None

                if not title_jp:
                    # As a last resort, fall back to uncleaned text
                    title_jp = raw_title.strip()

                details = details_cache.get(title_jp, {})

                # Apply overrides again here just in case
                director_value = details.get("director")
                if title_jp in DIRECTOR_OVERRIDES:
                    director_value = DIRECTOR_OVERRIDES[title_jp]

                purchase_url = None
                p_tag = card.find("a", href=True)
                if p_tag:
                    purchase_url = p_tag["href"]

                showing = {
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title_jp,
                    "date_text": show_date.isoformat(),
                    "showtime": _clean_text(time_tag),
                    "movie_title_en": details.get("movie_title_en") or movie_title_en,
                    "director": director_value,
                    "year": details.get("year"),
                    "country": details.get("country"),
                    "runtime_min": details.get("runtime_min"),
                    "synopsis": details.get("synopsis"),
                    "detail_page_url": details.get("detail_page_url"),
                    "purchase_url": purchase_url,
                }
                all_showings.append(showing)

    finally:
        if browser.is_connected():
            browser.close()
        pw_instance.stop()

    # Deduplicate by (date, title, time)
    unique_map: Dict[tuple, Dict] = {}
    for s in all_showings:
        key = (s["date_text"], s["movie_title"], s["showtime"])
        unique_map[key] = s

    unique_showings = list(unique_map.values())
    unique_showings.sort(key=lambda r: (r["date_text"], r["showtime"]))

    print(f"\nINFO [{CINEMA_NAME}]: Collected {len(unique_showings)} unique showings.")
    return unique_showings


# --- CLI test harness ---

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except TypeError:
            pass

    data = scrape_k2_cinema()

    if data:
        output_filename = "k2_cinema_showtimes.json"
        print(f"\nINFO: Writing {len(data)} records to {output_filename}...")
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"INFO: Successfully created {output_filename}.")

        print("\n--- Sample of a movie with metadata ---")
        from pprint import pprint

        for movie in data:
            if movie.get("year") or movie.get("runtime_min") or movie.get("country"):
                pprint(movie)
                break
        else:
            print("Could not find a movie with parsed metadata in the sample.")
    else:
        print("\nNo showings found.")
