from __future__ import annotations

from .ambassador_branch_helper import scrape_ambassador_branch

THEATER_ID = "3301d822-b385-4aa8-a9eb-aa59d58e95c9"
CINEMA_NAME = "Xinzhuang Ambassador Cinema"


def scrape_ambassador_xinzhuang():
    return scrape_ambassador_branch(theater_id=THEATER_ID, cinema_name=CINEMA_NAME)
