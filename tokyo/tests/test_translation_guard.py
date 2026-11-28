"""Regressions from the 27 Oct - 8 Nov 2026 silent translation outage.

The DeepSeek balance ran out. Every run got HTTP 402, translated nothing, and
still passed, while cinematokyo.com showed Japanese titles and synopses in
English mode. The audit reported 0 problems because it only looked inside
English fields, never at the Japanese fallback the page actually shows.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

TOKYO = Path(__file__).resolve().parents[1]
for path in (str(TOKYO), str(TOKYO.parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

import audit_showtimes  # noqa: E402
import main_scraper  # noqa: E402
import publication_health  # noqa: E402
from shared import ai_enrichment  # noqa: E402
from shared.ai_enrichment import AIEnrichmentClient  # noqa: E402

INSUFFICIENT_BALANCE = (
    '{"error":{"message":"Insufficient Balance (request_id: x)",'
    '"type":"insufficient_balance_error","param":null,"code":"invalid_request_error"}}'
)


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class CountingSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return self.response


def deepseek_client(session):
    client = AIEnrichmentClient(
        session=session, provider="deepseek", model="deepseek-v4-flash",
        base_url="https://api.deepseek.com", timeout_seconds=10,
    )
    client.api_key = "test-key"
    return client


def test_insufficient_balance_latches_ai_off_and_is_recorded():
    ai_enrichment.reset_account_errors()
    session = CountingSession(FakeResponse(402, INSUFFICIENT_BALANCE))
    client = deepseek_client(session)

    assert client._chat_completion("prompt", 0.2, 100) == ""
    assert client._chat_completion("prompt", 0.2, 100) == ""

    # One request, not one per batch (the outage logged ~30 identical 402s a run).
    assert session.calls == 1
    assert client.available is False
    assert client.last_error_note == ai_enrichment.AI_ACCOUNT_UNAVAILABLE
    errors = ai_enrichment.account_errors()
    assert [(e["provider"], e["status"]) for e in errors] == [("deepseek", 402)]
    assert "Insufficient Balance" in errors[0]["message"]
    ai_enrichment.reset_account_errors()


def test_rejected_key_is_an_account_error_too():
    ai_enrichment.reset_account_errors()
    client = deepseek_client(CountingSession(FakeResponse(401, "invalid api key")))
    client._chat_completion("prompt", 0.2, 100)
    assert [e["status"] for e in ai_enrichment.account_errors()] == [401]
    ai_enrichment.reset_account_errors()


def test_server_errors_are_not_account_errors():
    ai_enrichment.reset_account_errors()
    client = deepseek_client(CountingSession(FakeResponse(503, "busy")))
    client._chat_completion("prompt", 0.2, 100)
    assert ai_enrichment.account_errors() == []
    assert client.last_error_note == ai_enrichment.LOCAL_AI_UNAVAILABLE


def test_failures_where_ai_never_answered_retry_on_the_next_run():
    """A run before the top-up marked 139 titles failed; the 12-hour wait then made
    the next run skip them all even though the balance had been restored."""
    just_now = datetime.now(timezone.utc).isoformat()
    for note in (ai_enrichment.LOCAL_AI_UNAVAILABLE, ai_enrichment.AI_ACCOUNT_UNAVAILABLE):
        entry = {"failed": True, "notes": note, "last_ai_attempt_at": just_now}
        assert ai_enrichment.local_ai_retry_due(entry, retry_hours=12)


def test_unhelpful_ai_answers_still_wait_before_asking_again():
    just_now = datetime.now(timezone.utc).isoformat()
    entry = {"failed": True, "notes": ai_enrichment.LOCAL_AI_NO_RESULT, "last_ai_attempt_at": just_now}
    assert not ai_enrichment.local_ai_retry_due(entry, retry_hours=12)
    old = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    assert ai_enrichment.local_ai_retry_due({**entry, "last_ai_attempt_at": old}, retry_hours=12)


def test_status_file_carries_ai_account_errors_and_check_fails(tmp_path, monkeypatch, capsys):
    rows = [{"cinema_name": "A", "date_text": "2099-01-01"}]
    issue = {"provider": "deepseek", "model": "m", "status": 402, "message": "Insufficient Balance"}
    status = publication_health.collection_status(rows, [], ai_issues=[issue, dict(issue)])
    assert status["ai_issues"] == [issue, issue]

    path = tmp_path / "scrape_status.json"
    path.write_text(json.dumps(status), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["publication_health.py", "--check-ai", "--status", str(path)])
    assert publication_health.main() == 1
    out = capsys.readouterr().out
    # Same provider and status reported once, with the action a person must take.
    assert out.count("::error") == 1
    assert "Top up the provider balance" in out


def test_check_passes_when_ai_answered(tmp_path, monkeypatch):
    path = tmp_path / "scrape_status.json"
    path.write_text(json.dumps(publication_health.collection_status([], [])), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["publication_health.py", "--check-ai", "--status", str(path)])
    assert publication_health.main() == 0


def test_main_scraper_writes_ai_errors_into_the_status_file():
    source = (TOKYO / "main_scraper.py").read_text(encoding="utf-8")
    assert "ai_issues=ai_account_errors()" in source


def test_workflow_checks_ai_after_publishing_listings():
    workflow = yaml.safe_load((TOKYO.parent / ".github/workflows/tokyo-scrape-and-post.yml").read_text())
    steps = workflow["jobs"]["scrape-and-post"]["steps"]
    names = [step["name"] for step in steps]
    check = steps[names.index("Check AI translation provider")]
    assert "publication_health.py --check-ai" in check["run"]
    assert "continue-on-error" not in check
    # Listings go out first; the AI check only turns the run red afterwards.
    assert names.index("Sync Data to Website1 Repo") < names.index("Check AI translation provider")
    assert names.index("Check AI translation provider") < names.index("Create Auto-Fix Issue")


def test_audit_counts_the_japanese_fallback_shown_in_english_mode(capsys):
    rows = [
        # Translation failed: English fields empty, the page falls back to Japanese.
        {"movie_title": "残像", "date_text": "2026-11-08", "synopsis": "ソ連の影響下にある戦後ポーランド。"},
        # Translated: nothing Japanese is shown.
        {"movie_title": "コルチャック先生", "movie_title_en": "Korczak", "date_text": "2026-11-08",
         "synopsis": "ナチス占領下のポーランドで", "synopsis_en": "In Nazi-occupied Poland"},
    ]
    issues = audit_showtimes.print_frontend_quality(rows, today="2026-11-08")

    # The old check, which only looks inside English fields, misses it entirely.
    assert issues["english_japanese"] == []
    assert issues["english_mode_japanese_synopsis"] == [rows[0]]
    assert issues["english_mode_japanese_title"] == [rows[0]]
    out = capsys.readouterr().out
    assert "English mode shows a Japanese synopsis: 1/2 films" in out
    assert "::warning title=Japanese synopses in English mode::" in out


def test_audit_stays_quiet_when_english_mode_is_english(capsys):
    rows = [{"movie_title": "コルチャック先生", "movie_title_en": "Korczak", "date_text": "2026-11-08",
             "synopsis": "ナチス占領下", "synopsis_en": "In Nazi-occupied Poland"}]
    issues = audit_showtimes.print_frontend_quality(rows, today="2026-11-08")
    assert issues["english_mode_japanese_synopsis"] == []
    assert "::warning" not in capsys.readouterr().out


def test_english_title_that_repeats_the_japanese_title_is_blanked():
    # TMDB has no English title for キオク and falls back to the original.
    assert main_scraper._english_title_or_blank(
        {"movie_title": "キオク", "movie_title_en": "キオク", "movie_title_original": "キオク"}) == ""
    # Real English titles and mixed-script titles that differ are kept.
    assert main_scraper._english_title_or_blank(
        {"movie_title": "コルチャック先生", "movie_title_en": "Korczak"}) == "Korczak"
    assert main_scraper._english_title_or_blank(
        {"movie_title": "RYUJI 竜二", "movie_title_en": "Ryuji 竜二"}) == "Ryuji 竜二"


def test_gemini_account_error_also_stops_further_requests(monkeypatch):
    ai_enrichment.reset_account_errors()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class GeminiSession(CountingSession):
        def post(self, *args, **kwargs):
            self.calls += 1
            return self.response

    session = GeminiSession(FakeResponse(403, "API key not valid"))
    client = AIEnrichmentClient(
        session=session, provider="gemini", model="gemini-3-flash-preview",
        base_url="https://generativelanguage.googleapis.com/v1beta", timeout_seconds=10,
    )
    assert client.generate_text("prompt") == ""
    assert client.generate_text("prompt") == ""
    assert session.calls == 1
    assert client.last_error_note == ai_enrichment.AI_ACCOUNT_UNAVAILABLE
    assert [e["status"] for e in ai_enrichment.account_errors()] == [403]
    ai_enrichment.reset_account_errors()
