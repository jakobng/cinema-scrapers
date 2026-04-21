from __future__ import annotations

import sys
from typing import Dict, List

try:
    from cinema_modules.eiga_prefecture_module import DEFAULT_DAYS_AHEAD, scrape_eiga_prefecture
except ModuleNotFoundError:
    from eiga_prefecture_module import DEFAULT_DAYS_AHEAD, scrape_eiga_prefecture

CHIBA_PREF_ID = "12"

EIGA_NAME_ALIASES = {
    "千葉劇場": "千葉劇場",
    "キネマ旬報シアター": "キネマ旬報シアター",
}


def scrape_eiga_chiba(days_ahead: int = DEFAULT_DAYS_AHEAD) -> List[Dict[str, str]]:
    return scrape_eiga_prefecture(
        pref_id=CHIBA_PREF_ID,
        label="Eiga Chiba",
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

    print("Testing eiga.com Chiba scraper...")
    results = scrape_eiga_chiba()
    print(f"Collected {len(results)} listings.")
