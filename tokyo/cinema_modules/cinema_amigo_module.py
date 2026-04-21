from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CINEMA_NAME = "CINEMA AMIGO"
BASE_URL = "https://cinema-amigo.com/"
SCHEDULE_PDF_URL = urljoin(BASE_URL, "/wp-content/uploads/pdf/schedule.pdf")
AIRRESERVE_URL = "https://airrsv.net/cinema-amigo1/calendar"
AIRRESERVE_API_BASE = "https://airrsv.net/cinema-amigo1/stateful/calendar/lesson"
AIRRESERVE_SCHEDULE_ID = "L00003E931"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ja,en;q=0.8"}
SKIP_TITLES = {"休館", "貸切"}

_FULLWIDTH_TRANS = str.maketrans(
    "０１２３４５６７８９：／－〜～",
    "0123456789:/-~~",
)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize(text: str) -> str:
    return _clean_text(text.translate(_FULLWIDTH_TRANS))


def _today_jst() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("Asia/Tokyo")).date()


def _resolve_year(month: int, day: int, today: dt.date) -> int:
    candidate = dt.date(today.year, month, day)
    if candidate < today - dt.timedelta(days=45):
        return today.year + 1
    return today.year


def _date_range(start_month: int, start_day: int, end_month: int, end_day: int, today: dt.date) -> Iterable[dt.date]:
    year = _resolve_year(start_month, start_day, today)
    try:
        current = dt.date(year, start_month, start_day)
        end = dt.date(year + (1 if end_month < start_month else 0), end_month, end_day)
    except ValueError:
        return
    emitted = 0
    while current <= end and emitted <= 31:
        yield current
        current += dt.timedelta(days=1)
        emitted += 1


def _dates_for_schedule_line(line: str, today: dt.date) -> List[dt.date]:
    normalized = _normalize(line)
    range_match = re.search(r"(\d{1,2})/(\d{1,2}).{0,12}[~\-](?:(\d{1,2})/)?(\d{1,2})", normalized)
    if range_match:
        sm, sd, em, ed = range_match.groups()
        start_month = int(sm)
        end_month = int(em) if em else start_month
        return list(_date_range(start_month, int(sd), end_month, int(ed), today))
    single_match = re.search(r"(\d{1,2})/(\d{1,2})", normalized)
    if single_match:
        month = int(single_match.group(1))
        day = int(single_match.group(2))
        try:
            return [dt.date(_resolve_year(month, day, today), month, day)]
        except ValueError:
            return []
    return []


def _times_for_schedule_line(line: str) -> List[str]:
    normalized = _normalize(line)
    if "上映時間未定" in normalized:
        return []
    times = []
    for hour, minute in re.findall(r"\b(\d{1,2}):(\d{2})\b", normalized):
        times.append(f"{int(hour):02d}:{minute}")
    return list(dict.fromkeys(times))


def _parse_jsonp(payload: str) -> Optional[dict]:
    match = re.match(r"/\*\*/callback\((.*)\);?$", payload, re.S)
    if not match:
        return None
    return json.loads(match.group(1))


def _extract_schedule_text(soup: BeautifulSoup) -> str:
    heading = soup.find(lambda tag: tag.name in ("h2", "h3") and "SCHEDULE" in tag.get_text(" ", strip=True).upper())
    if not heading:
        return ""
    chunks = []
    for sibling in heading.find_all_next():
        if sibling is heading:
            continue
        if sibling.name in ("h2", "h3") and "ABOUT" in sibling.get_text(" ", strip=True).upper():
            break
        text = sibling.get_text("\n", strip=True)
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _extract_metadata(soup: BeautifulSoup) -> Dict[str, str]:
    text = soup.get_text("\n", strip=True)
    details = {"director": "", "year": "", "country": "", "runtime_min": ""}
    director_match = re.search(r"監督[:：]\s*([^\n]+)", text)
    if director_match:
        details["director"] = _clean_text(director_match.group(1))
    meta_match = re.search(r"([12０１２]\d{3}|[１２][０-９]{3})年?\s*[／/]\s*([^／/\n]+)\s*[／/]\s*(\d{2,3}|[０-９]{2,3})\s*min", text, re.IGNORECASE)
    if meta_match:
        year, country, runtime = meta_match.groups()
        details["year"] = year.translate(_FULLWIDTH_TRANS)
        details["country"] = _clean_text(country)
        details["runtime_min"] = runtime.translate(_FULLWIDTH_TRANS)
    return details


def _movie_links_from_home(soup: BeautifulSoup) -> List[str]:
    links = []
    for anchor in soup.select('a[href*="/20"]'):
        href = anchor.get("href") or ""
        text = anchor.get_text(" ", strip=True)
        if not href or not text:
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url not in links and re.search(r"/20\d{2}/\d{2}/\d+/?$", full_url):
            links.append(full_url)
    return links


def _parse_airreserve_dt(value: str) -> tuple[str, str]:
    date_text = f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    showtime = f"{value[8:10]}:{value[10:12]}"
    return date_text, showtime


