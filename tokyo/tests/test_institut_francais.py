"""Regression coverage for Institut francais Tokyo's current schedule markup."""

import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cinema_modules import institut_francais_module as institut  # noqa: E402


MARIE_ROZIER_HTML = """
<div class="event-box"><div class="inner"><div class="wrap">
  <div class="title-box"><p>場所</p></div>
  <div class="text-box"><p class="text-main">東京日仏学院エスパス・イマージュ</p></div>
</div></div></div>
<div class="detail-box">
  <div class="text-box">
    <h2><strong>〈プログラム A 〉</strong></h2>
    <h3>ザ・タッチ・リタッチド</h3>
    <h3><strong>上映日時：</strong></h3>
    <p><a href="https://peatix.com/event/1">9.19（土）16:00</a></p>
    <p><a href="https://peatix.com/event/2">9.20（日）14:00 上映後トーク</a></p>
  </div>
</div>
"""


AKER_MAN_HTML = """
<div class="event-box"><div class="inner">
  <div class="wrap">
    <div class="title-box"><p>日時</p></div>
    <div class="text-box"><p class="text-main">2026年10月2日（金）～24日（土）</p></div>
  </div>
  <div class="wrap">
    <div class="title-box"><p>会場</p></div>
    <div class="text-box"><p class="text-main">東京日仏学院エスパス・イマージュ</p></div>
  </div>
</div></div>
<div class="detail-box">
  <div class="text-box">
    <h2>家からの手紙 News from Home</h2>
    <p><strong>上映日時：</strong></p>
    <p>10.3（土）14:00</p>
    <p>10.17（土）15:30</p>
    <h2>向こう側から De l'Autre Cote</h2>
    <p><strong>上映日時：</strong></p>
    <p>10.11（日）11:o0</p>
  </div>
</div>
"""


def _parse(html: str, title: str, monkeypatch):
    soup = BeautifulSoup(html, "html.parser")
    monkeypatch.setattr(institut, "fetch_soup", lambda _url: soup)
    return institut.scrape_event_page("https://example.test/event", title)


def test_dotted_peatix_dates_are_parsed_and_keep_the_program(monkeypatch):
    rows = _parse(MARIE_ROZIER_HTML, "マリー・ロジエ特集", monkeypatch)

    assert [(row["date_text"], row["showtime"]) for row in rows] == [
        ("2026-09-19", "16:00"),
        ("2026-09-20", "14:00"),
    ]
    assert all(row["movie_title"] == "マリー・ロジエ特集 — 〈プログラム A 〉" for row in rows)
    assert all(row["purchase_url"].startswith("https://peatix.com/") for row in rows)


def test_schedule_is_parsed_before_peatix_tickets_exist(monkeypatch):
    rows = _parse(AKER_MAN_HTML, "シャンタル・アケルマン映画祭", monkeypatch)
    found = {(row["movie_title"], row["date_text"], row["showtime"]) for row in rows}

    assert ("家からの手紙 News from Home", "2026-10-03", "14:00") in found
    assert ("家からの手紙 News from Home", "2026-10-17", "15:30") in found
    assert ("向こう側から De l'Autre Cote", "2026-10-11", "11:00") in found
    assert all(row["purchase_url"] is None for row in rows)


def test_non_tokyo_venue_is_rejected(monkeypatch):
    html = AKER_MAN_HTML.replace("東京日仏学院エスパス・イマージュ", "福岡市総合図書館 映像ホール・シネラ")
    assert _parse(html, "福岡の上映", monkeypatch) == []


def test_wordpress_api_bypasses_an_empty_cached_archive(monkeypatch):
    monkeypatch.setattr(institut, "_write_event_cache", lambda _rows: None)
    monkeypatch.setattr(
        institut,
        "fetch_event_records",
        lambda: [
            {
                "link": "https://culture.institutfrancais.jp/event/akerman",
                "title": {"rendered": "シャンタル・アケルマン映画祭"},
                "content": {"rendered": AKER_MAN_HTML},
            }
        ],
    )
    monkeypatch.setattr(
        institut,
        "fetch_soup",
        lambda _url: (_ for _ in ()).throw(AssertionError("archive fallback used")),
    )

    rows = institut.scrape_institut_francais()

    assert len(rows) == 3
    assert {row["date_text"] for row in rows} == {
        "2026-10-03",
        "2026-10-11",
        "2026-10-17",
    }


def test_checked_in_cache_survives_ci_host_block(monkeypatch, tmp_path):
    cached = [
        {
            "cinema_name": institut.CINEMA_NAME,
            "movie_title": "Cached programme",
            "date_text": "2099-10-03",
            "showtime": "14:00",
        }
    ]
    cache_path = tmp_path / "institut.json"
    cache_path.write_text(__import__("json").dumps(cached), encoding="utf-8")
    monkeypatch.setattr(institut, "CACHE_PATH", cache_path)
    monkeypatch.setattr(institut, "fetch_event_records", lambda: [])
    monkeypatch.setattr(institut, "fetch_soup", lambda _url: None)

    assert institut.scrape_institut_francais() == cached
