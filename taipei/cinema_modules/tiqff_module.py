from __future__ import annotations

from .opentix_organizer_helper import scrape_opentix_organizer

ORGANIZER_ID = "1544892925691940865"
CINEMA_NAME = "Taiwan International Queer Film Festival"


def scrape_tiqff():
    return scrape_opentix_organizer(
        organizer_id=ORGANIZER_ID,
        cinema_name=CINEMA_NAME,
    )