def _fetch_airreserve_showtimes(days_ahead: int = 45) -> List[Dict[str, str]]:
    session = requests.Session()
    session.headers.update({**HEADERS, "X-Requested-With": "XMLHttpRequest"})
    try:
        session.get(AIRRESERVE_URL, timeout=20).raise_for_status()
        menu_response = session.get(
            f"{AIRRESERVE_API_BASE}/searchLessonMenuResrc",
            params={"schdlId": AIRRESERVE_SCHEDULE_ID},
            timeout=20,
        )
        menu_response.raise_for_status()
        menu_payload = _parse_jsonp(menu_response.text) or {}
    except (requests.RequestException, json.JSONDecodeError) as exc:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch AirReserve metadata: {exc}", file=sys.stderr)
        return []

    menu_list = ((menu_payload.get("dto") or {}).get("menuList") or [])
    menu_map = {item.get("menuId"): item.get("menuNm", "") for item in menu_list}
    today = _today_jst()
    listings: List[Dict[str, str]] = []
    seen = set()

    # AirReserve expects yyyymmddHHMMSS and the UI fetches week-sized windows.
    start = today
    end = today + dt.timedelta(days=days_ahead)
    cursor = start
    while cursor <= end:
        week_end = min(cursor + dt.timedelta(days=6), end)
        params = {
            "bookingFromDt": cursor.strftime("%Y%m%d000000"),
            "bookingToDt": week_end.strftime("%Y%m%d240000"),
        }
        try:
            response = session.get(AIRRESERVE_API_BASE, params=params, timeout=20)
            response.raise_for_status()
            payload = _parse_jsonp(response.text) or {}
        except (requests.RequestException, json.JSONDecodeError) as exc:
            print(f"ERROR: [{CINEMA_NAME}] Could not fetch AirReserve slots {params}: {exc}", file=sys.stderr)
            cursor = week_end + dt.timedelta(days=1)
            continue

        slot_map = ((payload.get("dto") or {}).get("lessonBookingRstMap") or {})
        for day_key, slots in slot_map.items():
            for slot in slots or []:
                entity = slot.get("slotEntity") or {}
                title = menu_map.get(entity.get("lessonSchdlId")) or entity.get("slotNm") or ""
                title = _clean_text(title)
                if not title or title in SKIP_TITLES:
                    continue
                from_dt = entity.get("fromDt")
                if not from_dt or len(from_dt) < 12:
                    continue
                date_text, showtime = _parse_airreserve_dt(from_dt)
                if dt.date.fromisoformat(date_text) < today:
                    continue
                key = (title, date_text, showtime)
                if key in seen:
                    continue
                seen.add(key)
                listings.append({
                    "cinema_name": CINEMA_NAME,
                    "cinema_address": "神奈川県逗子市新宿1-5-14",
                    "cinema_site_url": BASE_URL,
                    "movie_title": title,
                    "date_text": date_text,
                    "showtime": showtime,
                    "detail_page_url": AIRRESERVE_URL,
                    "purchase_url": AIRRESERVE_URL,
                })
        cursor = week_end + dt.timedelta(days=1)

    return listings


