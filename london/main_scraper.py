#!/usr/bin/env python3
# main_scraper.py
# London Cinema Scraper - V1.0
# Adapted from Tokyo cinema scraper for London independent cinemas

import json
import sys
import traceback
import re
import requests
import time
import os
import difflib
import smtplib
import ssl
import unicodedata
import threading
import concurrent.futures
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path
from bs4 import BeautifulSoup

# --- All cinema scraper modules ---
from cinema_modules import (
    bfi_southbank_module,
    prince_charles_module,
    garden_cinema_module,
    nickel_module,
    barbican_module,
    genesis_module,
    ica_module,
    close_up_module,
    phoenix_cinema_module,
    castle_cinema_module,
    electric_cinema_module,
    rio_cinema_module,
    dochouse_module,
    sands_films_module,
    cine_lumiere_module,
    lexi_cinema_module,
    arthouse_crouch_end_module,
    jw3_module,
    peckhamplex_module,
    rich_mix_module,
    act_one_module,
    chiswick_cinema_module,
    cinema_in_the_arches_module,
    david_lean_module,
    regent_street_module,
    kiln_theatre_module,
    riverside_studios_module,
    # Chain scrapers (cover multiple locations each)
    curzon_chain_module,
    everyman_chain_module,
    picturehouse_chain_module,
    # Additional individual cinemas
    bfi_imax_module,
    cine_real_module,
    coldharbour_blue_module,
    olympic_studios_module,
    the_arzner_module,
)

# --- Configuration ---
DATA_DIR = "data"
OUTPUT_JSON = os.path.join(DATA_DIR, "showtimes.json")
TMDB_CACHE_FILE = os.path.join(DATA_DIR, "tmdb_cache.json")

# Ensure data directory exists
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --- Monitor & Alert System ---
class ScrapeReport:
    def __init__(self):
        self.results = []
        self.total_showings = 0

    def add(self, cinema_name, status, count, error=None):
        self.results.append({
            "cinema": cinema_name,
            "status": status,
            "count": count,
            "error": str(error) if error else None
        })
        if count:
            self.total_showings += count

    def print_summary(self):
        print("\n" + "="*50)
        print("SCRAPE HEALTH REPORT")
        print("="*50)

        failures = []
        warnings = []

        # Header
        print(f"{'STATUS':<4} | {'CINEMA':<30} | {'COUNT':<5} | {'NOTES'}")
        print("-" * 70)

        for r in self.results:
            # Logic: If SUCCESS but 0 showings, treat as WARNING
            if r['status'] == 'SUCCESS' and r['count'] == 0:
                r['status'] = 'WARNING'
                warnings.append(r)
            elif r['status'] == 'FAILURE':
                failures.append(r)

            # Console Output Icons
            icon = "[OK]"
            if r['status'] == 'WARNING': icon = "[!!]"
            if r['status'] == 'FAILURE': icon = "[XX]"

            error_msg = f"{r['error']}" if r['error'] else ""
            if r['status'] == 'WARNING' and not error_msg:
                error_msg = "0 showings found"

            print(f"{icon:<4} | {r['cinema']:<30} | {r['count']:<5} | {error_msg}")

        print("-" * 70)
        print(f"Total Showings Collected: {self.total_showings}")
        return failures, warnings

    def send_email_alert(self, failures, warnings):
        """Sends an email if things went wrong."""
        if not failures and not warnings:
            return

        # 1. Gather Credentials
        smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", 465))
        sender_email = os.environ.get("SMTP_EMAIL")
        sender_password = os.environ.get("SMTP_PASSWORD")
        recipient_email = os.environ.get("ALERT_RECIPIENT_EMAIL")

        if not (sender_email and sender_password and recipient_email):
            print("Skipping email alert: Missing SMTP credentials.")
            return

        # 2. Build Content
        subject = f"London Scraper Alert: {len(failures)} Crashes, {len(warnings)} Empty"

        body_lines = ["The London Cinema Scraper encountered issues:\n"]

        if failures:
            body_lines.append(f"CRITICAL FAILURES ({len(failures)}):")
            for f in failures:
                body_lines.append(f"- {f['cinema']}: {f['error']}")
            body_lines.append("\n")

        if warnings:
            body_lines.append(f"POTENTIAL ISSUES (0 Showings Found):")
            for w in warnings:
                body_lines.append(f"- {w['cinema']}")

        body_lines.append("\nCheck the GitHub Actions logs for full details.")

        msg = EmailMessage()
        msg.set_content("\n".join(body_lines))
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = recipient_email

        # 3. Send
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)
            print("Alert email sent successfully.")
        except Exception as e:
            print(f"Failed to send email alert: {e}")

# Initialize Global Report
report = ScrapeReport()

# --- TMDB Utilities ---

TITLE_ALIASES = {
    "zootropolis 2": "Zootopia 2",
    "zootropolis": "Zootopia",
    "fools and a flower": "Fools & A Flower",
    "untold: the retreat": "The Retreat",
    "avatar: fire and ash": "Avatar 3",
    "labyrinth": "Labyrinth (1986)",  # Force the classic
    "speed": "Speed (1994)",  # Force the classic
    # Japanese titles with English translations
    "house [hausu]": "Hausu",
    "hausu": "Hausu",  # Japanese horror film 1977
    "house hausu": "Hausu",
    # Foreign title aliases
    "la danse: le ballet de l'opera de paris": "La Danse: The Paris Opera Ballet",
}

