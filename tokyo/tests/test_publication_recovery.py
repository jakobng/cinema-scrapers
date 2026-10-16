"""Regressions from the September–October 2026 publication outage."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup
import yaml

TOKYO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOKYO))
sys.path.insert(0, str(TOKYO.parent))
import build_site
from cinema_modules import meguro_cinema_module as meguro
from publication_health import audit_publication, collection_status
from tools import cinema_health_monitor as monitor

NOW = datetime(2026, 10, 17, 3, tzinfo=timezone.utc)


def broad_rows():
    return [{"cinema_name": f"Cinema {index % 20}", "date_text": "2026-10-17",
             "movie_title": f"Film {index}", "showtime": "19:00"}
            for index in range(100)]


def test_warning_does_not_block_a_fresh_broad_collection():
    rows = broad_rows()
    status = collection_status(rows, [{"cinema": "One source", "status": "WARNING"}],
                               now=NOW, run_id="123")
    assert audit_publication(rows, status, now=NOW, run_id="123")["status"] == "ok"
    assert status["source_issues"][0]["cinema"] == "One source"
    assert audit_publication(rows, status, now=NOW, run_id="124")["status"] == "failed"


def test_a_recent_rebuild_cannot_hide_old_collection_or_missing_cinemas():
    rows = broad_rows()
    old = collection_status(rows, [], now=NOW - timedelta(days=23))
    assert audit_publication(rows, old, now=NOW)["status"] == "failed"
    assert audit_publication(rows, {"generated_at": NOW.isoformat()}, now=NOW)["status"] == "failed"
    fresh = collection_status(rows, [], now=NOW)
    seven_cinemas = [{**row, "cinema_name": f"Cinema {i % 7}"} for i, row in enumerate(rows)]
    assert audit_publication(seven_cinemas, fresh, now=NOW)["status"] == "failed"
    assert audit_publication(rows[:17], fresh, now=NOW)["status"] == "failed"


def test_meguro_rolls_only_the_overnight_rows_to_the_next_calendar_day(monkeypatch):
    soup = BeautifulSoup('''<div id="sakuhin_detail"><h4>
      『Secret Sunshine』(2007年/韓国/142分)
      『Poetry』(2010年/韓国/139分)
      『Burning』(2018年/韓国/148分)</h4></div>
      <div id="timetable"><p>10月17日(土)</p><table class="time_box">
      <tr><td class="time_title">Secret Sunshine</td><td class="time_type2">23:20 ～ 終1:40</td></tr>
      <tr><td class="time_title">Poetry</td><td class="time_type2">1:55 ～ 終4:15</td></tr>
      <tr><td class="time_title">Burning</td><td class="time_type2">4:30 ～ 終7:00</td></tr>
      </table></div>''', "html.parser")
    monkeypatch.setattr(meguro, "CURRENT_YEAR", 2030)
    monkeypatch.setattr(meguro, "_fetch_soup", lambda _: soup)
    rows = meguro.scrape_meguro_cinema()
    dates = {row["movie_title"]: row["date_text"] for row in rows}
    assert dates == {"Secret Sunshine": "2030-10-17", "Poetry": "2030-10-18", "Burning": "2030-10-18"}
    assert meguro._overnight_offsets(["09:00", "13:00", "11:00", "15:00"]) == [0, 0, 0, 0]
    assert [day.isoformat() for day in meguro._parse_dates_from_text("10/19(月)・10/22(木)")] == ["2030-10-19", "2030-10-22"]


@pytest.mark.parametrize("cinema", ["CINEMA AMIGO", "小田原シネマ館"])
def test_verified_nouvelle_vague_correction_is_limited_to_verified_listings(cinema):
    import main_scraper
    decisions = main_scraper.load_film_identity_decisions(TOKYO / "data/film_identity_decisions.tsv")
    correct = {"tmdb_id": 1254808, "release_date": "2025-10-08", "director_en": "Richard Linklater"}
    wrong = {"tmdb_id": 32691, "release_date": "1990-01-01"}
    selected, details = main_scraper._select_film_identity_details(
        {"cinema_name": cinema, "movie_title": "ヌーヴェルヴァーグ", "year": "2025"},
        wrong, decisions, {"tmdb:1254808": correct})
    assert selected["tmdb_id"] == 1254808
    assert selected["year"] == "2025"
    assert details["director_en"] == "Richard Linklater"
    _, original = main_scraper._select_film_identity_details(
        {"cinema_name": "Another cinema", "movie_title": "ヌーヴェルヴァーグ", "year": "1990"},
        wrong, decisions, {"tmdb:1254808": correct})
    assert original["tmdb_id"] == 32691


def test_film_pages_keep_each_cinemas_booking_link_and_the_existing_counter(tmp_path, monkeypatch):
    rows = [{"cinema_name": name, "movie_title": "A Film", "tmdb_id": 1,
             "date_text": "2030-10-17", "showtime": "19:00", "purchase_url": link}
            for name, link in [("Cinema A", "https://a.example/book"), ("Cinema B", "https://b.example/book")]]
    path = tmp_path / "showtimes.json"
    path.write_text(json.dumps(rows))
    status = collection_status(rows, [], now=NOW)
    path.with_name("scrape_status.json").write_text(json.dumps(status))
    out = tmp_path / "site"
    monkeypatch.setattr(sys, "argv", ["build_site.py", "--data", str(path), "--template",
                        str(TOKYO / "site_template"), "--out", str(out), "--today", "2030-10-17"])
    build_site.main()
    film = next((out / "film").glob("*/index.html")).read_text()
    assert 'href="https://a.example/book"' in film
    assert 'href="https://b.example/book"' in film
    pages = list(out.rglob("*.html"))
    assert all(page.read_text().count("static.cloudflareinsights.com/beacon.min.js") == 1 for page in pages)
    assert all("2026-10-17 12:00 JST" in page.read_text()
               for page in pages if page != out / "index.html")
    assert json.loads((out / "data/showtimes_slim.json").read_text())["scrape_status"]["scraped_at"] == status["scraped_at"]


def test_static_booking_links_prefer_the_cinema_to_a_generic_movie_database():
    assert build_site.showtime_url({"cinema_name": "目黒シネマ",
                                   "detail_page_url": "https://eiga.com/movie/123/"}) == "https://www.okura-movie.co.jp/meguro_cinema/"
    assert build_site.showtime_url({"cinema_name": "Cinema A", "purchase_url": "https://a.example/book",
                                   "detail_page_url": "https://eiga.com/movie/123/"}) == "https://a.example/book"


@pytest.mark.parametrize("port", [465, 587])
def test_alerts_use_the_configured_smtp_transport_and_do_not_hide_delivery_errors(monkeypatch, port):
    for name, value in {"SMTP_EMAIL": "sender@example.test", "SMTP_PASSWORD": "test-only",
                        "ALERT_RECIPIENT_EMAIL": "owner@example.test", "SMTP_PORT": str(port)}.items():
        monkeypatch.setenv(name, value)
    ssl_connection, tls_connection = MagicMock(), MagicMock()
    monkeypatch.setattr(monitor.smtplib, "SMTP_SSL", ssl_connection)
    monkeypatch.setattr(monitor.smtplib, "SMTP", tls_connection)
    monitor.send_summary_email([{"city": "tokyo", "kind": "published-listings", "status": "failed",
                                 "summary": "Listings are 23 days old."}])
    connection = ssl_connection if port == 465 else tls_connection
    server = connection.return_value.__enter__.return_value
    server.send_message.assert_called_once()
    assert "23 days" in server.send_message.call_args.args[0].get_content()
    assert server.starttls.call_count == (0 if port == 465 else 1)
    server.send_message.side_effect = OSError("delivery failed")
    with pytest.raises(OSError, match="delivery failed"):
        monitor.send_summary_email([{"status": "failed"}])


def test_workflow_publishes_valid_partial_data_then_alerts_on_the_failed_source():
    workflow = yaml.safe_load((TOKYO.parent / ".github/workflows/tokyo-scrape-and-post.yml").read_text())
    steps = workflow["jobs"]["scrape-and-post"]["steps"]
    by_name = {step["name"]: step for step in steps}
    assert by_name["Run Scraper"]["continue-on-error"] is True
    names = [step["name"] for step in steps]
    assert names.index("Commit & Push Data (Cinema Scrapers Repo)") < names.index("Report incomplete collection after saving healthy listings")
    assert by_name["Send Failure Alert Email"]["if"] == "failure()"
    assert "publication_health.py --run-id" in by_name["Validate Showtime Data"]["run"]


def test_visible_collection_notice_uses_collection_time_not_build_time():
    source = (TOKYO / "site_template/index.html").read_text()
    start = source.index("const collectionStatusText =")
    end = source.index("const renderCollectionStatus =", start)
    code = source[start:end]
    check = '''const assert = require('node:assert/strict');
const i18n = {en: {collectionUnknown: 'unknown', collectionStale: 'stale', collectedAt: 'collected ', collectionPartial: 'partial'}};
''' + code + '''
const now = Date.parse('2026-10-17T03:00:00Z');
assert.equal(collectionStatusText({generated_at: new Date(now).toISOString()}, 'en', now), 'unknown');
assert.match(collectionStatusText({scraped_at:'2026-09-23T00:00:00Z'}, 'en', now), /stale/);
assert.doesNotMatch(collectionStatusText({scraped_at:'2026-10-17T00:00:00Z'}, 'en', now), /stale/);
assert.match(collectionStatusText({scraped_at:'2026-10-17T00:00:00Z', source_issues:[{}]}, 'en', now), /partial/);
'''
    subprocess.run(["node", "-e", check], check=True, capture_output=True, text=True)
