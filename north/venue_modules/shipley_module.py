# Shipley Art Gallery, Gateshead - exhibitions
# Runs on the shared Tyne & Wear Museums CMS; see _twam.py. Venue id 244.
from ._twam import scrape_twam_venue

VENUE_NAME = "Shipley Art Gallery"
VENUE_CITY = "Gateshead"
VENUE_ID = "244"


def scrape_shipley():
    return scrape_twam_venue(VENUE_ID, VENUE_NAME, VENUE_CITY)


if __name__ == "__main__":
    for r in scrape_shipley():
        print(f"{'IMG' if r['image_url'] else '---'} {str(r['start_date']):>10}..{str(r['end_date']):<10} | {r['exhibition_title'][:50]}")
