#!/usr/bin/env python3
# main_scraper.py
# Manchester Cinema Scraper - V1.0
# Adapted from London cinema scraper for Manchester independent cinemas

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
    home_mcr_module,
    cultplex_module,
    savoy_module,
    everyman_manchester_module,
    regent_module,
    plaza_module,
    block_cinema_module,
    small_world_cinema_module,
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

        for result in self.results:
            status = result["status"]
            cinema = result["cinema"][:29]  # Truncate long names
            count = str(result["count"]) if result["count"] is not None else ""
            error = result["error"]

            if status == "SUCCESS":
                status_icon = "OK"
                notes = ""
            elif status == "FAILURE":
                status_icon = "FAIL"
                notes = error or "Failed"
                failures.append((cinema, error))
            else:
                status_icon = "?"
                notes = error or "Unknown"
                warnings.append((cinema, error))

            print(f"{status_icon:<4} | {cinema:<30} | {count:<5} | {notes}")

        print("-" * 70)
        print(f"Total showings scraped: {self.total_showings}")

        return failures, warnings

    def send_email_alert(self, failures, warnings):
        """
        Send email alert for failures using environment variables.
        """
        if not failures:
            return

        smtp_server = os.environ.get("SMTP_SERVER")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        smtp_username = os.environ.get("SMTP_USERNAME")
        smtp_password = os.environ.get("SMTP_PASSWORD")
        alert_email = os.environ.get("ALERT_EMAIL")

        if not all([smtp_server, smtp_username, smtp_password, alert_email]):
            print("Email configuration incomplete - skipping alerts")
            return

        subject = f"Manchester Cinema Scraper Alert - {len(failures)} failures"

        body = "Manchester Cinema Scraper Report\n\n"
        body += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        body += f"Total showings: {self.total_showings}\n\n"

        if failures:
            body += "FAILURES:\n"
            for cinema, error in failures:
                body += f"  - {cinema}: {error}\n"

        if warnings:
            body += "\nWARNINGS:\n"
            for cinema, warning in warnings:
                body += f"  - {cinema}: {warning}\n"

        try:
            msg = EmailMessage()
            msg.set_content(body)
            msg['Subject'] = subject
            msg['From'] = smtp_username
            msg['To'] = alert_email

            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls(context=context)
                server.login(smtp_username, smtp_password)
                server.send_message(msg)

            print(f"Alert email sent to {alert_email}")

        except Exception as e:
            print(f"Failed to send alert email: {e}")


def clean_title_for_tmdb(title: str) -> str:
    """
    Clean movie titles for TMDB search. Manchester version - English titles only.
    """
    if not title:
        return ""

    # 1. Strip explicit Event Prefixes (often separated by : or - or –)
    prefix_patterns = [
        r"^(Narrow Margin presents|In Focus|Crafty Movie Night|Member's Request|Staff Pick|Relaxed Screening|Family Screening|Preview|Premiere|UK Premiere)[:\s–-]+",
        r"^(Throwback|Babykino|Carers & Babies|Toddler Club|Club Room|Dog-Friendly|Dog-Friendly Screening|Sensory Friendly|HOH|Caption|Autism Friendly)[:\s–-]+",
        r"^(DOCHOUSE|LSFF|ANZ FILM FESTIVAL|ANZ FF|RBO Live|RBO Encore|Met Opera Live|Met Opera Encore|NT Live|National Theatre Live|Exhibition on Screen|Royal Ballet|Royal Opera|Bolshoi Ballet)[:\s–-]+",
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
]


def should_skip_tmdb_enrichment(title: str) -> tuple[bool, str]:
    """
    Determine if a title should skip TMDB enrichment.
    Returns (should_skip, reason)
    """
    if not title:
        return True, "Empty title"

    title_lower = title.lower()

    # Skip non-film events
    for keyword in NON_FILM_EVENT_KEYWORDS:
        if keyword in title_lower:
            return True, f"Non-film event keyword: '{keyword}'"

    # Skip broadcast events (NT Live, Met Opera, etc.)
    if has_broadcast_brand(title):
        return True, "Broadcast event (NT Live, Met Opera, etc.)"

    return False, ""


def has_broadcast_brand(title: str) -> bool:
    """Check if title contains broadcast brand indicators."""
    broadcast_brands = [
        "nt live", "national theatre live",
        "met opera live", "met opera encore",
        "royal opera", "royal ballet", "bolshoi ballet",
        "exhibition on screen",
        "rbo live", "rbo encore",
    ]

    title_lower = title.lower()
    return any(brand in title_lower for brand in broadcast_brands)


def get_broadcast_required_tokens(title: str) -> list[str]:
    """Get tokens required for broadcast events to pass TMDB guard."""
    if not has_broadcast_brand(title):
        return []

    # For broadcast events, require specific tokens
    required_tokens = []
    title_lower = title.lower()

    if "nt live" in title_lower or "national theatre live" in title_lower:
        required_tokens.extend(["theatre", "play", "stage"])
    elif "met opera" in title_lower or "royal opera" in title_lower:
        required_tokens.extend(["opera"])
    elif "royal ballet" in title_lower or "bolshoi ballet" in title_lower:
        required_tokens.extend(["ballet", "dance"])

    return required_tokens


