from __future__ import annotations

from .ambassador_branch_helper import scrape_ambassador_branch

THEATER_ID = "453b2966-f7c2-44a9-b2eb-687493855d0e"
CINEMA_NAME = "Taipei Changchun Ambassador Cinema"


def scrape_ambassador_changchun():
    return scrape_ambassador_branch(theater_id=THEATER_ID, cinema_name=CINEMA_NAME)