def clean_title_for_tmdb(title: str) -> str:
    """
    Strips common suffixes/prefixes that confuse TMDB fuzzy matching.
    """
    if not title:
        return ""

    # 1. Strip explicit Event Prefixes (often separated by : or - or –)
    prefix_patterns = [
        r"^(Narrow Margin presents|In Focus|Crafty Movie Night|Member's Request|Staff Pick|Relaxed Screening|Family Screening|Preview|Premiere|UK Premiere)[:\s–-]+",
        r"^(Throwback|Babykino|Carers & Babies|Toddler Club|Club Room|Dog-Friendly|Dog-Friendly Screening|Sensory Friendly|HOH|Caption|Autism Friendly)[:\s–-]+",
        r"^(DOCHOUSE|LSFF|ANZ FILM FESTIVAL|ANZ FF|RBO Live|RBO Encore|Met Opera Live|Met Opera Encore|Exhibition on Screen|Royal Ballet|Royal Opera|Bolshoi Ballet)[:\s–-]+",
        r"^(Member's Preview|Members' Preview|Mystery Movie|Secret Movie|Surprise Movie)[:\s–-]+",
        r"^(Bar Trash|OffBeat|Pink Palace|Films For Workers|Coming Up|London Short Film Festival)[:\s–-]+",
        r"^(Phoenix Classics|Cine-Real presents|Green Screen)[:\s–-]+",
        # Additional event prefixes
        r"^(DRINK\s*&\s*DINE|Drink\s*&\s*Dine|DocFest Spotlights|Video Bazaar presents|TV Preview)[:\s–-]+",
        r"^(SCANNERS\s+INC\.?\s+PRESENTS|Scanners Inc\.? Presents|DELETED SCENES PRESENTS|Deleted Scenes Presents)[:\s–-]+",
        r"^(Holocaust Memorial Day|Lexi Seniors'? Film Club|Saturday Morning Picture Club)[:\s–-]+",
        r"^(Nostalgie|Red Flagged[^:]*presents|Queer East presents)[:\s–-]+",
        r"^An Evening with[^:]+[:\s–-]+",  # "An Evening with X: Film Title"
    ]
    cleaned = title
    for pat in prefix_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

    # 2. Strip standard rating/screening suffixes
    patterns = [
        r"4K Restor.*",                     # 4K Restore...
        r"4K Digital Remaster.*",           # 4K Digital Remaster
        r"Director's Cut",                  # Director's Cut
        r"Extended Edition",                # Extended Edition
        r"Anniversary Edition",             # Anniversary Edition
        r"Special Edition",                 # Special Edition
        r"Remastered",                      # Remastered
        r"\d+th Anniversary.*",             # 50th Anniversary...
        r"Double Bill.*",                   # Double Bill...
        r"Double Feature.*",                # Double Feature...
        r"\(\s*(U|PG|12A|12|15|15\*|18|R)\s*\)", # UK/US rating suffixes (ANYWHERE)
        r"\(\s*\d{4}\s*\)$",                # (1990)
        r"\(.*?version\)",                  # (XXX version)
        r"\[.*?\]",                         # [XXX] - e.g. [Kimi no Na wa.]
        r"(?i)\s+Encore\s*$",               # Encore screenings
        r"(?i)\s+\d{4}-\d{2,4}\s+Season\s*$", # 2025-26 Season

        # Sing-along suffixes
        r"(?i)\s+Sing[- ]?A[- ]?Long!?\s*$",  # Sing-A-Long, Sing-Along, Sing A Long
        r"(?i)\s+Sing[- ]?Along!?\s*$",

        # Noise words at end of string
        r"(?i)\b(parent and baby|carer|hard of hearing|captioned|subtitled|relaxed|autism|dementia|HOH|Babes-In-Arms)(\s+screening)?\s*$",
        r"(?i)\s+UK PREMIERE\s*$",

        # Aggressive suffix stripping for " + " or " - " (often Q&As)
        # e.g. "Power Station + director Q&A" -> "Power Station"
        r"\s(\+|–|-)\s+(intro|discussion|q\s*&\s*a|qa|panel|talk|shorts|live score|live music|director|presented by|hosted by|with|screening|recorded|cast).*$",
    ]

    for pat in patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

    # Cleanup whitespace
    cleaned = cleaned.strip()
    
    # Remove " 3D" or " 2D" at the very end
    cleaned = re.sub(r"\s(2D|3D)$", "", cleaned, flags=re.IGNORECASE)

    # If cleaning removed everything (unlikely), revert
    if not cleaned:
        return title

    return cleaned

def normalize_title_for_match(title: str) -> str:
    if not title:
        return ""
    normalized = unicodedata.normalize("NFKD", title)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def director_matches(query_director: str, tmdb_director: str) -> bool:
    q_norm = normalize_title_for_match(query_director)
    t_norm = normalize_title_for_match(tmdb_director)
    if not q_norm or not t_norm:
        return True
    if q_norm == t_norm or q_norm in t_norm or t_norm in q_norm:
        return True
    query_parts = [normalize_title_for_match(p) for p in re.split(r",|&| and |/|;", query_director)]
    tmdb_parts = [normalize_title_for_match(p) for p in re.split(r",|&| and |/|;", tmdb_director)]
    for part in query_parts:
        if part and (part in t_norm or t_norm in part):
            return True
    for part in tmdb_parts:
        if part and (part in q_norm or q_norm in part):
            return True
    return False

NON_FILM_EVENT_KEYWORDS = [
    "open mic",
    "free entry",
    "fun in the lounge",
    "quiz",
    "trivia",
    "workshop",
    "masterclass",
    "panel",
    "discussion",
    "in conversation",
    "talk",
    "live podcast",
    "book launch",
    "stand up",
    "stand-up",
    "comedy night",
    "live music",
    "dj set",
    "club night",
    "karaoke",
    "an evening with",
    "crafty movie night",
    "toddler club",
]

PROGRAM_EVENT_KEYWORDS = [
    "opening night",
    "closing night",
    "short film",
    "short films",
    "short film showcase",
    "shorts program",
    "shorts programme",
    "showcase",
    "spotlight",
    "spotlights",
    "programme",
    "program",
    "selection",
    "festival highlights",
]

