from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests


LOCAL_AI_UNAVAILABLE = "local_ai_unavailable"
LOCAL_AI_PARSE_FAILED = "local_ai_parse_failed"
LOCAL_AI_NO_RESULT = "local_ai_no_result"
TMDB_RETRY_FAILED = "tmdb_failed"


def env_truthy(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.lower() in ("1", "true", "yes", "on")


def parse_float(value: object, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def parse_int(value: object, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def retry_hours_from_env() -> float:
    return parse_float(os.environ.get("LOCAL_AI_RETRY_HOURS"), 12.0)


def local_ai_retry_due(entry: object, retry_hours: Optional[float] = None) -> bool:
    if not isinstance(entry, dict):
        return True
    if entry.get("notes") not in {
        LOCAL_AI_UNAVAILABLE,
        LOCAL_AI_PARSE_FAILED,
        LOCAL_AI_NO_RESULT,
        TMDB_RETRY_FAILED,
    }:
        return False
    attempted_at = entry.get("last_ai_attempt_at")
    if not attempted_at:
        return True
    retry_after = retry_hours if retry_hours is not None else retry_hours_from_env()
    try:
        parsed = datetime.fromisoformat(str(attempted_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - parsed >= timedelta(hours=retry_after)


def make_ai_failure_entry(note: str, provider: str, confidence: float = 0.0) -> Dict:
    return {
        "english_title": None,
        "release_year": None,
        "confidence": confidence,
        "notes": note,
        "failed": True,
        "ai_provider": provider,
        "last_ai_attempt_at": utc_now_iso(),
    }


def extract_json_list(text: str) -> List[Dict]:
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    candidates = [cleaned]
    array_start = cleaned.find("[")
    array_end = cleaned.rfind("]")
    if array_start != -1 and array_end != -1 and array_end > array_start:
        candidates.insert(0, cleaned[array_start : array_end + 1])
    object_start = cleaned.find("{")
    object_end = cleaned.rfind("}")
    if object_start != -1 and object_end != -1 and object_end > object_start:
        candidates.append(cleaned[object_start : object_end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            if any(key in data for key in ("english_title", "en_title", "translation")):
                return [data]
            data = data.get("resolutions") or data.get("translations") or data.get("results") or []
        if isinstance(data, list):
            return [entry for entry in data if isinstance(entry, dict)]
    return []


def extract_gemini_text(payload: Dict) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(parts, list):
        return ""
    texts: List[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("text"):
            texts.append(str(part["text"]))
    return "\n".join(texts).strip()


def parse_title_fallback(text: str) -> Optional[Dict]:
    if not text:
        return None
    text_unescaped = text.strip().replace('\\"', '"')
    if re.search(r"\"english_title\"\s*:\s*null", text_unescaped, flags=re.IGNORECASE):
        return {"english_title": None, "release_year": None, "confidence": None, "notes": ""}
    english_match = re.search(r"\"(?:english_title|en_title)\"\s*:\s*\"([^\"]+)\"", text_unescaped, flags=re.IGNORECASE)
    if not english_match:
        english_match = re.search(
            r"\"(?:english_title|en_title)\"\s*:\s*\"?([^\"\n\r\}]+)",
            text_unescaped,
            flags=re.IGNORECASE,
        )
    english_title = english_match.group(1).strip().strip('"').strip() if english_match else ""
    if not english_title:
        return None
    year_match = re.search(r"\"(?:release_year|year)\"\s*:\s*(\d{4})", text_unescaped, flags=re.IGNORECASE)
    confidence_match = re.search(r"\"confidence\"\s*:\s*([0-9]*\.?[0-9]+)", text_unescaped, flags=re.IGNORECASE)
    return {
        "english_title": english_title,
        "release_year": int(year_match.group(1)) if year_match else None,
        "confidence": float(confidence_match.group(1)) if confidence_match else None,
        "notes": "",
    }


def normalize_resolution_entry(entry: Dict, input_title: str, language_key: str) -> Optional[Dict]:
    title_value = entry.get("input_title") or entry.get(language_key) or entry.get("title") or input_title
    english_title = entry.get("english_title") or entry.get("en_title") or entry.get("translation")
    if not title_value or not english_title:
        return None

    confidence = entry.get("confidence")
    if isinstance(confidence, str):
        # Models often return a word ("high") instead of a number, especially in
        # batch mode. Map the common words; fall back to numeric parse, else None
        # (unknown) rather than 0.0 so it isn't mistaken for "no confidence".
        word_scores = {
            "very high": 0.95, "high": 0.9, "fairly high": 0.8, "medium-high": 0.75,
            "medium": 0.6, "moderate": 0.6, "fair": 0.5, "medium-low": 0.45,
            "low": 0.3, "very low": 0.1, "none": 0.0,
        }
        key = confidence.strip().lower()
        if key in word_scores:
            confidence = word_scores[key]
        else:
            parsed = parse_float(key, -1.0)
            confidence = parsed if parsed >= 0 else None
    release_year = entry.get("release_year") or entry.get("year")
    if isinstance(release_year, str) and release_year.isdigit():
        release_year = int(release_year)
    elif not isinstance(release_year, int):
        release_year = None

    director = entry.get("director")
    if isinstance(director, list):
        director = director[0] if director else None
    country = entry.get("country") or entry.get("countries")
    if isinstance(country, list):
        country = "/".join(str(value) for value in country if value) or None
    if isinstance(country, dict):
        country = country.get("name") or country.get("country")

    return {
        "input_title": str(title_value),
        "english_title": str(english_title).strip(),
        "release_year": release_year,
        "confidence": confidence,
        "notes": entry.get("notes") or "",
        "original_title": entry.get("original_title")
        or entry.get("native_title")
        or entry.get("original_language_title"),
        "director": director,
        "country": country,
    }


class AIEnrichmentClient:
    def __init__(self, session: requests.Session, provider: str, model: str, base_url: str, timeout_seconds: int) -> None:
        self.session = session
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.api_key: Optional[str] = None
        self.available: Optional[bool] = None
        self.last_error_note: Optional[str] = None

    @classmethod
    def from_env(cls, session: requests.Session) -> Optional["AIEnrichmentClient"]:
        provider = (os.environ.get("AI_ENRICHMENT_PROVIDER") or "").strip().lower()
        cloud_fallback = env_truthy("AI_CLOUD_FALLBACK", False)
        legacy_gemini_requested = any(
            os.environ.get(name)
            for name in ("GEMINI_RESOLVE_TITLES", "GEMINI_TRANSLATE_TITLES")
        )
        if not provider and cloud_fallback and legacy_gemini_requested:
            provider = "gemini"
        if not provider:
            return None

        if provider == "local":
            provider = "lmstudio"
        timeout_seconds = parse_int(os.environ.get("LOCAL_AI_TIMEOUT_SECONDS"), 90)
        if provider == "lmstudio":
            model = os.environ.get("LOCAL_AI_MODEL") or os.environ.get("AI_MODEL") or "local-model"
            base_url = os.environ.get("LOCAL_AI_BASE_URL") or "http://127.0.0.1:1234/v1"
            return cls(session, provider, model, base_url, timeout_seconds)
        if provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return None
            model = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
            if model.startswith("models/"):
                model = model.split("/", 1)[1]
            if "flash" not in model.lower():
                model = "gemini-3-flash-preview"
            return cls(session, provider, model, "https://generativelanguage.googleapis.com/v1beta", timeout_seconds)
        if provider in ("deepseek", "openai", "openai-compatible"):
            # OpenAI-compatible chat-completions providers (DeepSeek by default).
            if provider == "deepseek":
                api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY")
                base_url = os.environ.get("AI_BASE_URL") or "https://api.deepseek.com"
                model = os.environ.get("AI_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
            else:
                api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("AI_API_KEY")
                base_url = os.environ.get("AI_BASE_URL") or "https://api.openai.com/v1"
                model = os.environ.get("AI_MODEL") or "gpt-4o-mini"
            if not api_key:
                print(f"   AI enrichment skipped: {provider} requested but no API key set.")
                return None
            client = cls(session, provider, model, base_url, timeout_seconds)
            client.api_key = api_key
            return client
        print(f"   AI enrichment skipped: unsupported AI_ENRICHMENT_PROVIDER={provider!r}.")
        return None

    def health_check(self) -> bool:
        if self.available is not None:
            return self.available
        # Key-authenticated cloud providers: trust the key; per-request errors are
        # handled at call time (their /models endpoints need auth we don't send here).
        if self.provider in ("gemini", "deepseek", "openai", "openai-compatible"):
            self.available = True
            return True
        try:
            response = self.session.get(f"{self.base_url}/models", timeout=(2, 5))
            self.available = response.status_code == 200
            if self.available and self.model == "local-model":
                try:
                    models = response.json().get("data") or []
                    first_model = models[0].get("id") if models and isinstance(models[0], dict) else None
                    if first_model:
                        self.model = str(first_model)
                except (ValueError, AttributeError):
                    pass
        except requests.exceptions.RequestException as exc:
            self.last_error_note = LOCAL_AI_UNAVAILABLE
            print(f"   Local AI unavailable at {self.base_url}: {exc}")
            self.available = False
        if self.available:
            print(f"   Local AI available via {self.base_url} (model={self.model}).")
        return bool(self.available)

    def _chat_completion(self, prompt: str, temperature: float, max_tokens: int) -> str:
        if not self.health_check():
            self.last_error_note = LOCAL_AI_UNAVAILABLE
            return ""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        reasoning_effort = os.environ.get("LOCAL_AI_REASONING_EFFORT", "none").strip()
        if reasoning_effort and self.provider == "lmstudio":
            payload["reasoning_effort"] = reasoning_effort
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        try:
            response = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=(5, self.timeout_seconds),
            )
        except requests.exceptions.RequestException as exc:
            self.last_error_note = LOCAL_AI_UNAVAILABLE
            print(f"   Local AI request failed: {exc}")
            return ""
        if response.status_code != 200:
            self.last_error_note = LOCAL_AI_UNAVAILABLE
            print(f"   Local AI error {response.status_code}: {response.text[:200]}")
            return ""
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError):
            self.last_error_note = LOCAL_AI_PARSE_FAILED
            return ""

    def _gemini_generate(self, prompt: str, temperature: float, max_tokens: int, use_search_tool: bool) -> str:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return ""
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if use_search_tool:
            payload["tools"] = [{"google_search": {}}]
        endpoint = f"{self.base_url}/models/{self.model}:generateContent"
        try:
            response = self.session.post(endpoint, params={"key": api_key}, json=payload, timeout=(10, self.timeout_seconds))
        except requests.exceptions.RequestException as exc:
            self.last_error_note = "gemini_unavailable"
            print(f"   Gemini request failed: {exc}")
            return ""
        if response.status_code != 200:
            self.last_error_note = "gemini_error"
            print(f"   Gemini error {response.status_code}: {response.text[:300]}")
            return ""
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            self.last_error_note = "gemini_error"
            print(f"   Gemini error: {data['error']}")
            return ""
        return extract_gemini_text(data)

    def generate_text(self, prompt: str, temperature: float = 0.2, max_tokens: int = 2048, use_search_tool: bool = False) -> str:
        self.last_error_note = None
        if self.provider == "gemini":
            return self._gemini_generate(prompt, temperature, max_tokens, use_search_tool)
        return self._chat_completion(prompt, temperature, max_tokens)

    def resolve_titles(
        self,
        titles: List[str],
        source_language: str,
        language_key: str,
        batch_size: int = 1,
        use_search_tool: bool = False,
    ) -> Dict[str, Dict]:
        if not titles:
            return {}
        if not self.health_check():
            self.last_error_note = LOCAL_AI_UNAVAILABLE
            return {}

        results: Dict[str, Dict] = {}
        batch_size = max(1, batch_size)
        if self.provider == "gemini" and use_search_tool:
            batch_size = min(batch_size, 8)

        for start in range(0, len(titles), batch_size):
            batch = titles[start : start + batch_size]
            if len(batch) == 1:
                print(f"   AI resolving: {batch[0]}")
                prompt = (
                    f"You are given one {source_language} film title. "
                    "Find the official English title used for the film, not a literal translation. "
                    "If you cannot verify the official title, set english_title to null. "
                    "Return a single JSON object with keys: english_title, release_year, original_title, "
                    "director, country, confidence. Use null for unknown fields. Return only JSON.\n\n"
                    f"Title: {batch[0]}"
                )
                max_tokens = 4096
            else:
                preview = ", ".join(batch[:3])
                suffix = f" (+{len(batch) - 3} more)" if len(batch) > 3 else ""
                print(f"   AI resolving batch: {preview}{suffix}")
                prompt = (
                    f"You are given {source_language} film titles. "
                    "Find the official English title used for each film, not literal translations. "
                    "If you cannot verify an official title, set english_title to null. "
                    "Return a JSON array of objects with keys: input_title, english_title, release_year, "
                    "original_title, director, country, confidence. Use null for unknown fields. Return only JSON.\n\n"
                    "Titles:\n" + "\n".join(f"- {title}" for title in batch)
                )
                max_tokens = min(12288, max(2048, 512 * len(batch)))

            text = self.generate_text(prompt, temperature=0.2, max_tokens=max_tokens, use_search_tool=use_search_tool)
            parsed = extract_json_list(text)
            if not parsed and len(batch) == 1:
                fallback = parse_title_fallback(text)
                if fallback:
                    parsed = [fallback]
            if not parsed:
                self.last_error_note = self.last_error_note or LOCAL_AI_PARSE_FAILED
                preview = text[:300].encode("unicode_escape").decode("ascii") if text else ""
                print(f"   AI response parse failed. Preview: {preview}")
                continue

            for entry in parsed:
                input_title = entry.get("input_title") or entry.get(language_key) or entry.get("title")
                if not input_title and len(batch) == 1:
                    input_title = batch[0]
                normalized = normalize_resolution_entry(entry, str(input_title or ""), language_key)
                if not normalized:
                    continue
                result_key = normalized.pop("input_title")
                normalized["ai_provider"] = self.provider
                normalized["last_ai_attempt_at"] = utc_now_iso()
                results[str(result_key)] = normalized
                print(
                    "   AI resolved: "
                    f"{result_key} -> {normalized['english_title']} "
                    f"(year={normalized['release_year']}, conf={normalized['confidence']})"
                )
        if not results:
            self.last_error_note = self.last_error_note or LOCAL_AI_NO_RESULT
        return results

    def translate_synopses(self, synopses_to_translate: Dict[str, str], source_language: str) -> Dict[str, str]:
        if not synopses_to_translate:
            return {}
        if not self.health_check():
            self.last_error_note = LOCAL_AI_UNAVAILABLE
            return {}
        results: Dict[str, str] = {}
        items = list(synopses_to_translate.items())
        batch_size = max(1, min(20, parse_int(os.environ.get("AI_TRANSLATION_BATCH_SIZE"), 8)))
        for start in range(0, len(items), batch_size):
            batch = [
                (film_key, synopsis)
                for film_key, synopsis in items[start : start + batch_size]
                if synopsis and len(synopsis.strip()) >= 10
            ]
            if not batch:
                continue
            if len(batch) == 1:
                index = start + 1
                film_key, synopsis = batch[0]
                print(f"   Translating synopsis {index}/{len(items)}: {film_key[:50]}...")
                prompt = (
                    f"Translate the following {source_language} film synopsis into natural English. "
                    "Preserve names, tone, and key plot details. Return only the English translation.\n\n"
                    f"Synopsis:\n{synopsis}"
                )
                translated = self.generate_text(prompt, temperature=0.3, max_tokens=2048).strip()
                if translated:
                    results[film_key] = translated
                    print(f"   Translated: {film_key[:40]}... ({len(translated)} chars)")
                continue

            preview = ", ".join(film_key[:30] for film_key, _ in batch[:3])
            suffix = f" (+{len(batch) - 3} more)" if len(batch) > 3 else ""
            print(
                "   Translating synopsis batch "
                f"{start + 1}-{start + len(batch)}/{len(items)}: {preview}{suffix}"
            )
            prompt_items = []
            for index, (film_key, synopsis) in enumerate(batch, 1):
                prompt_items.append(
                    f"{index}. film_key: {film_key}\n"
                    f"synopsis:\n{synopsis}"
                )
            prompt = (
                f"Translate each {source_language} film synopsis into natural English. "
                "Preserve names, tone, and key plot details. "
                "Return only a JSON array. Each object must have exactly these keys: "
                "film_key and synopsis_en. Copy each film_key exactly from the input.\n\n"
                + "\n\n".join(prompt_items)
            )
            text = self.generate_text(
                prompt,
                temperature=0.3,
                max_tokens=min(12288, max(2048, 1024 * len(batch))),
            )
            parsed = extract_json_list(text)
            if not parsed:
                self.last_error_note = self.last_error_note or LOCAL_AI_PARSE_FAILED
                preview_text = text[:300].encode("unicode_escape").decode("ascii") if text else ""
                print(f"   Synopsis translation batch parse failed. Preview: {preview_text}")
                continue
            translated_count = 0
            for entry in parsed:
                if not isinstance(entry, dict):
                    continue
                film_key = str(entry.get("film_key") or entry.get("key") or "").strip()
                translated = str(entry.get("synopsis_en") or entry.get("translation") or "").strip()
                if not film_key or not translated:
                    continue
                if film_key in synopses_to_translate:
                    results[film_key] = translated
                    translated_count += 1
            print(f"   Translated batch items: {translated_count}/{len(batch)}")
        if not results:
            self.last_error_note = self.last_error_note or LOCAL_AI_NO_RESULT
        return results
