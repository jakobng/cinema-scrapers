# Taipei Cinema Scraper

Taipei-focused independent cinema scraper.

Current v1 venue coverage:

- SPOT Taipei Film House
- SPOT-Huashan
- Eslite Art House Songyan
- Wonderful Theatre
- Fuzhong 15

Deferred in the initial pass:

- Taiwan Film and Audiovisual Institute (TFAI), because the public program pages are behind Cloudflare in this environment.

## Usage

```powershell
$env:TMDB_API_KEY = "<optional>"
python main_scraper.py
```

The scraper writes output to `data/showtimes.json`.

