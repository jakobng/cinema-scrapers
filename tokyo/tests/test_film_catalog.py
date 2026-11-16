import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOKYO = Path(__file__).resolve().parents[1]


class FilmCatalogTests(unittest.TestCase):
    def test_published_film_url_survives_expiry_and_title_change(self):
        with tempfile.TemporaryDirectory() as scratch:
            data = Path(scratch) / "showtimes.json"
            out = Path(scratch) / "site"
            catalog = out / "data" / "film_catalog.json"
            url = "https://cinematokyo.com/film/1234567-test-film/"
            page = out / "film" / "1234567-test-film" / "index.html"
            options = [
                sys.executable, "-B", str(TOKYO / "build_site.py"),
                "--data", str(data), "--template", str(TOKYO / "site_template"),
                "--out", str(out), "--previous-film-catalog", str(catalog),
            ]
            screening = {
                "tmdb_id": 1234567,
                "movie_title": "Test Film",
                "movie_title_en": "Test Film",
                "synopsis": "Film synopsis",
                "cinema_name": "Test Cinema",
                "date_text": "2026-11-16",
                "showtime": "12:00",
                "booking_url": "https://example.com/ticket",
            }

            def build(rows, today):
                data.write_text(json.dumps(rows), encoding="utf-8")
                subprocess.run([*options, "--today", today], check=True, capture_output=True)
                return page.read_text(encoding="utf-8")

            active = build([screening], "2026-11-16")
            self.assertIn('"@type":"ScreeningEvent"', active)
            self.assertIn(screening["booking_url"], active)

            archived = build([], "2026-11-17")
            self.assertIn(f'<link rel="canonical" href="{url}">', archived)
            self.assertIn("Film synopsis", archived)
            self.assertIn("No upcoming screenings listed.", archived)
            self.assertIn("<time>2026-11-16</time>", archived)
            self.assertNotIn('"@type":"ScreeningEvent"', archived)
            self.assertNotIn(screening["booking_url"], archived)
            self.assertNotIn(url, (out / "index.html").read_text(encoding="utf-8"))
            self.assertIn(url, (out / "sitemap.xml").read_text(encoding="utf-8"))

            new_screening = {
                **screening,
                "movie_title_en": "Retitled Film",
                "date_text": "2026-11-18",
            }
            revived = build([new_screening], "2026-11-18")
            self.assertIn(f'<link rel="canonical" href="{url}">', revived)
            self.assertIn("Retitled Film", revived)
            self.assertIn('"@type":"ScreeningEvent"', revived)
            self.assertNotIn("No upcoming screenings listed.", revived)
