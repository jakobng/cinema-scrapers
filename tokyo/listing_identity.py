"""Pure listing identity transforms shared by publishing, building, and auditing."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import reduce
from collections import defaultdict


_EMPTY = (None, "", [], {})
_TMDB_IDENTITY_FIELDS = ("tmdb_id", "letterboxd_url")
_CREDIT_ROLES = {"監督", "脚本", "監督・脚本", "製作", "原作", "出演", "撮影", "音楽", "編集",
                 "director", "screenplay", "writer", "cast"}


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


def film_identity_key(item: dict) -> str:
    tmdb_id = str(item.get("tmdb_id") or "").strip()
    title = display_title(item) or str(item.get("movie_title_en") or "").strip()
    return f"t{tmdb_id}" if tmdb_id and tmdb_id != "0" \
        else "n" + (normalize_title(title) or title)


def visible_listing_key(item: dict) -> tuple:
    return (
        str(item.get("cinema_name") or "").strip(),
        str(item.get("date_text") or "").strip(),
        normalize_showtime(item.get("showtime")),
        film_identity_key(item),
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


def _preference_key(item: dict) -> tuple:
    return (
        _richness(item),
        json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
    )


def _prefer(preferred: dict, fallback: dict) -> dict:
    inherited = {key: value for key, value in fallback.items() if value not in _EMPTY}
    explicit = {key: value for key, value in preferred.items() if value not in _EMPTY}
    return {**inherited, **explicit}


def _merge_group(group: list[dict]) -> dict:
    ordered = sorted(group, key=_preference_key, reverse=True)
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
    same_year = not item_year or not donor_year or item_year == donor_year
    # A festival/production year can differ from a local release year. Only
    # reconcile that conflict with the same runtime AND physical screening.
    same_screening = all(item.get(field) and item.get(field) == donor.get(field)
                         for field in ("cinema_name", "date_text", "showtime"))
    runtime = str(item.get("runtime_min") or item.get("runtime") or "")
    donor_runtime = str(donor.get("runtime_min") or donor.get("runtime") or "")
    adjacent_year = (item_year.isdigit() and donor_year.isdigit()
                     and abs(int(item_year) - int(donor_year)) == 1)
    return same_year or bool(adjacent_year and same_screening and runtime
                             and runtime == donor_runtime)


def _title_aliases(item: dict) -> set[str]:
    return {normalize_title(item.get(field)) for field in (
        "movie_title", "movie_title_jp", "clean_title_jp", "movie_title_en",
        "movie_title_original",
    ) if item.get(field)}


def coalesce_film_ids(listings: list[dict]) -> list[dict]:
    aliases = defaultdict(list)
    for item in listings:
        if item.get("tmdb_id"):
            for alias in _title_aliases(item):
                aliases[alias].append(item)

    def coalesce(item: dict) -> dict:
        donors = [donor for alias in _title_aliases(item) for donor in aliases[alias]
                  if _compatible_year(item, donor)]
        donor_ids = {str(item.get("tmdb_id")) for item in donors}
        donor = max(donors, key=_preference_key) if len(donor_ids) == 1 else None
        return {**item, **({field: donor[field] for field in _TMDB_IDENTITY_FIELDS
                           if donor.get(field)} if donor else {})}

    return [coalesce(item) for item in listings]


def _clean_credits(item: dict) -> dict:
    return {**item, **{
        field: "" for field in ("director", "director_jp", "director_en")
        if str(item.get(field) or "").strip().casefold() in _CREDIT_ROLES
    }}


def _coalesce_film_metadata(listings: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for item in listings:
        groups[film_identity_key(item)].append(item)

    def metadata(group):
        years = [item for item in group if item.get("year")]
        # Prefer the cinema's production information to an aggregator's local
        # release year. Apply it to every row so card order cannot change it.
        year_source = max(years, key=lambda item: (
            not _is_eiga_detail(item), _preference_key(item)
        )) if years else {}
        originals = [item["movie_title_original"] for item in group
                     if item.get("original_language") == "en"
                     and str(item.get("movie_title_original") or "").isascii()
                     and normalize_title(item.get("movie_title_original"))
                     == normalize_title(display_title(item))]
        return {**({"year": year_source["year"]} if year_source else {}),
                **({"movie_title_en": sorted(set(originals))[0]} if originals else {})}

    return [{**item, **fields} for group in groups.values()
            for fields in (metadata(group),) for item in group]


def canonicalize_listings(listings: list[dict]) -> list[dict]:
    return dedupe_listings(_coalesce_film_metadata(coalesce_film_ids([
        _clean_credits(item) for item in listings
    ])))
