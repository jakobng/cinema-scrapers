# bluestudio_module.py
# Robust scraper for Cinema Blue Studio (シネマブルースタジオ)
# - Layout-agnostic parsing
# - Shift_JIS-safe decoding
# - Precise director extraction (trims trailing roles like 撮影)
# - Adds JP weekday label and ISO week number
# - De-duplicates identical (title, date, time) rows
# - Normalizes showtimes to zero-padded 24h HH:MM

from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from calendar import day_name
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CINEMA_NAME = "シネマブルースタジオ"
BASE_URL = "https://www.art-center.jp/tokyo/bluestudio/schedule.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BluestudioScraper/1.6)"}

# -------------------------------------------------------------------
# HTTP + Parsing
# -------------------------------------------------------------------
def _session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods={"GET"},
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update(HEADERS)
    return s


def _bs4_parse(text: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(text, "html5lib")
    except Exception:
        return BeautifulSoup(text, "html.parser")


def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    try:
        s = _session()
        r = s.get(url, timeout=25)
        r.raise_for_status()
        raw = r.content
        # Prefer CP932 (Shift_JIS superset) to avoid mojibake in Japanese labels.
        try:
            text = raw.decode("cp932", errors="replace")
        except Exception:
            text = raw.decode("utf-8", errors="replace")

        # If meta declares another charset (non-SJIS), try it.
        m = re.search(r'<meta[^>]+charset=["\']?([\w\-]+)', text, re.I)
        if m:
            enc = m.group(1).lower()
            if enc not in {"shift_jis", "shift-jis", "sjis", "cp932", "windows-31j"}:
                try:
                    text = raw.decode(enc, errors="replace")
                except Exception:
                    pass

        soup = _bs4_parse(text)
        print(
            f"DEBUG: HTTP {r.status_code}, bytes={len(raw)}, parser={'html5lib'}",
            file=sys.stderr,
        )
        return soup
    except requests.RequestException as e:
        print(f"ERROR: [{CINEMA_NAME}] Fetch failed: {e}", file=sys.stderr)
        return None

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
_FW = "０１２３４５６７８９：／（）～－ー．．　⇒→"
_HW = "0123456789:/()~--..  ->"
_TRANS = str.maketrans(dict(zip(_FW, _HW)))

def _normalize_text(t: str) -> str:
    if not t:
        return ""
    t = re.sub(r"(\d)\s+(\d)", r"\1\2", t)
    t = t.translate(_TRANS)
    t = re.sub(r"(⇒|→)+", "->", t)
    return " ".join(t.strip().split())

_WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

def _extract_date_range(t: str) -> Optional[Tuple[dt.date, dt.date]]:
    """
    Extract (start_date, end_date) from text like:
      2025/8/27（水）～2025/9/9（火） or 2025/8/27（水）～9/9（火）
    """
    t = _normalize_text(t)
    m1 = re.search(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", t)
    if not m1:
        return None
    y, mo, d = map(int, m1.groups())
    start = dt.date(y, mo, d)
    tail = t[m1.end():]
    m2 = re.search(r"[~〜\-\s]+(?:(\d{4})[./])?(\d{1,2})[./](\d{1,2})", tail)
    if not m2:
        return None
    y2s, mo2s, d2s = m2.groups()
    y2 = int(y2s) if y2s else y
    mo2, d2 = int(mo2s), int(d2s)
    if not y2s and mo2 < mo and (mo - mo2) > 6:
        y2 += 1
    end = dt.date(y2, mo2, d2)
    if end < start:
        end = dt.date(y2 + 1, mo2, d2)
    return start, end

_TIME_RE = r"\b(\d{1,2}):(\d{2})\b"

def _extract_times(t: str) -> List[str]:
    """
    Parse "上映時間" segment and return a list of HH:MM strings.
    """
    t = _normalize_text(t)
    m = re.search(r"上映時間[^0-9]*([0-9:/・･ ,　／/]+)", t)
    seg = m.group(1) if m else t
    times = []
    for h, mmin in re.findall(_TIME_RE, seg):
        times.append(f"{int(h):02d}:{int(mmin):02d}")
    # Preserve input order while de-duplicating
    out, seen = [], set()
    for t0 in times:
        if t0 not in seen:
            seen.add(t0)
            out.append(t0)
    return out


def _is_title_candidate(line: str) -> bool:
    if not line:
        return False
    if line.startswith("※"):
        return False
    if "上映" in line:
        return False
    if any(key in line for key in ("上映スケジュール", "schedule", "過去の上映作品", "Access", "交通", "ブルースタジオ", "シネマブルースタジオ")):
        return False
    if any(key in line for key in ("監督", "脚本", "製作", "撮影", "音楽", "出演", "料金", "チケット")):
        return False
    if re.search(r"\d{4}/\d{1,2}/\d{1,2}", line):
        return False
    if re.search(r"\d{1,2}：\d{2}", line) or re.search(_TIME_RE, _normalize_text(line)):
        return False
    if re.search(r"\d{4}年", line) and "分" in line:
        return False
    return True


def _clean_title(line: str) -> str:
    return line.split("※")[0].strip()

def _make_film_id(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    return slug if slug else "jp-" + hashlib.md5(title.encode()).hexdigest()[:10]

# -------------------------------------------------------------------
# Director extractor (precise)
# -------------------------------------------------------------------
ROLE_STOPS = r"(?:監督補|共同監督|助監督|撮影|音楽|出演|脚本|原作|編集|製作|制作|配給|字幕|監修|企画)"
NAME_CHARS = r"[^\s　／/()・,:]+"

def _extract_director(text: str) -> Optional[str]:
    """
    Return only the director's name, e.g. '黒沢清'.
    Handles:
      監督：黒沢清
      監督・脚本：黒沢 清
      監督・脚本・編集：黒沢清 撮影：…
      監督 黒沢清 撮影 …
    """
    t = _normalize_text(text)
    m = re.search(rf"監督(?:・[^：:]+)*[：:]\s*({NAME_CHARS}(?:[・･\s　]{NAME_CHARS})*)", t)
    if not m:
        m = re.search(rf"監督(?:・[^：:]+)*\s+({NAME_CHARS}(?:[・･\s　]{NAME_CHARS})*)", t)
    if not m:
        return None
    name = m.group(1).strip()
    # Trim trailing role labels whether or not they have a colon
    name = re.sub(rf"\s*(?:{ROLE_STOPS})(?:\s*[：:].*)?$", "", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name or None

# -------------------------------------------------------------------
# Details extraction (including optional synopsis when present)
# -------------------------------------------------------------------
def _parse_details_from_text(text: str) -> Dict:
    d = {"director": None, "year": None, "runtime_min": None, "country": None, "synopsis": None}
    t = _normalize_text(text)

    dir_ = _extract_director(t)
    if dir_:
        d["director"] = dir_

    m = re.search(r"\((\d{2,3})分\)", t)
    if m:
        d["runtime_min"] = m.group(1)

    m = re.search(r"(\d{4})年\s*([^\s()]+)?", t)
    if m:
        d["year"] = m.group(1)
        c = (m.group(2) or "").strip()
        if c and not c.endswith("分"):
            d["country"] = c

    # Optional synopsis: attempt to capture after あらすじ/解説/ストーリー if present
    m = re.search(r"(?:あらすじ|ストーリー|解説)\s*[:：]?\s*(.+?)(?=(?:\(\d{2,3}分\)|$))", t)
    if m:
        d["synopsis"] = m.group(1).strip() or None

    return d

# -------------------------------------------------------------------
# Main scraper
# -------------------------------------------------------------------
def scrape_bluestudio(max_days: int = 14) -> List[Dict]:
    print(f"INFO: [{CINEMA_NAME}] Starting scrape...", file=sys.stderr)
    soup = fetch_soup(BASE_URL)
    if not soup:
        return []

    today = dt.date.today()
    cutoff = today + dt.timedelta(days=max_days)
    all_showings: List[Dict] = []
    seen_blocks = set()   # (title, start, end)
    seen_rows = set()     # (title, date, time) for de-duplication

    lines = [line.strip() for line in soup.get_text("\n").split("\n") if line.strip()]
    line_showings: List[Dict] = []
    seen_rows_line = set()
    date_indices = []
    for idx, line in enumerate(lines):
        if re.search(r"\d{4}/\d{1,2}/\d{1,2}", line):
            date_indices.append(idx)

    for pos, idx in enumerate(date_indices):
        line = lines[idx]
        date_line = line
        if not re.search(r"\d{4}/\d{1,2}/\d{1,2}", date_line) and idx + 1 < len(lines):
            date_line = line + " " + lines[idx + 1]
        dr = _extract_date_range(date_line)
        if not dr:
            continue
        start, end = dr

        title = None
        for back in range(idx - 1, max(-1, idx - 10), -1):
            candidate = lines[back]
            if _is_title_candidate(candidate):
                title = _clean_title(candidate)
                break
        if not title:
            continue

        times = []
        for forward in range(idx, min(len(lines), idx + 8)):
            times = _extract_times(lines[forward])
            if times:
                break
        if not times:
            continue

        next_idx = date_indices[pos + 1] if pos + 1 < len(date_indices) else len(lines)
        block_text = " ".join(lines[idx:next_idx])
        details = _parse_details_from_text(block_text)

        day = max(today, start)
        while day <= end and day < cutoff:
            for t_str in times:
                row_key = (title, day.isoformat(), t_str)
                if row_key in seen_rows_line:
                    continue
                seen_rows_line.add(row_key)
                record = {
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "date_text": day.isoformat(),
                    "date_dow": day_name[day.weekday()],
                    "date_dow_jp": _WEEKDAY_JP[day.weekday()],
                    "date_iso_week": day.isocalendar().week,
                    "showtime": t_str,
                    "screen_name": None,
                    "detail_page_url": BASE_URL,
                    "film_id": _make_film_id(title),
                    **details,
                }
                line_showings.append(record)
            day += dt.timedelta(days=1)

    if line_showings:
        line_showings.sort(key=lambda x: (x.get("date_text", ""), x.get("showtime", ""), x.get("movie_title", "")))
        print(f"INFO: Scrape complete: {len(line_showings)} showings", file=sys.stderr)
        return line_showings

    # Primary path: table layout (modern/legacy both contain these labels)
    tables = [
        t for t in soup.find_all("table")
        if ("上映期間" in t.get_text() and "上映時間" in t.get_text())
    ]
    print(f"INFO: Found {len(tables)} tables", file=sys.stderr)

    def process_block(title: str, block_text: str):
        nonlocal all_showings, seen_blocks, seen_rows

        title = _normalize_text(title.split("※")[0])
        if not title:
            return

        dr = _extract_date_range(block_text)
        if not dr:
            return
        start, end = dr

        key = (title, start, end)
        if key in seen_blocks:
            return
        seen_blocks.add(key)

        times = _extract_times(block_text)
        if not times:
            return

        details = _parse_details_from_text(block_text)

        day = max(today, start)
        while day <= end and day < cutoff:
            for t_str in times:
                # De-dup per title/date/time
                row_key = (title, day.isoformat(), t_str)
                if row_key in seen_rows:
                    continue
                seen_rows.add(row_key)

                record = {
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "date_text": day.isoformat(),
                    "date_dow": day_name[day.weekday()],
                    "date_dow_jp": _WEEKDAY_JP[day.weekday()],
                    "date_iso_week": day.isocalendar().week,
                    "showtime": t_str,            # already zero-padded
                    "screen_name": None,
                    "detail_page_url": BASE_URL,
                    "film_id": _make_film_id(title),
                    **details,
                }
                all_showings.append(record)
            day += dt.timedelta(days=1)

    for tbl in tables:
        tx = tbl.get_text("\n", strip=True)
        title_tag = tbl.select_one("b,strong") or tbl.find("td")
        title = _normalize_text(title_tag.get_text()) if title_tag else ""
        process_block(title, tx)

    all_showings.sort(key=lambda x: (x.get("date_text", ""), x.get("showtime", ""), x.get("movie_title", "")))
    print(f"INFO: Scrape complete: {len(all_showings)} showings", file=sys.stderr)
    return all_showings

# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scrape showtimes from Cinema Blue Studio.")
    p.add_argument("--max-days", type=int, default=10, help="Days ahead to include (default: 10).")
    p.add_argument("--out", type=Path, default=Path("bluestudio_showtimes.json"),
                   help="Output JSON path (default: bluestudio_showtimes.json).")
    return p

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = _build_argparser().parse_args()
    data = scrape_bluestudio(max_days=args.max_days)
    if data:
        args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"INFO: Wrote {args.out} ({len(data)} records)", file=sys.stderr)
    else:
        print("No showings found.")
