import io
import sys
from pathlib import Path

import pytest


TOKYO_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TOKYO_DIR.parent
for path in (str(TOKYO_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import build_site  # noqa: E402
import main_scraper  # noqa: E402


HEADER = (
    "cinema\tlisting_title\tcandidate_tmdb_id\tverdict\t"
    "correct_tmdb_id\tevidence\n"
)


def decisions(*rows):
    stream = io.StringIO(HEADER + "".join("\t".join(row) + "\n" for row in rows))
    return main_scraper._parse_film_identity_decisions(stream)


def details(tmdb_id, title):
    return {
        "tmdb_id": tmdb_id,
        "tmdb_title_jp": title,
        "tmdb_title_en": title,
        "poster_path": f"/{tmdb_id}.jpg",
        "overview": f"{title} synopsis",
        "release_date": "1951-01-01",
    }


def test_correct_and_unknown_decisions_keep_the_candidate_without_mutation():
    item = {"cinema_name": "Cinema Vera", "movie_title": "殺人者〈1946年〉"}
    candidate = details(14638, "殺人者")
    reviewed = decisions(
        ("Cinema Vera", "殺人者〈1946年〉", "14638", "CORRECT", "", "Reviewed source"),
    )

    correct_item, correct_details = main_scraper._select_film_identity_details(
        item, candidate, reviewed, {"tmdb:14638": candidate}
    )
    unknown_item, unknown_details = main_scraper._select_film_identity_details(
        {**item, "cinema_name": "Another cinema"},
        candidate,
        reviewed,
        {"tmdb:14638": candidate},
    )

    assert correct_item == item
    assert correct_details == candidate
    assert unknown_item["cinema_name"] == "Another cinema"
    assert unknown_details == candidate
    assert "tmdb_id" not in item


def test_wrong_decision_replaces_only_with_the_reviewed_cached_record():
    item = {
        "cinema_name": "K's Cinema (ケイズシネマ)",
        "movie_title": "拳銃の報酬（1959）",
        "tmdb_id": 239000,
        "tmdb_poster_path": "/wrong.jpg",
        "movie_title_original": "The Big Operator",
        "director": "Robert Wise",
        "director_en": "Charles F. Haas",
        "runtime_min": "96",
        "runtime": 91,
    }
    wrong = details(239000, "The Big Operator")
    wrong.update(
        {
            "tmdb_title_original": "The Big Operator",
            "director": "Charles F. Haas",
            "director_en": "Charles F. Haas",
            "runtime": 91,
        }
    )
    correct = details(26983, "拳銃の報酬")
    correct.update(
        {
            "tmdb_title_original": "Odds Against Tomorrow",
            "director": "Robert Wise",
            "director_en": "Robert Wise",
            "runtime": 96,
        }
    )
    reviewed = decisions(
        (
            "K's Cinema (ケイズシネマ)",
            "拳銃の報酬（1959）",
            "239000",
            "WRONG",
            "26983",
            "K's Cinema identifies Robert Wise's 1959 film.",
        ),
    )

    selected_item, selected_details = main_scraper._select_film_identity_details(
        item, wrong, reviewed, {"tmdb:239000": wrong, "tmdb:26983": correct}
    )

    assert selected_item["tmdb_id"] == 26983
    assert "tmdb_poster_path" not in selected_item
    assert "movie_title_original" not in selected_item
    assert "director_en" not in selected_item
    assert "runtime" not in selected_item
    assert selected_item["director"] == "Robert Wise"
    assert selected_item["runtime_min"] == "96"
    assert selected_details == correct
    assert item["tmdb_id"] == 239000
    assert item["tmdb_poster_path"] == "/wrong.jpg"
    assert item["director_en"] == "Charles F. Haas"


def test_missing_replacement_record_suppresses_instead_of_falling_back():
    item = {
        "cinema_name": "Cinema Vera",
        "movie_title": "必死の逃避行",
        "tmdb_id": 252575,
    }
    wrong = details(252575, "The Terror Inside")
    reviewed = decisions(
        ("Cinema Vera", "必死の逃避行", "252575", "WRONG", "35955", "Reviewed source"),
    )

    selected_item, selected_details = main_scraper._select_film_identity_details(
        item, wrong, reviewed, {"tmdb:252575": wrong}
    )

    assert "tmdb_id" not in selected_item
    assert selected_details is None


@pytest.mark.parametrize(
    ("verdict", "correct_tmdb_id"),
    [
        ("WRONG", ""),
        ("WRONG", "314090 + 314186"),
        ("UNCERTAIN", ""),
    ],
)
def test_rejected_compound_and_uncertain_decisions_preserve_screening_but_strip_tmdb(
    verdict, correct_tmdb_id
):
    item = {
        "cinema_name": "NFAJ",
        "movie_title": "サイボーグ009／サイボーグ009 怪獣戦争",
        "date_text": "2026-08-01",
        "showtime": "18:00",
        "booking_url": "https://cinema.example/book",
        "image_url": "https://cinema.example/source-poster.jpg",
        "synopsis": "Cinema-native synopsis",
        "director": "Cinema director",
        "director_en": "Wrong TMDB director",
        "runtime_min": "96",
        "runtime": 18,
        "tmdb_id": 314186,
        "tmdb_poster_path": "/wrong.jpg",
        "tmdb_overview_jp": "Wrong synopsis",
        "letterboxd_url": "https://letterboxd.com/tmdb/314186/",
    }
    reviewed = decisions(
        (
            "NFAJ",
            item["movie_title"],
            "314186",
            verdict,
            correct_tmdb_id,
            "Reviewed source",
        ),
    )

    candidate = details(314186, "怪獣戦争")
    candidate.update({"director_en": "Wrong TMDB director", "runtime": 18})
    selected_item, selected_details = main_scraper._select_film_identity_details(
        item, candidate, reviewed, {}
    )

    assert selected_details is None
    assert selected_item["movie_title"] == item["movie_title"]
    assert selected_item["date_text"] == "2026-08-01"
    assert selected_item["showtime"] == "18:00"
    assert selected_item["booking_url"] == "https://cinema.example/book"
    assert selected_item["image_url"] == "https://cinema.example/source-poster.jpg"
    assert selected_item["synopsis"] == "Cinema-native synopsis"
    assert selected_item["director"] == "Cinema director"
    assert selected_item["runtime_min"] == "96"
    assert "director_en" not in selected_item
    assert "runtime" not in selected_item
    assert not any(key == "tmdb_id" or key.startswith("tmdb_") for key in selected_item)
    assert "letterboxd_url" not in selected_item
    assert item["tmdb_id"] == 314186


def test_decisions_are_exact_and_reject_duplicate_or_malformed_rows():
    reviewed = decisions(
        ("Cinema Vera", "ゴーレム", "741089", "WRONG", "107983", "Reviewed source"),
    )
    candidate = details(741089, "Golem")

    _, other_cinema = main_scraper._select_film_identity_details(
        {"cinema_name": "Another cinema", "movie_title": "ゴーレム"},
        candidate,
        reviewed,
        {"tmdb:741089": candidate},
    )
    _, other_candidate = main_scraper._select_film_identity_details(
        {"cinema_name": "Cinema Vera", "movie_title": "ゴーレム"},
        details(107983, "Golem"),
        reviewed,
        {"tmdb:107983": details(107983, "Golem")},
    )

    assert other_cinema["tmdb_id"] == 741089
    assert other_candidate["tmdb_id"] == 107983

    duplicate = io.StringIO(
        HEADER
        + "Cinema Vera\tゴーレム\t741089\tWRONG\t107983\tFirst\n"
        + "Cinema Vera\tゴーレム\t741089\tWRONG\t107983\tSecond\n"
    )
    malformed = io.StringIO(
        HEADER + "Cinema Vera\tゴーレム\t741089\tCORRECT\t107983\tBad replacement\n"
    )

    with pytest.raises(ValueError, match="duplicate"):
        main_scraper._parse_film_identity_decisions(duplicate)
    with pytest.raises(ValueError, match="CORRECT"):
        main_scraper._parse_film_identity_decisions(malformed)


def test_global_decision_survives_a_cinema_change():
    reviewed = decisions(
        ("*", "オブセッション　災愛", "1436161", "WRONG", "1339713", "Reviewed source"),
    )
    wrong = details(1436161, "Obsession")
    correct = details(1339713, "オブセッション 災愛")

    selected_item, selected_details = main_scraper._select_film_identity_details(
        {"cinema_name": "シネクイント", "movie_title": "オブセッション　災愛"},
        wrong,
        reviewed,
        {"tmdb:1436161": wrong, "tmdb:1339713": correct},
    )

    assert selected_item["tmdb_id"] == 1339713
    assert selected_details == correct


def test_tmdb_detail_fetch_rejects_an_invalid_replacement_id():
    class NotFoundResponse:
        status_code = 404

        def json(self):
            return {"status_code": 34, "status_message": "The resource could not be found."}

    class FakeSession:
        def get(self, *_args, **_kwargs):
            return NotFoundResponse()

    assert main_scraper._fetch_tmdb_details_by_id(999999999, FakeSession(), "key") is None


def test_suppressed_screening_survives_static_site_aggregation_without_tmdb():
    item = {
        "cinema_name": "NFAJ",
        "movie_title": "花様年華 4K + 花様年華2001",
        "date_text": "2026-08-01",
        "showtime": "18:00",
        "tmdb_id": 843,
    }
    reviewed = decisions(
        ("NFAJ", item["movie_title"], "843", "WRONG", "843 + 1430370", "Double bill"),
    )

    selected_item, selected_details = main_scraper._select_film_identity_details(
        item, details(843, "花様年華"), reviewed, {}
    )
    films, cinemas = build_site.aggregate([selected_item])

    assert selected_details is None
    assert list(films) == ["n花様年華 4K + 花様年華2001"]
    assert cinemas["NFAJ"]["showings"][0]["f"] == "n花様年華 4K + 花様年華2001"


def test_reviewed_ledger_contains_the_complete_audit_and_calibrations():
    reviewed = main_scraper.load_film_identity_decisions()

    assert len(reviewed) == 329
    assert reviewed[
        ("K's Cinema (ケイズシネマ)", "殺人者（1946）", 14638)
    ]["verdict"] == "CORRECT"
    assert reviewed[
        ("シネマヴェーラ渋谷", "怒りの河（1951）", 1346720)
    ]["correct_tmdb_id"] == "38732"
    assert reviewed[
        ("K's Cinema (ケイズシネマ)", "拳銃の報酬（1959）", 239000)
    ]["correct_tmdb_id"] == "26983"
    assert reviewed[
        ("国立映画アーカイブ", "サイボーグ009／サイボーグ009 怪獣戦争", 314186)
    ]["correct_tmdb_id"] == "314090 + 314186"
    assert reviewed[
        ("目黒シネマ", "夢の涯てまでも ディレクターズカット・", 10341)
    ]["verdict"] == "UNCERTAIN"
    assert reviewed[
        ("*", "オブセッション　災愛", 1436161)
    ]["correct_tmdb_id"] == "1339713"


def test_enrichment_routes_cached_matches_through_the_identity_gate(monkeypatch):
    title = "拳銃の報酬（1959）"
    item = {
        "cinema_name": "K's Cinema (ケイズシネマ)",
        "movie_title": title,
        "date_text": "2026-08-01",
        "showtime": "18:00",
        "tmdb_id": 239000,
        "tmdb_poster_path": "/wrong.jpg",
    }
    wrong = details(239000, "The Big Operator")
    correct = details(26983, "拳銃の報酬")
    cache = {
        title: wrong,
        "tmdb:239000": wrong,
        "tmdb:26983": correct,
    }
    reviewed = decisions(
        (
            "K's Cinema (ケイズシネマ)",
            title,
            "239000",
            "WRONG",
            "26983",
            "Reviewed source",
        ),
    )
    monkeypatch.setattr(main_scraper, "load_title_resolution_cache", lambda: {})
    monkeypatch.setattr(
        main_scraper.AIEnrichmentClient, "from_env", lambda _session: None
    )

    enriched = main_scraper.enrich_listings_with_tmdb_links(
        [item],
        cache,
        session=None,
        api_key="unused",
        identity_decisions=reviewed,
    )
    main_scraper._apply_letterboxd_urls(enriched)

    assert len(enriched) == 1
    assert enriched[0]["movie_title"] == title
    assert enriched[0]["tmdb_id"] == 26983
    assert enriched[0]["tmdb_poster_path"] == "/26983.jpg"
    assert enriched[0]["letterboxd_url"] == "https://letterboxd.com/tmdb/26983/"
