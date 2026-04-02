from __future__ import annotations

import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.shogakukan.co.jp/jinbocho-theater/program/"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.shogakukan.co.jp/jinbocho-theater/",
}
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
CIRCLED_DIGITS = {
    "①": 1,
    "②": 2,
    "③": 3,
    "④": 4,
    "⑤": 5,
    "⑥": 6,
    "⑦": 7,
    "⑧": 8,
    "⑨": 9,
    "⑩": 10,
    "⑪": 11,
    "⑫": 12,
    "⑬": 13,
    "⑭": 14,
    "⑮": 15,
    "⑯": 16,
    "⑰": 17,
    "⑱": 18,
    "⑲": 19,
    "⑳": 20,
}
CIRCLED_DIGIT_PATTERN = "".join(CIRCLED_DIGITS.keys())
CINEMA_NAME = "神保町シアター"


def clean_text(text: str) -> str:
    """Normalize whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def _normalize_schedule_line(line: str) -> str:
    if not line:
        return ""
    normalized = line.translate(FULLWIDTH_DIGITS)
    normalized = normalized.replace("：", ":").replace("／", "/")
    return normalized


def _normalize_number_token(token: str) -> Optional[int]:
    if not token:
        return None
    if token in CIRCLED_DIGITS:
        return CIRCLED_DIGITS[token]
    normalized = token.translate(FULLWIDTH_DIGITS)
    if normalized.isdigit():
        return int(normalized)
    return None


def _extract_film_number_and_title(raw_title: str) -> tuple[Optional[int], str]:
    title = clean_text(raw_title)
    if not title:
        return None, ""

    first_char = title[0]
    if first_char in CIRCLED_DIGITS:
        number = CIRCLED_DIGITS[first_char]
        cleaned = title[1:].lstrip(" .．)）")
        return number, cleaned

    m = re.match(r"^\s*([0-9０-９]{1,2})[\.．)）]?\s*(.*)$", title)
    if m:
        number = _normalize_number_token(m.group(1))
        cleaned = m.group(2).strip()
        return number, cleaned

    return None, title


def _extract_program_year(text: str) -> Optional[int]:
    if not text:
        return None
    if m := re.search(r"(19|20)\d{2}", text):
        return int(m.group(0))
    return None


def _format_iso_date(year: Optional[int], month: int, day: int) -> str:
    if not year:
        return f"{month}月{day}日"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_dates_from_line(
    line: str,
    current_month: Optional[int],
) -> tuple[list[tuple[int, int]], Optional[int], Optional[int]]:
    line = _normalize_schedule_line(line)
    dates: list[tuple[int, int]] = []
    line_year = _extract_program_year(line)

    for m in re.finditer(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", line):
        month = int(m.group(1))
        day = int(m.group(2))
        dates.append((month, day))
        current_month = month

    if not dates:
        for m in re.finditer(r"(\d{1,2})/(\d{1,2})", line):
            month = int(m.group(1))
            day = int(m.group(2))
            dates.append((month, day))
            current_month = month

    if not dates and current_month:
        for m in re.finditer(r"(\d{1,2})\s*日", line):
            day = int(m.group(1))
            dates.append((current_month, day))

    return dates, current_month, line_year


def _parse_showings_from_lines(lines: List[str], default_year: Optional[int]) -> List[Dict[str, str]]:
    showings: List[Dict[str, str]] = []
    current_month: Optional[int] = None

    for line in lines:
        line = clean_text(_normalize_schedule_line(line))
        if not line or ":" not in line:
            continue

        times = re.findall(r"\d{1,2}:\d{2}", line)
        if not times:
            continue

        dates, current_month, line_year = _parse_dates_from_line(line, current_month)
        if not dates:
            continue

        use_year = line_year or default_year
        for month, day in dates:
            date_text = _format_iso_date(use_year, month, day)
            for show_time in times:
                showings.append({"date_text": date_text, "showtime": show_time})

    return showings


def _parse_schedule_map_from_lines(
    lines: List[str],
    default_year: Optional[int],
) -> Dict[int, List[Dict[str, str]]]:
    schedule_map: Dict[int, List[Dict[str, str]]] = {}
    current_month: Optional[int] = None

    for line in lines:
        line = clean_text(_normalize_schedule_line(line))
        if not line or ":" not in line:
            continue

        dates, current_month, line_year = _parse_dates_from_line(line, current_month)
        if not dates:
            continue

        pairs = set()
        time_first = re.findall(
            rf"(\d{{1,2}}:\d{{2}})\s*[（(]?\s*([0-9０-９]|[{CIRCLED_DIGIT_PATTERN}])\s*[)）]?",
            line,
        )
        for time_text, number_text in time_first:
            film_number = _normalize_number_token(number_text)
            if film_number:
                pairs.add((film_number, time_text))

        number_first = re.findall(
            rf"([0-9０-９]|[{CIRCLED_DIGIT_PATTERN}])\s*[)）]?\s*(\d{{1,2}}:\d{{2}})",
            line,
        )
        for number_text, time_text in number_first:
            film_number = _normalize_number_token(number_text)
            if film_number:
                pairs.add((film_number, time_text))

        if not pairs:
            continue

        use_year = line_year or default_year
        for month, day in dates:
            date_text = _format_iso_date(use_year, month, day)
            for film_number, time_text in pairs:
                schedule_map.setdefault(film_number, []).append(
                    {"date_text": date_text, "showtime": time_text}
                )

    return schedule_map


def _extract_runtime_min(text: str) -> Optional[str]:
    if not text:
        return None
    normalized = text.translate(FULLWIDTH_DIGITS)
    hour_min = re.search(r"(\d{1,2})\s*時間\s*(\d{1,2})\s*分", normalized)
    if hour_min:
        hours = int(hour_min.group(1))
        minutes = int(hour_min.group(2))
        return str(hours * 60 + minutes)
    minute_only = re.search(r"(\d{2,3})\s*分", normalized)
    if minute_only:
        return minute_only.group(1)
    match = re.search(r"(\d{2,3})", normalized)
    if match:
        return match.group(1)
    return None


def _extract_country(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        ("\u65e5\u672c", "Japan"),
        ("\u30a2\u30e1\u30ea\u30ab|\u7c73\u56fd", "USA"),
        ("\u30a4\u30ae\u30ea\u30b9|\u82f1\u56fd", "UK"),
        ("\u30d5\u30e9\u30f3\u30b9", "France"),
        ("\u30c9\u30a4\u30c4", "Germany"),
        ("\u30a4\u30bf\u30ea\u30a2", "Italy"),
        ("\u30b9\u30da\u30a4\u30f3", "Spain"),
        ("\u97d3\u56fd", "South Korea"),
        ("\u4e2d\u56fd", "China"),
        ("\u9999\u6e2f", "Hong Kong"),
        ("\u53f0\u6e7e", "Taiwan"),
        ("\u30ed\u30b7\u30a2|\u30bd\u9023", "Russia"),
        ("\u30ab\u30ca\u30c0", "Canada"),
        ("\u30aa\u30fc\u30b9\u30c8\u30e9\u30ea\u30a2", "Australia"),
        ("\u30d6\u30e9\u30b8\u30eb", "Brazil"),
        ("\u30a2\u30eb\u30bc\u30f3\u30c1\u30f3", "Argentina"),
        ("\u30e1\u30ad\u30b7\u30b3", "Mexico"),
        ("\u30a4\u30f3\u30c9", "India"),
        ("\u30bf\u30a4", "Thailand"),
        ("\u30d9\u30c8\u30ca\u30e0", "Vietnam"),
        ("\u30d5\u30a3\u30ea\u30d4\u30f3", "Philippines"),
        ("\u30a4\u30f3\u30c9\u30cd\u30b7\u30a2", "Indonesia"),
        ("\u30c8\u30eb\u30b3", "Turkey"),
        ("\u30b9\u30a6\u30a7\u30fc\u30c7\u30f3", "Sweden"),
        ("\u30ce\u30eb\u30a6\u30a7\u30fc", "Norway"),
        ("\u30c7\u30f3\u30de\u30fc\u30af", "Denmark"),
        ("\u30d5\u30a3\u30f3\u30e9\u30f3\u30c9", "Finland"),
        ("\u30dd\u30fc\u30e9\u30f3\u30c9", "Poland"),
        ("\u30c1\u30a7\u30b3", "Czech Republic"),
        ("\u30aa\u30fc\u30b9\u30c8\u30ea\u30a2", "Austria"),
        ("\u30b9\u30a4\u30b9", "Switzerland"),
        ("\u30d9\u30eb\u30ae\u30fc", "Belgium"),
        ("\u30aa\u30e9\u30f3\u30c0", "Netherlands"),
        ("\u30ae\u30ea\u30b7\u30e3", "Greece"),
        ("\u30a2\u30a4\u30eb\u30e9\u30f3\u30c9", "Ireland"),
        ("\u30cb\u30e5\u30fc\u30b8\u30fc\u30e9\u30f3\u30c9", "New Zealand"),
        ("\u30a4\u30b9\u30e9\u30a8\u30eb", "Israel"),
        ("\u30a4\u30e9\u30f3", "Iran"),
        ("\u30a8\u30b8\u30d7\u30c8", "Egypt"),
        ("\u5357\u30a2\u30d5\u30ea\u30ab", "South Africa"),
        ("\u30a6\u30af\u30e9\u30a4\u30ca", "Ukraine"),
    ]
    for pattern, name in patterns:
        if re.search(pattern, text):
            return name
    return None


def _extract_detail_block_info(block: BeautifulSoup) -> Dict[str, Optional[str]]:
    info: Dict[str, Optional[str]] = {
        "director": None,
        "year": None,
        "runtime_min": None,
        "country": None,
        "synopsis": None,
    }

    sub = block.select_one(".filmBlock__sub")
    if sub:
        sub_text = clean_text(sub.get_text(" ", strip=True))
        year = _extract_program_year(sub_text)
        runtime = _extract_runtime_min(sub_text)
        country = _extract_country(sub_text)
        if year:
            info["year"] = str(year)
        if runtime:
            info["runtime_min"] = runtime
        if country:
            info["country"] = country

    for row in block.select(".filmInfo__row"):
        dt = row.select_one("dt")
        dd = row.select_one("dd")
        if not dt or not dd:
            continue
        label = clean_text(dt.get_text(" ", strip=True))
        if "監督" in label:
            director = clean_text(dd.get_text(" ", strip=True))
            if director:
                info["director"] = director
            continue
        if "製作国" in label or label == "国":
            country = clean_text(dd.get_text(" ", strip=True))
            if country:
                info["country"] = country

    film_text = block.select_one(".filmText p")
    if film_text:
        synopsis = clean_text(film_text.get_text(" ", strip=True))
        if synopsis:
            info["synopsis"] = synopsis

    if not info["synopsis"]:
        heading = block.find(lambda tag: tag.name in ("h3", "h4") and "物語" in tag.get_text())
        if heading:
            for sibling in heading.find_all_next():
                if sibling.name == "p":
                    synopsis = clean_text(sibling.get_text(" ", strip=True))
                    if synopsis:
                        info["synopsis"] = synopsis
                        break

    return info


def _split_detail_url(detail_url: str) -> tuple[str, Optional[str]]:
    if "#" not in detail_url:
        return detail_url, None
    base_url, fragment = detail_url.split("#", 1)
    return base_url, fragment or None


def _enrich_showings_from_detail_pages(showings: List[Dict]) -> None:
    soup_cache: Dict[str, Optional[BeautifulSoup]] = {}
    detail_cache: Dict[str, Dict[str, Optional[str]]] = {}

    for showing in showings:
        detail_url = showing.get("detail_page_url")
        if not detail_url or "#" not in detail_url:
            continue

        base_url, fragment = _split_detail_url(detail_url)
        if not fragment:
            continue

        cache_key = f"{base_url}#{fragment}"
        if cache_key in detail_cache:
            detail_info = detail_cache[cache_key]
        else:
            soup = soup_cache.get(base_url)
            if soup is None:
                soup = fetch_soup(base_url)
                soup_cache[base_url] = soup
            if soup is None:
                continue

            block = soup.select_one(f"#{fragment}")
            if not block:
                detail_info = {
                    "director": None,
                    "year": None,
                    "runtime_min": None,
                    "country": None,
                    "synopsis": None,
                }
            else:
                detail_info = _extract_detail_block_info(block)
            detail_cache[cache_key] = detail_info

        if detail_info.get("director") and not showing.get("director"):
            showing["director"] = detail_info["director"]
        if detail_info.get("year") and not showing.get("year"):
            showing["year"] = detail_info["year"]
        if detail_info.get("runtime_min") and not showing.get("runtime_min"):
            showing["runtime_min"] = detail_info["runtime_min"]
        if detail_info.get("country") and not showing.get("country"):
            showing["country"] = detail_info["country"]
        if detail_info.get("synopsis") and not showing.get("synopsis"):
            showing["synopsis"] = detail_info["synopsis"]


def _parse_schedule_page(soup: BeautifulSoup, site_root: str) -> List[Dict]:
    results: List[Dict] = []
    schedule_section = soup.select_one("section#schedule, #schedule, .schedule")
    if not schedule_section:
        return results

    for day in schedule_section.select("section.day[data-date], .day[data-date], [data-date]"):
        date_text = (day.get("data-date") or "").strip()
        if not date_text:
            continue
        if day.select_one(".closedCard"):
            continue

        for slot in day.select(".slot, .schedule-slot, .schedule-item"):
            time_tag = slot.select_one(".t, .time, time")
            title_tag = slot.select_one("a.title, .title a, .movie-title, .title, a[href]")
            if not time_tag or not title_tag:
                continue

            showtime = clean_text(time_tag.get_text(" ", strip=True))
            if not re.match(r"^\d{1,2}:\d{2}$", showtime):
                continue
            movie_title = clean_text(title_tag.get_text(" ", strip=True))
            href = (title_tag.get("href") or "").strip()
            detail_url = urljoin(site_root, href) if href else site_root

            runtime_min = None
            dur_tag = slot.select_one(".dur")
            if dur_tag:
                runtime_min = _extract_runtime_min(dur_tag.get_text(" ", strip=True))

            results.append(
                {
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title,
                    "movie_title_en": None,
                    "director": None,
                    "year": None,
                    "country": None,
                    "runtime_min": runtime_min,
                    "synopsis": None,
                    "date_text": date_text,
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                    "program_title": None,
                    "purchase_url": None,
                }
            )

    return results


def fetch_soup(url: str, *, encoding: str = "utf-8") -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup object, or None on error."""
    try:
        resp = requests.get(url, timeout=10, headers=REQUEST_HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {url}: {e}", file=sys.stderr)
        return None

    if encoding:
        resp.encoding = encoding
    return BeautifulSoup(resp.text, "html.parser")


def extract_year(text: str) -> Optional[str]:
    """
    Extract and convert Japanese era notation to Gregorian year.

    Handles typical patterns from this site, e.g.:
      S38('63)／大映京都／白黒／1時間36分
      S42('67)／...
      H10('98)／...
      H12(2000)／...
      R2('20)／...

    Priority:
      1. If there is an explicit 4-digit year in parentheses → use that.
      2. Otherwise, look for [SHR]<number> and convert era year → Gregorian.
    """
    # 1) Explicit 4-digit year, e.g. H12(2000)
    m4 = re.search(r"\((\d{4})\)", text)
    if m4:
        return m4.group(1)

    # 2) Era notation like S38, H10, R2
    m = re.search(r"([SHR])\s*(\d+)", text)
    if not m:
        return None

    era = m.group(1)
    era_year = int(m.group(2))

    if era == "S":  # Shōwa 1926–1989
        gregorian = 1925 + era_year
    elif era == "H":  # Heisei 1989–2019
        gregorian = 1988 + era_year
    elif era == "R":  # Reiwa 2019–
        gregorian = 2018 + era_year
    else:
        return None

    return str(gregorian)


def _parse_program_page(program_slug: str = "fujimura") -> List[Dict]:
    """
    Parse a single program (e.g. 'fujimura') and return a list of showings.
    """
    results: List[Dict] = []

    program_url = urljoin(BASE_URL, f"{program_slug}.html")
    soup = fetch_soup(program_url)
    if soup is None:
        soup = fetch_soup(urljoin(BASE_URL, f"{program_slug}/"))
    if soup is None:
        return results

    # Program title (including any subtitle/series label)
    title_block = soup.select_one("#program_top h3")
    if title_block:
        program_title = clean_text(title_block.get_text(" ", strip=True))
    else:
        program_title = ""

    # Overall period text, e.g. "2025年11月1日（土）～28日（金）"
    schedule_tag = soup.select_one("p.schedule")
    program_period_text = clean_text(schedule_tag.get_text()) if schedule_tag else ""
    program_year = _extract_program_year(program_period_text) or _extract_program_year(
        soup.get_text(" ", strip=True)
    )

    # Find the detailed list page (e.g. fujimura_list.html)
    list_href = None
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        href_clean = href.split("#", 1)[0].split("?", 1)[0]
        if href_clean.endswith("_list.html") or href_clean.endswith("_list"):
            list_href = href
            break

    if list_href is None:
        # Fallback: assume <slug>_list.html
        list_href = f"{program_slug}_list.html"

    list_url = urljoin(BASE_URL, list_href)
    list_soup = fetch_soup(list_url)
    if list_soup is None:
        return results

    schedule_lines = [
        line for line in soup.get_text("\n").splitlines() if ":" in line or "：" in line
    ]
    schedule_map = _parse_schedule_map_from_lines(schedule_lines, program_year)

    # Each film block
    film_blocks = list_soup.select("div.data2_film, .data2_film, .filmBlock, .film-block, article.film")
    for film in film_blocks:
        # --- Basic metadata ---
        h4 = film.select_one(".data2_title h4, h4, h3")
        movie_title = ""
        film_number = None
        if h4:
            film_number, movie_title = _extract_film_number_and_title(h4.get_text())

        text_blocks = [
            clean_text(p.get_text(" ", strip=True)) for p in film.select(".data2_text")
        ]
        meta_text = " ".join(text_blocks)

        # Year from Japanese era notation
        year = extract_year(meta_text)

        # Director
        director_match = re.search(r"監督[:：]\s*([^\s■／]+)", meta_text)
        director = director_match.group(1) if director_match else None

        # --- Showtimes ---
        sche_tag = film.select_one(".data2_sche")
        showings: List[Dict[str, Optional[str]]] = []

        if sche_tag:
            showings = _parse_showings_from_lines(
                sche_tag.get_text("\n").splitlines(),
                program_year,
            )

        if not showings and film_number and film_number in schedule_map:
            showings = list(schedule_map.get(film_number, []))

        # If for some reason no per-line showings parsed, fall back to program period
        if not showings:
            showings.append(
                {
                    "date_text": program_period_text,
                    "showtime": None,
                }
            )

        # --- Assemble standardized entries ---
        for s in showings:
            results.append(
                {
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title,
                    "movie_title_en": None,
                    "director": director,
                    "year": year,
                    "country": None,
                    "runtime_min": None,
                    "date_text": s["date_text"],
                    "showtime": s["showtime"],
                    "detail_page_url": list_url,
                    "program_title": program_title,
                    "purchase_url": None,
                }
            )

    return results


def _extract_showings_from_feature_text(text: str, default_year: Optional[int]) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    line = clean_text(_normalize_schedule_line(text))
    if not line:
        return entries

    for m in re.finditer(r"(\d{1,2})\s*/\s*(\d{1,2}).*?(\d{1,2}:\d{2})", line):
        month = int(m.group(1))
        day = int(m.group(2))
        showtime = m.group(3)
        entries.append(
            {
                "date_text": _format_iso_date(default_year, month, day),
                "showtime": showtime,
            }
        )
    return entries


def _parse_feature_page(feature_url: str) -> List[Dict]:
    results: List[Dict] = []
    soup = fetch_soup(feature_url)
    if soup is None:
        return results

    page_text = soup.get_text(" ", strip=True)
    default_year = _extract_program_year(feature_url) or _extract_program_year(page_text)

    h1 = soup.select_one("h1")
    program_title = clean_text(h1.get_text(" ", strip=True)) if h1 else ""

    for film in soup.select("article.filmBlock"):
        title_tag = film.select_one(".filmBlock__title, h3, h4")
        if not title_tag:
            continue
        _, movie_title = _extract_film_number_and_title(title_tag.get_text(" ", strip=True))
        if not movie_title:
            continue

        sub_tag = film.select_one(".filmBlock__sub")
        sub_text = clean_text(sub_tag.get_text(" ", strip=True)) if sub_tag else ""

        year = extract_year(sub_text)
        if not year:
            parsed_year = _extract_program_year(sub_text)
            year = str(parsed_year) if parsed_year else None

        runtime_min = _extract_runtime_min(sub_text)
        country = _extract_country(sub_text)

        director = None
        for row in film.select("dl.filmInfo__row, .filmInfo__row"):
            dt = row.select_one("dt")
            dd = row.select_one("dd")
            if not dt or not dd:
                continue
            label = clean_text(dt.get_text(" ", strip=True))
            if "監督" in label:
                director = clean_text(dd.get_text(" ", strip=True))
                break

        synopsis = None
        synopsis_tag = film.select_one(".filmText p, .filmText")
        if synopsis_tag:
            parsed_synopsis = clean_text(synopsis_tag.get_text(" ", strip=True))
            synopsis = parsed_synopsis or None

        slot_lines = [li.get_text(" ", strip=True) for li in film.select(".filmTimes__list li")]
        showings: List[Dict[str, str]] = []
        for slot in slot_lines:
            showings.extend(_extract_showings_from_feature_text(slot, default_year))

        if not showings:
            continue

        for s in showings:
            results.append(
                {
                    "cinema_name": CINEMA_NAME,
                    "movie_title": movie_title,
                    "movie_title_en": None,
                    "director": director,
                    "year": year,
                    "country": country,
                    "runtime_min": runtime_min,
                    "synopsis": synopsis,
                    "date_text": s["date_text"],
                    "showtime": s["showtime"],
                    "detail_page_url": feature_url,
                    "program_title": program_title,
                    "purchase_url": None,
                }
            )

    return results


def _get_current_feature_urls() -> List[str]:
    site_root = BASE_URL.replace("program/", "")
    soup = fetch_soup(site_root)
    if soup is None:
        return []

    feature_urls = set()
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href:
            continue
        full_url = urljoin(site_root, href).split("#", 1)[0]
        normalized_url = full_url.split("?", 1)[0].rstrip("/")
        if "/features/" in normalized_url and normalized_url.endswith(".html"):
            feature_urls.add(normalized_url)
    return sorted(feature_urls)


def _get_current_program_urls() -> List[str]:
    """
    Scrape the main page to find current and upcoming program URLs.
    Returns a list of absolute URLs to program pages.
    """
    site_root = BASE_URL.replace("program/", "") # https://www.shogakukan.co.jp/jinbocho-theater/
    soup = fetch_soup(site_root)
    if soup is None:
        return []

    program_urls = set()
    
    # Look for links in the "Now Showing" and "Coming Soon" sections
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href:
            continue
        # normalize to absolute URL using the site root, not the program base
        full_url = urljoin(site_root, href).split("#", 1)[0]
        normalized_url = full_url.split("?", 1)[0].rstrip("/")
        
        # Check if it looks like a program page
        if "/program/" not in normalized_url:
            continue
        if normalized_url.endswith(("index.html", "coming.html", "top.html")):
            continue
        if re.search(r"/program/[^/]+(?:\.html)?$", normalized_url):
            program_urls.add(normalized_url)

    return sorted(program_urls)


def scrape_jinbocho() -> List[Dict]:
    """
    Public entry point used by main_scraper.
    Dynamically finds program pages from the homepage.
    """
    all_showings = []
    site_root = BASE_URL.replace("program/", "")

    soup = fetch_soup(site_root)
    if soup is not None:
        schedule_showings = _parse_schedule_page(soup, site_root)
        if schedule_showings:
            _enrich_showings_from_detail_pages(schedule_showings)
            return schedule_showings
    
    # 1. Get program URLs from main page
    program_urls = _get_current_program_urls()
    print(f"DEBUG: Found program URLs: {program_urls}", file=sys.stderr)

    # 2. Parse each program page
    for url in program_urls:
        # Extract slug from URL for the _parse_program_page function if we want to keep using it as is,
        # OR better, modify _parse_program_page to handle the URL directly. 
        # But _parse_program_page constructs URL from slug: 
        # program_url = urljoin(BASE_URL, f"{program_slug}.html")
        
        # Let's extract the slug:
        # .../program/slug.html -> slug
        normalized_url = url.split("?", 1)[0].rstrip("/")
        match = re.search(r"/program/([^/?#]+?)(?:\.html)?$", normalized_url)
        if match:
            slug = match.group(1)
            # Avoid re-scraping list pages directly (though the logic handles it, usually we want the parent program page)
            if slug in {"", "program"} or "_list" in slug:
                continue
                
            print(f"DEBUG: Scraping program: {slug}", file=sys.stderr)
            showings = _parse_program_page(slug)
            all_showings.extend(showings)

    # 3. Fallback for current site structure: feature pages with filmBlock schedules
    if not all_showings:
        feature_urls = _get_current_feature_urls()
        print(f"DEBUG: Found feature URLs: {feature_urls}", file=sys.stderr)
        for feature_url in feature_urls:
            showings = _parse_feature_page(feature_url)
            all_showings.extend(showings)

    # Deduplicate
    deduped = {}
    for s in all_showings:
        key = (s.get("date_text"), s.get("showtime"), s.get("movie_title"))
        deduped[key] = s

    return list(deduped.values())


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            if sys.stdout.encoding != "utf-8":
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if sys.stderr.encoding != "utf-8":
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    data = scrape_jinbocho()
    print(f"{len(data)} showings found")
    
    with_times = [d for d in data if d['showtime']]
    print(f"Showings with times: {len(with_times)}")
    
    for d in with_times[:3]:
        print(d)