PROGRAM_CONTEXT_KEYWORDS = [
    "festival",
    "lsff",
    "london short film festival",
    "anz",
    "anz film festival",
    "docfest",
    "docfest spotlights",
    "short film festival",
]

BROADCAST_BRAND_REQUIREMENTS = [
    (["nt live", "national theatre live", "national theatre live presents"], ["national theatre", "nt live"]),
    (["met opera", "met opera live", "met opera encore", "metropolitan opera"], ["met opera", "metropolitan opera"]),
    (["royal opera", "royal opera house", "royal ballet", "rbo live", "rbo encore", "roh"], ["royal opera", "royal opera house", "royal ballet", "rbo", "roh"]),
    (["bolshoi ballet"], ["bolshoi", "bolshoi ballet"]),
    (["exhibition on screen"], ["exhibition on screen"]),
    (["glyndebourne"], ["glyndebourne"]),
]

COLON_SPLIT_PREFIX_KEYWORDS = [
    "met opera",
    "met opera live",
    "met opera encore",
    "metropolitan opera",
    "royal opera",
    "royal opera house",
    "royal ballet",
    "rbo live",
    "rbo encore",
    "roh",
    "bolshoi ballet",
    "exhibition on screen",
    "docfest",
    "docfest spotlights",
    "lsff",
    "london short film festival",
    "anz film festival",
    "anz ff",
    "pink palace",
    "bar trash",
    "offbeat",
    "video bazaar presents",
    "deleted scenes presents",
    "scanners inc presents",
    "phoenix classics",
    "cine-real presents",
    "films for workers",
    "saturday morning picture club",
    "lexi seniors film club",
    "holocaust memorial day",
]

def _normalize_keyword_list(keywords):
    return [normalize_title_for_match(k) for k in keywords if k]

_NON_FILM_EVENT_KEYWORDS = _normalize_keyword_list(NON_FILM_EVENT_KEYWORDS)
_PROGRAM_EVENT_KEYWORDS = _normalize_keyword_list(PROGRAM_EVENT_KEYWORDS)
_PROGRAM_CONTEXT_KEYWORDS = _normalize_keyword_list(PROGRAM_CONTEXT_KEYWORDS)
_COLON_SPLIT_PREFIX_KEYWORDS = _normalize_keyword_list(COLON_SPLIT_PREFIX_KEYWORDS)
_BROADCAST_BRAND_REQUIREMENTS = [
    (_normalize_keyword_list(triggers), _normalize_keyword_list(required))
    for triggers, required in BROADCAST_BRAND_REQUIREMENTS
]
_BROADCAST_BRAND_TRIGGERS = sorted({t for triggers, _ in _BROADCAST_BRAND_REQUIREMENTS for t in triggers})

def _title_has_any_keyword(norm_title: str, keywords_norm) -> bool:
    return any(k in norm_title for k in keywords_norm)

def is_probable_program_event(title: str) -> bool:
    norm = normalize_title_for_match(title)
    if not norm:
        return False
    if _title_has_any_keyword(norm, _PROGRAM_EVENT_KEYWORDS):
        if _title_has_any_keyword(norm, _PROGRAM_CONTEXT_KEYWORDS):
            return True
        if "short film" in norm or "short films" in norm:
            return True
    return False

def is_probable_non_film_event(title: str) -> bool:
    norm = normalize_title_for_match(title)
    if not norm:
        return False
    return _title_has_any_keyword(norm, _NON_FILM_EVENT_KEYWORDS)

def should_skip_tmdb_enrichment(title: str):
    if is_nt_live_title(title):
        return True, "nt live listing"
    if is_probable_program_event(title):
        return True, "program or festival event"
    if is_probable_non_film_event(title):
        return True, "non-film event"
    return False, ""

def has_broadcast_brand(title: str) -> bool:
    norm = normalize_title_for_match(title)
    if not norm:
        return False
    return _title_has_any_keyword(norm, _BROADCAST_BRAND_TRIGGERS)

def is_nt_live_title(title: str) -> bool:
    norm = normalize_title_for_match(title)
    if not norm:
        return False
    return "nt live" in norm or "national theatre live" in norm

def is_nt_live_listing(item: dict) -> bool:
    if not item:
        return False
    title = item.get("movie_title") or item.get("movie_title_en") or ""
    if is_nt_live_title(title):
        return True
    url_fields = [
        item.get("detail_page_url"),
        item.get("booking_url"),
        item.get("official_site"),
    ]
    for url in url_fields:
        if not url:
            continue
        lowered = str(url).lower()
        if "nt-live" in lowered or "national-theatre-live" in lowered:
            return True
    format_tags = item.get("format_tags") or []
    if isinstance(format_tags, list):
        for tag in format_tags:
            if is_nt_live_title(str(tag)):
                return True
    return False

def get_broadcast_required_tokens(title: str):
    norm = normalize_title_for_match(title)
    if not norm:
        return []
    required = []
    for triggers, needed in _BROADCAST_BRAND_REQUIREMENTS:
        if _title_has_any_keyword(norm, triggers):
            required.extend(needed)
    return list(dict.fromkeys(required))

def passes_broadcast_guard(required_tokens, result: dict) -> bool:
    if not required_tokens:
        return True
    combined = f"{result.get('title', '')} {result.get('original_title', '')}"
    norm = normalize_title_for_match(combined)
    return _title_has_any_keyword(norm, required_tokens)

def should_split_on_colon(title: str) -> bool:
    if ":" not in title:
        return False
    prefix = title.split(":", 1)[0]
    prefix_norm = normalize_title_for_match(prefix)
    return _title_has_any_keyword(prefix_norm, _COLON_SPLIT_PREFIX_KEYWORDS)

def map_tmdb_search_result(result: dict) -> dict:
    return {
        "id": result.get("id"),
        "title": result.get("title") or "",
        "original_title": result.get("original_title") or "",
        "release_date": result.get("release_date") or "",
        "vote_count": result.get("vote_count") or 0,
        "popularity": result.get("popularity") or 0,
    }

