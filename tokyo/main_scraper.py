#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# main_scraper.py
# V5.1: Robust Monitoring, Email Alerts, Smart Title Cleaning & Fixed Function Names

import json
import sys
import io

# Force UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import sys
import traceback
import re
import requests
import time
import os
import difflib
import smtplib
import ssl
import random
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.ai_enrichment import (
    AIEnrichmentClient,
    LOCAL_AI_NO_RESULT,
    TMDB_RETRY_FAILED,
    env_truthy,
    local_ai_retry_due,
    make_ai_failure_entry,
    retry_hours_from_env,
)

# --- All cinema scraper modules ---
from cinema_modules import eiga_tokyo_module, eiga_kanagawa_module, eiga_saitama_module, eiga_chiba_module
from cinema_modules import (
    bunkamura_module,
    bluestudio_module,
    cine_switch_ginza_module,
    cinemalice_module,
    eurospace_module,
    human_shibuya_module,
    human_yurakucho_module,
    image_forum_module,
    ks_cinema_module,
    laputa_asagaya_module,
    meguro_cinema_module,
    musashino_kan_module,
    nfaj_calendar_module as nfaj_module,
    polepole_module,
    shin_bungeiza_module,
    shimotakaido_module,
    stranger_module,
    theatre_shinjuku_module,
    waseda_shochiku_module,
    cinemart_shinjuku_module,
    cine_quinto_module,
    yebisu_garden_module,
    k2_cinema_module,
    kino_cinema_module,
    cinema_rosa_module,
    chupki_module,
    uplink_kichijoji_module,
    tollywood_module,
    morc_asagaya_module,
    jinbocho_theatre_module,
    cinema_vera_module,
    institut_francais_module,
    jack_and_betty_module,
    athenee_francais_module,
    white_cine_quinto_module,
    cinema_novecento_module,
    yokohama_cinemarine_module,
    kadokawa_yurakucho_module,
    cinema_neko_module,
    cinema_amigo_module,
    koenji_bacchus_module,
    koenji_cinema_club_module,
)

# --- Configuration ---
DATA_DIR = "data"
OUTPUT_JSON = os.path.join(DATA_DIR, "showtimes.json")
TMDB_CACHE_FILE = os.path.join(DATA_DIR, "tmdb_cache.json")
TMDB_CACHE_META_FILE = os.path.join(DATA_DIR, "tmdb_cache_meta.json")
FILMARKS_CACHE_FILE = os.path.join(DATA_DIR, "filmarks_cache.json")
TITLE_RESOLUTION_CACHE_FILE = os.path.join(DATA_DIR, "title_resolution_cache.json")
LEGACY_TITLE_TRANSLATION_CACHE_FILE = os.path.join(DATA_DIR, "title_translation_cache.json")
SYNOPSIS_TRANSLATION_CACHE_FILE = os.path.join(DATA_DIR, "synopsis_translation_cache.json")
MIN_TITLE_MATCH_SCORE = 0.7
MIN_FINAL_MATCH_SCORE = 0.6
YEARLESS_SUPPORT_CANDIDATE_THRESHOLD = 5

# Ensure data directory exists
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --- Helper: Normalizers ---
def _normalize_eurospace_schema(listings: list) -> list:
    """Matches Eurospace module output to standard schema."""
    normalized = []
    for show in listings:
        normalized.append({
            "cinema_name": show.get("cinema"),
            "movie_title": show.get("title"),
            "date_text": show.get("date"),
            "showtime": show.get("time"),
            "detail_page_url": show.get("url"),
            "director": show.get("director"),
            "year": str(show["year"]) if show.get("year") else "",
            "country": show.get("country"),
            "runtime_min": str(show["runtime"]) if show.get("runtime") else "",
            "synopsis": "",
            "movie_title_en": "",
        })
    return normalized

# --- Monitor & Alert System ---
class ScrapeReport:
    def __init__(self):
        self.results = []
        self.total_showings = 0

    def add(self, cinema_name, status, count, error=None, warn_if_empty=True):
        self.results.append({
            "cinema": cinema_name,
            "status": status,
            "count": count,
            "error": str(error) if error else None,
            "warn_if_empty": warn_if_empty,
        })
        if status == "SUCCESS" and count:
            self.total_showings += count

    def print_summary(self):
        print("\n" + "="*50)
        print("📊 SCRAPE HEALTH REPORT")
        print("="*50)
        
        failures = []
        warnings = []

        # Header
        print(f"{'STATUS':<4} | {'CINEMA':<25} | {'COUNT':<5} | {'NOTES'}")
        print("-" * 65)

        for r in self.results:
            # Logic: If SUCCESS but 0 showings, treat as WARNING unless the
            # source is intermittent or covered by a broader fallback scraper.
            if r['status'] == 'SUCCESS' and r['count'] == 0 and r.get("warn_if_empty", True):
                r['status'] = 'WARNING'
                warnings.append(r)
            elif r['status'] == 'FAILURE':
                failures.append(r)

            # Console Output Icons
            icon = "✅"
            if r['status'] == 'WARNING': icon = "⚠️ "
            if r['status'] == 'FAILURE': icon = "❌"
            
            error_msg = f"{r['error']}" if r['error'] else ""
            if r['status'] == 'WARNING' and not error_msg:
                error_msg = "0 showings found"

            print(f"{icon:<4} | {r['cinema']:<25} | {r['count']:<5} | {error_msg}")

        print("-" * 65)
        print(f"Total Showings Collected: {self.total_showings}")
        return failures, warnings

    def send_email_alert(self, failures, warnings):
        """Sends an email if things went wrong."""
        if not failures and not warnings:
            return

        # 1. Gather Credentials
        smtp_server = (os.environ.get("SMTP_SERVER") or "smtp.gmail.com").strip()
        # SSL port is usually 465
        smtp_port_raw = (os.environ.get("SMTP_PORT") or "465").strip()
        try:
            smtp_port = int(smtp_port_raw)
        except ValueError:
            print(f"ℹ️ Invalid SMTP_PORT={smtp_port_raw!r}; using 465.")
            smtp_port = 465
        sender_email = os.environ.get("SMTP_EMAIL")
        sender_password = os.environ.get("SMTP_PASSWORD")
        recipient_email = os.environ.get("ALERT_RECIPIENT_EMAIL") or sender_email

        if not (sender_email and sender_password and recipient_email):
            print("ℹ️ Skipping email alert: Missing SMTP credentials.")
            return

        # 2. Build Content
        subject = f"🚨 Scraper Alert: {len(failures)} Crashes, {len(warnings)} Empty"
        
        body_lines = ["The Cinema Scraper encountered issues:\n"]
        
        if failures:
            body_lines.append(f"❌ CRITICAL FAILURES ({len(failures)}):")
            for f in failures:
                body_lines.append(f"- {f['cinema']}: {f['error']}")
            body_lines.append("\n")

        if warnings:
            body_lines.append(f"⚠️ POTENTIAL ISSUES (0 Showings Found):")
            for w in warnings:
                if w.get("error"):
                    body_lines.append(f"- {w['cinema']}: {w['error']}")
                else:
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
            print("📧 Alert email sent successfully.")
        except Exception as e:
            print(f"❌ Failed to send email alert: {e}")

# Initialize Global Report
report = ScrapeReport()

# --- TMDB Utilities ---

# Bump CLEAN_TITLE_VERSION whenever clean_title_for_tmdb changes in a way that
# could rescue previously-unmatched titles. On the next run the scraper drops the
# cached "not found" (null) entries once so they are re-searched with the better
# query (see reset_stale_tmdb_nulls). Confirmed matches are always preserved.
CLEAN_TITLE_VERSION = 3


def clean_title_for_tmdb(title: str) -> str:
    """
    Aggressively strips 'noise' suffixes that confuse TMDB fuzzy matching.
    """
    if not title:
        return ""
    
    cleaned = title.replace("\u3000", " ").strip()
    # Normalise full-width 4K/2K (４Ｋ/２Ｋ) so the restoration patterns below match
    # decorations like "４Ｋデジタル修復版".
    cleaned = (cleaned.replace("４Ｋ", "4K").replace("２Ｋ", "2K")
                      .replace("４ｋ", "4K").replace("２ｋ", "2K"))
    keyword_pattern = (
        r"(?:上映|字幕|吹替|舞台挨拶|イベント|ｲﾍﾞﾝﾄ|特集|記念|公開|"
        r"オールナイト|未体験|復刻|再上映|先行|限定|特別|"
        r"ライブ|生中継|応援上映|4K|2K|リマスター|レストア|修復|デジタル)"
    )
    patterns = [
        rf"【[^】]*?{keyword_pattern}[^】]*】",
        rf"［[^］]*?{keyword_pattern}[^］]*］",
        rf"〈[^〉]*?{keyword_pattern}[^〉]*〉",
        rf"《[^》]*?{keyword_pattern}[^》]*》",
        rf"\[[^\]]*?{keyword_pattern}[^\]]*\]",
        rf"\([^\)]*?{keyword_pattern}[^\)]*\)",
        # Leading orphan-closing-bracket decoration, e.g. "字幕版】タイトル" — a scraped
        # fragment that lost its opening bracket. Only fires when the leading run
        # holds a known decoration keyword and ends at a close bracket.
        rf"^[^【［〈《\[(]{{0,14}}?{keyword_pattern}[^】］〉》\])]{{0,14}}?[】］〉》\])]",
        r"^\s*[A-Z]\.?\s+",
        r"^\s*\d+\.\s+",
        # 修復 (restoration) sits alongside リマスター/レストア (remaster/restore).
        r"\s*(?:4K|2K)\s*(?:デジタル)?(?:リマスター|レストア|修復)?(?:版)?\s*$",
        r"\s*(?:デジタル)?(?:リマスター|レストア|修復)(?:版)?\s*$",
        r"\s*(?:IMAX|Dolby|4DX|SCREENX)\s*$",
        r"\s*(?:完全版|ディレクターズカット|Director's Cut|DC版)\s*$",
        # Trailing version annotations, e.g. "（long version）" / "（オリジナル版）".
        r"\s*[（(]\s*(?:long|short|full|original|theatrical|extended|uncut|remastered|restored)\s*(?:version|ver\.?|cut|edition)?\s*[)）]\s*$",
        r"\s*[（(](?:ロング|ショート|オリジナル|劇場|完全)?(?:バージョン|ヴァージョン|版)[)）]\s*$",
        # Trailing re-release year annotation, e.g. "サムライ（1967）" / "罠(1949)".
        r"\s*[（(]\s*(?:19|20)\d{2}\s*[)）]\s*$",
        r"\s*(?:字幕|吹替)\s*$",
        # Anniversary suffixes: "25周年特別版", "公開20周年記念", "10周年記念上映".
        r"\s*(?:公開)?\d+周年(?:記念|特別)*(?:版|上映|上映版)?\s*$",
        r"\s*(?:公開\d+周年記念版|\d+周年記念版|\d+周年記念)\s*$",
        r"\s*(?:復刻版|再上映)\s*$",
        r"\s*(?:G|PG12|R15\+|R18\+)\s*$",
    ]

    def _strip_pass(text: str) -> str:
        # Leading full 【…】/［…］ decoration bracket (e.g. a festival-series prefix
        # like "【監督特集】" or "【驚くべき世界】"), even without a decoration keyword —
        # but only when a plausible title (>=2 chars) remains, so we never eat a whole
        # title. Uses [^【】] so nested/adjacent brackets aren't merged into one match.
        lead = re.match(r"^\s*(?:【[^【】]+】|［[^［］]+］)\s*(.+)$", text)
        if lead and len(lead.group(1).strip()) >= 2:
            text = lead.group(1).strip()
        for pat in patterns:
            text = re.sub(pat, "", text, flags=re.IGNORECASE)
        text = text.strip()
        # Drop Japanese quotation brackets (『』「」) that scraped titles carry but
        # TMDB never does — only when they cleanly WRAP the whole title, or are a
        # genuine ORPHAN (opener with no closer / closer with no opener). Never touch
        # internal or balanced multi-part brackets, which belong to event titles.
        wrap = re.match(r"^『(.+)』$", text) or re.match(r"^「(.+)」$", text)
        if wrap and "』" not in wrap.group(1) and "」" not in wrap.group(1):
            text = wrap.group(1).strip()
        if text.startswith("『") and "』" not in text:
            text = text[1:].strip()
        elif text.startswith("「") and "」" not in text:
            text = text[1:].strip()
        if text.endswith("』") and "『" not in text:
            text = text[:-1].strip()
        elif text.endswith("」") and "「" not in text:
            text = text[:-1].strip()
        return text

    # Iterate: a wrap like "『サムライ 4Kレストア』" only exposes its trailing decoration
    # ("4Kレストア") to the suffix strippers after the 『』 unwrap, so re-run until stable.
    for _ in range(3):
        stripped = _strip_pass(cleaned)
        if stripped == cleaned:
            break
        cleaned = stripped

    # If cleaning removed everything (unlikely), revert
    if not cleaned:
        return title

    return cleaned

