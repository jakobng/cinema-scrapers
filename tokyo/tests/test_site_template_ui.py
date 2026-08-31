import re
import unittest
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1] / "site_template" / "index.html"


class SiteTemplateUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")

    def test_recent_intro_and_schedule_links_are_removed(self):
        self.assertNotIn(
            "東京のミニシアター・名画座・インディペンデント映画館の上映時間を毎日更新。",
            self.source,
        )
        for path in ("today", "tonight", "weekend"):
            self.assertNotIn(f'href="/{path}/"', self.source)

    def test_multiday_showtime_chips_include_the_date(self):
        self.assertRegex(
            self.source,
            r'const includeDate = state\.filters\.date === "all"\s*\|\|\s*'
            r'state\.filters\.date === "next-7";',
        )

    def test_clear_filters_reapplies_the_smart_available_date(self):
        start = self.source.index('elements.clearFilters.addEventListener("click"')
        end = self.source.index("elements.viewButtons.forEach", start)
        handler = self.source[start:end]

        self.assertIn("applySmartDefaultDate(false);", handler)
        self.assertLess(
            handler.index("state.filters.date = getDefaultDateForView();"),
            handler.index("applySmartDefaultDate(false);"),
        )
        self.assertLess(
            handler.index("applySmartDefaultDate(false);"),
            handler.index("elements.dateSelect.value = state.filters.date;"),
        )

    def test_smart_date_probe_does_not_mutate_shared_filters(self):
        start = self.source.index("const presetHasResults")
        end = self.source.index('// "Smart today"', start)
        helper = self.source[start:end]

        self.assertNotIn("state.filters.date =", helper)
        self.assertIn("{ ...state.filters, date: preset }", helper)

    def test_explicit_cinema_site_url_wins_before_inference(self):
        self.assertIn("cinemaSiteUrl: item.cinema_site_url || \"\"", self.source)
        start = self.source.index("function getCinemaWebsite")
        end = self.source.index("function getShowtimeTargetUrl", start)
        helper = self.source[start:end]

        self.assertIn("showing.cinemaSiteUrl", helper)
        self.assertLess(helper.index("showing.cinemaSiteUrl"), helper.index("cinemaWebsiteOverrides"))
        self.assertLess(helper.index("showing.cinemaSiteUrl"), helper.index("const counts"))

    def test_canonical_slim_film_key_survives_normalization(self):
        self.assertIn("filmKey: filmKey", self.source)
        start = self.source.index("const getFilmKey")
        end = self.source.index("const groupByFilm", start)
        helper = self.source[start:end]

        self.assertIn("showing.filmKey", helper)
        self.assertNotIn("showing.titleDisplay", helper)

    def test_state_controls_and_results_expose_accessible_state(self):
        self.assertRegex(self.source, r'<h1>\s*<a[^>]+id="site-title"[^>]+href="/"')
        self.assertNotIn('document.querySelector("h1").addEventListener', self.source)
        self.assertIn('id="cinema-title" tabindex="-1"', self.source)
        self.assertRegex(
            self.source,
            r'id="film-results-count"[^>]+role="status"[^>]+aria-live="polite"',
        )
        self.assertGreaterEqual(self.source.count('aria-pressed="'), 4)
        self.assertGreaterEqual(
            self.source.count('button.setAttribute("aria-pressed", isActive ? "true" : "false");'),
            2,
        )
        self.assertIn("elements.cinemaTitle.focus", self.source)
        self.assertIn("returningButton.focus", self.source)

    def test_cinema_detail_retains_language_specific_film_fields(self):
        start = self.source.index("function renderCinemaShowtimes")
        end = self.source.index("function renderCinemaView", start)
        renderer = self.source[start:end]

        for assignment in (
            "titleJp: showing.titleJp",
            "titleEn: showing.titleEn",
            "directorEn: showing.directorEn",
        ):
            self.assertIn(assignment, renderer)


if __name__ == "__main__":
    unittest.main()