def run_tmdb_search(session, url, params, year_param):
    resp = session.get(url, params=params, timeout=5)
    data = resp.json()
    results = data.get("results", [])
    if not results and year_param in params:
        fallback_params = params.copy()
        del fallback_params[year_param]
        resp = session.get(url, params=fallback_params, timeout=5)
        data = resp.json()
        results = data.get("results", [])
    return results

def parse_year_value(raw_year):
    if not raw_year:
        return None
    try:
        # Handle cases like "2024 / 2025" or "1999 (restored)"
        clean_y = re.search(r"\d{4}", str(raw_year))
        if clean_y:
            year = int(clean_y.group(0))
        else:
            return None
    except ValueError:
        return None
    current_year = datetime.now().year
    if 1880 <= year <= current_year + 3:
        return year
    return None

def extract_year_from_title(title: str):
    if not title:
        return None
    # Look for (YYYY) at end of string or mid-string
    for match in re.findall(r"\((\d{4})\)", title):
        year = parse_year_value(match)
        if year:
            return year
    return None

def truncate_noisy_title(title: str) -> str:
    if not title:
        return ""
    if len(title) < 80:
        return title
    # Cut off if we hit obviously non-title description text
    for keyword in ["doors", "film", "certificate", "digital", "book here", "not for the easily"]:
        match = re.search(re.escape(keyword), title, flags=re.IGNORECASE)
        if match:
            return title[:match.start()].strip()
    return title

def strip_event_prefix(title: str) -> str:
    if not title:
        return ""
    
    # Handle separators: ":", " - ", " – "
    separators = [":", " - ", " – "]
    
    # Try splitting by first separator found
    for sep in separators:
        if sep in title:
            prefix, rest = title.split(sep, 1)
            prefix_norm = normalize_title_for_match(prefix)
            
            # Known prefixes to strip
            prefix_keywords = [
                "presents", "presented by",
                "relaxed screening", "senior free matinee", "seniors free matinee",
                "philosophical screens", "deleted scenes", "scanners inc",
                "evolution of horror", "narrow margin", "pitchblack playback",
                "film quiz", "in conversation", "preview", "premiere",
                "crafty movie night", "member's request", "staff pick",
                "in focus", "club room", "babykino", "kids club"
            ]
            
            if any(k in prefix_norm for k in prefix_keywords):
                return rest.strip()
            # If prefix looks like a date/time or location, maybe strip it? (Context dependent)
            
    return title

def strip_event_suffix(title: str) -> str:
    if not title:
        return ""
    suffix_patterns = [
        r"\s*\+\s*(intro|discussion|q\s*&\s*a|qa|panel|talk|shorts|live score|live music|director|presented by|hosted by).*$",
        r"\s*-\s*.*(intro|discussion|q\s*&\s*a|qa|panel|talk|live|presented by|hosted by|with).*$",
        r"(?i)\s+Q&A\s*$",
    ]
    cleaned = title
    for pat in suffix_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned

def build_search_queries(title: str):
    if not title:
        return []

    queries = []
    raw_base = truncate_noisy_title(title.strip())
    if has_broadcast_brand(raw_base):
        queries.append(raw_base)

    base = strip_event_prefix(raw_base)
    base = strip_event_suffix(base)

    # Handle square brackets e.g. "Your Name [Kimi no Na wa.]"
    # We want to search "Your Name" AND "Kimi no Na wa"
    bracket_matches = re.findall(r"\[([^\]]+)\]", base)

    cleaned_base = clean_title_for_tmdb(base)

    # Check aliases FIRST for the full original title (including brackets)
    # This handles cases like "House [Hausu]" -> "Hausu"
    full_lower = base.lower().strip()
    if full_lower in TITLE_ALIASES:
        queries.append(TITLE_ALIASES[full_lower])

    # Also check normalized version (brackets without spaces)
    normalized_full = re.sub(r'\s*\[', ' [', full_lower).strip()
    if normalized_full in TITLE_ALIASES:
        queries.append(TITLE_ALIASES[normalized_full])

    # Priority 1: Cleaned Base (e.g. "Hamnet")
    if cleaned_base and cleaned_base not in queries:
        queries.append(cleaned_base)
        # Check aliases for cleaned base
        lower_base = cleaned_base.lower()
        if lower_base in TITLE_ALIASES and TITLE_ALIASES[lower_base] not in queries:
            queries.append(TITLE_ALIASES[lower_base])

    # Priority 2: AKA/Bracket content (search using foreign/original title)
    for alt in bracket_matches:
        # Check for "aka Title" inside brackets
        aka_match = re.search(r"\baka\s+(.*)", alt, flags=re.IGNORECASE)
        candidate = aka_match.group(1).strip() if aka_match else alt.strip()
        candidate = clean_title_for_tmdb(candidate)
        if candidate and candidate not in queries:
            queries.append(candidate)
            # Also check alias for bracket content
            if candidate.lower() in TITLE_ALIASES and TITLE_ALIASES[candidate.lower()] not in queries:
                queries.append(TITLE_ALIASES[candidate.lower()])
            
    # Priority 3: Split by " + " or " & " (Double Bills)
    # Only split on the CLEANED base to avoid splitting event prefixes like "DRINK & DINE"
    if " + " in cleaned_base or " & " in cleaned_base:
        parts = re.split(r"\s*(?:\+|&)\s*", cleaned_base)
        for part in parts:
            part = strip_event_suffix(part.strip())
            part = clean_title_for_tmdb(part).strip(" .,:;")
            # Skip parts that are too short (likely noise) or look like event noise
            if part and len(part) > 3 and part not in queries:
                # Skip common noise words
                noise_words = {'intro', 'q', 'a', 'qa', 'discussion', 'panel', 'talk', 'with', 'recorded', 'cast'}
                if part.lower() not in noise_words:
                    queries.append(part)
    
    # Priority 4: Colon split (e.g. "National Theatre Live: Hamlet" -> "Hamlet")
    if ":" in cleaned_base and should_split_on_colon(raw_base):
        parts = cleaned_base.split(":", 1)
        if len(parts) > 1:
            suffix_part = parts[1].strip()
            if suffix_part and suffix_part not in queries:
                queries.append(suffix_part)

    # Uniqify
    final_queries = []
    for q in queries:
        q = q.strip(" .,:;")
        if q and q not in final_queries:
            final_queries.append(q)
            
    return final_queries

