# Cinema Scrapers

The scraper requires a valid TMDB API key supplied via the `TMDB_API_KEY` environment variable.

## Running locally

1. Obtain a new TMDB API key from your TMDB account dashboard. Revoke any key that has been
   checked into version control to prevent further exposure.
2. Export the key in your shell session before running the scraper:

   ```bash
   export TMDB_API_KEY="<your-new-key>"
   python main_scraper.py
   ```

   On Windows PowerShell use:

   ```powershell
   $env:TMDB_API_KEY = "<your-new-key>"
   python main_scraper.py
   ```

   Avoid committing the key to the repository—store it only in secure secret managers or
   environment variable stores.

## GitHub Actions

The provided `scrape_showtimes.yml` workflow already expects `TMDB_API_KEY` to be
configured as an Actions secret. Add the rotated key in **Settings → Secrets and variables → Actions**
so that the workflow can access it securely.