def load_tmdb_cache():
    if os.path.exists(TMDB_CACHE_FILE):
        try:
            with open(TMDB_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            return {}
    return {}

def save_tmdb_cache(cache):
    _write_json_file(TMDB_CACHE_FILE, cache, sort_keys=True)


# Markers that a listing is a RE-ISSUE (restoration / remaster / anniversary
# revival) of an older film. For these the listing's `year` is the re-release
# year (e.g. 2026), not the film's real year, so the year filter/scoring must not
# use it — TMDB's copy is dated to the original release.
_REISSUE_MARKER_RE = re.compile(
    r"レストア|リマスター|修復|復刻|ﾃﾞｼﾞﾀﾙ|4Kデジタル|2Kデジタル|"
    r"\d+周年|アニバーサリー|Anniversary|Restored|Remaster",
    re.IGNORECASE,
)


def _is_reissue_title(raw_title: str) -> bool:
    """True when the raw scraped title advertises a restoration/anniversary revival,
    so the re-release year in the listing should be ignored for TMDB matching."""
    if not raw_title:
        return False
    normalized = raw_title.replace("４Ｋ", "4K").replace("２Ｋ", "2K")
    return bool(_REISSUE_MARKER_RE.search(normalized))


# Edition/format annotations the AI sometimes appends to an English title, e.g.
# "In the Mood for Love (25th Anniversary Special Edition)" or "The Gift (4K
# Restored Version)". They poison the TMDB search, so drop a trailing parenthetical
# that is clearly such an annotation (never a real subtitle).
_AI_TITLE_ANNOTATION_RE = re.compile(
    r"\s*[（(][^（()）]*\b(?:4K|2K|restored|restoration|remaster(?:ed)?|"
    r"anniversary|special\s+edition|edition|version|digital|director'?s\s+cut|"
    r"uncut|remux)\b[^（()）]*[)）]\s*$",
    re.IGNORECASE,
)


def _strip_ai_title_annotation(english_title: str) -> str:
    if not english_title:
        return english_title
    stripped = _AI_TITLE_ANNOTATION_RE.sub("", english_title).strip()
    return stripped or english_title


def _load_clean_title_version() -> int:
    if os.path.exists(TMDB_CACHE_META_FILE):
        try:
            with open(TMDB_CACHE_META_FILE, "r", encoding="utf-8") as f:
                return int(json.load(f).get("clean_title_version", 0))
        except (json.JSONDecodeError, IOError, OSError, ValueError, TypeError):
            return 0
    return 0


def reset_stale_tmdb_nulls(cache: dict) -> bool:
    """When clean_title_for_tmdb improves (CLEAN_TITLE_VERSION bumps), drop cached
    'not found' (null) entries once so they are re-searched with the better query.

    Confirmed matches (dict entries) are always preserved, and the TMDB acceptance
    gate is unchanged — re-searching can only add correct matches, never wrong ones.
    The version is persisted alongside the (now null-free) cache so this runs at most
    once per bump and is robust to the nightly cache churn.
    """
    if _load_clean_title_version() >= CLEAN_TITLE_VERSION:
        return False
    removed = [key for key, value in cache.items() if value is None]
    for key in removed:
        del cache[key]
    print(
        f"   ♻️  Title cleaner v{CLEAN_TITLE_VERSION}: cleared {len(removed)} cached "
        "'not found' entries for re-search with the improved query."
    )
    # Persist the null-free cache and the new version together so disk stays consistent
    # even if the run is interrupted before enrichment finishes.
    save_tmdb_cache(cache)
    try:
        with open(TMDB_CACHE_META_FILE, "w", encoding="utf-8") as f:
            json.dump({"clean_title_version": CLEAN_TITLE_VERSION}, f)
    except (IOError, OSError) as exc:
        print(f"   ⚠️  Could not write {TMDB_CACHE_META_FILE}: {exc}")
    return bool(removed)

def load_synopsis_translation_cache():
    if os.path.exists(SYNOPSIS_TRANSLATION_CACHE_FILE):
        try:
            with open(SYNOPSIS_TRANSLATION_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            return {}
    return {}

def save_synopsis_translation_cache(cache):
    _write_json_file(SYNOPSIS_TRANSLATION_CACHE_FILE, cache, sort_keys=True)

def load_title_resolution_cache():
    paths_to_try = [TITLE_RESOLUTION_CACHE_FILE, LEGACY_TITLE_TRANSLATION_CACHE_FILE]
    for path in paths_to_try:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError, OSError):
                return {}
    return {}

def save_title_resolution_cache(cache):
    _write_json_file(TITLE_RESOLUTION_CACHE_FILE, cache, sort_keys=True)

def load_filmarks_cache():
    if os.path.exists(FILMARKS_CACHE_FILE):
        try:
            with open(FILMARKS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            return {}
    return {}

def save_filmarks_cache(cache):
    _write_json_file(FILMARKS_CACHE_FILE, cache, sort_keys=True)

FILMARKS_SEARCH_BASE_URL = "https://filmarks.com/search/movies"
FILMARKS_RESULT_BASE_URL = "https://filmarks.com"
FILMARKS_USER_AGENT = (
    "Mozilla/5.0 (compatible; TokyoCinemaShowtimes/1.0; "
    "+https://jakobng.github.io/website1/tokyo-cinemas.html)"
)
FILMARKS_ACCEPT_SCORE = 12
FILMARKS_ACCEPT_MARGIN = 2
ZERO_COUNT_RETRY_CINEMAS = {
    "Shimotakaido Cinema",
    "Shinjuku Musashino-kan",
}

def _clean_title_for_filmarks_query(title: str) -> str:
    if not title:
        return ""
    cleaned = str(title).replace("\u3000", " ").strip()
    cleaned = re.sub(r"^[「『\"'\s]+|[」』\"'\s]+$", "", cleaned)
    patterns = [
        r"[＊*].*$",
        r"\s*(?:デジタル上映|DCP上映|35mm上映|16mm上映)\s*$",
        r"\s*(?:字幕版|吹替版|日本語字幕|英語字幕|字幕|吹替)\s*$",
        r"\s*(?:4K|2K)\s*(?:デジタル)?(?:リマスター|レストア)?(?:版)?\s*$",
        r"\s*(?:上映|特別上映|再上映)\s*$",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^[「『\"'\s]+|[」』\"'\s]+$", "", cleaned)
    return cleaned.strip()

def _pick_filmarks_query(item: dict) -> tuple[str, str]:
    for field in ("clean_title_jp", "movie_title_jp", "movie_title", "movie_title_original", "movie_title_en"):
        query = _clean_title_for_filmarks_query(item.get(field))
        if query:
            return query, field
    return "", ""

def _build_filmarks_search_url(query: str) -> str:
    if not query:
        return ""
    return f"{FILMARKS_SEARCH_BASE_URL}?q={quote(query)}"

def _filmarks_match_norm(value: str) -> str:
    if not value:
        return ""
    normalized = str(value).lower()
    normalized = re.sub(r"<[^>]+>", " ", normalized)
    normalized = re.sub(r"[「」『』“”\"'\[\]（）()：:／/・･\s_\-\u3000]+", "", normalized)
    return normalized.strip()

def _filmarks_title_relation(query: str, candidate_title: str, item: dict) -> str:
    candidate_norm = _filmarks_match_norm(candidate_title)
    title_candidates = (
        query,
        item.get("clean_title_jp"),
        item.get("movie_title_jp"),
        item.get("movie_title"),
        item.get("movie_title_original"),
        item.get("movie_title_en"),
    )
    partial = False
    for title in title_candidates:
        title_norm = _filmarks_match_norm(_clean_title_for_filmarks_query(title))
        if not title_norm:
            continue
        if title_norm == candidate_norm:
            return "exact"
        if len(title_norm) >= 4 and (title_norm in candidate_norm or candidate_norm in title_norm):
            partial = True
    return "partial" if partial else "none"

def _filmarks_cache_key(item: dict, query: str) -> str:
    parts = [
        _filmarks_match_norm(query),
        str(_parse_year(item.get("year")) or ""),
        str(_parse_int(item.get("runtime_min") or item.get("runtime")) or ""),
        _filmarks_match_norm(item.get("director") or item.get("director_jp") or ""),
    ]
    return "::".join(parts)

def _extract_filmarks_candidate(cassette) -> Optional[dict]:
    onclick = cassette.get("onclick") or ""
    url_match = re.search(r"['\"](/movies/\d+)['\"]", onclick)
    if url_match:
        path = url_match.group(1)
    else:
        link = cassette.select_one('a[href^="/movies/"]')
        if not link:
            return None
        path = link.get("href", "").split("?", 1)[0]
    if not re.match(r"^/movies/\d+$", path):
        return None

    title_node = cassette.select_one(".p-content-cassette__title")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    if not title:
        poster = cassette.select_one("img[alt]")
        title = poster.get("alt", "").strip() if poster else ""
    if not title:
        return None

    text = cassette.get_text(" ", strip=True)
    year_match = re.search(r"上映日：\s*(\d{4})年", text)
    runtime_match = re.search(r"上映時間：\s*(\d+)分", text)
    director = ""
    for heading in cassette.find_all(["h4", "dt"]):
        if "監督" not in heading.get_text(" ", strip=True):
            continue
        people_list = heading.find_next("ul")
        person_link = people_list.find("a") if people_list else None
        if person_link:
            director = person_link.get_text(" ", strip=True)
            break

    return {
        "url": FILMARKS_RESULT_BASE_URL + path,
        "title": title,
        "year": year_match.group(1) if year_match else "",
        "runtime": runtime_match.group(1) if runtime_match else "",
        "director": director,
    }

def _parse_filmarks_candidates(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = []
    seen_urls = set()
    for cassette in soup.select(".js-cassette"):
        candidate = _extract_filmarks_candidate(cassette)
        if not candidate or candidate["url"] in seen_urls:
            continue
        seen_urls.add(candidate["url"])
        candidates.append(candidate)
    return candidates

def _score_filmarks_candidate(candidate: dict, query: str, item: dict) -> tuple[int, list[str], int]:
    score = 0
    reasons = []
    relation = _filmarks_title_relation(query, candidate.get("title", ""), item)
    if relation == "exact":
        score += 10
        reasons.append("title_exact")
    elif relation == "partial":
        score += 5
        reasons.append("title_partial")
    else:
        score -= 10
        reasons.append("title_miss")

    local_year = _parse_year(item.get("year"))
    candidate_year = _parse_year(candidate.get("year"))
    if local_year and candidate_year:
        if local_year == candidate_year:
            score += 3
            reasons.append("year")
        else:
            score -= 6
            reasons.append("year_mismatch")

    local_runtime = _parse_int(item.get("runtime_min") or item.get("runtime"))
    candidate_runtime = _parse_int(candidate.get("runtime"))
    if local_runtime and candidate_runtime:
        diff = abs(local_runtime - candidate_runtime)
        if diff == 0:
            score += 3
            reasons.append("runtime")
        elif diff <= 2:
            score += 1
            reasons.append("runtime_near")
        else:
            score -= 4
            reasons.append("runtime_mismatch")

    local_director = item.get("director") or item.get("director_jp") or ""
    candidate_director = candidate.get("director") or ""
    if local_director and candidate_director:
        if _normalize_person_name(local_director) == _normalize_person_name(candidate_director):
            score += 5
            reasons.append("director")
        else:
            score -= 5
            reasons.append("director_mismatch")

    support = sum(1 for reason in reasons if reason in ("year", "runtime", "runtime_near", "director"))
    return score, reasons, support

def _is_accepted_filmarks_match(best: Optional[dict], second: Optional[dict]) -> bool:
    if not best:
        return False
    reasons = best.get("reasons") or []
    score = best.get("score") or 0
    support = best.get("support") or 0
    second_score = (second or {}).get("score", -999)
    if "title_exact" not in reasons:
        return False
    if support >= 1 and score >= FILMARKS_ACCEPT_SCORE and score - second_score >= FILMARKS_ACCEPT_MARGIN:
        return True
    return support >= 2 and score >= FILMARKS_ACCEPT_SCORE + 3

def _fetch_filmarks_search(query: str, session: requests.Session) -> list[dict]:
    response = session.get(
        FILMARKS_SEARCH_BASE_URL,
        params={"q": query},
        headers={"User-Agent": FILMARKS_USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    return _parse_filmarks_candidates(response.text)

def _resolve_filmarks_entry(item: dict, query: str, session: requests.Session) -> dict:
    search_url = _build_filmarks_search_url(query)
    now = datetime.now(timezone.utc).isoformat()
    try:
        candidates = _fetch_filmarks_search(query, session)
    except Exception as exc:
        return {
            "status": "error",
            "query": query,
            "search_url": search_url,
            "error": str(exc),
            "updated_at": now,
        }

    scored = []
    for candidate in candidates:
        score, reasons, support = _score_filmarks_candidate(candidate, query, item)
        scored.append({
            **candidate,
            "score": score,
            "reasons": reasons,
            "support": support,
        })
    scored.sort(key=lambda candidate: candidate["score"], reverse=True)
    best = scored[0] if scored else None
    second = scored[1] if len(scored) > 1 else None
    accepted = _is_accepted_filmarks_match(best, second)
    return {
        "status": "accepted" if accepted else ("review" if best else "not_found"),
        "query": query,
        "search_url": search_url,
        "filmarks_url": best["url"] if accepted else "",
        "score": best.get("score") if best else None,
        "reasons": best.get("reasons") if best else [],
        "candidate": best,
        "candidate_count": len(scored),
        "updated_at": now,
    }

def enrich_listings_with_filmarks_links(listings: list, session: Optional[requests.Session] = None) -> list:
    if not env_truthy("FILMARKS_ENRICHMENT", True):
        return listings

    print("\n--- Starting Filmarks Link Enrichment ---")
    cache = load_filmarks_cache()
    updated_cache = False
    filmarks_session = session or requests.Session()
    unique_items = {}

    for item in listings:
        query, query_field = _pick_filmarks_query(item)
        if not query:
            continue
        search_url = _build_filmarks_search_url(query)
        item["filmarks_search_url"] = search_url
        key = _filmarks_cache_key(item, query)
        if not key:
            continue
        item["_filmarks_cache_key"] = key
        unique_items.setdefault(key, (item, query, query_field))

    throttle_seconds = float(os.environ.get("FILMARKS_REQUEST_DELAY", "0.5"))
    max_lookups = _parse_int(os.environ.get("FILMARKS_MAX_LOOKUPS", "")) or None
    lookups = accepted = review = not_found = errors = 0

    for key, (item, query, query_field) in unique_items.items():
        entry = cache.get(key)
        if isinstance(entry, dict):
            continue
        if max_lookups is not None and lookups >= max_lookups:
            break
        print(f"   🔗 Searching Filmarks for: {query}")
        entry = _resolve_filmarks_entry(item, query, filmarks_session)
        entry["query_field"] = query_field
        cache[key] = entry
        updated_cache = True
        lookups += 1
        status = entry.get("status")
        if status == "accepted":
            accepted += 1
            print(f"      ✅ {entry.get('filmarks_url')} (score={entry.get('score')})")
        elif status == "review":
            review += 1
            candidate = entry.get("candidate") or {}
            print(f"      ⚠️ Review: {candidate.get('title', '')} (score={entry.get('score')})")
        elif status == "not_found":
            not_found += 1
            print("      ❌ No Filmarks candidates found.")
        else:
            errors += 1
            print(f"      ❌ Filmarks lookup error: {entry.get('error')}")
        time.sleep(throttle_seconds)

    exact_count = search_count = 0
    for item in listings:
        key = item.pop("_filmarks_cache_key", "")
        entry = cache.get(key) if key else None
        if not isinstance(entry, dict):
            continue
        search_url = entry.get("search_url") or item.get("filmarks_search_url")
        if search_url:
            item["filmarks_search_url"] = search_url
            search_count += 1
        if entry.get("status") == "accepted" and entry.get("filmarks_url"):
            item["filmarks_url"] = entry["filmarks_url"]
            item["filmarks_match_confidence"] = entry.get("score")
            exact_count += 1
        else:
            item.pop("filmarks_url", None)
            item.pop("filmarks_match_confidence", None)

    if updated_cache:
        save_filmarks_cache(cache)
    print(
        "   Filmarks links: "
        f"{exact_count} exact / {search_count} search URLs. "
        f"Lookups this run: {lookups} "
        f"(accepted={accepted}, review={review}, not_found={not_found}, errors={errors})."
    )
    return listings

def _stringify_sort_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)

def _listing_sort_key(item: dict):
    return (
        _stringify_sort_value(item.get("date_text")),
        _stringify_sort_value(item.get("cinema_name")),
        _stringify_sort_value(item.get("showtime")),
        _stringify_sort_value(item.get("movie_title_jp") or item.get("movie_title")),
        _stringify_sort_value(item.get("movie_title_en")),
        _stringify_sort_value(item.get("detail_page_url")),
    )

def _prepare_listings_for_output(listings: list) -> list:
    # Stable ordering keeps daily commits small when upstream source order shifts.
    return sorted(listings, key=_listing_sort_key)

def _write_json_file(path, payload, sort_keys=False):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=sort_keys)

def _normalize_title_for_match(title: str) -> str:
    if not title:
        return ""
    cleaned = clean_title_for_tmdb(title)
    cleaned = cleaned.strip().lower()
    cleaned = re.sub(r"[\(\[\{???].*?[\)\]\}???]", "", cleaned)
    cleaned = re.sub(r"[\"'????]", "", cleaned)
    cleaned = re.sub(r"[\s:?/|\\_???????-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def _iter_title_aliases(*titles):
    seen = set()
    for title in titles:
        if not title:
            continue
        normalized = _normalize_title_for_match(title)
        if normalized and normalized not in seen:
            seen.add(normalized)
            yield normalized

def _build_tmdb_alias_index(cache: dict) -> dict:
    alias_index = {}
    for key, entry in cache.items():
        if not isinstance(key, str) or key.startswith("tmdb:") or not _is_tmdb_cache_hit(entry):
            continue
        alias_titles = (
            key,
            entry.get("tmdb_title_jp"),
            entry.get("tmdb_title_en"),
            entry.get("tmdb_title_original"),
        )
        for alias in _iter_title_aliases(*alias_titles):
            alias_index.setdefault(alias, entry)
    return alias_index

def _get_tmdb_cached_entry(cache: dict, alias_index: dict, title: str, tmdb_id=None):
    if tmdb_id:
        entry = cache.get(f"tmdb:{tmdb_id}")
        if entry is not None:
            return entry
    if title in cache:
        return cache.get(title)
    for alias in _iter_title_aliases(title):
        entry = alias_index.get(alias)
        if entry is not None:
            return entry
    return None

def _store_tmdb_cache_entry(cache: dict, alias_index: dict, title: str, details):
    cache[title] = details
    if not _is_tmdb_cache_hit(details):
        return
    cache[f"tmdb:{details['tmdb_id']}"] = details
    alias_titles = (
        title,
        details.get("tmdb_title_jp"),
        details.get("tmdb_title_en"),
        details.get("tmdb_title_original"),
    )
    for alias in _iter_title_aliases(*alias_titles):
        alias_index[alias] = details

def _build_resolution_alias_index(resolution_cache: dict) -> dict:
    alias_index = {}
    for key, entry in resolution_cache.items():
        if not isinstance(key, str):
            continue
        for alias in _iter_title_aliases(key):
            alias_index.setdefault(alias, entry)
    return alias_index

def _get_resolution_cached_entry(resolution_cache: dict, alias_index: dict, title: str):
    if title in resolution_cache:
        return resolution_cache.get(title)
    for alias in _iter_title_aliases(title):
        entry = alias_index.get(alias)
        if entry is not None:
            return entry
    return None

def _store_resolution_cache_entry(resolution_cache: dict, alias_index: dict, title: str, entry):
    resolution_cache[title] = entry
    for alias in _iter_title_aliases(title):
        alias_index[alias] = entry

def _title_synopsis_cache_keys(title: str) -> list[str]:
    keys = []
    if title:
        keys.append(f"title:{title}")
        normalized = _normalize_title_for_match(title)
        if normalized:
            keys.append(f"title_norm:{normalized}")
    return keys

def _get_synopsis_cache_keys_for_item(item: dict) -> list[str]:
    keys = []
    tmdb_id = item.get("tmdb_id")
    if tmdb_id:
        keys.append(f"tmdb:{tmdb_id}")
    for field in (
        "movie_title",
        "clean_title_jp",
        "movie_title_jp",
        "movie_title_en",
        "movie_title_original",
    ):
        keys.extend(_title_synopsis_cache_keys(item.get(field, "")))
    deduped = []
    seen = set()
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped

def _get_cached_synopsis_translation(cache: dict, item: dict):
    for key in _get_synopsis_cache_keys_for_item(item):
        if key in cache:
            return key, cache[key]
    return None, None

def _store_synopsis_translation(cache: dict, keys: list[str], translation: str):
    for key in keys:
        cache[key] = translation

def _is_usable_english_text(text: str) -> bool:
    return bool(text and str(text).strip() and not _contains_japanese(str(text)))

def _source_synopsis_for_translation(item: dict) -> str:
    for field in ("synopsis", "tmdb_overview_jp"):
        text = item.get(field)
        if text and _contains_japanese(str(text)):
            return str(text)
    return ""

def _apply_cached_synopsis_translations(listings: list, cache: dict) -> int:
    applied = 0
    for item in listings:
        if item.get("synopsis_en") and not _is_usable_english_text(item.get("synopsis_en")):
            item["synopsis_en"] = ""
        if _is_usable_english_text(item.get("synopsis_en")):
            continue
        _, cached_translation = _get_cached_synopsis_translation(cache, item)
        if _is_usable_english_text(cached_translation):
            item["synopsis_en"] = cached_translation
            applied += 1
    return applied

def _collect_synopses_to_translate(listings: list, cache: dict) -> tuple[dict, dict, int]:
    synopses_to_translate = {}
    film_key_to_items = {}
    cached_applied = 0

    for item in listings:
        if item.get("synopsis_en") and not _is_usable_english_text(item.get("synopsis_en")):
            item["synopsis_en"] = ""
        if _is_usable_english_text(item.get("synopsis_en")):
            continue

        jp_synopsis = _source_synopsis_for_translation(item)
        if not jp_synopsis:
            continue

        cache_keys = _get_synopsis_cache_keys_for_item(item)
        _, cached_translation = _get_cached_synopsis_translation(cache, item)
        if _is_usable_english_text(cached_translation):
            item["synopsis_en"] = cached_translation
            cached_applied += 1
            continue

        film_key = cache_keys[0] if cache_keys else f"title:{item.get('movie_title', '')}"
        if film_key not in synopses_to_translate:
            synopses_to_translate[film_key] = jp_synopsis
            film_key_to_items[film_key] = []
        film_key_to_items[film_key].append(item)

    return synopses_to_translate, film_key_to_items, cached_applied

def translate_missing_synopses(listings: list, cache: dict, ai_client) -> bool:
    updated_cache = False
    cached_applied = _apply_cached_synopsis_translations(listings, cache)
    if cached_applied:
        print(f"   Applied {cached_applied} cached English synopsis translations")

    if not env_truthy("AI_TRANSLATE_SYNOPSES", True):
        print("   Synopsis translation skipped; AI_TRANSLATE_SYNOPSES is disabled.")
        return updated_cache
    if not ai_client:
        print("   Synopsis translation skipped; no AI provider is configured.")
        return updated_cache
    if not ai_client.health_check():
        print("   Synopsis translation skipped; AI provider is unavailable.")
        return updated_cache

    print("\n📝 Translating missing English synopses...")
    synopses_to_translate, film_key_to_items, cached_applied = _collect_synopses_to_translate(listings, cache)
    if cached_applied:
        print(f"   Applied {cached_applied} cached English synopsis translations")
    if not synopses_to_translate:
        print("   No synopses need translation")
        return updated_cache

    print(f"   Found {len(synopses_to_translate)} unique films needing translation")
    translations = ai_client.translate_synopses(
        synopses_to_translate,
        source_language="Japanese",
    )
    translated_count = 0
    rejected_count = 0
    for film_key, en_synopsis in translations.items():
        if not _is_usable_english_text(en_synopsis):
            rejected_count += 1
            continue
        translation_keys = []
        for item in film_key_to_items.get(film_key, []):
            translation_keys.extend(_get_synopsis_cache_keys_for_item(item))
        _store_synopsis_translation(
            cache,
            translation_keys or [film_key],
            en_synopsis,
        )
        updated_cache = True
        translated_count += 1
        for item in film_key_to_items.get(film_key, []):
            item["synopsis_en"] = en_synopsis

    print(f"   ✓ Translated {translated_count} synopses")
    if rejected_count:
        print(f"   Rejected {rejected_count} translations containing Japanese text")
    return updated_cache

def _apply_letterboxd_urls(listings: list) -> None:
    for item in listings:
        tmdb_id = _parse_int(item.get("tmdb_id"))
        if tmdb_id:
            item["letterboxd_url"] = f"https://letterboxd.com/tmdb/{tmdb_id}/"
        else:
            item.pop("letterboxd_url", None)

EIGA_PREFERRED_FIELDS = (
    "movie_title",
    "movie_title_jp",
    "movie_title_en",
    "movie_title_original",
    "director",
    "director_jp",
    "director_en",
    "year",
    "country",
    "runtime_min",
    "synopsis",
    "synopsis_en",
    "detail_page_url",
    "image_url",
    "tags",
    "eiga_movie_id",
    "eiga_theater_id",
)

def _build_film_key(item: dict) -> str:
    for field in ("movie_title", "movie_title_jp", "movie_title_en", "movie_title_original"):
        value = item.get(field)
        if value:
            key = _normalize_title_for_match(value)
            if key:
                return key
    return ""

def _build_listing_key(item: dict, film_key: str) -> tuple:
    title_key = film_key or _normalize_title_for_match(item.get("movie_title", ""))
    if not title_key:
        title_key = item.get("movie_title", "")
    return (
        item.get("cinema_name", ""),
        item.get("date_text", ""),
        item.get("showtime", ""),
        title_key,
    )

def _build_eiga_film_index(listings: list) -> dict:
    film_index = {}
    for item in listings:
        film_key = _build_film_key(item)
        if not film_key:
            continue
        if film_key not in film_index:
            film_index[film_key] = {}
        meta = film_index[film_key]
        for field in EIGA_PREFERRED_FIELDS:
            value = item.get(field)
            if value and not meta.get(field):
                meta[field] = value
    return film_index

def _apply_eiga_metadata(target: dict, eiga_meta: dict) -> None:
    for field in EIGA_PREFERRED_FIELDS:
        value = eiga_meta.get(field)
        if value:
            target[field] = value

def _merge_eiga_with_legacy(eiga_listings: list, legacy_listings: list) -> list:
    film_index = _build_eiga_film_index(eiga_listings)
    merged = []
    seen = set()

    for item in eiga_listings:
        film_key = _build_film_key(item)
        key = _build_listing_key(item, film_key)
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)

    for item in legacy_listings:
        film_key = _build_film_key(item)
        merged_item = item
        if film_key and film_key in film_index:
            merged_item = dict(item)
            _apply_eiga_metadata(merged_item, film_index[film_key])
        key = _build_listing_key(merged_item, film_key)
        if key in seen:
            continue
        merged.append(merged_item)
        seen.add(key)

    return merged

def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()

def _parse_year(value):
    if not value:
        return None
    if m := re.search(r"(19|20)\d{2}", str(value)):
        return int(m.group(0))
    return None

def _parse_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None

def _normalize_person_name(name: str) -> str:
    if not name:
        return ""
    name = name.strip().lower()
    name = re.sub(r"[\s.,\u30fb]", "", name)
    return name

def _contains_japanese(text: str) -> bool:
    if not text:
        return False
    return re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text) is not None

def _pick_english_title_from_translations(translations: dict) -> str:
    if not translations:
        return ""
    entries = translations.get("translations") or []
    best_title = ""
    best_rank = 99
    for entry in entries:
        if entry.get("iso_639_1") != "en":
            continue
        data = entry.get("data") or {}
        title = data.get("title") or ""
        if not title or _contains_japanese(title):
            continue
        region = entry.get("iso_3166_1") or ""
        rank = 2
        if region == "US":
            rank = 0
        elif region == "GB":
            rank = 1
        if rank < best_rank:
            best_title = title
            best_rank = rank
    return best_title

def _pick_english_title_from_alt_titles(alt_titles: dict) -> str:
    if not alt_titles:
        return ""
    entries = alt_titles.get("titles") or []
    best_title = ""
    best_rank = 99
    english_regions = {"US", "GB", "AU", "CA", "IE", "NZ"}
    for entry in entries:
        region = entry.get("iso_3166_1") or ""
        if region not in english_regions:
            continue
        title = entry.get("title") or ""
        if not title or _contains_japanese(title):
            continue
        rank = 1 if region == "GB" else 0
        if rank < best_rank:
            best_title = title
            best_rank = rank
    return best_title

def _director_score(listing_director: str, tmdb_director: str):
    if not listing_director or not tmdb_director:
        return None
    a = _normalize_person_name(listing_director)
    b = _normalize_person_name(tmdb_director)
    if not a or not b:
        return None
    if a in b or b in a:
        return 1.0
    return _title_similarity(a, b)

def _country_score(listing_country: str, tmdb_countries):
    if not listing_country or not tmdb_countries:
        return None
    listing_tokens = [t for t in re.split(r"[\s/\uFF0F\u30fb,]+", listing_country) if t]
    if not listing_tokens:
        return None
    tmdb_tokens = set()
    for country in tmdb_countries:
        name = country.get("name") or ""
        iso = country.get("iso_3166_1") or ""
        for token in re.split(r"[\s/\uFF0F\u30fb,]+", f"{name} {iso}".strip()):
            if token:
                tmdb_tokens.add(token.lower())
    if not tmdb_tokens:
        return None
    for token in listing_tokens:
        normalized = token.lower()
        if normalized in tmdb_tokens:
            return 1.0
        for tmdb_token in tmdb_tokens:
            if normalized in tmdb_token or tmdb_token in normalized:
                return 1.0
    return 0.0

def _runtime_score(listing_runtime, tmdb_runtime):
    listing_minutes = _parse_int(listing_runtime)
    tmdb_minutes = _parse_int(tmdb_runtime)
    if not listing_minutes or not tmdb_minutes:
        return None
    diff = abs(listing_minutes - tmdb_minutes)
    if diff <= 5:
        return 1.0
    if diff <= 10:
        return 0.7
    if diff <= 20:
        return 0.4
    if diff <= 30:
        return 0.2
    return 0.0

def _title_match_score(title_info, candidate):
    query_titles = [
        _normalize_title_for_match(title_info.get("movie_title", "")),
        _normalize_title_for_match(title_info.get("movie_title_en", "")),
        _normalize_title_for_match(title_info.get("movie_title_original", "")),
    ]
    query_titles = [t for t in query_titles if t]
    candidate_titles = [
        _normalize_title_for_match(candidate.get("title", "")),
        _normalize_title_for_match(candidate.get("original_title", "")),
    ]
    candidate_titles = [t for t in candidate_titles if t]

    title_score = 0.0
    for query in query_titles:
        for cand in candidate_titles:
            title_score = max(title_score, _title_similarity(query, cand))
    return title_score

def _strong_title_match(english_title, details):
    if not english_title or not details:
        return False
    query = _normalize_title_for_match(english_title)
    if not query:
        return False
    candidates = [
        _normalize_title_for_match(details.get("tmdb_title_en", "")),
        _normalize_title_for_match(details.get("tmdb_title_jp", "")),
    ]
    candidates = [c for c in candidates if c]
    if not candidates:
        return False
    best = max(_title_similarity(query, cand) for cand in candidates)
    return best >= 0.9

def _year_match_score(listing_year, release_date):
    listing_year = _parse_year(listing_year)
    tmdb_year = _parse_year(release_date)
    if listing_year and tmdb_year:
        diff = abs(listing_year - tmdb_year)
        if diff == 0:
            return 1.0
        if diff == 1:
            return 0.3
        return -1.0
    return None

def _score_basic_candidate(candidate, title_info):
    title_score = _title_match_score(title_info, candidate)

    year_score = _year_match_score(title_info.get("year"), candidate.get("release_date"))
    year_score = year_score if year_score is not None else 0.0

    popularity = candidate.get("popularity") or 0.0
    popularity_score = min(float(popularity) / 50.0, 1.0)

    return (title_score * 0.85) + (year_score * 0.1) + (popularity_score * 0.05)

def _score_candidate_with_details(basic_score, details, title_info):
    score = basic_score * 0.7
    weight = 0.7

    year_score = _year_match_score(title_info.get("year"), details.get("release_date"))
    if year_score is not None:
        score += year_score * 0.2
        weight += 0.2

    runtime_score = _runtime_score(title_info.get("runtime_min"), details.get("runtime"))
    if runtime_score is not None:
        score += runtime_score * 0.1
        weight += 0.1

    director_score = _director_score(title_info.get("director"), details.get("director"))
    if director_score is not None:
        score += director_score * 0.1
        weight += 0.1

    country_score = _country_score(title_info.get("country"), details.get("tmdb_countries") or [])
    if country_score is not None:
        score += country_score * 0.1
        weight += 0.1

    if weight == 0:
        return basic_score
    return score / weight

def _search_tmdb(query, session, api_key, language):
    search_url = "https://api.themoviedb.org/3/search/movie"
    params = {
        "api_key": api_key,
        "query": query,
        "language": language,
        "include_adult": "false"
    }
    resp = session.get(search_url, params=params, timeout=5)
    data = resp.json()
    return data.get("results", [])

def _fetch_tmdb_details_by_id(tmdb_id, session, api_key):
    detail_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"

    # Fetch Japanese details
    params_jp = {
        "api_key": api_key,
        "language": "ja-JP",
        "append_to_response": "credits,images,translations,alternative_titles"
    }
    d_resp = session.get(detail_url, params=params_jp, timeout=5)
    d_data = d_resp.json()

    director_jp = ""
    director_id = None
    crew = d_data.get("credits", {}).get("crew", [])
    for c in crew:
        if c.get("job") == "Director":
            director_jp = c.get("name")
            director_id = c.get("id")
            break

    # Fetch English details
    overview_en = ""
    director_en = ""
    genres_en = []
    title_en = ""
    try:
        params_en = {
            "api_key": api_key,
            "language": "en-US",
            "append_to_response": "credits"
        }
        en_resp = session.get(detail_url, params=params_en, timeout=5)
        en_data = en_resp.json()
        title_en = en_data.get("title", "")
        overview_en = en_data.get("overview", "")
        genres_en = [g["name"] for g in en_data.get("genres", [])]
        en_crew = en_data.get("credits", {}).get("crew", [])
        for c in en_crew:
            if c.get("job") == "Director":
                director_en = c.get("name")
                if director_id is None:
                    director_id = c.get("id")
                break
    except Exception as e:
        print(f"   Warning: Could not fetch English details for TMDB ID {tmdb_id}: {e}")

    title_jp = d_data.get("title") or ""
    if not title_en or _contains_japanese(title_en) or (title_jp and title_en == title_jp):
        translated_title = _pick_english_title_from_translations(d_data.get("translations"))
        if not translated_title:
            translated_title = _pick_english_title_from_alt_titles(d_data.get("alternative_titles"))
        if translated_title:
            title_en = translated_title

    if director_id:
        person_url = f"https://api.themoviedb.org/3/person/{director_id}"
        try:
            person_jp_resp = session.get(
                person_url,
                params={"api_key": api_key, "language": "ja-JP"},
                timeout=5
            )
            person_jp = person_jp_resp.json()
            jp_name = person_jp.get("name") or ""
            if _contains_japanese(jp_name):
                director_jp = jp_name
            else:
                for alias in person_jp.get("also_known_as") or []:
                    if _contains_japanese(alias):
                        director_jp = alias
                        break
        except Exception as e:
            print(f"   Warning: Could not fetch Japanese director details for TMDB ID {tmdb_id}: {e}")
        try:
            person_en_resp = session.get(
                person_url,
                params={"api_key": api_key, "language": "en-US"},
                timeout=5
            )
            person_en = person_en_resp.json()
            en_name = person_en.get("name") or ""
            if en_name:
                director_en = en_name
        except Exception as e:
            print(f"   Warning: Could not fetch English director details for TMDB ID {tmdb_id}: {e}")

    if not director_jp and director_en:
        director_jp = director_en

    return {
        "tmdb_id": tmdb_id,
        "tmdb_title_jp": d_data.get("title"),
        "tmdb_title_en": title_en or d_data.get("original_title"),
        "tmdb_title_original": d_data.get("original_title"),
        "tmdb_original_language": d_data.get("original_language"),
        "overview": d_data.get("overview"),
        "overview_en": overview_en,
        "poster_path": d_data.get("poster_path"),
        "backdrop_path": d_data.get("backdrop_path"),
        "release_date": d_data.get("release_date"),
        "director": director_jp,
        "director_jp": director_jp,
        "director_en": director_en,
        "genres": [g["name"] for g in d_data.get("genres", [])],
        "genres_en": genres_en,
        "runtime": d_data.get("runtime"),
        "vote_average": d_data.get("vote_average"),
        "tmdb_countries": d_data.get("production_countries", []),
    }

def fetch_tmdb_details(title_info, session, api_key, require_year_match=False, year_tolerance=0):
    """
    Searches TMDB with JP + EN titles and scores candidates with soft heuristics.
    """
    movie_title = title_info.get("movie_title", "")
    movie_title_en = title_info.get("movie_title_en", "")
    movie_title_original = title_info.get("movie_title_original", "")

    queries = []
    seen_queries = set()

    def _add_query(query, language):
        query = (query or "").strip()
        if not query:
            return
        key = (query.lower(), language)
        if key in seen_queries:
            return
        seen_queries.add(key)
        queries.append((query, language))

    _add_query(movie_title, "ja-JP")
    cleaned_jp = clean_title_for_tmdb(movie_title)
    if cleaned_jp and cleaned_jp != movie_title:
        _add_query(cleaned_jp, "ja-JP")

    _add_query(movie_title_en, "en-US")
    cleaned_en = clean_title_for_tmdb(movie_title_en)
    if cleaned_en and cleaned_en != movie_title_en:
        _add_query(cleaned_en, "en-US")

    _add_query(movie_title_original, "en-US")
    cleaned_original = clean_title_for_tmdb(movie_title_original)
    if cleaned_original and cleaned_original != movie_title_original:
        _add_query(cleaned_original, "en-US")

    if not queries:
        print(
            "   TMDB debug: no queries available for title info. "
            f"title='{movie_title}' english='{movie_title_en}' original='{movie_title_original}'"
        )
        return None

    try:
        candidates = {}
        for query, language in queries:
            results = _search_tmdb(query, session, api_key, language)
            print(f"   TMDB debug: query='{query}' lang={language} results={len(results)}")
            for result in results:
                if "id" in result:
                    candidates[result["id"]] = result

        print(f"   TMDB debug: unique candidates={len(candidates)}")
        candidate_count = len(candidates)
        if not candidates:
            print("   TMDB debug: no candidates after search.")
            return None

        listing_year = _parse_year(title_info.get("year"))
        if require_year_match and listing_year:
            before_filter = len(candidates)
            filtered = {}
            for cand_id, cand in candidates.items():
                tmdb_year = _parse_year(cand.get("release_date"))
                if not tmdb_year:
                    continue
                if abs(tmdb_year - listing_year) > year_tolerance:
                    continue
                filtered[cand_id] = cand
            candidates = filtered
            print(
                "   TMDB debug: year filter "
                f"listing_year={listing_year} tolerance={year_tolerance} "
                f"before={before_filter} after={len(candidates)}"
            )
            if not candidates:
                print("   TMDB debug: no candidates after year filter.")
                return None
        elif require_year_match:
            print("   TMDB debug: year filter skipped (listing year missing).")

        if not candidates:
            print("   TMDB debug: no candidates available after filtering.")
            return None

        scored = [(_score_basic_candidate(cand, title_info), cand) for cand in candidates.values()]
        scored.sort(key=lambda x: x[0], reverse=True)

        best_score, best_candidate = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0

        needs_details = len(scored) > 1 and (best_score < 0.85 or (best_score - second_score) < 0.1)
        candidate_slice = scored[:3] if needs_details else scored[:1]
        print(
            "   TMDB debug: scoring "
            f"best_score={best_score:.3f} second_score={second_score:.3f} "
            f"needs_details={needs_details} candidates_considered={len(candidate_slice)}"
        )
        print(
            "   TMDB debug: best candidate "
            f"id={best_candidate.get('id')} "
            f"title='{best_candidate.get('title')}' "
            f"original='{best_candidate.get('original_title')}'"
        )

        details_by_id = {}
        for score, cand in candidate_slice:
            details = _fetch_tmdb_details_by_id(cand["id"], session, api_key)
            if details:
                details_by_id[cand["id"]] = details

        best_details = None
        best_final_score = -1.0
        for score, cand in candidate_slice:
            details = details_by_id.get(cand["id"])
            final_score = _score_candidate_with_details(score, details, title_info) if details else score
            if final_score > best_final_score:
                best_final_score = final_score
                best_details = details
                best_candidate = cand

        if not best_details:
            best_details = _fetch_tmdb_details_by_id(best_candidate["id"], session, api_key)
        if not best_details:
            print("   TMDB debug: missing details for best candidate.")
            return None

        title_score = _title_match_score(title_info, best_candidate)
        year_score = _year_match_score(title_info.get("year"), best_details.get("release_date"))
        runtime_score = _runtime_score(title_info.get("runtime_min"), best_details.get("runtime"))
        director_score = _director_score(title_info.get("director"), best_details.get("director"))
        country_score = _country_score(title_info.get("country"), best_details.get("tmdb_countries") or [])

        support_scores = [s for s in (year_score, runtime_score, director_score, country_score) if s is not None]
        has_support = any(s >= 0.7 for s in support_scores)
        director_override = (
            director_score == 1.0 and (
                (year_score is not None and year_score >= 0.9)
                or runtime_score == 1.0
                or title_score >= 0.6
            )
        )
        print(
            "   TMDB debug: match scores "
            f"title={title_score:.3f} year={(year_score if year_score is not None else 'n/a')} "
            f"runtime={(runtime_score if runtime_score is not None else 'n/a')} "
            f"director={(director_score if director_score is not None else 'n/a')} "
            f"country={(country_score if country_score is not None else 'n/a')} "
            f"final={best_final_score:.3f}"
        )

        if director_override:
            return best_details
        if best_final_score < MIN_FINAL_MATCH_SCORE:
            print(
                "   TMDB debug: reject "
                f"best_final_score={best_final_score:.3f} < {MIN_FINAL_MATCH_SCORE}"
            )
            return None
        if title_score < MIN_TITLE_MATCH_SCORE and not has_support:
            print(
                "   TMDB debug: reject "
                f"title_score={title_score:.3f} < {MIN_TITLE_MATCH_SCORE} and no support"
            )
            return None
        if not listing_year and candidate_count >= YEARLESS_SUPPORT_CANDIDATE_THRESHOLD and not has_support:
            print(
                "   TMDB debug: reject yearless listing with many candidates "
                f"candidates={candidate_count} support=False"
            )
            return None
        return best_details

    except Exception as e:
        print(f"   TMDB Error for '{movie_title}': {e}")
        return None

def _is_tmdb_cache_hit(entry):
    return isinstance(entry, dict) and entry.get("tmdb_id")

def _extract_legacy_tmdb_id(entry):
    if not isinstance(entry, dict):
        return None
    if entry.get("tmdb_id"):
        return None
    legacy_id = entry.get("id")
    if isinstance(legacy_id, int):
        return legacy_id
    if isinstance(legacy_id, str) and legacy_id.isdigit():
        return int(legacy_id)
    return None

def _build_title_info(listings):
    title_info = {}
    for item in listings:
        title = item.get("movie_title")
        if not title:
            continue
        info = title_info.setdefault(title, {
            "movie_title": title,
            "movie_title_en": "",
            "movie_title_original": "",
            "year": "",
            "runtime_min": "",
            "director": "",
            "country": "",
        })
        for field in ("movie_title_en", "movie_title_original", "year", "runtime_min", "director", "country"):
            if not info.get(field) and item.get(field):
                info[field] = item.get(field)
    return title_info

def _chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]

def _load_existing_listings(path):
    if not os.path.exists(path):
        print(f"❌ Enrich-only mode: {path} not found.")
        sys.exit(1)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"❌ Enrich-only mode: failed to read {path}: {exc}")
        sys.exit(1)
    if not isinstance(data, list):
        print(f"❌ Enrich-only mode: {path} did not contain a list.")
        sys.exit(1)
    return data

def _extract_gemini_text(payload):
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(parts, list):
        return ""
    texts = []
    for part in parts:
        if isinstance(part, dict) and part.get("text"):
            texts.append(part["text"])
    return "\n".join(texts).strip()

def _parse_gemini_json(text):
    if not text:
        return []
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if "english_title" in data or "en_title" in data or "translation" in data:
                return [data]
            data = data.get("resolutions") or data.get("translations") or data.get("results") or []
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
            try:
                data = json.loads(text[obj_start:obj_end + 1])
                if isinstance(data, dict):
                    if data.get("english_title") or data.get("en_title") or data.get("translation"):
                        return [data]
            except json.JSONDecodeError:
                pass
        return []

def _parse_gemini_fallback(text, input_title):
    if not text or not input_title:
        return None
    text = text.strip()
    text_unescaped = text.replace('\\"', '"')
    if re.search(r"\"english_title\"\s*:\s*null", text_unescaped, flags=re.IGNORECASE):
        return {"english_title": None, "release_year": None, "confidence": None, "notes": ""}
    english_match = re.search(r"\"english_title\"\s*:\s*\"([^\"]+)\"", text_unescaped, flags=re.IGNORECASE)
    if not english_match:
        english_match = re.search(r"\"en_title\"\s*:\s*\"([^\"]+)\"", text_unescaped, flags=re.IGNORECASE)
    if not english_match:
        english_match = re.search(r"\"english_title\"\s*:\s*\"?([^\"\n\r\}]+)", text_unescaped, flags=re.IGNORECASE)
    if not english_match:
        english_match = re.search(r"\"en_title\"\s*:\s*\"?([^\"\n\r\}]+)", text_unescaped, flags=re.IGNORECASE)
    english_title = ""
    if english_match:
        english_title = english_match.group(1).strip().strip('"').strip()
    if not english_title:
        return None
    year_match = re.search(r"\"release_year\"\s*:\s*(\d{4})", text_unescaped, flags=re.IGNORECASE)
    if not year_match:
        year_match = re.search(r"\"year\"\s*:\s*(\d{4})", text_unescaped, flags=re.IGNORECASE)
    confidence_match = re.search(r"\"confidence\"\s*:\s*([0-9]*\.?[0-9]+)", text_unescaped, flags=re.IGNORECASE)
    release_year = int(year_match.group(1)) if year_match else None
    confidence = float(confidence_match.group(1)) if confidence_match else None
    return {
        "english_title": english_title,
        "release_year": release_year,
        "confidence": confidence,
        "notes": "",
    }

def _gemini_year_matches(details, release_year, english_title=None):
    if not details or not release_year:
        return True
    tmdb_year = _parse_year(details.get("release_date"))
    if not tmdb_year:
        return True
    diff = abs(tmdb_year - release_year)
    if diff == 0:
        return True
    if diff == 1 and english_title and _strong_title_match(english_title, details):
        return True
    return False

def _resolve_titles_with_gemini(titles, session, api_key, model, use_search_tool, batch_size):
    if not titles:
        return {}
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    results = {}
    total_prompt_tokens = 0
    total_tool_tokens = 0
    total_output_tokens = 0

    if use_search_tool:
        batch_size = min(batch_size, 8)

    batches = list(_chunked(titles, batch_size))
    while batches:
        batch = batches.pop(0)
        if not batch:
            continue
        if len(batch) == 1:
            print(f"   Gemini resolving: {batch[0]}")
        else:
            preview_titles = ", ".join(batch[:3])
            suffix = f" (+{len(batch) - 3} more)" if len(batch) > 3 else ""
            print(f"   Gemini resolving batch: {preview_titles}{suffix}")
        if len(batch) == 1:
            prompt = (
                "You are given one Japanese film title. Use web search to find the "
                "official English title (not a literal translation). Return a single "
                "JSON object (not an array) with keys: english_title, release_year, "
                "original_title, director, country, confidence. Use null for unknown "
                "fields. If unsure, set english_title to null. Return only JSON."
            )
            title_lines = f"Title: {batch[0]}"
            max_output_tokens = 4096
        else:
            prompt = (
                "You are given Japanese film titles. Use web search to find the official "
                "English title (not a literal translation). Return JSON array of objects "
                "with keys: input_title, english_title, release_year, original_title, "
                "director, country, confidence. Use null for unknown fields. If unsure, "
                "set english_title to null. Return only JSON."
            )
            title_lines = "\n".join(f"- {title}" for title in batch)
            max_output_tokens = min(12288, max(2048, 512 * len(batch)))
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": f"{prompt}\n\nTitles:\n{title_lines}"}]}
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        if use_search_tool:
            payload["tools"] = [{"google_search": {}}]

        attempts = 0
        resp = None
        while attempts < 2:
            attempts += 1
            try:
                resp = session.post(endpoint, params={"key": api_key}, json=payload, timeout=(10, 90))
                break
            except requests.exceptions.RequestException as exc:
                print(f"   Gemini request failed (attempt {attempts}): {exc}")
                time.sleep(1.5 * attempts)
        if resp is None:
            if len(batch) > 1:
                mid = len(batch) // 2
                batches.insert(0, batch[mid:])
                batches.insert(0, batch[:mid])
            continue
        if resp.status_code != 200:
            print(f"   Gemini error {resp.status_code}: {resp.text[:300]}")
            if resp.status_code == 429 and len(batch) > 1:
                mid = len(batch) // 2
                batches.insert(0, batch[mid:])
                batches.insert(0, batch[:mid])
            continue
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            print(f"   Gemini error: {data['error']}")
            continue
        finish_reason = None
        if isinstance(data, dict):
            candidates = data.get("candidates") or []
            if candidates:
                finish_reason = candidates[0].get("finishReason")
        usage = data.get("usageMetadata") if isinstance(data, dict) else None
        if isinstance(usage, dict):
            total_prompt_tokens += int(usage.get("promptTokenCount") or 0)
            total_tool_tokens += int(usage.get("toolUsePromptTokenCount") or 0)
            total_output_tokens += int(usage.get("candidatesTokenCount") or 0)
            total_output_tokens += int(usage.get("thoughtsTokenCount") or 0)
        if finish_reason or usage:
            print(f"   Gemini debug: finishReason={finish_reason} usage={usage}")
        text = _extract_gemini_text(data)
        parsed = _parse_gemini_json(text)
        if not parsed:
            keys = list(data.keys()) if isinstance(data, dict) else []
            preview = ""
            if isinstance(text, str):
                preview = text[:400].encode("unicode_escape").decode("ascii")
            print(f"   Gemini response parse failed. Keys: {keys} Preview: {preview}")
            if len(batch) == 1:
                fallback = _parse_gemini_fallback(text, batch[0])
                if fallback is not None:
                    if not fallback.get("english_title"):
                        print(f"   Gemini returned no English title for: {batch[0]}")
                        continue
                    results[batch[0]] = fallback
                    print(
                        "   Gemini resolved (fallback): "
                        f"{batch[0]} -> {fallback['english_title']} "
                        f"(year={fallback['release_year']}, conf={fallback['confidence']})"
                    )
                    continue
                print(f"   Gemini parse failed for: {batch[0]}")
            if len(batch) > 1:
                mid = len(batch) // 2
                batches.insert(0, batch[mid:])
                batches.insert(0, batch[:mid])
            continue

        resolved_any = False
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            input_title = entry.get("input_title") or entry.get("jp_title") or entry.get("title")
            if not input_title and len(batch) == 1:
                input_title = batch[0]
            english_title = entry.get("english_title") or entry.get("en_title") or entry.get("translation")
            original_title = (
                entry.get("original_title")
                or entry.get("native_title")
                or entry.get("original_language_title")
            )
            director = entry.get("director")
            country = entry.get("country") or entry.get("countries")
            confidence = entry.get("confidence")
            notes = entry.get("notes") or ""
            release_year = entry.get("release_year") or entry.get("year")
            if not input_title or not english_title:
                continue
            if isinstance(confidence, str):
                try:
                    confidence = float(confidence)
                except ValueError:
                    confidence = None
            if isinstance(release_year, str) and release_year.isdigit():
                release_year = int(release_year)
            elif not isinstance(release_year, int):
                release_year = None
            if isinstance(director, list):
                director = director[0] if director else None
            if isinstance(country, list):
                country = "/".join(str(c) for c in country if c) or None
            if isinstance(country, dict):
                name = country.get("name") or country.get("country")
                country = name if name else None
            results[input_title] = {
                "english_title": english_title,
                "release_year": release_year,
                "confidence": confidence,
                "notes": notes,
                "original_title": original_title,
                "director": director,
                "country": country,
            }
            print(
                "   Gemini resolved: "
                f"{input_title} -> {english_title} "
                f"(year={release_year}, conf={confidence})"
            )
            resolved_any = True
        if len(batch) == 1 and not resolved_any:
            print(f"   Gemini returned no English title for: {batch[0]}")

    if total_prompt_tokens or total_tool_tokens or total_output_tokens:
        input_tokens = total_prompt_tokens + total_tool_tokens
        output_tokens = total_output_tokens
        input_cost = (input_tokens / 1_000_000) * 0.50
        output_cost = (output_tokens / 1_000_000) * 3.00
        total_cost = input_cost + output_cost
        print(
            "   Gemini usage summary: "
            f"input_tokens={input_tokens} output_tokens={output_tokens} "
            f"estimated_cost=${total_cost:.4f}"
        )
    return results


def _translate_synopses_with_gemini(synopses_to_translate, session, api_key, model):
    """
    Translates Japanese synopses to English using Gemini.

    Args:
        synopses_to_translate: dict mapping film_key -> japanese_synopsis
        session: requests session
        api_key: Gemini API key
        model: Gemini model name (e.g., 'gemini-3-flash-preview')

    Returns:
        dict mapping film_key -> english_synopsis
    """
    if not synopses_to_translate:
        return {}

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    results = {}
    total_prompt_tokens = 0
    total_output_tokens = 0

    # Process one at a time for reliability (synopses can be long)
    items = list(synopses_to_translate.items())

    for i, (film_key, jp_synopsis) in enumerate(items, 1):
        if not jp_synopsis or len(jp_synopsis.strip()) < 10:
            continue

        print(f"   Translating synopsis {i}/{len(items)}: {film_key[:50]}...")

        prompt = (
            "Translate the following Japanese film synopsis to English. "
            "Maintain the tone and style. Return only the English translation, nothing else.\n\n"
            f"Japanese synopsis:\n{jp_synopsis}"
        )

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]}
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 2048,
            },
        }

        attempts = 0
        resp = None
        while attempts < 2:
            attempts += 1
            try:
                resp = session.post(endpoint, params={"key": api_key}, json=payload, timeout=(10, 60))
                break
            except requests.exceptions.RequestException as exc:
                print(f"   Gemini translation request failed (attempt {attempts}): {exc}")
                time.sleep(1.5 * attempts)

        if resp is None:
            continue

        if resp.status_code != 200:
            print(f"   Gemini translation error {resp.status_code}: {resp.text[:200]}")
            if resp.status_code == 429:
                time.sleep(2)
            continue

        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            print(f"   Gemini translation error: {data['error']}")
            continue

        # Extract usage info
        usage = data.get("usageMetadata") if isinstance(data, dict) else None
        if isinstance(usage, dict):
            total_prompt_tokens += int(usage.get("promptTokenCount") or 0)
            total_output_tokens += int(usage.get("candidatesTokenCount") or 0)

        # Extract translated text
        translated_text = _extract_gemini_text(data)
        if translated_text:
            results[film_key] = translated_text.strip()
            print(f"   ✓ Translated: {film_key[:40]}... ({len(translated_text)} chars)")

    if total_prompt_tokens or total_output_tokens:
        # Gemini 3 flash pricing (approximate)
        input_cost = (total_prompt_tokens / 1_000_000) * 0.10
        output_cost = (total_output_tokens / 1_000_000) * 0.40
        total_cost = input_cost + output_cost
        print(
            f"   Gemini translation summary: "
            f"input_tokens={total_prompt_tokens} output_tokens={total_output_tokens} "
            f"estimated_cost=${total_cost:.4f}"
        )

    return results