def score_tmdb_result(query: str, result: dict, query_year=None, query_runtime=None, strict_year=False) -> float:
    """
    Sophisticated scoring to match Listings to TMDB Results.
    Factors: Title Similarity, Year Match, Runtime Match, Popularity.
    """
    query_norm = normalize_title_for_match(query)
    if not query_norm:
        return 0.0

    title_norm = normalize_title_for_match(result.get("title", ""))
    original_norm = normalize_title_for_match(result.get("original_title", ""))
    original_raw = result.get("original_title", "")

    # 1. Title Score (0.0 - 1.0)
    # ---------------------------------------------------------
    ratios = []
    title_ratio = 0.0
    original_ratio = 0.0

    if title_norm:
        title_ratio = difflib.SequenceMatcher(None, query_norm, title_norm).ratio()
        ratios.append(title_ratio)
    if original_norm and original_norm != title_norm:
        original_ratio = difflib.SequenceMatcher(None, query_norm, original_norm).ratio()
        ratios.append(original_ratio)

    if not ratios:
        return 0.0

    best_ratio = max(ratios)

    # Bonus: If query matches original_title better than title, this is likely
    # the correct foreign film (e.g., "Hausu" matching Japanese "ハウス" entry)
    original_match_bonus = 0.0
    if original_ratio > title_ratio + 0.1:
        # Query matches original title significantly better
        original_match_bonus = 0.1
    # Also bonus if original_title contains non-ASCII (foreign language)
    if original_raw and any(ord(c) > 127 for c in original_raw):
        if original_ratio > 0.7 or title_ratio > 0.85:
            original_match_bonus += 0.05
    
    # Token overlap bonus (good for swapped words)
    query_tokens = set(query_norm.split())
    title_tokens = set(title_norm.split()) if title_norm else set()
    if not title_tokens and original_norm:
        title_tokens = set(original_norm.split())

    token_overlap = 0.0
    if query_tokens and title_tokens:
        token_overlap = len(query_tokens & title_tokens) / len(query_tokens | title_tokens)

    # Base Text Score + foreign title bonus
    score = (0.7 * best_ratio) + (0.3 * token_overlap) + original_match_bonus

    # 2. Year Logic
    # ---------------------------------------------------------
    result_year = None
    release_date = result.get("release_date")
    if release_date:
        try:
            result_year = int(release_date.split("-")[0])
        except ValueError:
            result_year = None

    if query_year and result_year:
        diff = abs(result_year - query_year)
        
        # SPECIAL LOGIC: If query_year is THIS YEAR (or next), it might be a screening date, not release date.
        # So if we have a great title match but an old movie, don't penalize.
        current_year = datetime.now().year
        is_screening_year = (query_year >= current_year)
        
        if diff == 0:
            score += 0.15      # Perfect Year Match -> Big Boost
        elif diff == 1:
            score += 0.05      # Close enough
        elif diff > 20:
            if is_screening_year and best_ratio > 0.9 and not strict_year:
                 # It's an old movie (e.g. 1990) being screened in 2026.
                 # The user (scraper) provided 2026.
                 # We forgive the year mismatch because the title match is very strong.
                 pass 
            else:
                score -= 0.3   # Different era -> Heavy Penalty
        else:
            if not (is_screening_year and best_ratio > 0.9 and not strict_year):
                score -= 0.1   # Wrong year (unless handled above)
            
    # 3. Runtime Logic (If Year is missing or ambiguous)
    # ---------------------------------------------------------
    # Use runtime to distinguish Short Films vs Features (e.g. "Your Name")
    # Only if we have a query runtime to check against
    if query_runtime:
        # We try to use the runtime from the result if available.
        # Note: Search results often don't have runtime, but if we are re-scoring detailed objects they will.
        res_runtime = result.get("runtime")
        if res_runtime:
            try:
                r_diff = abs(int(query_runtime) - int(res_runtime))
                if r_diff <= 15:
                    score += 0.1   # Matches well
                elif r_diff > 40:
                    score -= 0.25  # Big mismatch (Short vs Feature)
            except:
                pass

    # 4. Popularity / Vote Count (Sanity Check)
    # ---------------------------------------------------------
    # If a movie is very obscure (low votes) but matches title, 
    # it might be a short film or database junk.
    vote_count = result.get("vote_count", 0)
    if vote_count > 5000:
        score += 0.05
    elif vote_count < 5:
        score -= 0.05

    # 5. Length Penalties
    # ---------------------------------------------------------
    # Short queries ("X") are dangerous
    if len(query_norm.split()) <= 1:
        if vote_count < 50:
            score -= 0.25
        elif vote_count < 200:
            score -= 0.1
        if best_ratio < 0.95:
            score -= 0.1

    return min(max(score, 0.0), 1.0) # Clamp 0..1

