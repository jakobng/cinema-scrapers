import copy
import json
import sys
from pathlib import Path

import pytest


TOKYO_DIR = Path(__file__).resolve().parents[1]
if str(TOKYO_DIR) not in sys.path:
    sys.path.insert(0, str(TOKYO_DIR))

import build_site  # noqa: E402
import build_slim_showtimes  # noqa: E402
from listing_identity import canonicalize_listings, visible_listing_key  # noqa: E402


def test_publish_seam_dedupes_visible_showings_and_coalesces_one_safe_tmdb_id():
    rows = [
        {
            "cinema_name": "テストシネマ",
            "movie_title": "シェルター（吹替）",
            "movie_title_jp": "シェルター",
            "date_text": "2026-08-29",
            "showtime": "9:30",
            "purchase_url": "https://cinema.example/tickets",
            "year": "2026",
        },
        {
            "cinema_name": "テストシネマ",
            "movie_title": "シェルター",
            "movie_title_jp": "シェルター",
            "date_text": "2026-08-29",
            "showtime": "09:30",
            "detail_page_url": "https://eiga.com/movie/1/",
            "tmdb_id": 123,
            "letterboxd_url": "https://letterboxd.com/tmdb/123/",
            "year": "2026",
        },
        {
            "cinema_name": "別の映画館",
            "movie_title": "シェルター",
            "movie_title_jp": "シェルター",
            "date_text": "2026-08-30",
            "showtime": "18:00",
            "year": "2026",
        },
        {
            "cinema_name": "旧作映画館",
            "movie_title": "シェルター",
            "movie_title_jp": "シェルター",
            "date_text": "2026-08-30",
            "showtime": "20:00",
            "year": "2010",
        },
    ]

    canonical = canonicalize_listings(rows)

    assert len(canonical) == 3
    assert len({visible_listing_key(item) for item in canonical}) == 3
    first = next(item for item in canonical if item["cinema_name"] == "テストシネマ")
    assert first["showtime"] == "09:30"
    assert first["purchase_url"] == "https://cinema.example/tickets"
    assert first["tmdb_id"] == 123
    assert next(item for item in canonical if item["cinema_name"] == "別の映画館")["tmdb_id"] == 123
    assert not next(item for item in canonical if item["cinema_name"] == "旧作映画館").get("tmdb_id")


def test_sitemap_omits_unverifiable_dates_and_includes_intent_pages():
    sitemap = build_site.build_sitemap(
        "https://cinematokyo.com",
        {"Cinema": "cinema"},
        {"t1": "1-film"},
        {"today": (), "tonight": (), "weekend": ()},
    )

    assert "<lastmod>" not in sitemap
    assert "<changefreq>" not in sitemap
    assert "https://cinematokyo.com/today/" in sitemap
    assert "https://cinematokyo.com/tonight/" in sitemap
    assert "https://cinematokyo.com/weekend/" in sitemap
    assert build_site.next_weekend_dates("2026-08-29") == {"2026-08-29", "2026-08-30"}
    assert build_site.next_weekend_dates("2026-08-30") == {"2026-08-30"}
    assert build_site.is_evening_showtime("18:00")
    assert not build_site.is_evening_showtime("未定")


def paprika_rows():
    return [
        {
            "cinema_name": "Morc阿佐ヶ谷",
            "cinema_site_url": "https://www.morc-asagaya.com/",
            "movie_title": "パプリカ",
            "movie_title_en": "Paprika",
            "date_text": "2026-08-30",
            "showtime": "10:00",
            "tmdb_id": 4977,
            "booking_url": "https://www.morc-asagaya.com/film/paprika",
            "letterboxd_url": "https://letterboxd.com/tmdb/4977/",
        },
        {
            "cinema_name": "Stranger (ストレンジャー)",
            "cinema_site_url": "https://stranger.jp/",
            "movie_title": "パプリカ",
            "movie_title_en": "Paprika",
            "date_text": "2026-08-30",
            "showtime": "12:00",
            "tmdb_id": 4977,
            "booking_url": "https://stranger.jp/movie/4977",
            "letterboxd_url": "https://letterboxd.com/tmdb/4977/",
        },
    ]