def _attempt_tmdb_with_english_title(
    title,
    title_info,
    english_title,
    release_year,
    session,
    api_key,
    original_title=None,
    director=None,
    country=None,
    require_year_match=False,
    year_tolerance=0,
):
    if not english_title:
        return None
    english_title = _strip_ai_title_annotation(english_title)
    resolved_info = dict(title_info)
    resolved_info["movie_title_en"] = english_title
    if release_year:
        resolved_info["year"] = str(release_year)
    if original_title and not resolved_info.get("movie_title_original"):
        resolved_info["movie_title_original"] = original_title
    if director and not resolved_info.get("director"):
        resolved_info["director"] = director
    if country and not resolved_info.get("country"):
        resolved_info["country"] = country
    return fetch_tmdb_details(
        resolved_info,
        session,
        api_key,
        require_year_match=require_year_match,
        year_tolerance=year_tolerance,
    )

def enrich_listings_with_tmdb_links(listings, cache, session, api_key):
    """
    Iterates over listings, checks TMDB for metadata/images.
    Updates listings in-place and updates cache.
    """
    print(f"\n--- Starting Robust Enrichment for {len(listings)} listings ---")
    
    title_info = _build_title_info(listings)
    unique_titles = list(title_info.keys())
    tmdb_alias_index = _build_tmdb_alias_index(cache)
    print(f"   Unique films to process: {len(unique_titles)}")
    tmdb_ids = sorted({
        _parse_int(item.get("tmdb_id"))
        for item in listings
        if _parse_int(item.get("tmdb_id"))
    })
    if tmdb_ids:
        print(f"   TMDB IDs provided: {len(tmdb_ids)}")

    def _tmdb_coverage(label):
        total = len(unique_titles)
        if total == 0:
            return
        matched = sum(
            1 for title in unique_titles
            if _is_tmdb_cache_hit(_get_tmdb_cached_entry(cache, tmdb_alias_index, title))
        )
        percent = (matched / total) * 100
        print(f"   TMDB coverage {label}: {matched}/{total} ({percent:.1f}%)")
    
    updated_cache = False
    retry_not_found = os.environ.get("TMDB_RETRY_NOT_FOUND", "").lower() in ("1", "true", "yes")

    for tmdb_id in tmdb_ids:
        cache_key = f"tmdb:{tmdb_id}"
        cached = cache.get(cache_key)
        if _is_tmdb_cache_hit(cached):
            continue
        print(f"   🔍 Fetching TMDB details by ID: {tmdb_id}")
        details = _fetch_tmdb_details_by_id(tmdb_id, session, api_key)
        if details:
            _store_tmdb_cache_entry(cache, tmdb_alias_index, cache_key, details)
            updated_cache = True
            print(f"      ✅ Found: {details['tmdb_title_jp']} (ID: {details['tmdb_id']})")
        else:
            cache[cache_key] = None
            updated_cache = True
            print("      ❌ Not found.")
        time.sleep(0.3)
    
    for title, info in title_info.items():
        has_cache_entry = title in cache
        cache_entry = cache.get(title)
        if has_cache_entry and _is_tmdb_cache_hit(cache_entry):
            continue
        if not has_cache_entry and _is_tmdb_cache_hit(_get_tmdb_cached_entry(cache, tmdb_alias_index, title)):
            continue
        if has_cache_entry and cache_entry is None and not retry_not_found:
            continue
        
        legacy_id = _extract_legacy_tmdb_id(cache_entry)
        if legacy_id:
            print(f"   🔍 Fetching TMDB details by cached ID: {title}")
            details = _fetch_tmdb_details_by_id(legacy_id, session, api_key)
            if details:
                _store_tmdb_cache_entry(cache, tmdb_alias_index, title, details)
                updated_cache = True
                print(f"      ✅ Found: {details['tmdb_title_jp']} (ID: {details['tmdb_id']})")
            else:
                cache[title] = None
                updated_cache = True
                print("      ❌ Not found.")
            time.sleep(0.3)
            continue
        
        print(f"   🔍 Searching TMDB for: {title}")
        # Re-issues (4K restorations, anniversary revivals) list the RE-RELEASE year,
        # not the film's year, so the hard year filter would reject the real (old)
        # TMDB entry. Blank the year for these and let the title/runtime/director
        # acceptance gate carry the match instead.
        search_info = info
        if _is_reissue_title(title) and info.get("year"):
            search_info = dict(info)
            search_info["year"] = ""
            print(f"      ↺ Re-issue detected; ignoring listing year {info.get('year')!r} for match.")
            details = fetch_tmdb_details(search_info, session, api_key, require_year_match=False)
        else:
            details = fetch_tmdb_details(search_info, session, api_key, require_year_match=True, year_tolerance=0)
        
        if details:
            _store_tmdb_cache_entry(cache, tmdb_alias_index, title, details)
            updated_cache = True
            print(f"      ✅ Found: {details['tmdb_title_jp']} (ID: {details['tmdb_id']})")
        else:
            cache[title] = None
            updated_cache = True
            print("      ❌ Not found.")
        
        time.sleep(0.3)

    _tmdb_coverage("before AI")

    resolution_cache = load_title_resolution_cache()
    resolution_cache_updated = False

    ai_client = AIEnrichmentClient.from_env(session)
    ai_provider = ai_client.provider if ai_client else ""
    ai_resolve_titles = bool(ai_client) and env_truthy("AI_RESOLVE_TITLES", True)
    ai_use_search_tool = bool(ai_client and ai_provider == "gemini" and env_truthy("GEMINI_USE_SEARCH_TOOL", True))
    ai_batch_size = _parse_int(os.environ.get("AI_BATCH_SIZE") or os.environ.get("GEMINI_BATCH_SIZE") or "1") or 1
    ai_confidence_threshold = float(
        os.environ.get("AI_CONFIDENCE_THRESHOLD") or os.environ.get("GEMINI_CONFIDENCE_THRESHOLD") or "0.6"
    )
    ai_retry_low_confidence = env_truthy("AI_RETRY_LOW_CONFIDENCE", False)
    local_ai_retry_hours = retry_hours_from_env()

    if ai_client and not ai_client.health_check():
        print("   AI enrichment skipped for now; local provider is unavailable.")

    resolution_alias_index = _build_resolution_alias_index(resolution_cache)
    unresolved_titles = [
        title for title in unique_titles
        if not _is_tmdb_cache_hit(_get_tmdb_cached_entry(cache, tmdb_alias_index, title))
    ]
    titles_to_resolve = []

    for title in unresolved_titles:
        info = title_info[title]
        if info.get("movie_title_en"):
            continue

        cached_entry = _get_resolution_cached_entry(resolution_cache, resolution_alias_index, title)
        cached_english_title = None
        cached_confidence = None
        cached_release_year = None
        cached_original_title = None
        cached_director = None
        cached_country = None
        if isinstance(cached_entry, dict):
            if cached_entry.get("failed"):
                if local_ai_retry_due(cached_entry, local_ai_retry_hours):
                    cached_entry = None
                else:
                    continue
        if isinstance(cached_entry, dict):
            cached_english_title = cached_entry.get("english_title")
            cached_confidence = cached_entry.get("confidence")
            cached_release_year = cached_entry.get("release_year")
            cached_original_title = cached_entry.get("original_title")
            cached_director = cached_entry.get("director")
            cached_country = cached_entry.get("country")
            if isinstance(cached_release_year, str) and cached_release_year.isdigit():
                cached_release_year = int(cached_release_year)
        elif isinstance(cached_entry, str):
            cached_english_title = cached_entry

        # A falsy confidence (None or 0.0) means "unknown" — try the lookup anyway,
        # since TMDB re-validation is the real accuracy gate. Only a positive
        # confidence below the threshold is treated as a genuine low-confidence skip.
        if cached_english_title and (
            not cached_confidence
            or cached_confidence >= ai_confidence_threshold
            or ai_retry_low_confidence
        ):
            use_release_year = cached_release_year
            print(
                "   🔁 Retrying TMDB with cached English title: "
                f"{title} -> {cached_english_title} "
                f"(cached_year={cached_release_year}, used_year={use_release_year})"
            )
            details = _attempt_tmdb_with_english_title(
                title,
                info,
                cached_english_title,
                use_release_year,
                session,
                api_key,
                original_title=cached_original_title,
                director=cached_director,
                country=cached_country,
            )
            if details and use_release_year and not _gemini_year_matches(details, use_release_year, cached_english_title):
                tmdb_year = _parse_year(details.get("release_date"))
                print(
                    f"      ⚠️ Year mismatch for {title}: "
                    f"ai_year={use_release_year}, tmdb_year={tmdb_year}. "
                    "Skipping TMDB match."
                )
                details = None
            if details:
                _store_tmdb_cache_entry(cache, tmdb_alias_index, title, details)
                updated_cache = True
                print(f"      ✅ Found: {details['tmdb_title_jp']} (ID: {details['tmdb_id']})")
            if not details:
                print(f"      ❌ TMDB retry failed for cached English title: {title}")
                if isinstance(cached_entry, dict):
                    failed_entry = dict(cached_entry)
                    failed_entry["failed"] = True
                    failed_entry.setdefault("notes", TMDB_RETRY_FAILED)
                else:
                    failed_entry = {
                        "english_title": cached_english_title,
                        "release_year": cached_release_year,
                        "confidence": cached_confidence,
                        "notes": TMDB_RETRY_FAILED,
                        "failed": True,
                    }
                _store_resolution_cache_entry(resolution_cache, resolution_alias_index, title, failed_entry)
                resolution_cache_updated = True
            time.sleep(0.3)
            continue
        if cached_english_title and cached_confidence and cached_confidence < ai_confidence_threshold:
            print(
                "   AI cached English title skipped due to low confidence: "
                f"{title} -> {cached_english_title} (conf={cached_confidence})"
            )

        if ai_resolve_titles and not cached_english_title:
            titles_to_resolve.append(title)

    if ai_client and ai_resolve_titles and titles_to_resolve and ai_client.health_check():
        print(f"   🤖 Resolving English titles with AI for {len(titles_to_resolve)} titles...")
        # Feed the AI the director/year/country the listing already carries — for
        # JP-titled repertory classics this is the difference between a hit and a null.
        resolve_hints = {}
        for t in titles_to_resolve:
            info = title_info.get(t, {})
            hint = {
                "director": info.get("director") or info.get("director_jp") or info.get("director_en"),
                "year": info.get("year"),
                "country": info.get("country"),
            }
            if any(hint.values()):
                resolve_hints[t] = hint
        resolutions = ai_client.resolve_titles(
            titles_to_resolve,
            source_language="Japanese",
            language_key="jp_title",
            batch_size=ai_batch_size,
            use_search_tool=ai_use_search_tool,
            hints=resolve_hints,
        )

        for title, entry in resolutions.items():
            _store_resolution_cache_entry(resolution_cache, resolution_alias_index, title, entry)
            resolution_cache_updated = True

        missing_after = [title for title in titles_to_resolve if title not in resolutions]
        if missing_after:
            note = ai_client.last_error_note or LOCAL_AI_NO_RESULT
            for title in missing_after:
                _store_resolution_cache_entry(
                    resolution_cache,
                    resolution_alias_index,
                    title,
                    make_ai_failure_entry(note, ai_provider),
                )
            resolution_cache_updated = True

        for title, entry in resolutions.items():
            english_title = entry.get("english_title")
            confidence = entry.get("confidence")
            release_year = entry.get("release_year")
            original_title = entry.get("original_title")
            director = entry.get("director")
            country = entry.get("country")
            if confidence is not None and confidence < ai_confidence_threshold:
                print(
                    "   AI English title skipped due to low confidence: "
                    f"{title} -> {english_title} (conf={confidence})"
                )
                continue
            if english_title:
                info = title_info.get(title, {"movie_title": title})
                use_release_year = release_year
                print(
                    "   🔁 Retrying TMDB with AI English title: "
                    f"{title} -> {english_title} "
                    f"(ai_year={release_year}, used_year={use_release_year})"
                )
                details = _attempt_tmdb_with_english_title(
                    title,
                    info,
                    english_title,
                    use_release_year,
                    session,
                    api_key,
                    original_title=original_title,
                    director=director,
                    country=country,
                )
                if details and use_release_year and not _gemini_year_matches(details, use_release_year, english_title):
                    tmdb_year = _parse_year(details.get("release_date"))
                    print(
                        f"      ⚠️ Year mismatch for {title}: "
                        f"ai_year={use_release_year}, tmdb_year={tmdb_year}. "
                        "Skipping TMDB match."
                    )
                    details = None
                if details:
                    _store_tmdb_cache_entry(cache, tmdb_alias_index, title, details)
                    updated_cache = True
                    print(f"      ✅ Found: {details['tmdb_title_jp']} (ID: {details['tmdb_id']})")
                if not details:
                    print(f"      ❌ TMDB retry failed for AI English title: {title}")
                    failed_entry = dict(entry)
                    failed_entry["failed"] = True
                    failed_entry.setdefault("notes", TMDB_RETRY_FAILED)
                    _store_resolution_cache_entry(resolution_cache, resolution_alias_index, title, failed_entry)
                    resolution_cache_updated = True
            time.sleep(0.3)
    elif ai_client and ai_resolve_titles and titles_to_resolve:
        note = ai_client.last_error_note or LOCAL_AI_NO_RESULT
        for title in titles_to_resolve:
            _store_resolution_cache_entry(
                resolution_cache,
                resolution_alias_index,
                title,
                make_ai_failure_entry(note, ai_provider),
            )
        resolution_cache_updated = True

    _tmdb_coverage("after AI")

    # Apply cached data to listings
    for item in listings:
        t = item["movie_title"]
        tmdb_id = _parse_int(item.get("tmdb_id"))
        d = _get_tmdb_cached_entry(cache, tmdb_alias_index, t, tmdb_id=tmdb_id)
        if not _is_tmdb_cache_hit(d):
            continue
        # Merge fields if missing in scraper data
        if not item.get("tmdb_id") and d.get("tmdb_id"):
            item["tmdb_id"] = d["tmdb_id"]
        if not item.get("tmdb_backdrop_path") and d.get("backdrop_path"):
            item["tmdb_backdrop_path"] = d.get("backdrop_path")
        if not item.get("tmdb_poster_path") and d.get("poster_path"):
            item["tmdb_poster_path"] = d.get("poster_path")
        if not item.get("tmdb_overview_jp") and d.get("overview"):
            item["tmdb_overview_jp"] = d.get("overview")
        if not item.get("tmdb_overview_en") and d.get("overview_en"):
            item["tmdb_overview_en"] = d.get("overview_en")
        if not item.get("clean_title_jp") and d.get("tmdb_title_jp"):
            item["clean_title_jp"] = d.get("tmdb_title_jp")

        # Prefer TMDB posters; only keep eiga image when TMDB has none
        if item.get("tmdb_poster_path"):
            if item.get("image_url"):
                item["image_url"] = ""
        if not item.get("movie_title_jp"):
            item["movie_title_jp"] = d.get("tmdb_title_jp") or item.get("movie_title") or ""
        title_jp = item.get("movie_title_jp") or item.get("movie_title") or ""
        if not item.get("movie_title_original") and d.get("tmdb_title_original"):
            item["movie_title_original"] = d.get("tmdb_title_original")
        if not item.get("original_language") and d.get("tmdb_original_language"):
            item["original_language"] = d.get("tmdb_original_language")
        if item.get("runtime") in (None, "") and d.get("runtime") is not None:
            item["runtime"] = d.get("runtime")
        if not item.get("genres") and d.get("genres"):
            item["genres"] = d.get("genres")
        if item.get("vote_average") in (None, "") and d.get("vote_average") is not None:
            item["vote_average"] = d.get("vote_average")

        # If scraper didn't provide English title
        if d.get("tmdb_title_en"):
            current_en = item.get("movie_title_en") or ""
            if (not current_en) or _contains_japanese(current_en) or (title_jp and current_en == title_jp):
                item["movie_title_en"] = d.get("tmdb_title_en")

        # If scraper didn't provide Director
        if not item.get("director"):
            item["director"] = d.get("director")
        if not item.get("director_jp"):
            item["director_jp"] = d.get("director_jp") or d.get("director") or item.get("director") or ""

        # Add English director name from TMDB
        if not item.get("director_en") and d.get("director_en"):
            item["director_en"] = d.get("director_en")

        # Add English genres from TMDB
        if not item.get("genres_en") and d.get("genres_en"):
            item["genres_en"] = d.get("genres_en")

        # Always prefer TMDB year if available, as cinemas often list local release year
        if d.get("release_date"):
            item["year"] = d["release_date"].split("-")[0]

    if updated_cache:
        save_tmdb_cache(cache)
    if resolution_cache_updated:
        save_title_resolution_cache(resolution_cache)
        
    return listings

