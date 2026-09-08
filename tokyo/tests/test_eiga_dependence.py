"""The check that would have caught kino cinema Minatomirai.

A venue can look completely healthy while its dedicated scraper is dead, because
the Eiga.com aggregators quietly cover the same cinemas. Per-cinema row counts
cannot see that; this can.
"""
import collections
import io
import unittest
from pathlib import Path

SCRAPER = Path(__file__).resolve().parents[1] / "main_scraper.py"


def _load_report_fn():
    """Exec just the reporting function -- importing main_scraper pulls in the world."""
    src = SCRAPER.read_text(encoding="utf-8")
    start = src.index("def report_eiga_dependence")
    end = src.index("def _title_similarity")
    ns = {"collections": collections}
    exec(src[start:end], ns)
    return ns["report_eiga_dependence"]


def row(cinema, date="2026-09-08", time="19:00", title="A Film"):
    return {"cinema_name": cinema, "date_text": date, "showtime": time, "movie_title": title}


report = _load_report_fn()


class EigaDependenceTest(unittest.TestCase):
    def test_a_venue_only_the_aggregator_supplies_is_named(self):
        # The real shape of the Minatomirai bug: the aggregator carries the venue,
        # no dedicated module emits a single row for it, and the site looks fine.
        eiga = [row("kino cinéma横浜みなとみらい") for _ in range(51)]
        legacy = [row("kino cinéma新宿"), row("kino cinéma立川髙島屋S.C.館")]
        self.assertEqual(report(eiga, legacy), ["kino cinéma横浜みなとみらい"])

    def test_a_venue_its_own_module_also_produces_is_not_named(self):
        # One row from the dedicated module is enough to clear it, even though the
        # aggregator supplies far more -- the module is demonstrably alive.
        eiga = [row("kino cinéma横浜みなとみらい") for _ in range(51)]
        legacy = [row("kino cinéma横浜みなとみらい")]
        self.assertEqual(report(eiga, legacy), [])

    def test_nothing_is_named_when_every_venue_has_its_own_scraper(self):
        self.assertEqual(report([row("目黒シネマ")], [row("目黒シネマ")]), [])

    def test_rows_without_a_cinema_name_are_ignored(self):
        self.assertEqual(report([{"date_text": "2026-09-08"}], [row("目黒シネマ")]), [])

    def test_the_report_is_wired_into_the_scrape(self):
        src = SCRAPER.read_text(encoding="utf-8")
        call = src.index("report_eiga_dependence(eiga_listings, legacy_listings)")
        merge = src.index("listings = _merge_eiga_with_legacy(eiga_listings, legacy_listings)")
        # Must run on the unmerged lists: after the merge the two sources are
        # indistinguishable and the whole signal is gone.
        self.assertLess(call, merge)


if __name__ == "__main__":
    unittest.main()
