import json
import os
import re
import sys

# Import the functions from main_scraper
# We need to add the directory to path
sys.path.append(os.path.abspath('london-cinema-scrapers'))
from main_scraper import clean_title_for_tmdb, build_search_queries

def test_improvements():
    test_cases = [
        "Throwback: Speed",
        "Throwback: About Time",
        "Babykino: Marty Supreme",
        "Carers & Babies: HAMNET",
        "Toddler Club: Shaun the Sheep Movie",
        "NT Live: Hamlet",
        "National Theatre Live: The Audience (2026 Encore)",
        "DOCHOUSE: COEXISTENCE, MY ASS",
        "LSFF: Can You Imagine A World?",
        "ANZ FILM FESTIVAL: PIKE RIVER",
        "RBO Live: La Traviata (2026)",
        "Zootropolis 2",
        "Power Station + director Q&A",
        "Hamnet (12A) captioned screening",
        "Exhibition on Screen: Frida Kahlo 2026 Encore",
        "Cine-Real presents: The Third Man.",
        "Avatar: Fire and Ash (3D)"
    ]

    print(f"{'ORIGINAL':<50} | {'CLEANED':<30} | {'QUERIES'}")
    print("-" * 110)

    for case in test_cases:
        cleaned = clean_title_for_tmdb(case)
        queries = build_search_queries(case)
        print(f"{case[:48]:<50} | {cleaned:<30} | {', '.join(queries)}")

if __name__ == "__main__":
    test_improvements()
