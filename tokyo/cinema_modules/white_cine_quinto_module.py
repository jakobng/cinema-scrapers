from __future__ import annotations

from typing import Dict, List

from cinema_modules.cine_quinto_common import scrape_cine_quinto_weekly_schedule

CINEMA_NAME = "ホワイト シネクイント"
LISTING_URL = "https://www.cinequinto.com/white/movie/"
TICKET_URL = "https://www.cinequinto.com/white/ticket/"


def scrape_white_cine_quinto(max_days: int = 7) -> List[Dict]:
    return scrape_cine_quinto_weekly_schedule(
        listing_url=LISTING_URL,
        cinema_name=CINEMA_NAME,
        ticket_url=TICKET_URL,
    )


if __name__ == "__main__":
    rows = scrape_white_cine_quinto()
    print(f"Collected {len(rows)} rows.")