def test_site_build_uses_canonical_lossless_slim_for_paprika(tmp_path, monkeypatch):
    data_path = tmp_path / "showtimes.json"
    output_path = tmp_path / "site"
    data_path.write_text(json.dumps(paprika_rows(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "build_site.py",
        "--data", str(data_path),
        "--template", str(TOKYO_DIR / "site_template"),
        "--out", str(output_path),
        "--today", "2026-08-30",
    ])

    build_site.main()

    payload = json.loads(
        (output_path / "data" / "showtimes_slim.json").read_text(encoding="utf-8")
    )
    inflated = [{**payload["films"][row["f"]], **row} for row in payload["showings"]]
    by_cinema = {row["cinema_name"]: row for row in inflated}
    assert by_cinema["Morc阿佐ヶ谷"]["booking_url"] == \
        "https://www.morc-asagaya.com/film/paprika"
    assert by_cinema["Stranger (ストレンジャー)"]["booking_url"] == \
        "https://stranger.jp/movie/4977"
    assert by_cinema["Morc阿佐ヶ谷"]["cinema_site_url"] == \
        "https://www.morc-asagaya.com/"
    assert by_cinema["Stranger (ストレンジャー)"]["cinema_site_url"] == \
        "https://stranger.jp/"
    assert {row["letterboxd_url"] for row in inflated} == {
        "https://letterboxd.com/tmdb/4977/"
    }


def test_slim_round_trip_rejects_a_dropped_showing_override():
    payload = build_slim_showtimes.build_slim(paprika_rows(), "2026-08-30")
    corrupted = copy.deepcopy(payload)
    stranger = next(
        row for row in corrupted["showings"]
        if row["cinema_name"] == "Stranger (ストレンジャー)"
    )
    stranger.pop("booking_url")

    with pytest.raises(ValueError, match="round-trip"):
        build_slim_showtimes.validate_round_trip(
            paprika_rows(), corrupted, "2026-08-30"
        )


def test_static_film_page_uses_source_image_and_omits_global_details_link():
    film = {
        "movie_title": "パプリカ",
        "movie_title_en": "Paprika",
        "image_url": "https://cinema.example/paprika.jpg",
        "booking_url": "https://www.morc-asagaya.com/film/paprika",
        "_showings": [
            {"cinema_name": "Morc阿佐ヶ谷", "date_text": "2026-08-30", "showtime": "10:00"},
            {"cinema_name": "Stranger", "date_text": "2026-08-30", "showtime": "12:00"},
        ],
    }
    build_site.render_film_page.cinema_slugs = {}

    multi_cinema_html = build_site.render_film_page(
        "t4977", film, "4977-paprika", "https://cinematokyo.com", "2026-08-30"
    )
    single_cinema_html = build_site.render_film_page(
        "t4977",
        {**film, "_showings": film["_showings"][:1]},
        "4977-paprika",
        "https://cinematokyo.com",
        "2026-08-30",
    )

    assert 'src="https://cinema.example/paprika.jpg"' in multi_cinema_html
    assert 'property="og:image" content="https://cinema.example/paprika.jpg"' in multi_cinema_html
    assert "公式サイト / Details" not in multi_cinema_html
    assert "公式サイト / Details" not in single_cinema_html


def test_same_tmdb_screening_dedupes_deterministically_despite_title_variants():
    rows = [
        {
            "cinema_name": "Test Cinema",
            "movie_title": "パプリカ",
            "date_text": "2026-08-30",
            "showtime": "10:00",
            "tmdb_id": 4977,
            "booking_url": "https://cinema.example/a",
        },
        {
            "cinema_name": "Test Cinema",
            "movie_title": "Paprika",
            "date_text": "2026-08-30",
            "showtime": "10:00",
            "tmdb_id": 4977,
            "booking_url": "https://cinema.example/b",
        },
    ]

    forward = canonicalize_listings(rows)
    backward = canonicalize_listings(list(reversed(rows)))

    assert len(forward) == 1
    assert forward == backward


def test_tmdb_identity_donor_is_deterministic_for_missing_rows():
    rows = [
        {
            "cinema_name": "Cinema A",
            "movie_title": "Shared Film",
            "date_text": "2026-08-30",
            "showtime": "10:00",
            "tmdb_id": 99,
            "letterboxd_url": "https://letterboxd.com/film/a/",
        },
        {
            "cinema_name": "Cinema B",
            "movie_title": "Shared Film",
            "date_text": "2026-08-30",
            "showtime": "12:00",
            "tmdb_id": 99,
            "letterboxd_url": "https://letterboxd.com/film/b/",
        },
        {
            "cinema_name": "Cinema C",
            "movie_title": "Shared Film",
            "date_text": "2026-08-30",
            "showtime": "14:00",
        },
    ]
    identity_fields = lambda listings: {
        item["cinema_name"]: (item.get("tmdb_id"), item.get("letterboxd_url"))
        for item in canonicalize_listings(listings)
    }

    forward = identity_fields(rows)
    backward = identity_fields(list(reversed(rows)))

    assert forward == backward
    assert forward["Cinema C"] == (99, "https://letterboxd.com/film/b/")


def test_no_tmdb_punctuation_variants_share_one_film_identity():
    rows = [
        {
            "cinema_name": "Cinema A",
            "movie_title": "A Test: Film",
            "date_text": "2026-08-30",
            "showtime": "10:00",
        },
        {
            "cinema_name": "Cinema B",
            "movie_title": "A Test—Film",
            "date_text": "2026-08-31",
            "showtime": "12:00",
        },
    ]

    films, _ = build_site.aggregate(rows)
    slim = build_slim_showtimes.build_slim(rows, "2026-08-30")
    film = films["natestfilm"]
    legacy_id = "n" + (film.get("movie_title") or film.get("movie_title_jp"))

    assert set(films) == {"natestfilm"}
    assert set(slim["films"]) == {"natestfilm"}
    assert build_site.film_slug("natestfilm", film) == \
        f"a-test-film-{build_site.short_hash(legacy_id)}"


def test_prerendered_index_lists_exist_only_inside_noscript(tmp_path):
    template = tmp_path / "index.html"
    template.write_text(
        '<html><head><title>Old</title><meta name="description" content="Old">'
        '</head><body><div id="film-results-list"></div></body></html>',
        encoding="utf-8",
    )
    output = build_site.build_index(
        template,
        {"t4977": {"movie_title_jp": "パプリカ"}},
        {"Stranger": "stranger"},
        {"t4977": "4977-paprika"},
        "https://cinematokyo.com",
        "2026-08-30",
    )

    assert '<noscript><div id="seo-prerender" data-prerender="1">' in output
    assert "</div></noscript>" in output
