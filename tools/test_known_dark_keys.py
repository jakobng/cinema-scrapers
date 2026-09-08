"""Every KNOWN_DARK key must name a scraper that is actually registered.

A key that matches nothing is a silent no-op: the venue it was meant to excuse
keeps raising a warning, and the entry sits there looking like it works. Two of
the original six were wrong this way -- "Cine-Real" against a registry that
spells it "Ciné-Real", and a Japanese cinema_name where the registry uses the
English label -- which is the same class of mismatch that made Taoyuan Arts
Cinema II look dead in the Taipei audit.

Run: python3 tools/test_known_dark_keys.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CITIES = ("london", "manchester", "tokyo", "taipei")


def read(city: str) -> str:
    return (ROOT / city / "main_scraper.py").read_text(encoding="utf-8")


def known_dark_keys(src: str) -> set[str]:
    start = src.index("KNOWN_DARK = {")
    block = src[start : src.index("}", start) + 1]
    return set(re.findall(r'^\s+"([^"]+)":', block, re.M))


def registered_names(src: str) -> set[str]:
    """Display names from the (name, func, ...) tuples in the scraper registries."""
    return set(re.findall(r'^\s+\("([^"]+)",\s*\w+_module\.', src, re.M)) | set(
        re.findall(r'^\s+\("([^"]+)",\s*\w+\.scrape', src, re.M)
    )


class KnownDarkKeysTest(unittest.TestCase):
    def test_every_key_names_a_registered_scraper(self):
        for city in CITIES:
            src = read(city)
            with self.subTest(city=city):
                orphans = known_dark_keys(src) - registered_names(src)
                self.assertEqual(
                    orphans,
                    set(),
                    f"{city}: KNOWN_DARK names no registered scraper: {sorted(orphans)}",
                )

    def test_every_city_states_a_reason(self):
        # The reason is the whole point -- an entry without one is just a mute button.
        for city in CITIES:
            src = read(city)
            start = src.index("KNOWN_DARK = {")
            block = src[start : src.index("}", start) + 1]
            with self.subTest(city=city):
                for key, reason in re.findall(r'^\s+"([^"]+)":\s*"([^"]*)"', block, re.M):
                    self.assertGreater(len(reason), 20, f"{city}/{key}: reason too thin")

    def test_the_registries_are_actually_being_found(self):
        # Guards the regexes above: if they stop matching, every other assertion
        # here passes vacuously.
        for city, least in (("london", 30), ("manchester", 5), ("tokyo", 40), ("taipei", 15)):
            with self.subTest(city=city):
                self.assertGreaterEqual(len(registered_names(read(city))), least)


if __name__ == "__main__":
    unittest.main()
