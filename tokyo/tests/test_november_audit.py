"""Regressions for the four issues verified on cinematokyo.com on 2026-11-04."""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

TOKYO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOKYO))
import build_site
from cinema_modules import bunkamura_module as bunkamura
from listing_identity import canonicalize_listings


@pytest.mark.parametrize("ending", ["～(終)21:30", "〜（終）21:30", " ～ 21:30", " 終了21:30"])
def test_bunkamura_does_not_publish_the_end_of_blue_heron(monkeypatch, ending):
    monkeypatch.setattr(bunkamura, "_fetch", lambda _: (
        '<div class="timetable_todays"><p class="timetable_todays_caption">'
        '[～11/5(木)]<br>10:50 / 13:30 / 15:30 / 19:45' + ending + '</p></div>'
    ))
    assert bunkamura._grab_times("/blue-heron.html") == ["10:50", "13:30", "15:30", "19:45"]


def blue_heron_rows():
    common = {"cinema_name": bunkamura.CINEMA_NAME, "date_text": "2026-11-04",
              "showtime": "19:45", "movie_title_en": "Blue Heron", "runtime_min": "91"}
    return [
        {**common, "movie_title": "Blue Heron ブルーヘロン", "year": "2026",
         "tmdb_id": 1184941, "director_en": "Sophy Romvari",
         "detail_page_url": "https://eiga.com/movie/106645/",
         "cinema_site_url": "https://www.bunkamura.co.jp/cinema_miyashita/"},
        {**common, "movie_title": "Blue Heron／ブルーヘロン", "year": "2025",
         "director": "ソフィー・ロムヴァリ",
         "detail_page_url": "https://www.bunkamura.co.jp/cinema/lineup/26_blueheron.html"},
    ]


def test_blue_heron_coalesces_using_the_official_production_year():
    rows = blue_heron_rows()
    original = copy.deepcopy(rows)
    canonical = canonicalize_listings(rows)
    assert len(canonical) == 1
    assert canonical[0]["tmdb_id"] == 1184941
    assert canonical[0]["year"] == "2025"
    assert canonicalize_listings(list(reversed(rows))) == canonical
    assert rows == original


def test_different_years_without_a_matching_physical_screening_remain_separate():
    rows = blue_heron_rows()
    rows[1]["showtime"] = "21:00"
    assert len(canonicalize_listings(rows)) == 2
    rows[1]["showtime"] = "19:45"
    rows[1]["year"] = "1999"
    assert len(canonicalize_listings(rows)) == 2


def test_subservience_uses_the_source_title_alias_and_keeps_the_booking_link():
    common = {"cinema_name": "ヒューマントラストシネマ渋谷", "date_text": "2026-11-04",
              "showtime": "19:00", "year": "2024", "runtime_min": "106"}
    rows = [
        {**common, "movie_title": "ザ・ハウスメAIド〈服従〉", "movie_title_jp": "Subservience",
         "movie_title_original": "Subservience", "original_language": "en",
         "movie_title_en": "Soumise", "tmdb_id": 1064028,
         "purchase_url": "https://ttcg-shibuya.cineticket.jp/book"},
        {**common, "movie_title": "ザ・ハウスメAIド　服従",
         "detail_page_url": "https://eiga.com/movie/106736/"},
    ]
    canonical = canonicalize_listings(rows)
    assert len(canonical) == 1
    assert canonical[0]["movie_title_en"] == "Subservience"
    assert canonical[0]["purchase_url"] == rows[0]["purchase_url"]


def test_credit_role_is_not_a_director_name_and_valid_source_credit_survives():
    row = {"movie_title": "キリコのタクト YELL", "director": "雑賀俊朗",
           "director_jp": "脚本", "director_en": "脚本"}
    fixed = canonicalize_listings([row])[0]
    assert fixed["director"] == "雑賀俊朗"
    assert fixed.get("director_jp") != "脚本"
    assert fixed.get("director_en") != "脚本"


def test_guide_pages_reselect_today_in_japan_from_current_data():
    page = build_site.render_schedule_page("Today", "Today", "today", [], {}, {}, {},
                                           "https://cinematokyo.com")
    script = next(code for code in re.findall(r"<script>(.*?)</script>", page, re.S)
                  if "selectGuideShowings" in code)
    helpers = script[script.index("const guideDateText"):script.index("const renderGuide")]
    check = helpers + '''
const assert = require('node:assert/strict');
const rows = [{date_text: '2026-11-03', showtime: '20:00'},
              {date_text: '2026-11-04', showtime: '10:50'},
              {date_text: '2026-11-04', showtime: '19:45'},
              {date_text: '2026-11-05', showtime: '20:00'}];
const today = guideDateText(new Date('2026-11-03T15:01:00Z'));
assert.equal(today, '2026-11-04');
assert.deepEqual(selectGuideShowings(rows, today, 'today'), rows.slice(1, 3));
assert.deepEqual(selectGuideShowings(rows, today, 'tonight'), rows.slice(2, 3));
assert.deepEqual(selectGuideShowings(rows, '2026-11-05', 'today'), rows.slice(3));
'''
    subprocess.run(["node", "-e", check], check=True, capture_output=True, text=True)
    assert 'cache: "no-cache"' in script
    assert 'visibilitychange' in script
