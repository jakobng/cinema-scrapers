import sys
from pathlib import Path


TOKYO_DIR = Path(__file__).resolve().parents[1]
if str(TOKYO_DIR) not in sys.path:
    sys.path.insert(0, str(TOKYO_DIR))

import build_site  # noqa: E402
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
