"""Fast, offline unit tests for clean_title_for_tmdb and the null-cache reset.

These don't hit the network — they lock in the decoration-stripping behaviour that
lets the nightly TMDB pass resolve posters + Letterboxd links for re-releases and
JP-titled classics, and guard against over-stripping good titles.

Run: python -m pytest tokyo/tests/test_title_cleaning.py
 or: python tokyo/tests/test_title_cleaning.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_scraper as m  # noqa: E402


# (raw scraped title -> expected cleaned query) for titles that SHOULD now resolve.
SHOULD_CLEAN = {
    "字幕版】プラダを着た悪魔": "プラダを着た悪魔",
    "字幕版】『プロジェクト・ヘイル・メアリー": "プロジェクト・ヘイル・メアリー",
    "【吹替】マーズ・エクスプレス": "マーズ・エクスプレス",
    "ノスタルジア 4K修復版": "ノスタルジア",
    "暗殺の森 4K修復版": "暗殺の森",
    "乱 4Kデジタル修復版": "乱",
    "プッシャー修復版": "プッシャー",
    "『犬神家の一族』４Ｋデジタル修復版": "犬神家の一族",
    "『蘇える金狼』４Ｋデジタル修復版": "蘇える金狼",
    "台北ストーリー 4Kデジタル修復版": "台北ストーリー",
    "トニー滝谷 ４Ｋリマスター版": "トニー滝谷",
    "何食わぬ顔（long version）": "何食わぬ顔",
    "『カラオケ行こ！』": "カラオケ行こ！",
    # A 『…』 wrap with the restoration suffix OUTSIDE the brackets — needs the
    # unwrap and the suffix strip to both fire (iterated cleaning).
    "『サムライ 4Kレストア』": "サムライ",
    "『戦国自衛隊』４Ｋデジタル修復版": "戦国自衛隊",
    # Anniversary "特別版" (not 記念版) suffix.
    "花様年華 25周年特別版": "花様年華",
    # Trailing re-release year annotation.
    "サムライ（1967）": "サムライ",
    "罠(1949)": "罠",
    # Leading festival-series 【…】 prefix with no decoration keyword inside.
    "【ミケランジェロ・フランマルティーノの驚くべき世界】四つのいのち": "四つのいのち",
    "【フェリーニ特集】道": "道",
}

# Titles that must pass through UNCHANGED (no over-stripping of real titles).
SHOULD_KEEP = [
    "秒速5センチメートル",
    "PERFECT DAYS",
    "ドライブ・マイ・カー",
    "君たちはどう生きるか",
    "4分間のピアニスト",  # leading "4" must not be eaten as a "4K"/numbering artifact
]

# Multi-part / event titles with internal brackets must not be mangled.
SHOULD_NOT_MANGLE = [
    "『歌舞伎役者 片岡仁左衛門』「登仙の巻」",
]


def test_decorations_are_stripped():
    for raw, expected in SHOULD_CLEAN.items():
        assert m.clean_title_for_tmdb(raw) == expected, raw


def test_good_titles_untouched():
    for title in SHOULD_KEEP:
        assert m.clean_title_for_tmdb(title) == title, title


def test_internal_brackets_not_mangled():
    for title in SHOULD_NOT_MANGLE:
        cleaned = m.clean_title_for_tmdb(title)
        # internal quotation brackets must survive (we only unwrap whole/orphan ones)
        assert "』" in cleaned and "「" in cleaned, title


def test_never_returns_empty():
    for raw in ["4K修復版", "字幕版】", "リマスター版", "　"]:
        assert m.clean_title_for_tmdb(raw), raw  # falls back to the original, never ""


def test_reissue_detection():
    # Restorations/anniversary revivals list the RE-RELEASE year, so must be flagged
    # so the enrichment pass ignores the (wrong) listing year.
    for raw in ["『戦国自衛隊』４Ｋデジタル修復版", "花様年華 25周年特別版", "ノスタルジア 4K修復版",
                "乱 4Kデジタル修復版"]:
        assert m._is_reissue_title(raw), raw
    # Current-release films (even with a year in a paren) must NOT be flagged.
    for raw in ["PERFECT DAYS", "ドライブ・マイ・カー", "サムライ（1967）", "国宝"]:
        assert not m._is_reissue_title(raw), raw


def test_ai_title_annotation_stripped():
    cases = {
        "In the Mood for Love (25th Anniversary Special Edition)": "In the Mood for Love",
        "The Gift (4K Restored Version)": "The Gift",
        "Ran (4K Digital Restoration)": "Ran",
    }
    for raw, expected in cases.items():
        assert m._strip_ai_title_annotation(raw) == expected, raw
    # Real subtitles / parentheticals that are part of the title must survive.
    for keep in ["Blade Runner", "Le Samouraï", "Back to the Future Part II", "8½"]:
        assert m._strip_ai_title_annotation(keep) == keep, keep


def test_reset_clears_nulls_once_and_preserves_hits():
    d = tempfile.mkdtemp()
    orig_cache, orig_meta = m.TMDB_CACHE_FILE, m.TMDB_CACHE_META_FILE
    m.TMDB_CACHE_FILE = os.path.join(d, "tmdb_cache.json")
    m.TMDB_CACHE_META_FILE = os.path.join(d, "tmdb_cache_meta.json")
    try:
        cache = {
            "プラダを着た悪魔": {"tmdb_id": 12345},  # confirmed hit
            "tmdb:999": {"tmdb_id": 999},             # id-keyed hit
            "字幕版】プラダを着た悪魔": None,          # stale null
            "ノスタルジア 4K修復版": None,             # stale null
        }
        assert m.reset_stale_tmdb_nulls(cache) is True
        assert cache["プラダを着た悪魔"] and "tmdb:999" in cache  # hits preserved
        assert all(v is not None for v in cache.values())        # nulls gone
        assert json.load(open(m.TMDB_CACHE_META_FILE))["clean_title_version"] == m.CLEAN_TITLE_VERSION
        # idempotent: a second call (version already current) changes nothing
        assert m.reset_stale_tmdb_nulls(cache) is False
    finally:
        m.TMDB_CACHE_FILE, m.TMDB_CACHE_META_FILE = orig_cache, orig_meta


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc!r}")
    print("ALL PASS" if not failed else f"{failed} FAILED")
    sys.exit(1 if failed else 0)
