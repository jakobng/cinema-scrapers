from __future__ import annotations

from typing import Dict, List

from cinema_modules.cine_quinto_common import scrape_cine_quinto_weekly_schedule

CINEMA_NAME = "シネクイント"
LISTING_URL = "https://www.cinequinto.com/shibuya/movie/"
TICKET_URL = "https://www.cinequinto.com/shibuya/ticket/"


def scrape_cine_quinto(max_days: int = 7) -> List[Dict]:
    return scrape_cine_quinto_weekly_schedule(
        listing_url=LISTING_URL,
        cinema_name=CINEMA_NAME,
        ticket_url=TICKET_URL,
    )


if __name__ == "__main__":
    rows = scrape_cine_quinto()
    print(f"Collected {len(rows)} rows.")
