# Hatton Gallery, Newcastle University - exhibitions
# Runs on the shared Tyne & Wear Museums CMS; see _twam.py. Venue id 241.
from ._twam import scrape_twam_venue

VENUE_NAME = "Hatton Gallery"
VENUE_CITY = "Newcastle"
VENUE_ID = "241"


def scrape_hatton():
    return scrape_twam_venue(VENUE_ID, VENUE_NAME, VENUE_CITY)


if __name__ == "__main__":
    for r in scrape_hatton():
        print(f"{'IMG' if r['image_url'] else '---'} {str(r['start_date']):>10}..{str(r['end_date']):<10} | {r['exhibition_title'][:50]}")