# --- Scraper Runner Wrapper ---

def _run_scraper(name, func, listings_list, normalize_func=None, warn_if_empty=True):
    """
    Runs a scraper function with robust error handling and reporting.
    """
    print(f"\nScraping {name} ...")
    try:
        # Run the scraper
        rows = func() or []

        # A small retry helps avoid false zero-row warnings when a live page
        # briefly fails to load or parses incompletely.
        if not rows and name in ZERO_COUNT_RETRY_CINEMAS:
            print(f"   ↻ Retrying {name} once because the first pass returned 0 rows...")
            time.sleep(1.5)
            rows = func() or []
        
        # Apply normalization if needed (e.g. for Eurospace)
        if normalize_func and rows:
            rows = normalize_func(rows)
        
        count = len(rows)
        print(f"→ {count} showings from {name}.")
        listings_list.extend(rows)
        
        # Report Success
        report.add(name, "SUCCESS", count, warn_if_empty=warn_if_empty)
        
    except SystemExit as e:
        # Some scraper modules still call sys.exit() on network or parse failures.
        # Catch it here so one broken module does not abort the rest of the run.
        print(f"⚠️ Error in {name}: {e}")
        report.add(name, "FAILURE", 0, error=e)
    except Exception as e:
        # Report Failure but DO NOT CRASH main execution
        print(f"⚠️ Error in {name}: {e}")
        # traceback.print_exc() # Uncomment for deep debugging
        report.add(name, "FAILURE", 0, error=e)

