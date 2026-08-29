#!/usr/bin/env python3
"""Audit Tokyo showtime data for frontend-visible quality issues."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from listing_identity import visible_listing_key
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

CINEMA_SITE_FALLBACKS = {
    "Bunkamura ル・シネマ 渋谷宮下": "https://www.bunkamura.co.jp/cinema/",
    "CINEMA AMIGO": "https://cinema-amigo.com/",
    "K2 Cinema": "https://k2-cinema.com/",
    "K's Cinema (ケイズシネマ)": "https://www.ks-cinema.com/",
    "シネマート新宿": "https://www.cinemart.co.jp/theater/shinjuku/",
    "シネマヴェーラ渋谷": "https://www.cinemavera.com/",
    "シネマブルースタジオ": "http://www.art-center.jp/tokyo/bluestudio/profile.html",
    "シネスイッチ銀座": "https://cineswitch.com/",
    "テアトル新宿": "https://ttcg.jp/theatre_shinjuku/",
    "ヒューマントラストシネマ渋谷": "https://ttcg.jp/human_shibuya/",
    "ポレポレ東中野": "https://pole2.co.jp/",
    "ユーロスペース": "https://www.eurospace.co.jp/",
    "下北沢トリウッド": "https://tollywood.jp/",
    "下高井戸シネマ": "https://shimotakaidocinema.com/",
    "国立映画アーカイブ": "https://www.nfaj.go.jp/",
    "新宿武蔵野館": "https://shinjuku.musashino-k.jp/",
    "早稲田松竹": "https://wasedashochiku.co.jp/",
    "目黒シネマ": "https://www.okura-movie.co.jp/meguro_cinema/",
    "神保町シアター": "https://www.shogakukan.co.jp/jinbocho-theater/",
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
        or CINEMA_SITE_FALLBACKS.get(item.get("cinema_name") or "")
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


def contains_japanese(text: object) -> bool:
    return bool(text and any("\u3040" <= ch <= "\u30ff" or "\u3400" <= ch <= "\u9fff" for ch in str(text)))


def is_program_row(item: dict) -> bool:
    title = str(item.get("movie_title") or item.get("movie_title_jp") or "").strip()
    program_title = str(item.get("program_title") or "").strip()
    tags = " ".join(str(tag) for tag in (item.get("tags") or []))
    haystack = f"{title} {program_title} {tags}"
    return bool(
        program_title
        or "プログラム" in haystack
        or "特集" in haystack
        or "Program" in haystack
        or "programme" in haystack.lower()
    )


def expected_letterboxd_url(item: dict) -> str:
    tmdb_id = item.get("tmdb_id")
    if tmdb_id in (None, "", 0, "0"):
        return ""
    try:
        tmdb_id = int(str(tmdb_id).strip())
    except (TypeError, ValueError):
        return ""
    return f"https://letterboxd.com/tmdb/{tmdb_id}/"


def print_frontend_quality(data: list[dict], today: str | None = None) -> dict:
    future = [item for item in data if not today or str(item.get("date_text") or "") >= today]
    bad_synopsis_en = [item for item in future if contains_japanese(item.get("synopsis_en"))]
    english_japanese = [
        item for item in future
        if contains_japanese(item.get("synopsis_en") or item.get("tmdb_overview_en") or "")
    ]
    invalid_letterboxd = [
        item for item in future
        if item.get("letterboxd_url") and item.get("letterboxd_url") != expected_letterboxd_url(item)
    ]
    program_rows = [item for item in future if is_program_row(item)]
    eligible = [item for item in future if not is_program_row(item)]
    eligible_with_tmdb = [item for item in eligible if item.get("tmdb_id")]
    missing_tmdb = [item for item in eligible if not item.get("tmdb_id")]

    print("Frontend quality")
    print(f"  English-mode Japanese synopsis rows: {len(english_japanese)}")
    print(f"  synopsis_en containing Japanese: {len(bad_synopsis_en)}")
    print(f"  invalid exact Letterboxd URLs: {len(invalid_letterboxd)}")
    print(f"  program/event rows separated: {len(program_rows)}")
    print(
        "  exact Letterboxd eligible rows with TMDB: "
        f"{len(eligible_with_tmdb)}/{len(eligible)} "
        f"({(len(eligible_with_tmdb) / len(eligible) * 100) if eligible else 100:.1f}%)"
    )
    print(f"  eligible rows missing TMDB IDs: {len(missing_tmdb)}")

    return {
        "bad_synopsis_en": bad_synopsis_en,
        "english_japanese": english_japanese,
        "invalid_letterboxd": invalid_letterboxd,
        "program_rows": program_rows,
        "eligible": eligible,
        "missing_tmdb": missing_tmdb,
    }


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
    parser.add_argument("--fail-linkless", action="store_true", help="Treat current/future rows without any URL or known cinema fallback as critical")
    args = parser.parse_args()

    data_path = Path(args.data)
    data = load_json(data_path)
    future = [item for item in data if str(item.get("date_text") or "") >= args.today]

    duplicates = []
    counts = Counter(visible_listing_key(item) for item in future)
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
    frontend_issues = print_frontend_quality(data, args.today)

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

    # Only structural problems block a publish. A malformed title or a duplicated
    # row means a scraper is emitting garbage, and shipping that is worse than
    # shipping nothing. Quality problems degrade a single film's page, so they are
    # reported and never gate the run — one bad row must not cost every other
    # showing its data commit, website sync and Instagram post. The scraper drops
    # the offending field before writing (_sanitize_cosmetic_fields), so a non-zero
    # count here means that repair missed a case, not that bad data was published.
    critical_count = len(malformed) + len(duplicates)
    if args.fail_linkless:
        critical_count += len(linkless)
    quality_count = (
        len(frontend_issues["bad_synopsis_en"])
        + len(frontend_issues["english_japanese"])
        + len(frontend_issues["invalid_letterboxd"])
    )
    if quality_count:
        print(f"Quality warnings (non-blocking): {quality_count}", file=sys.stderr)
    if args.strict and critical_count:
        print(f"Critical audit failures: {critical_count}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