def passes_broadcast_guard(required_tokens: list[str], result: dict) -> bool:
    """Check if TMDB result passes broadcast event guard."""
    if not required_tokens:
        return True

    # Check title and overview for required tokens
    text_to_check = ""
    if result.get("title"):
        text_to_check += result["title"].lower() + " "
    if result.get("overview"):
        text_to_check += result["overview"].lower()

    return any(token in text_to_check for token in required_tokens)


TITLE_ALIASES = {
    # Common title variations
    "the holdovers": "the holdovers",
    "oppenheimer": "oppenheimer",
}


def get_title_queries(title: str) -> list[str]:
    """
    Generate search queries for TMDB from a cinema listing title.
    Manchester version - simplified for English titles only.
    """
    queries = []
    raw_base = title
    cleaned_base = clean_title_for_tmdb(raw_base)

    # Priority 1: Cleaned base title
    if cleaned_base:
        queries.append(cleaned_base)
        # Also check alias for cleaned base
        if cleaned_base.lower() in TITLE_ALIASES:
            queries.append(TITLE_ALIASES[cleaned_base.lower()])

    # Priority 2: Handle AKA patterns like "Title (AKA Alternative)"
    aka_match = re.search(r"\baka\s+(.*)", raw_base, flags=re.IGNORECASE)
    if aka_match:
        candidate = aka_match.group(1).strip()
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


def strip_event_suffix(text: str) -> str:
    """Strip event suffixes from text."""
    if not text:
        return ""

    patterns = [
        r"\s+(with|hosted by|presented by|introduced by)\s+.*$",
        r"\s+(q&a|qa|discussion|talk|panel)\s*$",
        r"\s+(live|recorded)\s*$",
    ]

    result = text
    for pattern in patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)

    return result.strip()


def should_split_on_colon(text: str) -> bool:
    """Determine if title should be split on colon."""
    # Don't split if colon is preceded by broadcast brand
    before_colon = text.split(":", 1)[0].lower()
    broadcast_brands = ["nt live", "national theatre live", "met opera", "royal opera", "royal ballet"]
    return not any(brand in before_colon for brand in broadcast_brands)


