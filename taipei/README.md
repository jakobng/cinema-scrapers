# Taipei Cinema Scraper

Taipei-focused independent cinema scraper.

Current v1 venue coverage:

- SPOT Taipei Film House
- SPOT-Huashan
- Eslite Art House Songyan
- Wonderful Theatre
- Fuzhong 15
- Taiwan Film and Audiovisual Institute (TFAI)
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

- `Skyline Film` is treated as a recurring film club / rooftop screening series rather than a fixed cinema building.
- `Taoyuan Arts Cinema II` and `Zhongli Arts Cinema` are included because they run recurring art-house programming and fit the same non-mainstream brief, even though they sit outside Taipei city proper.