def is_cache_match_ok(title: str, cached: dict, query_year=None, query_runtime=None, query_director=None) -> bool:
    if not cached:
        return False
    
    # Construct a pseudo-result from cache to pass to scorer
    pseudo_result = {
        "title": cached.get("tmdb_title") or "",
        "original_title": cached.get("tmdb_original_title") or "",
        "release_date": cached.get("release_date") or "",
        "vote_count": 1000 # Assume cached items were vetted or popular enough
    }

    required_tokens = get_broadcast_required_tokens(title)
    if required_tokens and not passes_broadcast_guard(required_tokens, pseudo_result):
        return False
    
    if query_director and cached.get("director"):
        if not director_matches(query_director, cached.get("director", "")):
            return False

    score = score_tmdb_result(
        title,
        pseudo_result,
        query_year=query_year,
        query_runtime=query_runtime,
        strict_year=has_broadcast_brand(title),
    )
    
    # Runtime check for cached items (since we have the runtime in cache)
    if query_runtime and cached.get("runtime"):
        try:
            r_diff = abs(int(query_runtime) - int(cached["runtime"]))
            if r_diff > 30: # If duration differs by >30 mins, invalidate cache
                print(f"   [Cache Invalidate] Runtime mismatch for '{title}': Listed {query_runtime}m vs Cached {cached['runtime']}m")
                return False
        except:
            pass
            
    return score >= 0.70 # Slightly higher threshold for cache trust

