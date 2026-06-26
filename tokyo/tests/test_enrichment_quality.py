import sys
from pathlib import Path


TOKYO_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TOKYO_DIR.parent
for path in (str(TOKYO_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import audit_showtimes  # noqa: E402
import build_site  # noqa: E402
import main_scraper  # noqa: E402
from shared.ai_enrichment import AIEnrichmentClient  # noqa: E402


def test_synopsis_cache_keys_cover_title_aliases_and_ignore_japanese_cache():
    item = {
        "tmdb_id": 123,
        "movie_title": "カプリス",
        "clean_title_jp": "カプリス",
        "movie_title_jp": "カプリス",
        "movie_title_en": "Caprice",
        "movie_title_original": "Caprice",
        "synopsis": "これは日本語の紹介文です。",
    }

    keys = main_scraper._get_synopsis_cache_keys_for_item(item)

    assert "tmdb:123" in keys
    assert "title:カプリス" in keys
    assert "title_norm:カプリス" in keys
    assert "title:Caprice" in keys
    assert "title_norm:caprice" in keys

    applied = main_scraper._apply_cached_synopsis_translations(
        [item],
        {"title:カプリス": "これはまだ日本語です。"},
    )

    assert applied == 0
    assert not item.get("synopsis_en")


def test_translate_missing_synopses_rejects_non_english_ai_output(monkeypatch):
    class FakeAI:
        def health_check(self):
            return True

        def translate_synopses(self, synopses_to_translate, source_language):
            return {key: "これはまだ日本語です。" for key in synopses_to_translate}

    monkeypatch.setenv("AI_TRANSLATE_SYNOPSES", "true")
    item = {
        "movie_title": "口蹄疫から生きのびた豚",
        "synopsis": "2010年に韓国で発生した口蹄疫による養豚の大量殺処分に着想を得た作品。",
    }
    cache = {}

    updated = main_scraper.translate_missing_synopses([item], cache, FakeAI())

    assert updated is False
    assert cache == {}
    assert not item.get("synopsis_en")


def test_translate_missing_synopses_stores_translation_under_aliases(monkeypatch):
    class FakeAI:
        def health_check(self):
            return True

        def translate_synopses(self, synopses_to_translate, source_language):
            return {key: "A natural English synopsis." for key in synopses_to_translate}

    monkeypatch.setenv("AI_TRANSLATE_SYNOPSES", "true")
    item = {
        "tmdb_id": 456,
        "movie_title": "森に聴く Listen to the Forest",
        "movie_title_en": "Listen to the Forest",
        "synopsis": "人類よりはるかに長い時を生きる巨木の森を訪ねる。",
    }
    cache = {}

    updated = main_scraper.translate_missing_synopses([item], cache, FakeAI())

    assert updated is True
    assert item["synopsis_en"] == "A natural English synopsis."
    assert cache["tmdb:456"] == "A natural English synopsis."
    assert cache["title:森に聴く Listen to the Forest"] == "A natural English synopsis."
    assert cache["title:Listen to the Forest"] == "A natural English synopsis."


def test_shared_translate_synopses_batches_json_results(monkeypatch):
    class FakeAI(AIEnrichmentClient):
        def __init__(self):
            super().__init__(session=None, provider="deepseek", model="test", base_url="http://example", timeout_seconds=10)
            self.available = True

        def generate_text(self, prompt, temperature=0.2, max_tokens=2048, use_search_tool=False):
            assert "JSON array" in prompt
            return """
            [
              {"film_key": "film:a", "synopsis_en": "First translated synopsis."},
              {"film_key": "film:b", "synopsis_en": "Second translated synopsis."}
            ]
            """

    monkeypatch.setenv("AI_TRANSLATION_BATCH_SIZE", "2")
    translations = FakeAI().translate_synopses(
        {
            "film:a": "日本語の紹介文がここに入ります。",
            "film:b": "別の日本語の紹介文がここに入ります。",
        },
        source_language="Japanese",
    )

    assert translations == {
        "film:a": "First translated synopsis.",
        "film:b": "Second translated synopsis.",
    }


def test_letterboxd_urls_are_exact_tmdb_urls_only():
    rows = [
        {"tmdb_id": "987", "letterboxd_url": "https://letterboxd.com/film/wrong/"},
        {"movie_title": "特集上映", "letterboxd_url": "https://letterboxd.com/search/foo/"},
    ]

    main_scraper._apply_letterboxd_urls(rows)

    assert rows[0]["letterboxd_url"] == "https://letterboxd.com/tmdb/987/"
    assert "letterboxd_url" not in rows[1]


def test_build_slim_preserves_synopsis_en_and_exact_letterboxd_url():
    showings = [
        {
            "cinema_name": "テストシネマ",
            "movie_title": "カプリス",
            "movie_title_en": "Caprice",
            "date_text": "2026-06-20",
            "showtime": "12:00",
            "tmdb_id": 987,
            "synopsis": "日本語の紹介文。",
            "synopsis_en": "An English synopsis.",
            "letterboxd_url": "https://letterboxd.com/tmdb/987/",
        }
    ]

    films, cinemas = build_site.aggregate(showings)
    slim = build_site.build_slim(films, cinemas, "2026-06-20T00:00:00+09:00")
    film = slim["films"]["t987"]

    assert film["synopsis_en"] == "An English synopsis."
    assert film["letterboxd_url"] == "https://letterboxd.com/tmdb/987/"


def test_audit_frontend_quality_flags_bad_english_and_bad_letterboxd():
    rows = [
        {
            "movie_title": "カプリス",
            "tmdb_id": 987,
            "date_text": "2026-06-20",
            "synopsis_en": "これは日本語です。",
            "letterboxd_url": "https://letterboxd.com/tmdb/123/",
        },
        {
            "movie_title": "中編プログラム A",
            "program_title": "特集",
            "date_text": "2026-06-20",
            "synopsis": "Program row without TMDB is allowed.",
        },
    ]

    issues = audit_showtimes.print_frontend_quality(rows, today="2026-06-20")

    assert issues["english_japanese"] == [rows[0]]
    assert issues["bad_synopsis_en"] == [rows[0]]
    assert issues["invalid_letterboxd"] == [rows[0]]
    assert issues["missing_tmdb"] == []
