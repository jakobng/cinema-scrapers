from __future__ import annotations

from .opentix_organizer_helper import scrape_opentix_organizer

ORGANIZER_ID = "1419922383411732480"
CINEMA_NAME = "Taipei Film Festival"


def scrape_taipei_film_festival():
    return scrape_opentix_organizer(
        organizer_id=ORGANIZER_ID,
        cinema_name=CINEMA_NAME,
    )