# --- Main Execution ---

def main():
    # --- TIMEZONE SAFETY CHECK ---
    # Ensure we're using JST explicitly to match generate_post.py
    JST = timezone(timedelta(hours=9))
    now_utc = datetime.now(timezone.utc)
    now_jst = now_utc.astimezone(JST)
    today_jst = now_jst.date()

    print(f"🕒 Scraper Start Time:")
    print(f"   UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"   JST: {now_jst.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"   Today (JST): {today_jst.isoformat()}")
    print(f"   System timezone: {time.tzname}")
    print()

    tmdb_key = os.environ.get("TMDB_API_KEY")
    if not tmdb_key:
        print("⚠️ Warning: TMDB_API_KEY not found. Metadata enrichment will be skipped.")

    # Prepare TMDB session
    api_session = requests.Session()
    tmdb_cache = load_tmdb_cache()
    reset_stale_tmdb_nulls(tmdb_cache)
    synopsis_translation_cache = load_synopsis_translation_cache()
    synopsis_translation_cache_updated = False

    sample_unmatched = None
    for i, arg in enumerate(sys.argv):
        if arg in ("--sample-unmatched", "--sample_unmatched"):
            if i + 1 < len(sys.argv):
                sample_unmatched = _parse_int(sys.argv[i + 1])
        elif arg.startswith("--sample-unmatched=") or arg.startswith("--sample_unmatched="):
            _, value = arg.split("=", 1)
            sample_unmatched = _parse_int(value)

    enrich_only = "--enrich-only" in sys.argv or "--enrich_only" in sys.argv
    if enrich_only:
        print(f"Enrich-only mode: loading existing listings from {OUTPUT_JSON}...")
        listings = _load_existing_listings(OUTPUT_JSON)
        print(f"Loaded {len(listings)} listings.")
        output_path = OUTPUT_JSON
        if sample_unmatched:
            unmatched_titles = sorted({
                item.get("movie_title")
                for item in listings
                if item.get("movie_title") and not item.get("tmdb_id")
            })
            if not unmatched_titles:
                print("No unmatched titles available for sampling.")
                return
            sample_size = min(sample_unmatched, len(unmatched_titles))
            sample_titles = set(random.Random(42).sample(unmatched_titles, sample_size))
            listings = [item for item in listings if item.get("movie_title") in sample_titles]
            output_path = os.path.join(DATA_DIR, "showtimes.sample.json")
            print(f"Enrich-only sample mode: {sample_size} titles -> {len(listings)} listings.")
        if tmdb_key:
            listings = enrich_listings_with_tmdb_links(listings, tmdb_cache, api_session, tmdb_key)

        ai_client = AIEnrichmentClient.from_env(api_session)
        if translate_missing_synopses(listings, synopsis_translation_cache, ai_client):
            synopsis_translation_cache_updated = True

        listings = enrich_listings_with_filmarks_links(listings, api_session)
        _apply_letterboxd_urls(listings)

        print(f"Saving to {output_path}...")
        listings = _prepare_listings_for_output(listings)

        today_count = sum(1 for item in listings if item.get("date_text") == today_jst.isoformat())
        all_dates = set(item.get("date_text") for item in listings if item.get("date_text"))
        print(f"\n📊 Data Summary:")
        print(f"   Total listings: {len(listings)}")
        print(f"   Listings for today ({today_jst.isoformat()}): {today_count}")
        print(f"   Unique dates in data: {sorted(all_dates)[:10]}")

        if today_count == 0 and listings:
            print(f"\n⚠️  WARNING: No listings found for today ({today_jst.isoformat()})!")
            print("   This may cause generate_post.py to fail or show old data.")
            print("   Cinema websites may not have updated their schedules yet.")

        try:
            _write_json_file(output_path, listings)
            print("✅ Done.")
        except Exception as e:
            print(f"❌ Critical Error saving JSON: {e}")
            sys.exit(1)
        if synopsis_translation_cache_updated:
            save_synopsis_translation_cache(synopsis_translation_cache)
        return

    eiga_listings = []
    legacy_listings = []

    # 1. DEFINE SCRAPERS TO RUN
    # Format: (Display Name, Function Object, Optional Normalizer)
    eiga_scrapers_to_run = [
        ("Eiga.com Tokyo", eiga_tokyo_module.scrape_eiga_tokyo, None),
        ("Eiga.com Kanagawa", eiga_kanagawa_module.scrape_eiga_kanagawa, None),
        ("Eiga.com Saitama", eiga_saitama_module.scrape_eiga_saitama, None),
        ("Eiga.com Chiba", eiga_chiba_module.scrape_eiga_chiba, None),
    ]

    legacy_scrapers_to_run = [
        ("Bunkamura", bunkamura_module.scrape_bunkamura, None),
        ("K's Cinema", ks_cinema_module.scrape_ks_cinema, None),
        ("Shin-Bungeiza", shin_bungeiza_module.scrape_shin_bungeiza, None),
        ("Shimotakaido Cinema", shimotakaido_module.scrape_shimotakaido, None),
        ("Stranger", stranger_module.scrape_stranger, None),
        ("Meguro Cinema", meguro_cinema_module.scrape_meguro_cinema, None),
        ("Image Forum", image_forum_module.scrape, None),
        ("Theatre Shinjuku", theatre_shinjuku_module.scrape_theatre_shinjuku, None),
        ("Pole Pole Higashi-Nakano", polepole_module.scrape_polepole, None),
        ("Cinema Blue Studio", bluestudio_module.scrape_bluestudio, None),
        ("Human Trust Cinema Shibuya", human_shibuya_module.scrape_human_shibuya, None),
        ("Human Trust Cinema Yurakucho", human_yurakucho_module.scrape_human_yurakucho, None),
        ("Laputa Asagaya", laputa_asagaya_module.scrape_laputa_asagaya, None),
        ("Shinjuku Musashino-kan", musashino_kan_module.scrape_musashino_kan, None),
        ("Waseda Shochiku", waseda_shochiku_module.scrape_waseda_shochiku, None, False),
        ("National Film Archive", nfaj_module.scrape_nfaj_calendar, None),
        ("Cinemart Shinjuku", cinemart_shinjuku_module.scrape_cinemart_shinjuku, None),
        ("Cine Quinto", cine_quinto_module.scrape_cine_quinto, None),
        ("Yebisu Garden Cinema", yebisu_garden_module.scrape_yebisu_garden_cinema, None),
        ("K2 Cinema", k2_cinema_module.scrape_k2_cinema, None),
        ("Kino Cinema", kino_cinema_module.scrape_kino_cinema, None),
        ("Cinema Rosa", cinema_rosa_module.scrape_cinema_rosa, None),
        ("Chupki", chupki_module.scrape_chupki, None),
        ("Uplink Kichijoji", uplink_kichijoji_module.scrape_uplink_kichijoji, None),
        ("Tollywood", tollywood_module.scrape_tollywood, None),
        ("Morc Asagaya", morc_asagaya_module.fetch_morc_asagaya_showings, None),
        ("Eurospace", eurospace_module.scrape, _normalize_eurospace_schema),
        ("CineMalice", cinemalice_module.scrape_cinemalice, None),
        ("Cine Switch Ginza", cine_switch_ginza_module.scrape_cine_switch_ginza, None),
        ("Jinbocho Theatre", jinbocho_theatre_module.scrape_jinbocho, None),
        ("Cinema Vera Shibuya", cinema_vera_module.scrape_cinema_vera, None),
        ("Institut Francais Tokyo", institut_francais_module.scrape_institut_francais, None),
        ("Jack and Betty Yokohama", jack_and_betty_module.scrape_jack_and_betty, None),
        ("Cinema Novecento", cinema_novecento_module.scrape_cinema_novecento, None),
        ("Athenee Francais", athenee_francais_module.scrape_athenee_francais, None, False),
        ("White Cine Quinto", white_cine_quinto_module.scrape_white_cine_quinto, None),
        ("Yokohama Cinemarine", yokohama_cinemarine_module.scrape_yokohama_cinemarine, None),
        ("Kadokawa Cinema Yurakucho", kadokawa_yurakucho_module.scrape_kadokawa_yurakucho, None),
        ("Cinema Neko Ome", cinema_neko_module.scrape_cinema_neko, None),
        ("Koenji Theater Bacchus", koenji_bacchus_module.scrape_koenji_bacchus, None, False),
        ("Koenji Cinema Club", koenji_cinema_club_module.scrape_koenji_cinema_club, None, False),
        ("Cinema Amigo", cinema_amigo_module.scrape_cinema_amigo, None),
    ]

    # 2. RUN THEM ONE BY ONE
    for item in eiga_scrapers_to_run:
        name = item[0]
        func = item[1]
        norm = item[2] if len(item) > 2 else None
        warn_if_empty = item[3] if len(item) > 3 else True
        _run_scraper(name, func, eiga_listings, normalize_func=norm, warn_if_empty=warn_if_empty)

    for item in legacy_scrapers_to_run:
        name = item[0]
        func = item[1]
        norm = item[2] if len(item) > 2 else None
        warn_if_empty = item[3] if len(item) > 3 else True
        _run_scraper(name, func, legacy_listings, normalize_func=norm, warn_if_empty=warn_if_empty)

    listings = _merge_eiga_with_legacy(eiga_listings, legacy_listings)

    # 3. ENRICHMENT
    print(f"\nCollected a total of {len(listings)} showings.")

    if tmdb_key:
        listings = enrich_listings_with_tmdb_links(listings, tmdb_cache, api_session, tmdb_key)

    ai_client = AIEnrichmentClient.from_env(api_session)
    if translate_missing_synopses(listings, synopsis_translation_cache, ai_client):
        synopsis_translation_cache_updated = True

    for item in listings:
        if not item.get("movie_title_jp"):
            item["movie_title_jp"] = item.get("movie_title") or ""
        if "movie_title_en" not in item:
            item["movie_title_en"] = ""
        if not item.get("director_jp"):
            item["director_jp"] = item.get("director") or ""
        if "director_en" not in item:
            item["director_en"] = ""

    listings = enrich_listings_with_filmarks_links(listings, api_session)
    _apply_letterboxd_urls(listings)

    # 4. SAVE OUTPUT
    print(f"Saving to {OUTPUT_JSON}...")
    listings = _prepare_listings_for_output(listings)

    # --- DATE VALIDATION ---
    # Check if we have data for today (JST) to help diagnose date issues
    today_count = sum(1 for item in listings if item.get("date_text") == today_jst.isoformat())
    all_dates = set(item.get("date_text") for item in listings if item.get("date_text"))

    print(f"\n📊 Data Summary:")
    print(f"   Total listings: {len(listings)}")
    print(f"   Listings for today ({today_jst.isoformat()}): {today_count}")
    print(f"   Unique dates in data: {sorted(all_dates)[:10]}")

    if today_count == 0 and listings:
        print(f"\n⚠️  WARNING: No listings found for today ({today_jst.isoformat()})!")
        print(f"   This may cause generate_post.py to fail or show old data.")
        print(f"   Cinema websites may not have updated their schedules yet.")

    try:
        _write_json_file(OUTPUT_JSON, listings)
        print("✅ Done.")
    except Exception as e:
        print(f"❌ Critical Error saving JSON: {e}")
        sys.exit(1)
    if synopsis_translation_cache_updated:
        save_synopsis_translation_cache(synopsis_translation_cache)

    link_coverage_warn_threshold = float(os.environ.get("LINK_COVERAGE_WARN_THRESHOLD", "0.95"))
    linkless_count = sum(
        1 for item in listings
        if not item.get("detail_page_url") and not item.get("purchase_url")
    )
    link_coverage = ((len(listings) - linkless_count) / len(listings)) if listings else 1.0
    print(
        f"   Detail/booking URL coverage: {link_coverage:.1%} "
        f"({linkless_count} missing)"
    )
    if link_coverage < link_coverage_warn_threshold:
        report.add(
            "Listing links",
            "WARNING",
            0,
            error=(
                f"{linkless_count} listings missing detail/booking URLs "
                f"({link_coverage:.1%} coverage)"
            ),
        )

    # 5. REPORTING & ALERTS
    failures, warnings = report.print_summary()
    
    # Send email if configured
    report.send_email_alert(failures, warnings)

    fail_on_failures = os.environ.get("SCRAPER_FAIL_ON_FAILURE", "").lower() in ("1", "true", "yes")
    fail_on_warnings = os.environ.get("SCRAPER_FAIL_ON_WARNING", "").lower() in ("1", "true", "yes")
    fail_reasons = []
    if fail_on_failures and failures:
        fail_reasons.append(f"{len(failures)} scraper failure(s)")
    if fail_on_warnings and warnings:
        fail_reasons.append(f"{len(warnings)} scraper warning(s)")
    if fail_reasons:
        print(
            "❌ Failing run due to scrape health policy: "
            + ", ".join(fail_reasons)
        )
        sys.exit(1)

if __name__ == "__main__":
    main()