def load_tmdb_cache() -> dict:
    """Load TMDB cache from JSON file."""
    if os.path.exists(TMDB_CACHE_FILE):
        try:
            with open(TMDB_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load TMDB cache: {e}")
    return {}


def save_tmdb_cache(cache: dict):
    """Save TMDB cache to JSON file."""
    try:
        with open(TMDB_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving TMDB cache: {e}")


def fetch_tmdb_details(movie_title: str, session: requests.Session, api_key: str, movie_year=None, movie_runtime=None) -> dict:
    """
    Fetch movie details from TMDB API.
    Manchester version - adapted for English titles only.
    """
    base_url = "https://api.themoviedb.org/3"

    queries = get_title_queries(movie_title)
    if not queries:
        return None

    candidates = []
    seen_ids = set()

    for query in queries:
        if not query or len(query) < 2:
            continue

        # Search TMDB
        search_url = f"{base_url}/search/movie"
        params = {
            "api_key": api_key,
            "query": query,
            "language": "en-US",
            "page": 1
        }

        try:
            response = session.get(search_url, params=params, timeout=10)
            response.raise_for_status()
            search_data = response.json()

            results = search_data.get("results", [])
            if not results:
                continue

            # Score and collect candidates
            required_tokens = get_broadcast_required_tokens(movie_title)
            strict_year = has_broadcast_brand(movie_title)

            for result in results[:5]:  # Check top 5 results
                res_id = result.get("id")
                if not res_id or res_id in seen_ids:
                    continue
                seen_ids.add(res_id)

                if required_tokens and not passes_broadcast_guard(required_tokens, result):
                    continue

                score = score_tmdb_result(query, result, query_year=movie_year, query_runtime=movie_runtime, strict_year=strict_year)

                # Add to candidates
                candidates.append({
                    "score": score,
                    "result": result,
                    "query": query
                })

        except Exception as e:
            print(f"   TMDB search error for '{query}': {e}")
            continue

    # Sort candidates by score descending
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Filter top candidates
    score_threshold = 0.7 if has_broadcast_brand(movie_title) else 0.65
    top_candidates = [c for c in candidates if c["score"] >= score_threshold]

    if not top_candidates:
        return None

    # Refined Selection: Check Runtimes for top contenders
    best_match = None

    # If we have a runtime to verify, we'll check the top 3 candidates
    check_limit = 3 if movie_runtime else 1

    for candidate in top_candidates[:check_limit]:
        res = candidate["result"]
        res_id = res.get("id")
        if not res_id:
            continue

        # Fetch full details
        detail_url = f"{base_url}/movie/{res_id}"
        d_params = {
            "api_key": api_key,
            "language": "en-GB",
            "append_to_response": "credits"
        }

        try:
            d_resp = session.get(detail_url, params=d_params, timeout=10)
            d_resp.raise_for_status()
            d_data = d_resp.json()

            # Now we have runtime
            tmdb_runtime = d_data.get("runtime") or 0

            # Runtime validation
            if movie_runtime and tmdb_runtime > 0:
                diff = abs(movie_runtime - tmdb_runtime)
                # Relaxed threshold for very long movies (often have intermissions in cinemas)
                threshold = 45 if movie_runtime > 180 else 30
                if diff > threshold:
                    # Mismatch! Penalize this candidate significantly
                    res_title = d_data.get("title") or d_data.get("name") or "Unknown"
                    print(f"   [Skip] '{res_title}' runtime mismatch ({tmdb_runtime} vs {movie_runtime})")
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

        except Exception as e:
            print(f"   TMDB detail fetch error for ID {res_id}: {e}")

    return best_match


def score_tmdb_result(query: str, result: dict, query_year=None, query_runtime=None, strict_year=False) -> float:
    """
    Sophisticated scoring to match Listings to TMDB Results.
    Factors: Title Similarity, Year Match, Runtime Match, Popularity.
    Manchester version - adapted for English titles.
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
    # the correct foreign film (though Manchester focuses on English content)
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
    # Use runtime to distinguish Short Films vs Features
    if query_runtime:
        # We try to use the runtime from the result if available.
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


def is_cache_match_ok(title: str, cached: dict, query_year=None, query_runtime=None) -> bool:
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

    return score >= 0.7  # Same threshold as fresh searches


def enrich_listings_with_tmdb_links(listings, cache, session, api_key):
    """
    Iterates over listings, checks TMDB for metadata/images.
    Updates listings in-place and updates cache.
    Manchester version - adapted for English titles.
    """
    print(f"\n--- Starting Enrichment for {len(listings)} listings ---")

    # Group by movie title to avoid duplicate API calls
    unique_map = {} # title -> {year, runtime, count}

    # Force retry for previously failed items by clearing 'None' from cache
    initial_cache_size = len(cache)
    cache = {k: v for k, v in cache.items() if v is not None}
    if len(cache) < initial_cache_size:
        print(f"   Cleared {initial_cache_size - len(cache)} 'Not Found' entries from cache to retry with new logic.")

    for item in listings:
        title = item.get("movie_title")
        if not title:
            continue

        year = parse_year_value(item.get("year"))
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
            unique_map[title] = {"years": set(), "runtimes": set()}

        if year: unique_map[title]["years"].add(year)
        if runtime: unique_map[title]["runtimes"].add(runtime)

    print(f"   Unique films to process: {len(unique_map)}")

    updated_cache = False

    for title, meta in unique_map.items():
        # Pick best representative year/runtime (heuristics)
        rep_year = list(meta["years"])[0] if meta["years"] else None
        rep_runtime = list(meta["runtimes"])[0] if meta["runtimes"] else None

        cached = cache.get(title)

        # Check if cache is still valid given our new stricter rules
        if cached:
            skip_tmdb, _ = should_skip_tmdb_enrichment(title)
            if skip_tmdb:
                cached = None
                cache.pop(title, None)
            elif not is_cache_match_ok(title, cached, query_year=rep_year, query_runtime=rep_runtime):
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
            details = fetch_tmdb_details(title, session, api_key, movie_year=rep_year, movie_runtime=rep_runtime)

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


def parse_year_value(year_str):
    """Parse year from string."""
    if not year_str:
        return None
    try:
        return int(str(year_str).strip())
    except:
        return None


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
    # Manchester version: GMT/BST instead of JST/UTC
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
        # Manchester cinemas
        ("HOME Manchester", home_mcr_module.scrape_home_mcr),
        ("Cultplex", cultplex_module.scrape_cultplex),
        ("The Savoy", savoy_module.scrape_savoy),
        ("Everyman Manchester", everyman_manchester_module.scrape_everyman_manchester),
        ("Regent Cinema", regent_module.scrape_regent),
        ("The Plaza", plaza_module.scrape_plaza),
        ("The Block Cinema", block_cinema_module.scrape_block_cinema),
        ("Small World Cinema Club", small_world_cinema_module.scrape_small_world_cinema),
    ]

    # 2. RUN ALL SCRAPERS IN PARALLEL
    print(f"Starting scrape of {len(scrapers_to_run)} Manchester independent/arthouse cinemas...")
    report = ScrapeReport()

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(scrapers_to_run), 8)) as executor:
        # Submit all tasks
        future_to_scraper = {}
        for name, func, *normalizer in scrapers_to_run:
            future = executor.submit(_run_scraper_task, name, func, normalizer[0] if normalizer else None)
            future_to_scraper[future] = name

        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_scraper):
            name, status, rows, error = future.result()

            if status == "SUCCESS":
                print(f"-> {len(rows)} showings from {name}.")
                listings.extend(rows)
                report.add(name, "SUCCESS", len(rows))
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