def load_tmdb_cache():
    if os.path.exists(TMDB_CACHE_FILE):
        try:
            with open(TMDB_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_tmdb_cache(cache):
    with open(TMDB_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def fetch_tmdb_details(movie_title, session, api_key, movie_year=None, movie_runtime=None, movie_director=None):
    """
    Searches TMDB for movie_title with logic to find the BEST match, not just the first.
    """
    search_url = "https://api.themoviedb.org/3/search/movie"

    skip_tmdb, skip_reason = should_skip_tmdb_enrichment(movie_title)
    if skip_tmdb:
        print(f"   [Skip] '{movie_title}' ({skip_reason})")
        return None

    # Extract year if not provided
    query_year = parse_year_value(movie_year) or extract_year_from_title(movie_title)
    
    # Parse runtime if provided
    query_runtime = None
    if movie_runtime:
        try:
            query_runtime = int(movie_runtime)
        except:
            pass

    strict_year = has_broadcast_brand(movie_title)
    required_tokens = get_broadcast_required_tokens(movie_title)
    queries = build_search_queries(movie_title)

    try:
        candidates = []
        seen_ids = set()

        for query in queries:
            params = {
                "api_key": api_key,
                "query": query,
                "language": "en-GB",
                "include_adult": "false"
            }
            if query_year:
                params["year"] = query_year
            results = run_tmdb_search(session, search_url, params, "year")
            for result in results:
                mapped = map_tmdb_search_result(result)
                res_id = mapped.get("id")
                if not res_id or res_id in seen_ids:
                    continue
                seen_ids.add(res_id)

                if required_tokens and not passes_broadcast_guard(required_tokens, mapped):
                    continue

                score = score_tmdb_result(
                    query,
                    mapped,
                    query_year=query_year,
                    query_runtime=query_runtime,
                    strict_year=strict_year,
                )
                
                # Add to candidates
                candidates.append({
                    "score": score,
                    "result": result,
                    "query": query
                })

        # Sort candidates by score descending
        candidates.sort(key=lambda x: x["score"], reverse=True)
        
        # Filter top candidates
        score_threshold = 0.7 if strict_year else 0.65
        top_candidates = [c for c in candidates if c["score"] >= score_threshold]
        
        if not top_candidates:
            return None
            
        # Refined Selection: Check Runtimes for top contenders
        # If we have a runtime, we might need to fetch details for the top matches to verify runtime
        # because 'search' results don't include runtime.
        
        best_match = None
        
        # If we have a runtime to verify, we'll check the top 3 candidates
        check_limit = 3 if (query_runtime or movie_director) else 1
        
        for candidate in top_candidates[:check_limit]:
            res = candidate["result"]
            res_id = res.get("id")
            if not res_id:
                continue
            
            # Fetch full details
            detail_url = f"https://api.themoviedb.org/3/movie/{res_id}"
            d_params = {
                "api_key": api_key,
                "language": "en-GB",
                "append_to_response": "credits,images"
            }
            d_resp = session.get(detail_url, params=d_params, timeout=5)
            d_data = d_resp.json()
            
            # Now we have runtime
            tmdb_runtime = d_data.get("runtime") or 0
            
            # Runtime validation
            if query_runtime and tmdb_runtime > 0:
                diff = abs(query_runtime - tmdb_runtime)
                # Relaxed threshold for very long movies (often have intermissions in cinemas)
                threshold = 45 if query_runtime > 180 else 30
                if diff > threshold:
                    # Mismatch! Penalize this candidate significantly
                    res_title = d_data.get("title") or d_data.get("name") or "Unknown"
                    print(f"   [Skip] '{res_title}' runtime mismatch ({tmdb_runtime} vs {query_runtime})")
                    continue # Skip this one, try next
                elif diff < 10:
                    # Good match!
                    pass
            
            # If we pass checks, this is our winner
            # Extract Director
            director = ""
            crew = d_data.get("credits", {}).get("crew", [])
            for c in crew:
                if c.get("job") == "Director":
                    director = c.get("name")
                    break

            if movie_director and director and not director_matches(movie_director, director):
                res_title = d_data.get("title") or d_data.get("name") or "Unknown"
                print(f"   [Skip] '{res_title}' director mismatch ({director} vs {movie_director})")
                continue
            
            best_match = {
                "tmdb_id": d_data["id"],
                "tmdb_title": d_data.get("title"),
                "tmdb_original_title": d_data.get("original_title"),
                "overview": d_data.get("overview"),
                "poster_path": d_data.get("poster_path"),
                "backdrop_path": d_data.get("backdrop_path"),
                "release_date": d_data.get("release_date"),
                "director": director,
                "runtime": d_data.get("runtime"),
                "genres": [g["name"] for g in d_data.get("genres", [])],
                "vote_average": d_data.get("vote_average")
            }
            
            if candidate["query"] != movie_title:
                print(f"   Matched via '{candidate['query']}' (Score: {candidate['score']:.2f})")
                
            break # We found the best passing candidate

        return best_match

    except Exception as e:
        print(f"   TMDB Error for '{movie_title}': {e}")

    return None

def enrich_listings_with_tmdb_links(listings, cache, session, api_key):
    """
    Iterates over listings, checks TMDB for metadata/images.
    Updates listings in-place and updates cache.
    """
    print(f"\n--- Starting Enrichment for {len(listings)} listings ---")

    # Group by movie title to avoid duplicate API calls
    # We now also consider year/runtime/director in the key or lookups
    unique_map = {} # title -> {years, runtimes, directors}
    skip_tmdb_titles = set()
    skip_tmdb_items = set()
    
    # Force retry for previously failed items by clearing 'None' from cache
    initial_cache_size = len(cache)
    cache = {k: v for k, v in cache.items() if v is not None}
    if len(cache) < initial_cache_size:
        print(f"   Cleared {initial_cache_size - len(cache)} 'Not Found' entries from cache to retry with new logic.")

    for item in listings:
        title = item.get("movie_title")
        if not title:
            continue
        if is_nt_live_listing(item):
            skip_tmdb_titles.add(title)
            skip_tmdb_items.add(id(item))
            continue
            
        year = parse_year_value(item.get("year"))
        director = item.get("director")
        if director:
            director = str(director).strip()
        runtime = None
        if item.get("runtime_min"):
             try: 
                 runtime = int(str(item["runtime_min"]).replace("min","").strip())
             except: 
                 pass
        elif item.get("runtime"):
             try: 
                 runtime = int(item["runtime"]) 
             except: 
                 pass

        if title not in unique_map:
            unique_map[title] = {"years": set(), "runtimes": set(), "directors": set()}
            
        if year: unique_map[title]["years"].add(year)
        if runtime: unique_map[title]["runtimes"].add(runtime)
        if director: unique_map[title]["directors"].add(director)
            
    print(f"   Unique films to process: {len(unique_map)}")

    updated_cache = False
    for title in skip_tmdb_titles:
        if title in cache:
            cache.pop(title, None)
            updated_cache = True

    for title, meta in unique_map.items():
        # Pick best representative year/runtime (heuristics)
        rep_year = list(meta["years"])[0] if meta["years"] else None
        rep_runtime = list(meta["runtimes"])[0] if meta["runtimes"] else None
        rep_director = list(meta["directors"])[0] if meta["directors"] else None

        cached = cache.get(title)
        
        # Check if cache is still valid given our new stricter rules
        if cached:
            skip_tmdb, _ = should_skip_tmdb_enrichment(title)
            if skip_tmdb:
                cached = None
                cache.pop(title, None)
            elif not is_cache_match_ok(
                title,
                cached,
                query_year=rep_year,
                query_runtime=rep_runtime,
                query_director=rep_director,
            ):
                # print(f"   Invalidating cache for {title}")
                cached = None
                cache.pop(title, None)

        if title not in cache:
            # If we haven't checked this title before
            skip_tmdb, skip_reason = should_skip_tmdb_enrichment(title)
            if skip_tmdb:
                print(f"   Skipping TMDB for: {title} ({skip_reason})")
                cache[title] = None
                continue

            print(f"   Searching TMDB for: {title} (Yr: {rep_year}, Run: {rep_runtime})")
            details = fetch_tmdb_details(
                title,
                session,
                api_key,
                movie_year=rep_year,
                movie_runtime=rep_runtime,
                movie_director=rep_director,
            )

            if details:
                cache[title] = details
                updated_cache = True
                print(f"      Found: {details['tmdb_title']} (ID: {details['tmdb_id']})")
            else:
                cache[title] = None # Mark as not found so we don't retry immediately
                print(f"      Not found.")

            time.sleep(0.3) # Rate limiting

    # Apply cached data to listings
    for item in listings:
        if id(item) in skip_tmdb_items:
            continue
        t = item["movie_title"]
        if t in cache and cache[t]:
            d = cache[t]
            # Merge fields if missing in scraper data
            if not item.get("tmdb_id"):
                item["tmdb_id"] = d["tmdb_id"]
            if not item.get("tmdb_title"):
                item["tmdb_title"] = d["tmdb_title"]
            if not item.get("tmdb_original_title"):
                item["tmdb_original_title"] = d["tmdb_original_title"]
            if not item.get("tmdb_backdrop_path"):
                item["tmdb_backdrop_path"] = d["backdrop_path"]
            if not item.get("tmdb_poster_path"):
                item["tmdb_poster_path"] = d["poster_path"]
            if not item.get("tmdb_overview"):
                item["tmdb_overview"] = d["overview"]
            if not item.get("runtime"):
                item["runtime"] = d["runtime"]
            if not item.get("genres"):
                item["genres"] = d["genres"]
            if not item.get("vote_average"):
                item["vote_average"] = d["vote_average"]

            # If scraper didn't provide Director
            if not item.get("director"):
                item["director"] = d["director"]

            # If scraper didn't provide Year
            if not item.get("year") and d["release_date"]:
                item["year"] = d["release_date"].split("-")[0]

    if updated_cache:
        save_tmdb_cache(cache)

    return listings

# --- Scraper Runner Wrapper ---

def _run_scraper_task(name, func, normalize_func=None):
    """
    Internal task for parallel execution.
    Returns (name, status, rows, error)
    """
    try:
        # Run the scraper
        rows = func() or []

        # Apply normalization if needed
        if normalize_func and rows:
            rows = normalize_func(rows)

        return name, "SUCCESS", rows, None

    except Exception as e:
        return name, "FAILURE", [], e

# --- Main Execution ---

def main():
    # --- TIMEZONE SAFETY CHECK ---
    # Use UK timezone (GMT/BST - automatically handles daylight saving)
    # Note: For simplicity, we use UTC and let UK dates handle themselves
    # In production, consider using pytz for proper BST handling
    UK_OFFSET = timezone(timedelta(hours=0))  # Base GMT, adjust for BST as needed
    now_utc = datetime.now(timezone.utc)
    now_uk = now_utc.astimezone(UK_OFFSET)
    today_uk = now_uk.date()

    print(f"Scraper Start Time:")
    print(f"   UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"   UK:  {now_uk.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"   Today (UK): {today_uk.isoformat()}")
    print(f"   System timezone: {time.tzname}")
    print()

    tmdb_key = os.environ.get("TMDB_API_KEY")
    if not tmdb_key:
        print("Warning: TMDB_API_KEY not found. Metadata enrichment will be skipped.")

    # Prepare TMDB session
    api_session = requests.Session()
    tmdb_cache = load_tmdb_cache()

    listings = []

    # 1. DEFINE SCRAPERS TO RUN
    # Format: (Display Name, Function Object, Optional Normalizer)
    scrapers_to_run = [
        # Individual cinemas
        ("BFI Southbank", bfi_southbank_module.scrape_bfi_southbank),
        ("BFI IMAX", bfi_imax_module.scrape_bfi_imax),
        ("Prince Charles Cinema", prince_charles_module.scrape_prince_charles),
        ("The Garden Cinema", garden_cinema_module.scrape_garden_cinema),
        ("The Nickel", nickel_module.scrape_nickel),
        ("Barbican Cinema", barbican_module.scrape_barbican),
        ("Genesis Cinema", genesis_module.scrape_genesis),
        ("ICA Cinema", ica_module.scrape_ica),
        ("Close-Up Film Centre", close_up_module.scrape_close_up),
        ("Phoenix Cinema", phoenix_cinema_module.scrape_phoenix_cinema),
        ("The Castle Cinema", castle_cinema_module.scrape_castle_cinema),
        ("Electric Cinema", electric_cinema_module.scrape_electric_cinema),
        ("Bertha DocHouse", dochouse_module.scrape_dochouse),
        ("Sands Films Cinema Club", sands_films_module.scrape_sands_films),
        ("Ciné Lumière", cine_lumiere_module.scrape_cine_lumiere),
        ("Rio Cinema", rio_cinema_module.scrape_rio),
        ("The Lexi Cinema", lexi_cinema_module.scrape_lexi_cinema),
        ("ArtHouse Crouch End", arthouse_crouch_end_module.scrape_arthouse_crouch_end),
        ("JW3 Cinema", jw3_module.scrape_jw3),
        ("Peckhamplex", peckhamplex_module.scrape_peckhamplex),
        ("Rich Mix", rich_mix_module.scrape_rich_mix),
        ("ActOne Cinema & Cafe", act_one_module.scrape_act_one_cinema),
        ("Chiswick Cinema", chiswick_cinema_module.scrape_chiswick_cinema),
        ("The Cinema in the Arches", cinema_in_the_arches_module.scrape_cinema_in_the_arches),
        ("David Lean Cinema", david_lean_module.scrape_david_lean),
        ("Regent Street Cinema", regent_street_module.scrape_regent_street),
        ("Kiln Theatre", kiln_theatre_module.scrape_kiln_theatre),
        ("Riverside Studios", riverside_studios_module.scrape_riverside_studios),
        ("Ciné-Real", cine_real_module.scrape_cine_real),
        ("Coldharbour Blue", coldharbour_blue_module.scrape_coldharbour_blue),
        ("Olympic Studios (Barnes)", olympic_studios_module.scrape_olympic_studios),
        ("The Arzner", the_arzner_module.scrape_the_arzner),
        # Chain scrapers (multiple locations each)
        ("Curzon Cinemas", curzon_chain_module.scrape_all_curzon),
        ("Everyman Cinemas", everyman_chain_module.scrape_everyman_locations),
        ("Picturehouse Cinemas", picturehouse_chain_module.scrape_all_picturehouse),
    ]

    print(f"Starting {len(scrapers_to_run)} scrapers in parallel...")

    # 2. RUN SCRAPERS IN PARALLEL
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_cinema = {}
        for item in scrapers_to_run:
            name = item[0]
            func = item[1]
            norm = item[2] if len(item) > 2 else None
            
            future = executor.submit(_run_scraper_task, name, func, norm)
            future_to_cinema[future] = name

        for future in concurrent.futures.as_completed(future_to_cinema):
            name, status, rows, error = future.result()
            count = len(rows)
            
            if status == "SUCCESS":
                print(f"-> {count} showings from {name}.")
                listings.extend(rows)
                report.add(name, "SUCCESS", count)
            else:
                print(f"Error in {name}: {error}")
                report.add(name, "FAILURE", 0, error=error)

    # 3. ENRICHMENT
    print(f"\nCollected a total of {len(listings)} showings.")

    if tmdb_key:
        listings = enrich_listings_with_tmdb_links(listings, tmdb_cache, api_session, tmdb_key)

    # 4. SAVE OUTPUT
    print(f"Saving to {OUTPUT_JSON}...")

    # --- DATE VALIDATION ---
    today_count = sum(1 for item in listings if item.get("date_text") == today_uk.isoformat())
    all_dates = set(item.get("date_text") for item in listings if item.get("date_text"))

    print(f"\nData Summary:")
    print(f"   Total listings: {len(listings)}")
    print(f"   Listings for today ({today_uk.isoformat()}): {today_count}")
    print(f"   Unique dates in data: {sorted(all_dates)[:10]}")

    if today_count == 0 and listings:
        print(f"\n   WARNING: No listings found for today ({today_uk.isoformat()})!")
        print(f"   Cinema websites may not have updated their schedules yet.")

    try:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(listings, f, ensure_ascii=False, indent=2)
        print("Done.")
    except Exception as e:
        print(f"Critical Error saving JSON: {e}")
        sys.exit(1)

    # 5. REPORTING & ALERTS
    failures, warnings = report.print_summary()

    # Send email if configured
    report.send_email_alert(failures, warnings)

if __name__ == "__main__":
    main()


