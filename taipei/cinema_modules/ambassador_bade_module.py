from __future__ import annotations

from .ambassador_branch_helper import scrape_ambassador_branch

THEATER_ID = "8fda9934-73d4-4c14-b1c4-386c2b81045c"
CINEMA_NAME = "Bade Ambassador Cinema"


def scrape_ambassador_bade():
    return scrape_ambassador_branch(theater_id=THEATER_ID, cinema_name=CINEMA_NAME)
