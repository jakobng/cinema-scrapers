from __future__ import annotations

import sys
from typing import Dict, List

try:
    from cinema_modules.eiga_prefecture_module import DEFAULT_DAYS_AHEAD, scrape_eiga_prefecture
except ModuleNotFoundError:
    from eiga_prefecture_module import DEFAULT_DAYS_AHEAD, scrape_eiga_prefecture

SAITAMA_PREF_ID = "11"

EIGA_NAME_ALIASES = {
    "川越スカラ座": "川越スカラ座",
    "深谷シネマ": "深谷シネマ",
}


def scrape_eiga_saitama(days_ahead: int = DEFAULT_DAYS_AHEAD) -> List[Dict[str, str]]:
    return scrape_eiga_prefecture(
        pref_id=SAITAMA_PREF_ID,
        label="Eiga Saitama",
        aliases=EIGA_NAME_ALIASES,
        days_ahead=days_ahead,
    )


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("Testing eiga.com Saitama scraper...")
    results = scrape_eiga_saitama()
    print(f"Collected {len(results)} listings.")
