# Taipei Cinema Scraper

Taipei-focused independent cinema scraper.

Current v1 venue coverage:

- SPOT Taipei Film House
- SPOT-Huashan
- Eslite Art House Songyan
- Wonderful Theatre
- Fuzhong 15
- Taiwan Film and Audiovisual Institute (TFAI)

## Usage

```powershell
$env:TMDB_API_KEY = "<optional>"
python main_scraper.py
```

The scraper writes output to `data/showtimes.json`.

TFAI is sourced from the official OPENTIX organizer storefront and event pages because the main TFAI site is Cloudflare-blocked from this environment. `node` must be available for the OPENTIX payload decoder.

