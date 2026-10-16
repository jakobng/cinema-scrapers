"""Official closures must expire or disappear, rather than hide later failures."""
from datetime import date
from pathlib import Path
import sys
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cinema_modules import bluestudio_module as blue, musashino_kan_module as musashino


def test_musashino_needs_both_a_current_closure_banner_and_no_current_films(monkeypatch):
    def check(markup):
        monkeypatch.setattr(musashino, "_fetch_soup", lambda _: BeautifulSoup(markup, "html.parser"))
        return musashino.current_closure_reason()
    assert check('<div class="module-hero"><h4 class="title">臨時休館のお知らせ</h4></div><p>上映中の作品はありません。</p>')
    assert check('<div class="old-news">臨時休館のお知らせ</div><p>上映中の作品はありません。</p>') is None
    assert check('<div class="module-hero"><h4 class="title">臨時休館のお知らせ</h4></div><p>上映中の作品：A Film</p>') is None
    monkeypatch.setattr(musashino, "_fetch_soup", lambda _: None)
    assert musashino.current_closure_reason() is None


def test_blue_studio_pause_expires_at_its_announced_end(monkeypatch):
    soup = BeautifulSoup('''<p>※2026/10/14（水）〜2026/11/3（火）の間は一般公開審査会場として使用するため通常上映の予定はございません。通常上映再開は2026/11/4（水）以降を予定しております。</p>''', "html.parser")
    monkeypatch.setattr(blue, "fetch_soup", lambda _: soup)
    assert blue.current_closure_reason(today=date(2026, 10, 17))
    assert blue.current_closure_reason(today=date(2026, 11, 4)) is None


def test_verified_closure_is_a_note_and_a_missing_notice_remains_a_warning(monkeypatch):
    import main_scraper
    monkeypatch.setitem(main_scraper.LIVE_CLOSURE_CHECKS, "Shinjuku Musashino-kan", lambda: "Official temporary closure")
    report = main_scraper.ScrapeReport()
    report.add("Shinjuku Musashino-kan", "SUCCESS", 0)
    assert report.print_summary() == ([], [])
    assert report.results[0]["status"] == "DARK"
    monkeypatch.setitem(main_scraper.LIVE_CLOSURE_CHECKS, "Shinjuku Musashino-kan", lambda: None)
    report = main_scraper.ScrapeReport()
    report.add("Shinjuku Musashino-kan", "SUCCESS", 0)
    assert len(report.print_summary()[1]) == 1
