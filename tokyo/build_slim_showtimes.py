#!/usr/bin/env python3
"""Build a slim, normalized variant of showtimes.json for the website.

The full showtimes.json repeats film-level metadata (synopses, posters,
directors...) on every showing row, which makes the published file ~11 MB.
This script groups rows by film, stores shared fields once, and keeps a
per-showing override only where a row's value differs from the group's,
so the page can reconstruct each original row exactly with
``Object.assign({}, films[s.f], s)``.

The full showtimes.json remains the published source of truth (the audit
baseline and the footer download link depend on it); this output is purely
additive. Parameterized so other cities (London/Taipei/Manchester) can
reuse it once their pages support the slim shape.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from listing_identity import film_identity_key

JST = timezone(timedelta(hours=9))

# Only the fields the website page reads (normalizeShowings() and helpers
# in tokyo-cinemas.html). Everything else is dropped from the slim file.
SHOWING_FIELDS = ("cinema_name", "date_text", "showtime", "cinema_site_url")
FILM_FIELDS = (
    "movie_title",
    "movie_title_jp",
    "movie_title_en",
    "clean_title_jp",
    "movie_title_original",
    "tmdb_original_title",
    "program_title",
    "director",
    "director_en",
    "year",
    "runtime_min",
    "runtime",
    "genres",
    "genres_en",
    "tags",
    "original_language",
    "tmdb_original_language",
    "synopsis",
    "synopsis_en",
    "tmdb_overview_en",
    "tmdb_overview_jp",
    "source_language_note",
    "language_note",
    "source_audio_language",
    "source_subtitle_language",
    "audio_language",
    "subtitle_language",
    "booking_url",
    "purchase_url",
    "detail_page_url",
    "official_site",
    "vote_average",
    "tmdb_id",
    "tmdb_poster_path",
    "tmdb_backdrop_path",
    "image_url",
    "letterboxd_url",
)


def _freeze(value) -> str:
    # Counter key for possibly-unhashable values (genres lists etc.).
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _project(row: dict) -> dict:
    return {
        field: "" if row.get(field) is None else row.get(field, "")
        for field in (*SHOWING_FIELDS, *FILM_FIELDS)
    }


def validate_round_trip(rows: list[dict], slim: dict, today: str) -> None:
    expected = Counter(
        _freeze(_project(row))
        for row in rows
        if (row.get("date_text") or "") >= today
    )
    actual = Counter(
        _freeze(_project({**slim["films"].get(showing["f"], {}), **showing}))
        for showing in slim["showings"]
    )
    if actual != expected:
        raise ValueError("Slim feed round-trip mismatch")


def build_slim(rows: list[dict], today: str) -> dict:
    future_rows = [r for r in rows if (r.get("date_text") or "") >= today]

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in future_rows:
        groups[film_identity_key(row)].append(row)

    films: dict[str, dict] = {}
    showings: list[dict] = []
    for key, group in groups.items():
        film: dict = {}
        for field in FILM_FIELDS:
            counts = Counter(_freeze(r.get(field, "")) for r in group)
            mode_value = json.loads(counts.most_common(1)[0][0])
            if mode_value not in ("", None):
                film[field] = mode_value
        films[key] = film
        for row in group:
            showing = {"f": key}
            for field in SHOWING_FIELDS:
                value = row.get(field, "")
                if value not in ("", None):
                    showing[field] = value
            for field in FILM_FIELDS:
                value = row.get(field, "")
                if value is None:
                    value = ""
                if value != film.get(field, ""):
                    showing[field] = value
            showings.append(showing)

    slim = {
        "schema": 1,
        "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "films": films,
        "showings": showings,
    }
    validate_round_trip(future_rows, slim, today)
    return slim


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in", dest="src", default="data/showtimes.json")
    parser.add_argument("--out", dest="dst", default="data/showtimes_slim.json")
    parser.add_argument("--today", default=None, help="ISO date override (default: today in JST)")
    args = parser.parse_args()

    today = args.today or datetime.now(JST).strftime("%Y-%m-%d")
    rows = json.loads(Path(args.src).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        print(f"❌ {args.src} is empty or not a list; refusing to build slim file.")
        return 1

    slim = build_slim(rows, today)
    if not slim["showings"]:
        print(f"❌ No current/future showings (today={today}); refusing to build slim file.")
        return 1

    Path(args.dst).write_text(
        json.dumps(slim, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"✅ Slim showtimes: {len(slim['showings'])} showings, "
        f"{len(slim['films'])} films -> {args.dst} "
        f"({Path(args.dst).stat().st_size / 1_000_000:.1f} MB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
