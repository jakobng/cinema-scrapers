from __future__ import annotations

import datetime as _dt
import re
import sys
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://eiga.com"
DEFAULT_DAYS_AHEAD = 7
REQUEST_DELAY_SEC = 0.2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.8",
}


def _normalize_key(name: str) -> str:
    name = name.strip().lower()
    return re.sub(r"[\s\u3000・\-ー–—\(\)（）【】\[\]]+", "", name)


def _build_name_map(aliases: Dict[str, str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for eiga_name, canonical in aliases.items():
        mapping[_normalize_key(eiga_name)] = canonical
        mapping[_normalize_key(canonical)] = canonical
    return mapping


def _log(label: str, message: str) -> None:
    line = f"INFO: [{label}] {message}"
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding, errors="replace"), flush=True)


def _get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    response = session.get(url, timeout=15)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    return BeautifulSoup(response.text, "html.parser")


def _extract_cinema_address(soup: BeautifulSoup) -> str:
    text = soup.get_text(" ", strip=True)
    match = re.search(r"所在地\s*([^行]+?)\s*行き方", text)
    if match:
        return match.group(1).strip()
    return ""


def _extract_cinema_site_url(soup: BeautifulSoup) -> str:
    for anchor in soup.select("a[href]"):
        label = anchor.get_text(strip=True)
        if "映画館公式ページ" in label or label == "公式ページ":
            return anchor["href"]
    return ""


def _normalize_showtime(value: str) -> str:
    match = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$", value)
    if not match:
        return value.strip()
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _extract_showtimes_for_date(section: BeautifulSoup, date_key: str) -> List[str]:
    tables = section.select("table.weekly-schedule")
    if not tables:
        return []
    times: List[str] = []
    for table in tables:
        cells = table.select(f'td[data-date="{date_key}"]')
        for cell in cells:
            cell_times: List[str] = []
            for span in cell.find_all("span"):
                text = span.get_text(strip=True)
                if re.match(r"^\d{1,2}:\d{2}$", text):
                    cell_times.append(_normalize_showtime(text))
            text = cell.get_text(" ", strip=True)
            range_pat = re.compile(r"(\d{1,2}:\d{2})\s*[~\u301c\uFF5E\-–—]\s*(\d{1,2}:\d{2})")
            range_ends = {_normalize_showtime(end) for _, end in range_pat.findall(text)}
            for raw_time in re.findall(r"\b\d{1,2}:\d{2}\b", text):
                normalized = _normalize_showtime(raw_time)
                if normalized in range_ends:
                    continue
                if normalized not in cell_times:
                    cell_times.append(normalized)
            for showtime in cell_times:
                if showtime not in times:
                    times.append(showtime)
    return times


def _extract_image_url(section: BeautifulSoup) -> str:
    img = section.select_one(".movie-image img")
    if not img:
        return ""
    src = (img.get("src") or "").strip()
    if not src:
        return ""
    src_lower = src.lower()
    if "noimg" in src_lower or "noposter" in src_lower:
        return ""
    full_url = urljoin(BASE_URL, src)
    full_url = re.sub(r"/(160|320)\.jpg$", "/640.jpg", full_url)
    full_url = re.sub(r"/(160|320)\.png$", "/640.png", full_url)
    return full_url


def _extract_movie_details(
    session: requests.Session,
    detail_url: str,
    movie_id: str,
    cache: Dict[str, Dict[str, str]],
    label: str,
) -> Dict[str, str]:
    if movie_id in cache:
        return cache[movie_id]

    details = {
        "director": "",
        "year": "",
        "runtime_min": "",
        "country": "",
        "synopsis": "",
    }

    try:
        soup = _get_soup(detail_url, session)
    except requests.RequestException as exc:
        print(f"ERROR: [{label}] Failed to fetch movie detail {detail_url}: {exc}", file=sys.stderr)
        cache[movie_id] = details
        return details

    synopsis = ""
    for selector in ("#story p", ".outline p", ".outline", ".story p"):
        node = soup.select_one(selector)
        if node:
            synopsis = node.get_text(" ", strip=True)
            if synopsis:
                break
    if not synopsis:
        heading = soup.find(lambda tag: tag.name in ("h2", "h3") and "解説・あらすじ" in tag.get_text())
        if heading:
            for sibling in heading.find_all_next():
                if sibling.name in ("p", "div"):
                    text = sibling.get_text(" ", strip=True)
                    if len(text) > 30:
                        synopsis = text
                        break
    details["synopsis"] = synopsis

    detail_line = ""
    for node in soup.select("p, div, li"):
        text = node.get_text(" ", strip=True)
        if "年製作" in text and "分" in text:
            detail_line = text
            break
    if not detail_line:
        text = soup.get_text(" ", strip=True)
        match = re.search(r"\d{4}年製作／[^。]+?分／[^。]+", text)
        if match:
            detail_line = match.group(0)

    if detail_line:
        year_match = re.search(r"(\d{4})年製作", detail_line)
        runtime_match = re.search(r"(\d{2,3})分", detail_line)
        country_match = re.search(r"／([^／]+?)配給", detail_line)
        if year_match:
            details["year"] = year_match.group(1)
        if runtime_match:
            details["runtime_min"] = runtime_match.group(1)
        if country_match:
            details["country"] = country_match.group(1)

    director = ""
    for dt in soup.find_all("dt"):
        if "監督" in dt.get_text(strip=True):
            dd = dt.find_next_sibling("dd")
            if dd:
                director = dd.get_text(" ", strip=True)
                break
    if not director:
        text = soup.get_text(" ", strip=True)
        match = re.search(r"監督\s*([^\s/]+)", text)
        if match:
            director = match.group(1)
    details["director"] = director

    cache[movie_id] = details
    time.sleep(REQUEST_DELAY_SEC)
    return details


