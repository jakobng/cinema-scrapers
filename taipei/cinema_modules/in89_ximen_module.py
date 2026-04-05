from __future__ import annotations

from .in89_branch_helper import scrape_in89_branch

THEATER_ID = "3"
CINEMA_NAME = "Taipei Ximen in89 Cinema"


def scrape_in89_ximen():
    return scrape_in89_branch(theater_id=THEATER_ID, cinema_name=CINEMA_NAME)
