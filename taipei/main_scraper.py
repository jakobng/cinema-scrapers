#!/usr/bin/env python3
from __future__ import annotations

import difflib
import io
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from cinema_modules import (
    clab_module,
    eslite_arthouse_module,
    fuzhong15_module,
    guling_street_module,
    in89_taoyuan_module,
    in89_ximen_module,
    lightbox_module,
    skyline_film_module,
    spot_huashan_module,
    spot_taipei_module,
    taipei_film_festival_module,
    taipei_cinema_park_module,
    taoyuan_arts_cinema_ii_module,
    tfam_module,
    tfai_opentix_module,
    tiqff_module,
    treasure_hill_module,
    women_make_waves_module,
    wonderful_theatre_module,
    zhongli_arts_cinema_module,
)

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DATA_DIR = Path("data")
OUTPUT_JSON = DATA_DIR / "showtimes.json"
TMDB_CACHE_FILE = DATA_DIR / "tmdb_cache.json"
TITLE_RESOLUTION_CACHE_FILE = DATA_DIR / "title_resolution_cache.json"
SYNOPSIS_TRANSLATION_CACHE_FILE = DATA_DIR / "synopsis_translation_cache.json"
TAIPEI_TZ = timezone(timedelta(hours=8))


class ScrapeReport:
    def __init__(self) -> None:
        self.results: List[Dict[str, object]] = []
        self.total_showings = 0

    def add(self, cinema_name: str, status: str, count: int, error: Optional[Exception] = None) -> None:
        self.results.append(
            {
                "cinema": cinema_name,
                "status": status,
                "count": count,
                "error": str(error) if error else None,
            }
        )
        self.total_showings += count

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("TAIPEI SCRAPE HEALTH REPORT")
        print("=" * 60)
        print(f"{'STATUS':<8} {'VENUE':<28} {'COUNT':<6} NOTES")
        print("-" * 60)
        for item in self.results:
            notes = item["error"] or ""
            print(f"{item['status']:<8} {item['cinema']:<28} {item['count']:<6} {notes}")
        print("-" * 60)
        print(f"Total showings collected: {self.total_showings}")


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json_cache(path: Path) -> Dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_json_cache(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_tmdb_cache() -> Dict[str, Dict]:
    return _load_json_cache(TMDB_CACHE_FILE)


def save_tmdb_cache(cache: Dict[str, Dict]) -> None:
    _save_json_cache(TMDB_CACHE_FILE, cache)


def load_title_resolution_cache() -> Dict[str, Dict]:
    return _load_json_cache(TITLE_RESOLUTION_CACHE_FILE)


def save_title_resolution_cache(cache: Dict[str, Dict]) -> None:
    _save_json_cache(TITLE_RESOLUTION_CACHE_FILE, cache)


def load_synopsis_translation_cache() -> Dict[str, str]:
    return _load_json_cache(SYNOPSIS_TRANSLATION_CACHE_FILE)


def save_synopsis_translation_cache(cache: Dict[str, str]) -> None:
    _save_json_cache(SYNOPSIS_TRANSLATION_CACHE_FILE, cache)


def normalize_title_for_match(title: str) -> str:
    cleaned = (title or "").lower().strip()
    cleaned = re.sub(r"[【】\[\]（）()「」『』《》〈〉:：]", " ", cleaned)
    cleaned = re.sub(r"[\"'`.,!?/\\|_+-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def clean_title_for_tmdb(title: str) -> str:
    cleaned = normalize_title_for_match(title)
    cleaned = re.sub(r"^(?:【[^】]+】\s*)+", "", cleaned)
    cleaned = re.sub(
        r"\s*(4k|2k|數位修復版|數位修復|經典電影院|早安！周日經典電影院|特別放映|影展版|限定版)\s*$",
        "",
        cleaned,
    )
    return cleaned.strip()


def _parse_year(value: object) -> Optional[int]:
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def _parse_int(value: object) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_float(value: object, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def _chunked(items: List[str], size: int) -> List[List[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _contains_cjk(text: str) -> bool:
    if not text:
        return False
    return re.search(r"[\u3400-\u9fff]", text) is not None


def _iter_title_aliases(*titles: object) -> List[str]:
    seen = set()
    aliases: List[str] = []
    for title in titles:
        value = str(title or "").strip()
        if not value:
            continue
        for candidate in (value, normalize_title_for_match(value), clean_title_for_tmdb(value)):
            candidate = str(candidate or "").strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                aliases.append(candidate)
    return aliases


def _build_resolution_alias_index(resolution_cache: Dict[str, Dict]) -> Dict[str, Dict]:
    alias_index: Dict[str, Dict] = {}
    for key, entry in resolution_cache.items():
        if not isinstance(key, str):
            continue
        for alias in _iter_title_aliases(key):
            alias_index[alias] = entry
    return alias_index


def _get_resolution_cached_entry(resolution_cache: Dict[str, Dict], alias_index: Dict[str, Dict], title: str):
    if title in resolution_cache:
        return resolution_cache[title]
    for alias in _iter_title_aliases(title):
        if alias in alias_index:
            return alias_index[alias]
    return None


def _store_resolution_cache_entry(
    resolution_cache: Dict[str, Dict], alias_index: Dict[str, Dict], title: str, entry: Dict
) -> None:
    resolution_cache[title] = entry
    for alias in _iter_title_aliases(title):
        alias_index[alias] = entry


def _title_synopsis_cache_keys(title: str) -> List[str]:
    keys: List[str] = []
    if title:
        keys.append(f"title:{title}")
        normalized = normalize_title_for_match(title)
        if normalized:
            keys.append(f"title_norm:{normalized}")
    return keys


def _get_synopsis_cache_keys_for_item(item: Dict) -> List[str]:
    keys: List[str] = []
    tmdb_id = _parse_int(item.get("tmdb_id"))
    if tmdb_id:
        keys.append(f"tmdb:{tmdb_id}")
    keys.extend(_title_synopsis_cache_keys(str(item.get("movie_title") or "")))
    return keys


def _get_cached_synopsis_translation(cache: Dict[str, str], item: Dict):
    for key in _get_synopsis_cache_keys_for_item(item):
        if key in cache:
            return key, cache[key]
    return None, None


def _store_synopsis_translation(cache: Dict[str, str], keys: List[str], translation: str) -> None:
    for key in keys:
        cache[key] = translation


def _score_tmdb_result(query: str, result: Dict, query_year: Optional[int]) -> float:
    query_norm = clean_title_for_tmdb(query)
    if not query_norm:
        return 0.0
    title_norm = normalize_title_for_match(str(result.get("title") or ""))
    original_norm = normalize_title_for_match(str(result.get("original_title") or ""))
    ratio = max(
        difflib.SequenceMatcher(None, query_norm, title_norm).ratio() if title_norm else 0.0,
        difflib.SequenceMatcher(None, query_norm, original_norm).ratio() if original_norm else 0.0,
    )
    score = ratio
    release_date = str(result.get("release_date") or "")
    if query_year and re.match(r"^\d{4}", release_date):
        result_year = int(release_date[:4])
        diff = abs(result_year - query_year)
        if diff == 0:
            score += 0.12
        elif diff == 1:
            score += 0.05
        elif diff > 8:
            score -= 0.12
    return score


def _tmdb_query_candidates(item: Dict) -> List[str]:
    queries: List[str] = []
    seen = set()
    for field in ("movie_title", "movie_title_en", "movie_title_original"):
        value = str(item.get(field) or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(value)
    return queries


def _extract_gemini_text(payload: Dict) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(parts, list):
        return ""
    texts: List[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("text"):
            texts.append(part["text"])
    return "\n".join(texts).strip()


def _parse_gemini_json(text: str):
    if not text:
        return []
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
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
                data = json.loads(text[obj_start : obj_end + 1])
                if isinstance(data, dict):
                    if data.get("english_title") or data.get("en_title") or data.get("translation"):
                        return [data]
            except json.JSONDecodeError:
                pass
        return []


def _parse_gemini_fallback(text: str, input_title: str):
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
    english_title = english_match.group(1).strip().strip('"').strip() if english_match else ""
    if not english_title:
        return None
    year_match = re.search(r"\"release_year\"\s*:\s*(\d{4})", text_unescaped, flags=re.IGNORECASE)
    if not year_match:
        year_match = re.search(r"\"year\"\s*:\s*(\d{4})", text_unescaped, flags=re.IGNORECASE)
    confidence_match = re.search(r"\"confidence\"\s*:\s*([0-9]*\.?[0-9]+)", text_unescaped, flags=re.IGNORECASE)
    return {
        "english_title": english_title,
        "release_year": int(year_match.group(1)) if year_match else None,
        "confidence": float(confidence_match.group(1)) if confidence_match else None,
        "notes": "",
    }


def _strong_title_match(english_title: str, details: Dict) -> bool:
    query = normalize_title_for_match(english_title)
    if not query:
        return False
    candidates = [
        normalize_title_for_match(str(details.get("tmdb_title") or "")),
        normalize_title_for_match(str(details.get("tmdb_original_title") or "")),
        normalize_title_for_match(str(details.get("tmdb_title_en") or "")),
    ]
    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return False
    best = max(difflib.SequenceMatcher(None, query, candidate).ratio() for candidate in candidates)
    return best >= 0.9


def _gemini_year_matches(details: Dict, release_year: Optional[int], english_title: Optional[str] = None) -> bool:
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


def _resolve_titles_with_gemini(
    titles: List[str],
    session: requests.Session,
    api_key: str,
    model: str,
    use_search_tool: bool,
    batch_size: int,
) -> Dict[str, Dict]:
    if not titles:
        return {}

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    results: Dict[str, Dict] = {}
    total_prompt_tokens = 0
    total_tool_tokens = 0
    total_output_tokens = 0

    if use_search_tool:
        batch_size = min(batch_size, 8)
    batch_size = max(batch_size, 1)

    batches = _chunked(titles, batch_size)
    while batches:
        batch = batches.pop(0)
        if len(batch) == 1:
            print(f"   Gemini resolving: {batch[0]}")
            prompt = (
                "You are given one film title written in Traditional Chinese or Chinese. "
                "Use web search to find the official English title used for the film, not a literal translation. "
                "Return a single JSON object with keys: english_title, release_year, original_title, "
                "director, country, confidence. Use null for unknown fields. If unsure, set english_title to null. "
                "Return only JSON."
            )
            title_lines = f"Title: {batch[0]}"
            max_output_tokens = 4096
        else:
            preview_titles = ", ".join(batch[:3])
            suffix = f" (+{len(batch) - 3} more)" if len(batch) > 3 else ""
            print(f"   Gemini resolving batch: {preview_titles}{suffix}")
            prompt = (
                "You are given film titles written in Traditional Chinese or Chinese. "
                "Use web search to find the official English title used for each film, not a literal translation. "
                "Return a JSON array of objects with keys: input_title, english_title, release_year, "
                "original_title, director, country, confidence. Use null for unknown fields. "
                "If unsure, set english_title to null. Return only JSON."
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
        response = None
        while attempts < 2:
            attempts += 1
            try:
                response = session.post(endpoint, params={"key": api_key}, json=payload, timeout=(10, 90))
                break
            except requests.exceptions.RequestException as exc:
                print(f"   Gemini request failed (attempt {attempts}): {exc}")
                time.sleep(1.5 * attempts)

        if response is None:
            if len(batch) > 1:
                mid = len(batch) // 2
                batches.insert(0, batch[mid:])
                batches.insert(0, batch[:mid])
            continue

        if response.status_code != 200:
            print(f"   Gemini error {response.status_code}: {response.text[:300]}")
            if response.status_code == 429 and len(batch) > 1:
                mid = len(batch) // 2
                batches.insert(0, batch[mid:])
                batches.insert(0, batch[:mid])
            continue

        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            print(f"   Gemini error: {data['error']}")
            continue

        usage = data.get("usageMetadata") if isinstance(data, dict) else None
        finish_reason = None
        if isinstance(data, dict):
            candidates = data.get("candidates") or []
            if candidates:
                finish_reason = candidates[0].get("finishReason")
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
            preview = text[:400].encode("unicode_escape").decode("ascii") if isinstance(text, str) else ""
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
            input_title = entry.get("input_title") or entry.get("zh_title") or entry.get("title")
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
                confidence = _parse_float(confidence, 0.0)
            if isinstance(release_year, str) and release_year.isdigit():
                release_year = int(release_year)
            elif not isinstance(release_year, int):
                release_year = None
            if isinstance(director, list):
                director = director[0] if director else None
            if isinstance(country, list):
                country = "/".join(str(value) for value in country if value) or None
            if isinstance(country, dict):
                country = country.get("name") or country.get("country")

            results[str(input_title)] = {
                "english_title": str(english_title).strip(),
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


def _translate_synopses_with_gemini(
    synopses_to_translate: Dict[str, str], session: requests.Session, api_key: str, model: str
) -> Dict[str, str]:
    if not synopses_to_translate:
        return {}

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    results: Dict[str, str] = {}
    total_prompt_tokens = 0
    total_output_tokens = 0

    items = list(synopses_to_translate.items())
    for index, (film_key, zh_synopsis) in enumerate(items, 1):
        if not zh_synopsis or len(zh_synopsis.strip()) < 10:
            continue

        print(f"   Translating synopsis {index}/{len(items)}: {film_key[:50]}...")
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Translate the following Traditional Chinese or Chinese film synopsis into natural English. "
                                "Preserve names, tone, and key plot details. Return only the English translation.\n\n"
                                f"Chinese synopsis:\n{zh_synopsis}"
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 2048,
            },
        }

        attempts = 0
        response = None
        while attempts < 2:
            attempts += 1
            try:
                response = session.post(endpoint, params={"key": api_key}, json=payload, timeout=(10, 60))
                break
            except requests.exceptions.RequestException as exc:
                print(f"   Gemini translation request failed (attempt {attempts}): {exc}")
                time.sleep(1.5 * attempts)

        if response is None:
            continue

        if response.status_code != 200:
            print(f"   Gemini translation error {response.status_code}: {response.text[:200]}")
            if response.status_code == 429:
                time.sleep(2)
            continue

        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            print(f"   Gemini translation error: {data['error']}")
            continue

        usage = data.get("usageMetadata") if isinstance(data, dict) else None
        if isinstance(usage, dict):
            total_prompt_tokens += int(usage.get("promptTokenCount") or 0)
            total_output_tokens += int(usage.get("candidatesTokenCount") or 0)

        translated_text = _extract_gemini_text(data).strip()
        if translated_text:
            results[film_key] = translated_text
            print(f"   Translated: {film_key[:40]}... ({len(translated_text)} chars)")

    if total_prompt_tokens or total_output_tokens:
        input_cost = (total_prompt_tokens / 1_000_000) * 0.10
        output_cost = (total_output_tokens / 1_000_000) * 0.40
        total_cost = input_cost + output_cost
        print(
            "   Gemini translation summary: "
            f"input_tokens={total_prompt_tokens} output_tokens={total_output_tokens} "
            f"estimated_cost=${total_cost:.4f}"
        )

    return results


def _lookup_tmdb_details_in_cache(item: Dict, cache: Dict[str, Dict]) -> Optional[Dict]:
    query_year = _parse_year(item.get("year"))
    for query in _tmdb_query_candidates(item):
        cache_key = f"{clean_title_for_tmdb(query)}::{query_year or ''}"
        if cache_key in cache:
            cached = cache[cache_key]
            if cached:
                return cached
    return None


def fetch_tmdb_details(
    item: Dict,
    session: requests.Session,
    api_key: Optional[str],
    cache: Dict[str, Dict],
) -> Optional[Dict]:
    # Reuse cached TMDB payloads even on runs without API credentials.
    query_year = _parse_year(item.get("year"))
    cached_details = _lookup_tmdb_details_in_cache(item, cache)
    if cached_details:
        return cached_details
    if not api_key:
        return None

    for query in _tmdb_query_candidates(item):
        cache_key = f"{clean_title_for_tmdb(query)}::{query_year or ''}"
        if cache_key in cache:
            continue
        params = {
            "api_key": api_key,
            "query": query,
            "language": "zh-TW",
            "include_adult": "false",
        }
        if query_year:
            params["year"] = query_year

        try:
            response = session.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results and query_year:
                params.pop("year", None)
                response = session.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
                response.raise_for_status()
                results = response.json().get("results", [])
            if not results:
                cache[cache_key] = None
                continue

            scored = sorted(results, key=lambda result: _score_tmdb_result(query, result, query_year), reverse=True)
            best = scored[0]
            if _score_tmdb_result(query, best, query_year) < 0.58:
                cache[cache_key] = None
                continue

            detail_en_response = session.get(
                f"https://api.themoviedb.org/3/movie/{best['id']}",
                params={"api_key": api_key, "language": "en-US", "append_to_response": "credits,translations"},
                timeout=10,
            )
            detail_en_response.raise_for_status()
            detail_en = detail_en_response.json()

            detail_local_response = session.get(
                f"https://api.themoviedb.org/3/movie/{best['id']}",
                params={"api_key": api_key, "language": "zh-TW"},
                timeout=10,
            )
            detail_local_response.raise_for_status()
            detail_local = detail_local_response.json()

            director = ""
            for crew in detail_en.get("credits", {}).get("crew", []):
                if crew.get("job") == "Director":
                    director = crew.get("name") or ""
                    break

            tmdb_title_en = str(detail_en.get("title") or "")
            tmdb_title_local = str(detail_local.get("title") or best.get("title") or "")
            tmdb_overview_en = str(detail_en.get("overview") or "")
            tmdb_overview_local = str(detail_local.get("overview") or "")

            payload = {
                "tmdb_id": detail_en.get("id"),
                "tmdb_title": tmdb_title_en or tmdb_title_local,
                "tmdb_title_en": tmdb_title_en,
                "tmdb_title_local": tmdb_title_local,
                "tmdb_original_title": detail_en.get("original_title"),
                "tmdb_poster_path": detail_en.get("poster_path"),
                "tmdb_backdrop_path": detail_en.get("backdrop_path"),
                "tmdb_overview": tmdb_overview_local or tmdb_overview_en,
                "tmdb_overview_en": tmdb_overview_en,
                "runtime": detail_en.get("runtime"),
                "genres": [genre.get("name") for genre in detail_en.get("genres", []) if genre.get("name")],
                "director_en": director,
                "release_date": detail_en.get("release_date") or "",
            }
            cache[cache_key] = payload
            return payload
        except Exception:
            cache[cache_key] = None
            continue

    return None


def _attempt_tmdb_with_english_title(
    item: Dict,
    english_title: str,
    release_year: Optional[int],
    session: requests.Session,
    api_key: str,
    cache: Dict[str, Dict],
    original_title: Optional[str] = None,
    director: Optional[str] = None,
    country: Optional[str] = None,
) -> Optional[Dict]:
    if not english_title:
        return None

    query_item = dict(item)
    query_item["movie_title_en"] = english_title
    if release_year and not _parse_year(query_item.get("year")):
        query_item["year"] = str(release_year)
    if original_title and not query_item.get("movie_title_original"):
        query_item["movie_title_original"] = original_title
    if director and not query_item.get("director_en"):
        query_item["director_en"] = director
    if country and not query_item.get("country"):
        query_item["country"] = country
    return fetch_tmdb_details(query_item, session, api_key, cache)


def _needs_english_title_resolution(item: Dict) -> bool:
    english_title = str(item.get("movie_title_en") or "").strip()
    source_title = str(item.get("movie_title") or "").strip()
    if not english_title:
        return True
    if _contains_cjk(english_title):
        return True
    if source_title and normalize_title_for_match(english_title) == normalize_title_for_match(source_title):
        return True
    return False


def _apply_gemini_resolution(item: Dict, entry: Dict) -> None:
    english_title = str(entry.get("english_title") or "").strip()
    original_title = str(entry.get("original_title") or "").strip()
    director = str(entry.get("director") or "").strip()
    country = str(entry.get("country") or "").strip()
    release_year = entry.get("release_year")

    if english_title and _needs_english_title_resolution(item):
        item["movie_title_en"] = english_title
    if original_title and not item.get("movie_title_original"):
        item["movie_title_original"] = original_title
    if director and not item.get("director_en"):
        item["director_en"] = director
    if director and not item.get("director"):
        item["director"] = director
    if country and not item.get("country"):
        item["country"] = country
    if release_year and not _parse_year(item.get("year")):
        item["year"] = str(release_year)


def _apply_tmdb_details(item: Dict, details: Dict) -> None:
    if not details:
        return
    if details.get("director_en") and not item.get("director_en"):
        item["director_en"] = details["director_en"]
    if not item.get("director") and details.get("director_en"):
        item["director"] = details["director_en"]
    if not item.get("runtime_min") and details.get("runtime"):
        item["runtime_min"] = str(details["runtime"])
    if details.get("tmdb_id"):
        item["tmdb_id"] = details["tmdb_id"]
    if details.get("tmdb_title"):
        item["tmdb_title"] = details["tmdb_title"]
    if details.get("tmdb_title_en"):
        item["tmdb_title_en"] = details["tmdb_title_en"]
    if details.get("tmdb_title_local"):
        item["tmdb_title_local"] = details["tmdb_title_local"]
    if details.get("tmdb_original_title"):
        item["tmdb_original_title"] = details["tmdb_original_title"]
    if details.get("tmdb_poster_path"):
        item["tmdb_poster_path"] = details["tmdb_poster_path"]
    if details.get("tmdb_backdrop_path"):
        item["tmdb_backdrop_path"] = details["tmdb_backdrop_path"]
    if details.get("tmdb_overview"):
        item["tmdb_overview"] = details["tmdb_overview"]
    if details.get("tmdb_overview_en"):
        item["tmdb_overview_en"] = details["tmdb_overview_en"]
    if details.get("genres"):
        item["genres"] = details["genres"]
    if details.get("tmdb_title") and _needs_english_title_resolution(item):
        item["movie_title_en"] = details["tmdb_title"]


def enrich_listings_with_tmdb(listings: List[Dict], api_key: Optional[str]) -> List[Dict]:
    tmdb_cache = load_tmdb_cache()
    resolution_cache = load_title_resolution_cache()
    synopsis_translation_cache = load_synopsis_translation_cache()
    resolution_alias_index = _build_resolution_alias_index(resolution_cache)
    resolution_cache_updated = False
    synopsis_translation_cache_updated = False

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    items_by_title: Dict[str, List[Dict]] = {}
    for item in listings:
        title = str(item.get("movie_title") or "").strip()
        if title:
            items_by_title.setdefault(title, []).append(item)

    tmdb_enabled = bool(api_key)
    for item in listings:
        details = fetch_tmdb_details(item, session, api_key, tmdb_cache)
        if details:
            _apply_tmdb_details(item, details)

    gemini_key = os.environ.get("GEMINI_API_KEY")
    gemini_resolve_titles = os.environ.get("GEMINI_RESOLVE_TITLES", "").lower() in ("1", "true", "yes")
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
    if gemini_model.startswith("models/"):
        gemini_model = gemini_model.split("/", 1)[1]
    if "flash" not in gemini_model.lower():
        gemini_model = "gemini-3-flash-preview"
    gemini_use_search_env = os.environ.get("GEMINI_USE_SEARCH_TOOL")
    gemini_use_search_tool = gemini_use_search_env.lower() in ("1", "true", "yes") if gemini_use_search_env else True
    gemini_batch_size = _parse_int(os.environ.get("GEMINI_BATCH_SIZE", "1")) or 1
    gemini_confidence_threshold = _parse_float(os.environ.get("GEMINI_CONFIDENCE_THRESHOLD"), 0.6)

    unresolved_titles: List[str] = []
    for title, title_items in items_by_title.items():
        if any(item.get("tmdb_id") for item in title_items):
            continue
        if not any(_needs_english_title_resolution(item) for item in title_items):
            continue
        unresolved_titles.append(title)

    if gemini_resolve_titles and not gemini_key:
        print("   Gemini resolution skipped: GEMINI_API_KEY not set.")

    titles_to_resolve: List[str] = []
    for title in unresolved_titles:
        title_items = items_by_title.get(title, [])
        sample_item = title_items[0] if title_items else {"movie_title": title}
        cached_entry = _get_resolution_cached_entry(resolution_cache, resolution_alias_index, title)

        cached_english_title = None
        cached_confidence = None
        cached_release_year = None
        cached_original_title = None
        cached_director = None
        cached_country = None

        if isinstance(cached_entry, dict):
            if cached_entry.get("failed"):
                continue
            cached_english_title = cached_entry.get("english_title")
            cached_confidence = cached_entry.get("confidence")
            cached_release_year = cached_entry.get("release_year")
            cached_original_title = cached_entry.get("original_title")
            cached_director = cached_entry.get("director")
            cached_country = cached_entry.get("country")
            if isinstance(cached_release_year, str) and cached_release_year.isdigit():
                cached_release_year = int(cached_release_year)

        if cached_english_title and (cached_confidence is None or cached_confidence >= gemini_confidence_threshold):
            use_release_year = cached_release_year if cached_release_year and not _parse_year(sample_item.get("year")) else None
            for item in title_items:
                _apply_gemini_resolution(item, cached_entry)
            details = fetch_tmdb_details(sample_item, session, api_key, tmdb_cache)
            if details:
                for item in title_items:
                    _apply_tmdb_details(item, details)
            elif tmdb_enabled:
                print(
                    "   Retrying TMDB with cached English title: "
                    f"{title} -> {cached_english_title} "
                    f"(cached_year={cached_release_year}, used_year={use_release_year})"
                )
                details = _attempt_tmdb_with_english_title(
                    sample_item,
                    str(cached_english_title),
                    use_release_year,
                    session,
                    api_key,
                    tmdb_cache,
                    original_title=str(cached_original_title or "") or None,
                    director=str(cached_director or "") or None,
                    country=str(cached_country or "") or None,
                )
                if details and use_release_year and not _gemini_year_matches(details, use_release_year, str(cached_english_title)):
                    tmdb_year = _parse_year(details.get("release_date"))
                    print(
                        f"      Year mismatch for {title}: "
                        f"gemini_year={use_release_year}, tmdb_year={tmdb_year}. Skipping TMDB match."
                    )
                    details = None
                if details:
                    for item in title_items:
                        _apply_tmdb_details(item, details)
                else:
                    print(f"      TMDB retry failed for cached English title: {title}")
                    failed_entry = dict(cached_entry)
                    failed_entry["failed"] = True
                    failed_entry.setdefault("notes", "tmdb_failed")
                    _store_resolution_cache_entry(resolution_cache, resolution_alias_index, title, failed_entry)
                    resolution_cache_updated = True
                time.sleep(0.3)
            continue

        if gemini_key and gemini_resolve_titles and not cached_english_title:
            titles_to_resolve.append(title)

    if gemini_key and gemini_resolve_titles and titles_to_resolve:
        print(f"   Resolving English titles with Gemini for {len(titles_to_resolve)} titles...")
        resolutions = _resolve_titles_with_gemini(
            titles_to_resolve,
            session,
            gemini_key,
            gemini_model,
            gemini_use_search_tool,
            gemini_batch_size,
        )

        for title, entry in resolutions.items():
            _store_resolution_cache_entry(resolution_cache, resolution_alias_index, title, entry)
            resolution_cache_updated = True

        for title in titles_to_resolve:
            if title not in resolutions:
                _store_resolution_cache_entry(
                    resolution_cache,
                    resolution_alias_index,
                    title,
                    {
                        "english_title": None,
                        "release_year": None,
                        "confidence": 0.0,
                        "notes": "gemini_failed",
                        "failed": True,
                    },
                )
                resolution_cache_updated = True

        for title, entry in resolutions.items():
            english_title = str(entry.get("english_title") or "").strip()
            confidence = entry.get("confidence")
            release_year = entry.get("release_year")
            title_items = items_by_title.get(title, [])
            sample_item = title_items[0] if title_items else {"movie_title": title}

            if confidence is not None and float(confidence) < gemini_confidence_threshold:
                print(
                    "   Gemini English title skipped due to low confidence: "
                    f"{title} -> {english_title} (conf={confidence})"
                )
                continue

            for item in title_items:
                _apply_gemini_resolution(item, entry)

            if not english_title:
                continue

            use_release_year = release_year if release_year and not _parse_year(sample_item.get("year")) else None
            if tmdb_enabled:
                print(
                    "   Retrying TMDB with Gemini English title: "
                    f"{title} -> {english_title} "
                    f"(gemini_year={release_year}, used_year={use_release_year})"
                )
                details = _attempt_tmdb_with_english_title(
                    sample_item,
                    english_title,
                    use_release_year,
                    session,
                    api_key,
                    tmdb_cache,
                    original_title=str(entry.get("original_title") or "") or None,
                    director=str(entry.get("director") or "") or None,
                    country=str(entry.get("country") or "") or None,
                )
                if details and use_release_year and not _gemini_year_matches(details, use_release_year, english_title):
                    tmdb_year = _parse_year(details.get("release_date"))
                    print(
                        f"      Year mismatch for {title}: "
                        f"gemini_year={use_release_year}, tmdb_year={tmdb_year}. Skipping TMDB match."
                    )
                    details = None
                if details:
                    for item in title_items:
                        _apply_tmdb_details(item, details)
                else:
                    print(f"      TMDB retry failed for Gemini English title: {title}")
                    failed_entry = dict(entry)
                    failed_entry["failed"] = True
                    failed_entry.setdefault("notes", "tmdb_failed")
                    _store_resolution_cache_entry(resolution_cache, resolution_alias_index, title, failed_entry)
                    resolution_cache_updated = True
                time.sleep(0.3)

    if gemini_key:
        print("\nTranslating missing English synopses...")
        synopses_to_translate: Dict[str, str] = {}
        film_key_to_items: Dict[str, List[Dict]] = {}

        for item in listings:
            if item.get("tmdb_overview_en") or item.get("synopsis_en"):
                continue
            zh_synopsis = str(item.get("synopsis") or item.get("tmdb_overview") or "").strip()
            if not zh_synopsis or not _contains_cjk(zh_synopsis):
                continue
            cache_keys = _get_synopsis_cache_keys_for_item(item)
            _, cached_translation = _get_cached_synopsis_translation(synopsis_translation_cache, item)
            if cached_translation:
                item["synopsis_en"] = cached_translation
                continue
            film_key = cache_keys[-1] if cache_keys else f"title:{item.get('movie_title', '')}"
            if film_key not in synopses_to_translate:
                synopses_to_translate[film_key] = zh_synopsis
                film_key_to_items[film_key] = []
            film_key_to_items[film_key].append(item)

        if synopses_to_translate:
            print(f"   Found {len(synopses_to_translate)} unique films needing translation")
            translations = _translate_synopses_with_gemini(
                synopses_to_translate,
                session,
                gemini_key,
                gemini_model,
            )
            for film_key, en_synopsis in translations.items():
                translation_keys: List[str] = []
                for item in film_key_to_items.get(film_key, []):
                    translation_keys.extend(_get_synopsis_cache_keys_for_item(item))
                    item["synopsis_en"] = en_synopsis
                _store_synopsis_translation(synopsis_translation_cache, translation_keys or [film_key], en_synopsis)
                synopsis_translation_cache_updated = True
            print(f"   Translated {len(translations)} synopses")
        else:
            print("   No synopses need translation")

    save_tmdb_cache(tmdb_cache)
    if resolution_cache_updated:
        save_title_resolution_cache(resolution_cache)
    if synopsis_translation_cache_updated:
        save_synopsis_translation_cache(synopsis_translation_cache)
    return listings


def dedupe_listings(listings: List[Dict]) -> List[Dict]:
    deduped: Dict[tuple, Dict] = {}
    for item in listings:
        key = (
            item.get("cinema_name"),
            item.get("movie_title"),
            item.get("date_text"),
            item.get("showtime"),
        )
        deduped[key] = item
    return sorted(
        deduped.values(),
        key=lambda row: (
            str(row.get("date_text") or ""),
            str(row.get("showtime") or ""),
            str(row.get("cinema_name") or ""),
            str(row.get("movie_title") or ""),
        ),
    )


def run() -> int:
    ensure_data_dir()
    report = ScrapeReport()

    scrapers = [
        ("SPOT Taipei", spot_taipei_module.scrape_spot_taipei),
        ("SPOT-Huashan", spot_huashan_module.scrape_spot_huashan),
        ("Eslite Art House Songyan", eslite_arthouse_module.scrape_eslite_arthouse),
        ("Wonderful Theatre", wonderful_theatre_module.scrape_wonderful_theatre),
        ("Fuzhong 15", fuzhong15_module.scrape_fuzhong15),
        ("TFAI", tfai_opentix_module.scrape_tfai_opentix),
        ("Guling Street Avant-garde Theatre", guling_street_module.scrape_guling_street),
        ("Taoyuan Station in89 Cinema", in89_taoyuan_module.scrape_in89_taoyuan),
        ("Taipei Ximen in89 Cinema", in89_ximen_module.scrape_in89_ximen),
        ("Lightbox Photo Library", lightbox_module.scrape_lightbox),
        ("Taipei Fine Arts Museum", tfam_module.scrape_tfam),
        ("C-LAB", clab_module.scrape_clab),
        ("Treasure Hill Artist Village", treasure_hill_module.scrape_treasure_hill),
        ("Taipei Cinema Park", taipei_cinema_park_module.scrape_taipei_cinema_park),
        ("Taipei Film Festival", taipei_film_festival_module.scrape_taipei_film_festival),
        ("Women Make Waves", women_make_waves_module.scrape_women_make_waves),
        ("Taiwan International Queer Film Festival", tiqff_module.scrape_tiqff),
        ("Skyline Film", skyline_film_module.scrape_skyline_film),
        ("Taoyuan Arts Cinema II", taoyuan_arts_cinema_ii_module.scrape_taoyuan_arts_cinema_ii),
        ("Zhongli Arts Cinema", zhongli_arts_cinema_module.scrape_zhongli_arts_cinema),
    ]

    listings: List[Dict] = []
    for name, func in scrapers:
        try:
            rows = func()
            listings.extend(rows)
            report.add(name, "SUCCESS", len(rows))
            print(f"Collected {len(rows)} showings from {name}")
        except Exception as exc:
            report.add(name, "FAILURE", 0, exc)
            print(f"ERROR in {name}: {exc}")
            traceback.print_exc()

    listings = dedupe_listings(listings)
    tmdb_key = os.environ.get("TMDB_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    listings = enrich_listings_with_tmdb(listings, tmdb_key)
    if not tmdb_key and not gemini_key:
        print("TMDB_API_KEY and GEMINI_API_KEY not set. Applied cached enrichment only.")

    OUTPUT_JSON.write_text(json.dumps(listings, ensure_ascii=False, indent=2), encoding="utf-8")
    report.print_summary()

    today = datetime.now(TAIPEI_TZ).date().isoformat()
    future_count = sum(1 for item in listings if str(item.get("date_text") or "") >= today)
    print(f"Saved {len(listings)} total showings to {OUTPUT_JSON}")
    print(f"Current/future showings from {today}: {future_count}")
    return 0 if listings else 1


if __name__ == "__main__":
    raise SystemExit(run())