def discover_prefecture_theaters(pref_id: str, session: requests.Session) -> List[Dict[str, str]]:
    theater_list_url = f"{BASE_URL}/theater/{pref_id}/"
    soup = _get_soup(theater_list_url, session)
    theaters: Dict[str, Dict[str, str]] = {}
    for anchor in soup.select(f'a[href^="/theater/{pref_id}/"]'):
        href = anchor.get("href", "")
        match = re.match(rf"^/theater/{pref_id}/(\d{{6}})/(\d{{4}})/", href)
        if not match:
            continue
        area_id, theater_id = match.groups()
        name = anchor.get_text(strip=True)
        if not name:
            continue
        theaters[theater_id] = {
            "name": name,
            "area_id": area_id,
            "theater_id": theater_id,
            "url": urljoin(BASE_URL, href),
        }
    return list(theaters.values())


def scrape_eiga_prefecture(
    *,
    pref_id: str,
    label: str,
    aliases: Dict[str, str],
    days_ahead: int = DEFAULT_DAYS_AHEAD,
) -> List[Dict[str, str]]:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    session = requests.Session()
    session.headers.update(HEADERS)
    name_map = _build_name_map(aliases)

    _log(label, "Fetching theater list...")
    theaters = discover_prefecture_theaters(pref_id, session)
    if not theaters:
        print(f"ERROR: [{label}] No theaters discovered from eiga.com list.", file=sys.stderr)
        return []
    _log(label, f"Discovered {len(theaters)} total theaters.")

    target_theaters = []
    for theater in theaters:
        canonical = aliases.get(theater["name"]) or name_map.get(_normalize_key(theater["name"]))
        if not canonical:
            continue
        theater["canonical_name"] = canonical
        target_theaters.append(theater)

    if not target_theaters:
        print(f"ERROR: [{label}] No independent theaters matched.", file=sys.stderr)
        return []
    _log(label, f"Matched {len(target_theaters)} independent theaters.")

    today = _dt.datetime.now(ZoneInfo("Asia/Tokyo")).date()
    dates = [today + _dt.timedelta(days=offset) for offset in range(days_ahead + 1)]

    listings: List[Dict[str, str]] = []
    movie_detail_cache: Dict[str, Dict[str, str]] = {}

    for idx, theater in enumerate(target_theaters, start=1):
        cinema_name = theater["canonical_name"]
        area_id = theater["area_id"]
        theater_id = theater["theater_id"]
        cinema_address = ""
        cinema_site_url = ""
        _log(label, f"({idx}/{len(target_theaters)}) {cinema_name} ({area_id}/{theater_id})")

        for target_date in dates:
            date_key = target_date.strftime("%Y%m%d")
            date_text = target_date.strftime("%Y-%m-%d")
            schedule_url = f"{BASE_URL}/theater/{pref_id}/{area_id}/{theater_id}/?date={date_key}"

            try:
                soup = _get_soup(schedule_url, session)
            except requests.RequestException as exc:
                print(f"ERROR: [{label}] Failed to fetch {schedule_url}: {exc}", file=sys.stderr)
                continue

            if not cinema_address:
                cinema_address = _extract_cinema_address(soup)
            if not cinema_site_url:
                cinema_site_url = _extract_cinema_site_url(soup)

            date_start_count = len(listings)
            for section in soup.select('section[id^="m"]'):
                section_id = section.get("id", "")
                movie_id_match = re.match(r"m(\d+)", section_id)
                movie_id = movie_id_match.group(1) if movie_id_match else ""

                title_anchor = section.select_one("h2.title-xlarge a")
                movie_title = title_anchor.get_text(strip=True) if title_anchor else ""
                if not movie_title:
                    continue

                detail_url = ""
                if title_anchor and title_anchor.get("href"):
                    detail_url = urljoin(BASE_URL, title_anchor["href"])

                showtimes = _extract_showtimes_for_date(section, date_key)
                if not showtimes:
                    continue

                movie_details = {}
                if movie_id and detail_url:
                    movie_details = _extract_movie_details(session, detail_url, movie_id, movie_detail_cache, label)

                movie_type = " ".join(
                    span.get_text(strip=True)
                    for span in section.select(".movie-type span")
                    if span.get_text(strip=True)
                ).strip()

                for showtime in showtimes:
                    listings.append({
                        "cinema_name": cinema_name,
                        "cinema_address": cinema_address,
                        "cinema_site_url": cinema_site_url,
                        "movie_title": movie_title,
                        "movie_title_jp": movie_title,
                        "movie_title_en": "",
                        "movie_title_original": "",
                        "date_text": date_text,
                        "showtime": showtime,
                        "booking_url": cinema_site_url,
                        "detail_page_url": detail_url,
                        "image_url": _extract_image_url(section),
                        "director": movie_details.get("director", ""),
                        "year": movie_details.get("year", ""),
                        "country": movie_details.get("country", ""),
                        "runtime_min": movie_details.get("runtime_min", ""),
                        "synopsis": movie_details.get("synopsis", ""),
                        "tags": movie_type,
                        "eiga_movie_id": movie_id,
                        "eiga_theater_id": theater_id,
                    })

            _log(label, f"{cinema_name} {date_text}: {len(listings) - date_start_count} showings")
            time.sleep(REQUEST_DELAY_SEC)

    return listings
