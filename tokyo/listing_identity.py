"""Pure listing identity transforms shared by publishing, building, and auditing."""

from __future__ import annotations

import re
import unicodedata
from functools import reduce


_EMPTY = (None, "", [], {})
_TMDB_IDENTITY_FIELDS = ("tmdb_id", "letterboxd_url")


def normalize_showtime(value) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else text


def display_title(item: dict) -> str:
    return str(
        item.get("movie_title_jp")
        or item.get("clean_title_jp")
        or item.get("movie_title")
        or ""
    ).strip()


def normalize_title(value) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def visible_listing_key(item: dict) -> tuple:
    return (
        str(item.get("cinema_name") or "").strip(),
        str(item.get("date_text") or "").strip(),
        normalize_showtime(item.get("showtime")),
        normalize_title(display_title(item)),
    )


def _has_official_action(item: dict) -> bool:
    return any(item.get(field) for field in ("booking_url", "purchase_url", "cinema_site_url"))


def _is_eiga_detail(item: dict) -> bool:
    return "eiga.com" in str(item.get("detail_page_url") or "")


def _richness(item: dict) -> tuple:
    return (
        _has_official_action(item),
        not _is_eiga_detail(item),
        bool(item.get("tmdb_id")),
        sum(value not in _EMPTY for value in item.values()),
    )


def _prefer(preferred: dict, fallback: dict) -> dict:
    inherited = {key: value for key, value in fallback.items() if value not in _EMPTY}
    explicit = {key: value for key, value in preferred.items() if value not in _EMPTY}
    return {**inherited, **explicit}


def _merge_group(group: list[dict]) -> dict:
    ordered = sorted(group, key=_richness, reverse=True)
    merged = reduce(_prefer, ordered[1:], dict(ordered[0]))
    return {**merged, "showtime": normalize_showtime(merged.get("showtime"))}


def dedupe_listings(listings: list[dict]) -> list[dict]:
    # ponytail: immutable O(n²) grouping is acceptable below 10k rows; use a
    # transient defaultdict if the feed grows beyond that ceiling.
    groups = reduce(
        lambda acc, item: {
            **acc,
            visible_listing_key(item): [*acc.get(visible_listing_key(item), []), dict(item)],
        },
        listings,
        {},
    )
    return [_merge_group(group) for group in groups.values()]


def _compatible_year(item: dict, donor: dict) -> bool:
    item_year = str(item.get("year") or "").strip()
    donor_year = str(donor.get("year") or "").strip()
    return not item_year or not donor_year or item_year == donor_year


def coalesce_film_ids(listings: list[dict]) -> list[dict]:
    # ponytail: same bounded immutable grouping as dedupe_listings.
    groups = reduce(
        lambda acc, item: {
            **acc,
            normalize_title(display_title(item)): [
                *acc.get(normalize_title(display_title(item)), []),
                dict(item),
            ],
        },
        listings,
        {},
    )

    def coalesce(group: list[dict]) -> list[dict]:
        donors = {str(item.get("tmdb_id")): item for item in group if item.get("tmdb_id")}
        donor = next(iter(donors.values())) if len(donors) == 1 else None
        return [
            {
                **item,
                **(
                    {
                        field: donor.get(field)
                        for field in _TMDB_IDENTITY_FIELDS
                        if donor.get(field)
                    }
                    if donor and _compatible_year(item, donor)
                    else {}
                ),
            }
            for item in group
        ]

    return [item for group in groups.values() for item in coalesce(group)]


def canonicalize_listings(listings: list[dict]) -> list[dict]:
    return coalesce_film_ids(dedupe_listings(listings))
