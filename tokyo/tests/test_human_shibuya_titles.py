"""TTCG's booking feed mangles titles when a detail page 404s.

It appends an event annotation and truncates the base title to fit a fixed-width
field, so one film arrives as a different record per date and none of them match
TMDB. Seen live on 2026-09-10 as 361[0911ｲﾍﾞﾝﾄ] / 361[0912ｲﾍﾞﾝﾄ] /
361[0914ｲﾍﾞﾝﾄ] and 私たちは[0913しゃべれば].

Run: python3 tokyo/tests/test_human_shibuya_titles.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cinema_modules.human_shibuya_module import (  # noqa: E402
    _repair_truncated_titles,
    _strip_booking_annotation,
)


def row(title, annotated=False, date="2026-09-11"):
    return {"movie_title": title, "_annotated": annotated, "date_text": date}


class StripAnnotationTest(unittest.TestCase):
    def test_strips_full_and_half_width_brackets(self):
        for raw, want in (
            ("地上げ屋[0911イベント]", "地上げ屋"),
            ("361[0911ｲﾍﾞﾝﾄ]", "361"),
            ("私たちは[0913しゃべれば]", "私たちは"),
            ("なにか［0914イベント］", "なにか"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_strip_booking_annotation(raw)[0], want)
                self.assertTrue(_strip_booking_annotation(raw)[1])

    def test_leaves_ordinary_titles_alone(self):
        for raw in ("フィッシュストーリー", "361 WHITE AND BLACK【アンコール上映】", "ムカデ人間 4K"):
            with self.subTest(raw=raw):
                self.assertEqual(_strip_booking_annotation(raw), (raw, False))

    def test_never_empties_a_title(self):
        # A title that is nothing but an annotation must keep something rather
        # than become "", which would render as a blank card.
        self.assertEqual(_strip_booking_annotation("[0911イベント]")[0], "[0911イベント]")
        self.assertEqual(_strip_booking_annotation(None), (None, False))


class RepairTruncatedTitlesTest(unittest.TestCase):
    def test_adopts_the_full_title_when_the_stub_is_a_prefix(self):
        rows = [row("私たちは", annotated=True), row("私たちは、ちょうどいい。")]
        self.assertEqual(
            [r["movie_title"] for r in _repair_truncated_titles(rows)],
            ["私たちは、ちょうどいい。", "私たちは、ちょうどいい。"],
        )

    def test_merges_one_film_split_across_dates(self):
        rows = [
            row("361", annotated=True, date="2026-09-11"),
            row("361", annotated=True, date="2026-09-12"),
            row("361", annotated=True, date="2026-09-14"),
            row("361 WHITE AND BLACK【アンコール上映】"),
        ]
        titles = {r["movie_title"] for r in _repair_truncated_titles(rows)}
        self.assertEqual(titles, {"361 WHITE AND BLACK【アンコール上映】"})

    def test_never_touches_a_title_that_was_not_annotated(self):
        # 敵 is a real film. It must not be swallowed by 敵前上陸 just because
        # one is a prefix of the other -- only stripped rows are repairable.
        rows = [row("敵"), row("敵前上陸")]
        self.assertEqual([r["movie_title"] for r in _repair_truncated_titles(rows)], ["敵", "敵前上陸"])

    def test_leaves_an_ambiguous_stub_alone(self):
        # Two candidates means we cannot know which; guessing would be worse
        # than showing the short form.
        rows = [row("愛の", annotated=True), row("愛のむきだし"), row("愛の不毛")]
        self.assertEqual(_repair_truncated_titles(rows)[0]["movie_title"], "愛の")

    def test_strips_the_internal_marker_from_every_row(self):
        rows = [row("361", annotated=True), row("フィッシュストーリー")]
        self.assertTrue(all("_annotated" not in r for r in _repair_truncated_titles(rows)))


if __name__ == "__main__":
    unittest.main()