def _extract_pdf_schedule_month(text: str, today: dt.date) -> tuple[int, int]:
    match = re.search(r"MOVIE\s*&\s*EVENT\s*SCHEDULE\s*(\d{4})\.(\d{1,2})", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return today.year, today.month


def _showtime_for_pdf_x(x0: float) -> str:
    if x0 < 340:
        return "10:00"
    if x0 < 430:
        return "12:30"
    if x0 < 520:
        return "15:00"
    return "17:30"


def _clean_pdf_movie_title(text: str) -> str:
    parts = [_clean_text(part) for part in text.splitlines()]
    cleaned = []
    for part in parts:
        if not part:
            continue
        normalized = _normalize(part)
        if re.match(r"^\d{1,2}:\d{2}$", normalized):
            continue
        if re.search(r"^\(?\d{2,3}\s*min\)?$", normalized, re.IGNORECASE):
            continue
        if re.search(r"^\d{4}年", normalized):
            continue
        compact = re.sub(r"\s+", "", normalized).upper()
        if any(skip in compact for skip in ("休映", "休館", "CLOSED", "AMIGO", "逗子海岸映画祭", "BARTIME", "MARKET")):
            continue
        if "上映" in compact and re.search(r"\d{1,2}:\d{2}", compact):
            continue
        cleaned.append(part)
    title = _clean_text(" ".join(cleaned))
    title = re.sub(r"\s*（\d{2,3}min）", "", title, flags=re.IGNORECASE)
    return title


def _fetch_pdf_showtimes() -> List[Dict[str, str]]:
    try:
        import fitz
    except ImportError:
        print(f"INFO: [{CINEMA_NAME}] PyMuPDF not installed; skipping PDF schedule fallback.")
        return []

    try:
        response = requests.get(SCHEDULE_PDF_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch schedule PDF: {exc}", file=sys.stderr)
        return []

    today = _today_jst()
    listings: List[Dict[str, str]] = []
    seen = set()
    try:
        doc = fitz.open(stream=response.content, filetype="pdf")
    except Exception as exc:
        print(f"ERROR: [{CINEMA_NAME}] Could not parse schedule PDF: {exc}", file=sys.stderr)
        return []

    all_text = "\n".join(page.get_text() for page in doc)
    schedule_year, current_month = _extract_pdf_schedule_month(all_text, today)

    for page in doc:
        blocks = page.get_text("blocks")
        date_rows = []
        month = current_month
        for block in sorted(blocks, key=lambda item: (item[1], item[0])):
            x0, y0, _x1, _y1, text = block[:5]
            if not (190 <= x0 <= 260):
                continue
            line = _normalize(" ".join(text.split()))
            match = re.search(r"(?:(\d{1,2})\s*/\s*)?(\d{1,2})\s*（", line)
            if not match:
                continue
            if match.group(1):
                month = int(match.group(1))
            if not month:
                continue
            day = int(match.group(2))
            year = schedule_year + (1 if month < current_month and current_month >= 10 else 0)
            try:
                date_value = dt.date(year, month, day)
            except ValueError:
                continue
            date_rows.append((y0, date_value))

        if not date_rows:
            continue

        for block in blocks:
            x0, y0, x1, y1, text = block[:5]
            if not (250 <= x0 <= 610 and 45 <= y0 <= 545):
                continue
            title = _clean_pdf_movie_title(text)
            if not title or len(title) < 2:
                continue
            nearest_y, date_value = min(date_rows, key=lambda row: abs(row[0] - y0))
            if abs(nearest_y - y0) > 18 or date_value < today:
                continue
            showtime = _showtime_for_pdf_x(x0)
            key = (title, date_value.isoformat(), showtime)
            if key in seen:
                continue
            seen.add(key)
            listings.append({
                "cinema_name": CINEMA_NAME,
                "cinema_address": "神奈川県逗子市新宿1-5-14",
                "cinema_site_url": BASE_URL,
                "movie_title": title,
                "date_text": date_value.isoformat(),
                "showtime": showtime,
                "detail_page_url": SCHEDULE_PDF_URL,
            })

    return listings


def scrape_cinema_amigo() -> List[Dict[str, str]]:
    airreserve_listings = _fetch_airreserve_showtimes()
    pdf_listings = _fetch_pdf_showtimes()
    listings: List[Dict[str, str]] = []
    seen = set()
    for item in airreserve_listings + pdf_listings:
        key = (item.get("movie_title"), item.get("date_text"), item.get("showtime"))
        if key in seen:
            continue
        seen.add(key)
        listings.append(item)
    if listings:
        return sorted(listings, key=lambda item: (item["date_text"], item["showtime"], item["movie_title"]))

    try:
        response = requests.get(BASE_URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {BASE_URL}: {exc}", file=sys.stderr)
        return []

    home_soup = BeautifulSoup(response.text, "html.parser")
    today = _today_jst()
    listings: List[Dict[str, str]] = []
    seen = set()

    for detail_url in _movie_links_from_home(home_soup):
        try:
            detail_response = requests.get(detail_url, headers=HEADERS, timeout=20)
            detail_response.raise_for_status()
        except requests.RequestException as exc:
            print(f"ERROR: [{CINEMA_NAME}] Could not fetch detail {detail_url}: {exc}", file=sys.stderr)
            continue

        soup = BeautifulSoup(detail_response.text, "html.parser")
        title_node = soup.select_one("h1, .entry-title, .post-title")
        title = _clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        if not title:
            og_title = soup.select_one('meta[property="og:title"]')
            title = _clean_text(og_title.get("content", "")) if og_title else ""
        if not title:
            continue

        schedule_text = _extract_schedule_text(soup)
        if not schedule_text:
            continue
        details = _extract_metadata(soup)

        for raw_line in schedule_text.splitlines():
            line = _clean_text(raw_line)
            dates = [value for value in _dates_for_schedule_line(line, today) if value >= today]
            times = _times_for_schedule_line(line)
            if not dates or not times:
                continue
            for date_value in dates:
                for showtime in times:
                    key = (title, date_value.isoformat(), showtime)
                    if key in seen:
                        continue
                    seen.add(key)
                    listings.append({
                        "cinema_name": CINEMA_NAME,
                        "cinema_address": "神奈川県逗子市新宿1-5-14",
                        "cinema_site_url": BASE_URL,
                        "movie_title": title,
                        "date_text": date_value.isoformat(),
                        "showtime": showtime,
                        "detail_page_url": detail_url,
                        **details,
                    })

    if not listings:
        print(f"INFO: [{CINEMA_NAME}] No current public film showtimes with explicit times found.")
    return listings


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    data = scrape_cinema_amigo()
    print(f"Collected {len(data)} listings.")
