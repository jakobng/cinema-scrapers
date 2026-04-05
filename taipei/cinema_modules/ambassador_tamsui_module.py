from __future__ import annotations

from .ambassador_branch_helper import scrape_ambassador_branch

THEATER_ID = "1e42d235-c3cf-4f75-a382-af60f67a4aad"
CINEMA_NAME = "Tamsui Ambassador Cinema"


def scrape_ambassador_tamsui():
    return scrape_ambassador_branch(theater_id=THEATER_ID, cinema_name=CINEMA_NAME)
