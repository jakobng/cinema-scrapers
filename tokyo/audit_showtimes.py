#!/usr/bin/env python3
"""Audit Tokyo showtime data for frontend-visible quality issues."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse


JST = timezone(timedelta(hours=9))

BLOCKED_DETAIL_HOST_SUFFIXES = (
    "eiga.com",
    "eigaland.com",
    "jorudan.co.jp",
    "hellomovie.info",
)

EXPECTED_CINEMA_HOST_HINTS = {
    "CINEMA AMIGO": ("cinema-amigo.com", "airrsv.net"),
    "K2 Cinema": ("k2-cinema.com",),
    "シネマブルースタジオ": ("art-center.jp",),
    "シネマヴェーラ渋谷": ("cinemavera.com",),
    "下高井戸シネマ": ("shimotakaidocinema.com",),
    "国立映画アーカイブ": ("nfaj.go.jp",),
    "目黒シネマ": ("okura-movie.co.jp",),
    "神保町シアター": ("shogakukan.co.jp",),
}

ALLOWLIST_LINKLESS = {
    # Program-row placeholders may not have a per-title page, but should still be rare.
    ("下高井戸シネマ", "レオス・カラックス監督初期傑作"),
}


def load_json(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise SystemExit(f"{path} must contain a JSON array")
    return data


def today_jst() -> str:
    return datetime.now(JST).date().isoformat()


def has_usable_link(item: dict) -> bool:
    return bool(
        item.get("booking_url")
        or item.get("purchase_url")
        or item.get("detail_page_url")
        or item.get("official_site")
        or item.get("cinema_site_url")
    )


def host_for(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def is_blocked_detail_url(item: dict) -> bool:
    url = item.get("detail_page_url") or ""
    host = host_for(url).lower()
    return any(host == suffix or host.endswith("." + suffix) for suffix in BLOCKED_DETAIL_HOST_SUFFIXES)


def expected_host_mismatch(item: dict) -> bool:
    url = item.get("detail_page_url") or item.get("booking_url") or item.get("purchase_url") or ""
    host = host_for(url).lower()
    if not host:
        return False
    hints = EXPECTED_CINEMA_HOST_HINTS.get(item.get("cinema_name"))
    if not hints:
        return False
    return not any(hint in host for hint in hints)


def malformed_title(item: dict) -> bool:
    title = str(item.get("movie_title") or item.get("movie_title_jp") or "").strip()
    if not title:
        return True
    if title in {":", "：", "-", "ー", "／", "/"}:
        return True
    return not any(ch.isalnum() or "\u3040" <= ch <= "\u9fff" for ch in title)


def brief_rows(rows: list[dict], limit: int = 12) -> list[str]:
    lines = []
    for item in rows[:limit]:
        lines.append(
            "  - {cinema} | {date} {time} | {title}".format(
                cinema=item.get("cinema_name") or "?",
                date=item.get("date_text") or "?",
                time=item.get("showtime") or "?",
                title=item.get("movie_title") or item.get("movie_title_jp") or "?",
            )
        )
    if len(rows) > limit:
        lines.append(f"  ... {len(rows) - limit} more")
    return lines


def compare_website_sync(scraper_data: list[dict], website_path: Path | None) -> list[str]:
    if not website_path or not website_path.exists():
        return []
    website_data = load_json(website_path)
    scraper_keys = {
        (
            item.get("cinema_name"),
            item.get("movie_title"),
            item.get("date_text"),
            item.get("showtime"),
        )
        for item in scraper_data
    }
    website_keys = {
        (
            item.get("cinema_name"),
            item.get("movie_title"),
            item.get("date_text"),
            item.get("showtime"),
        )
        for item in website_data
    }
    missing_on_website = scraper_keys - website_keys
    extra_on_website = website_keys - scraper_keys
    if not missing_on_website and not extra_on_website:
        return ["Website sync: OK"]
    return [
        "Website sync differs:",
        f"  scraper rows: {len(scraper_data)}",
        f"  website rows: {len(website_data)}",
        f"  missing on website: {len(missing_on_website)}",
        f"  extra on website: {len(extra_on_website)}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Tokyo showtimes JSON.")
    parser.add_argument("--data", default="data/showtimes.json", help="Path to scraper showtimes JSON")
    parser.add_argument("--website-data", default="", help="Optional website1 showtimes JSON path for sync comparison")
    parser.add_argument("--today", default=today_jst(), help="ISO date to treat as today")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero for critical current/future issues")
    args = parser.parse_args()

    data_path = Path(args.data)
    data = load_json(data_path)
    future = [item for item in data if str(item.get("date_text") or "") >= args.today]

    duplicates = []
    counts = Counter(
        (
            item.get("cinema_name"),
            item.get("movie_title"),
            item.get("date_text"),
            item.get("showtime"),
        )
        for item in future
    )
    for key, count in counts.items():
        if count > 1:
            duplicates.append((key, count))

    malformed = [item for item in future if malformed_title(item)]
    linkless = [
        item
        for item in future
        if not has_usable_link(item)
        and (item.get("cinema_name"), item.get("movie_title")) not in ALLOWLIST_LINKLESS
    ]
    blocked_detail = [item for item in future if is_blocked_detail_url(item)]
    mismatched_hosts = [item for item in future if expected_host_mismatch(item)]
    missing_tmdb = [item for item in future if not item.get("tmdb_id")]
    missing_english = [item for item in future if not item.get("movie_title_en")]

    by_cinema = defaultdict(int)
    for item in future:
        by_cinema[item.get("cinema_name") or "Unknown"] += 1

    print("Tokyo showtimes audit")
    print(f"  data: {data_path}")
    print(f"  today: {args.today}")
    print(f"  total rows: {len(data)}")
    print(f"  current/future rows: {len(future)}")
    print(f"  current/future cinemas: {len(by_cinema)}")
    print(f"  missing TMDB IDs: {len(missing_tmdb)}")
    print(f"  missing English titles: {len(missing_english)}")
    print(f"  malformed titles: {len(malformed)}")
    print(f"  linkless rows: {len(linkless)}")
    print(f"  non-cinema detail hosts: {len(blocked_detail)}")
    print(f"  expected-host mismatches: {len(mismatched_hosts)}")
    print(f"  duplicate rows: {len(duplicates)}")

    for label, rows in (
        ("Malformed titles", malformed),
        ("Linkless rows", linkless),
        ("Non-cinema detail hosts", blocked_detail),
        ("Expected-host mismatches", mismatched_hosts),
    ):
        if rows:
            print(label + ":")
            print("\n".join(brief_rows(rows)))

    if duplicates:
        print("Duplicate rows:")
        for key, count in duplicates[:12]:
            print(f"  - {key} x{count}")
        if len(duplicates) > 12:
            print(f"  ... {len(duplicates) - 12} more")

    website_path = Path(args.website_data) if args.website_data else None
    for line in compare_website_sync(data, website_path):
        print(line)

    critical_count = len(malformed) + len(linkless) + len(duplicates)
    if args.strict and critical_count:
        print(f"Critical audit failures: {critical_count}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
