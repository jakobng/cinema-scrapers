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
from shared.ai_enrichment import AIEnrichmentClient, extract_json_list  # noqa: E402


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


def test_japanese_in_tmdb_overview_en_is_translated_not_leaked():
    """TMDB sometimes serves Japanese in the English overview field. That text must
    be picked up as a translation source, otherwise audit_showtimes' critical
    english_japanese check has nothing to translate and the workflow stays red."""
    jp_in_en_field = {"tmdb_overview_en": "戦後の東京を舞台にした家族の再生の物語。"}
    assert main_scraper._source_synopsis_for_translation(jp_in_en_field) == (
        "戦後の東京を舞台にした家族の再生の物語。"
    )

    # A genuinely English overview must never be re-translated.
    real_english = {"tmdb_overview_en": "A story of a family set in post-war Tokyo."}
    assert main_scraper._source_synopsis_for_translation(real_english) == ""

    # The original Japanese fields still win when present.
    both = {"synopsis": "本来の日本語あらすじ。", "tmdb_overview_en": "英語の混ざった文。"}
    assert main_scraper._source_synopsis_for_translation(both) == "本来の日本語あらすじ。"


def test_japanese_tmdb_english_overview_is_demoted_not_published():
    """TMDB's en-US overview is sometimes the Japanese text. It must never survive
    into tmdb_overview_en: build_site renders that verbatim as the English synopsis
    and the audit counts it as a critical failure that blocks the whole publish."""
    japanese = {"tmdb_overview_en": "戦後の東京を舞台にした家族の再生の物語。"}
    english = {"tmdb_overview_en": "A story of a family set in post-war Tokyo."}
    already_jp = {"tmdb_overview_en": "英語欄の日本語。", "tmdb_overview_jp": "本来の日本語。"}

    assert main_scraper._demote_japanese_english_overviews([japanese, english, already_jp]) == 2

    # Demoted, but kept as a translation source rather than discarded.
    assert japanese["tmdb_overview_en"] == ""
    assert japanese["tmdb_overview_jp"] == "戦後の東京を舞台にした家族の再生の物語。"
    assert main_scraper._source_synopsis_for_translation(japanese) != ""

    assert english["tmdb_overview_en"] == "A story of a family set in post-war Tokyo."
    assert already_jp["tmdb_overview_jp"] == "本来の日本語。"  # existing JP not overwritten

    # The audit's critical check must now be clean without any AI call succeeding.
    rows = [dict(item, movie_title="X", tmdb_id=1, date_text="2026-06-20") for item in (japanese, english)]
    assert audit_showtimes.print_frontend_quality(rows, today="2026-06-20")["english_japanese"] == []


def test_demotion_runs_even_when_ai_is_unavailable(monkeypatch):
    """The publish gate must not depend on the AI provider being reachable."""
    monkeypatch.setenv("AI_TRANSLATE_SYNOPSES", "true")
    item = {"movie_title": "X", "tmdb_overview_en": "日本語のあらすじ。"}

    main_scraper.translate_missing_synopses([item], {}, None)

    assert item["tmdb_overview_en"] == ""


def test_broken_batch_json_salvages_the_intact_entries():
    """One truncated tail or one bad entry used to lose every film in the batch."""
    truncated = (
        '```json\n[\n'
        '  {"film_key": "tmdb:1", "synopsis_en": "First synopsis."},\n'
        '  {"film_key": "tmdb:2", "synopsis_en": "Second synopsis."},\n'
        '  {"film_key": "tmdb:3", "synopsis_en": "Third is cut off mid-sen'
    )
    salvaged = extract_json_list(truncated)
    assert [entry["film_key"] for entry in salvaged] == ["tmdb:1", "tmdb:2"]

    # A raw newline inside a quoted synopsis is invalid strict JSON but recoverable.
    raw_newline = '[{"film_key": "tmdb:9", "synopsis_en": "Line one.\nLine two."}]'
    assert extract_json_list(raw_newline) == [
        {"film_key": "tmdb:9", "synopsis_en": "Line one.\nLine two."}
    ]

    # Genuinely contentless replies still yield nothing.
    assert extract_json_list("I'm sorry, I cannot help with that.") == []


def test_invalid_model_400_latches_ai_off_instead_of_retrying_all_run():
    """A retired model name (deepseek-chat) 400s on every call. Latch the client off
    so it fails loudly once, rather than silently degrading the whole run."""
    class FakeResponse:
        status_code = 400
        text = '{"error":{"message":"The supported API model names are deepseek-v4-pro or deepseek-v4-flash, but you passed deepseek-chat.","type":"invalid_request_error"}}'

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse()

    session = FakeSession()
    client = AIEnrichmentClient(
        session=session, provider="deepseek", model="deepseek-chat",
        base_url="https://api.deepseek.com", timeout_seconds=10,
    )
    client.api_key = "test-key"

    assert client._chat_completion("prompt", 0.2, 100) == ""
    assert session.calls == 1
    assert client.available is False

    # Subsequent calls must short-circuit without hitting the API again.
    assert client._chat_completion("prompt", 0.2, 100) == ""
    assert session.calls == 1


def test_deepseek_default_model_is_a_live_model():
    """Guards the exact regression: the default must be a model DeepSeek still serves."""
    import os
    from shared import ai_enrichment

    for var in ("AI_MODEL", "DEEPSEEK_MODEL", "AI_BASE_URL"):
        os.environ.pop(var, None)
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    os.environ["AI_ENRICHMENT_PROVIDER"] = "deepseek"

    client = ai_enrichment.AIEnrichmentClient.from_env(session=None)
    assert client is not None
    assert client.model in {"deepseek-v4-flash", "deepseek-v4-pro"}


def test_deepseek_requests_disable_thinking_by_default():
    """DeepSeek v4 bills reasoning tokens against max_tokens. Left on, an 8-title
    batch exhausts the budget and returns empty content (finish_reason=length)."""
    captured = {}

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            captured.update(json)
            return FakeResponse()

    client = AIEnrichmentClient(
        session=FakeSession(), provider="deepseek", model="deepseek-v4-flash",
        base_url="https://api.deepseek.com", timeout_seconds=10,
    )
    client.api_key = "test-key"
    assert client._chat_completion("prompt", 0.2, 4096) == "ok"
    assert captured["thinking"] == {"type": "disabled"}

    # Other OpenAI-compatible providers must not receive the DeepSeek-only field.
    captured.clear()
    other = AIEnrichmentClient(
        session=FakeSession(), provider="openai", model="gpt-4o-mini",
        base_url="https://api.openai.com/v1", timeout_seconds=10,
    )
    other.api_key = "test-key"
    other._chat_completion("prompt", 0.2, 4096)
    assert "thinking" not in captured
