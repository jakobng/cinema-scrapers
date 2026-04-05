# Taipei Cinema Scraper

Taipei-focused independent cinema and semiregular screening scraper.

Current v1 venue coverage:

- SPOT Taipei Film House
- SPOT-Huashan
- Eslite Art House Songyan
- Wonderful Theatre
- Fuzhong 15
- Taiwan Film and Audiovisual Institute (TFAI)
- Guling Street Avant-garde Theatre
- Lightbox Photo Library
- Taipei Fine Arts Museum
- Taiwan Contemporary Culture Lab (C-LAB)
- Treasure Hill Artist Village
- Taipei Cinema Park
- Taipei Film Festival
- Women Make Waves
- Taiwan International Queer Film Festival
- Skyline Film
- Taoyuan Arts Cinema II
- Zhongli Arts Cinema

## Usage

```powershell
$env:TMDB_API_KEY = "<optional>"
python main_scraper.py
```

The scraper writes output to `data/showtimes.json`.

TFAI is sourced from the official OPENTIX organizer storefront and event pages because the main TFAI site is Cloudflare-blocked from this environment. `node` must be available for the OPENTIX payload decoder.

Additional venue notes:

- Coverage now includes selected arts venues and screening programs when they run recurring or semiregular film / moving-image events, not just dedicated cinema buildings.
- `Skyline Film` is treated as a recurring film club / rooftop screening series rather than a fixed cinema building.
- `Guling Street Avant-garde Theatre`, `Taipei Fine Arts Museum`, `C-LAB`, `Lightbox Photo Library`, and `Treasure Hill Artist Village` are included on that broader rule: they do not behave like daily cinemas, but their official event feeds are suitable for film-oriented screenings when those events are present.
- `Taipei Cinema Park` is included as a seasonal / outdoor screening source. Its official event feed is mostly non-film programming, so the scraper only emits entries when event copy explicitly indicates screenings or pop-up cinema.
- `Taipei Film Festival`, `Women Make Waves`, and `Taiwan International Queer Film Festival` are sourced from their official OPENTIX organizer storefronts. These scrapers will often be dormant outside active festival or program windows, but they are reliable sources for recurring non-mainstream screening cycles.
- `Taoyuan Arts Cinema II` and `Zhongli Arts Cinema` are included because they run recurring art-house programming and fit the same non-mainstream brief, even though they sit outside Taipei city proper.

