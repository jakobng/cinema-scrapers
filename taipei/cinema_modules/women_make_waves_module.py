from __future__ import annotations

from .opentix_organizer_helper import scrape_opentix_organizer

ORGANIZER_ID = "1559092709744377857"
CINEMA_NAME = "Women Make Waves"


def scrape_women_make_waves():
    return scrape_opentix_organizer(
        organizer_id=ORGANIZER_ID,
        cinema_name=CINEMA_NAME,
    )
