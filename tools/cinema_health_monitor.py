#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
import hashlib
import json
import os
from pathlib import Path
import random
import re
import smtplib
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
GRAPH_API_VERSION = "v21.0"
USER_AGENT = "cinema-scrapers-health-monitor/1.0 (+https://github.com/jakobng/cinema-scrapers)"


@dataclass(frozen=True)
class CityConfig:
    name: str
    data_path: str
    min_current_showings: int
    ig_user_env: str | None = None
    ig_token_env: str | None = None
    ig_profile_url: str | None = None
    max_latest_ig_age_hours: int = 40
    max_latest_movie_asset_age_hours: int = 40


CITIES: dict[str, CityConfig] = {
    "tokyo": CityConfig(
        name="tokyo",
        data_path="tokyo/data/showtimes.json",
        min_current_showings=20,
        ig_user_env="IG_USER_ID",
        ig_token_env="IG_ACCESS_TOKEN",
        ig_profile_url="https://www.instagram.com/tokyominitheater/",
    ),
    "london": CityConfig(
        name="london",
        data_path="london/data/showtimes.json",
        min_current_showings=20,
        ig_user_env="LONDON_IG_USER_ID",
        ig_token_env="LONDON_IG_ACCESS_TOKEN",
        ig_profile_url="https://www.instagram.com/londoncinemashowtimes/",
    ),
    "manchester": CityConfig(
        name="manchester",
        data_path="manchester/data/showtimes.json",
        min_current_showings=5,
        ig_user_env="MANCHESTER_IG_USER_ID",
        ig_token_env="MANCHESTER_IG_ACCESS_TOKEN",
        ig_profile_url="https://www.instagram.com/manchestercinemashowtimes/",
    ),
    "taipei": CityConfig(
        name="taipei",
        data_path="taipei/data/showtimes.json",
        min_current_showings=5,
    ),
}


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_week_key() -> str:
    year, week, _ = now_utc().isocalendar()
    return f"{year}-W{week:02d}"


def load_showtimes(config: CityConfig) -> list[dict[str, Any]]:
    path = ROOT / config.data_path
    return json.loads(path.read_text(encoding="utf-8"))


def parse_date(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    return match.group(0) if match else value.strip()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def compact_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def title_matches_body(title: str, body: str) -> bool:
    title = normalize_text(title)
    body_norm = normalize_text(body)
    if not title or not body_norm:
        return False
    if title in body_norm:
        return True

    compact_title = compact_text(title)
    compact_body = compact_text(body_norm)
    if len(compact_title) >= 5 and compact_title in compact_body:
        return True

    tokens = [token for token in re.split(r"[^a-z0-9]+", title) if len(token) >= 4]
    if not tokens:
        return False
    hits = sum(1 for token in tokens[:6] if token in body_norm)
    return hits >= max(1, min(2, len(tokens)))


def time_matches_body(showtime: str, body: str) -> bool:
    if not showtime:
        return False
    clean = showtime.strip()
    if clean in body:
        return True
    match = re.match(r"^(\d{1,2}):(\d{2})$", clean)
    if not match:
        return False
    hour, minute = match.groups()
    variants = {
        f"{int(hour)}:{minute}",
        f"{int(hour)}.{minute}",
        f"{int(hour)}時{minute}",
        f"{int(hour)}:{minute}".replace(":", ""),
    }
    return any(variant in body for variant in variants)


def source_url_for(row: dict[str, Any]) -> str:
    for key in ("detail_page_url", "booking_url", "purchase_url", "cinema_site_url"):
        value = str(row.get(key) or "").strip()
        if value.startswith(("http://", "https://")):
            return value
    return ""


def fetch_text(url: str, timeout: int) -> tuple[int, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(750_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, raw.decode(charset, errors="ignore"), str(response.url)
    except urllib.error.HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", errors="ignore")
        return exc.code, body, url
    except Exception as exc:
        return 0, str(exc), url


def deterministic_sample(rows: list[dict[str, Any]], city: str, sample_size: int) -> list[dict[str, Any]]:
    candidates = [row for row in rows if source_url_for(row)]
    seed = hashlib.sha256(f"{iso_week_key()}:{city}".encode("utf-8")).hexdigest()
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:sample_size]


def audit_source_rows(config: CityConfig, rows: list[dict[str, Any]], sample_size: int, timeout: int) -> dict[str, Any]:
    today = now_utc().date().isoformat()
    future = [row for row in rows if parse_date(str(row.get("date_text") or "")) >= today]
    sampled = deterministic_sample(future, config.name, sample_size)
    failures: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []

    for row in sampled:
        title = str(row.get("movie_title") or row.get("movie_title_en") or "").strip()
        showtime = str(row.get("showtime") or "").strip()
        url = source_url_for(row)
        status, body, final_url = fetch_text(url, timeout)
        title_ok = title_matches_body(title, body)
        time_ok = time_matches_body(showtime, body)
        ok = 200 <= status < 400 and (title_ok or time_ok)
        summary = {
            "cinema": row.get("cinema_name"),
            "title": title,
            "date": row.get("date_text"),
            "showtime": showtime,
            "url": url,
            "final_url": final_url,
            "status": status,
            "title_found": title_ok,
            "time_found": time_ok,
        }
        checked.append(summary)
        if not ok:
            failures.append(summary)
        time.sleep(0.4)

    failure_ratio = (len(failures) / len(sampled)) if sampled else 0.0
    # A single sampled page can be dynamic, geo-gated, or written in a way that
    # hides the title from simple text matching. Require at least two bad rows
    # before creating an issue, while still reporting the single-row warning.
    failed_enough_for_issue = len(failures) >= 2
    return {
        "city": config.name,
        "kind": "source-audit",
        "status": "failed" if failed_enough_for_issue else "ok",
        "checked_count": len(checked),
        "failure_count": len(failures),
        "failure_ratio": failure_ratio,
        "checked": checked,
        "failures": failures,
        "future_showing_count": len(future),
    }


def git_last_touched(paths: list[str]) -> datetime | None:
    completed = run(["git", "log", "-1", "--format=%ct", "--", *paths], check=False)
    text = completed.stdout.strip()
    if not text:
        return None
    try:
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    except ValueError:
        return None


def audit_repo_output(config: CityConfig) -> dict[str, Any]:
    paths = [
        f"{config.name}/ig_posts/post_v2_caption.txt",
        f"{config.name}/ig_posts/post_v2_image_00.png",
    ]
    touched = git_last_touched(paths)
    if not touched:
        return {
            "city": config.name,
            "kind": "repo-output",
            "status": "skipped",
            "summary": "No movie-post output history found.",
        }
    age_hours = (now_utc() - touched).total_seconds() / 3600
    return {
        "city": config.name,
        "kind": "repo-output",
        "status": "failed" if age_hours > config.max_latest_movie_asset_age_hours else "ok",
        "latest_output_at": touched.isoformat(),
        "age_hours": round(age_hours, 1),
        "threshold_hours": config.max_latest_movie_asset_age_hours,
    }


def graph_get(path: str, params: dict[str, str], timeout: int) -> dict[str, Any]:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{path.lstrip('/')}"
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_graph_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    if value.endswith("+0000"):
        value = value[:-5] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def audit_instagram(config: CityConfig, timeout: int) -> dict[str, Any]:
    if not config.ig_user_env or not config.ig_token_env:
        return {"city": config.name, "kind": "instagram", "status": "skipped", "summary": "No Instagram account configured."}

    user_id = os.environ.get(config.ig_user_env, "").strip()
    token = os.environ.get(config.ig_token_env, "").strip()
    if not user_id or not token:
        return {
            "city": config.name,
            "kind": "instagram",
            "status": "skipped",
            "summary": f"Missing {config.ig_user_env} or {config.ig_token_env}; skipped local IG check.",
        }

    try:
        data = graph_get(
            user_id,
            {
                "fields": "id,username,media.limit(5){id,caption,media_type,timestamp,permalink}",
                "access_token": token,
            },
            timeout,
        )
    except urllib.error.HTTPError as exc:
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            error_body = {"error": {"message": str(exc)}}
        return {
            "city": config.name,
            "kind": "instagram",
            "status": "failed",
            "summary": error_body.get("error", {}).get("message", str(exc)),
            "profile_url": config.ig_profile_url,
        }
    except Exception as exc:
        return {
            "city": config.name,
            "kind": "instagram",
            "status": "failed",
            "summary": str(exc),
            "profile_url": config.ig_profile_url,
        }

    media = (data.get("media") or {}).get("data") or []
    if not media:
        return {
            "city": config.name,
            "kind": "instagram",
            "status": "failed",
            "summary": "Instagram Graph API returned no recent media.",
            "username": data.get("username"),
            "profile_url": config.ig_profile_url,
        }

    latest = media[0]
    latest_at = parse_graph_timestamp(str(latest.get("timestamp") or ""))
    age_hours = (now_utc() - latest_at).total_seconds() / 3600 if latest_at else None
    stale = age_hours is None or age_hours > config.max_latest_ig_age_hours
    return {
        "city": config.name,
        "kind": "instagram",
        "status": "failed" if stale else "ok",
        "username": data.get("username"),
        "profile_url": config.ig_profile_url,
        "latest_media_id": latest.get("id"),
        "latest_permalink": latest.get("permalink"),
        "latest_timestamp": latest.get("timestamp"),
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "threshold_hours": config.max_latest_ig_age_hours,
    }


def audit_data_freshness(config: CityConfig, rows: list[dict[str, Any]]) -> dict[str, Any]:
    today = now_utc().date().isoformat()
    future = [row for row in rows if parse_date(str(row.get("date_text") or "")) >= today]
    dates = sorted({parse_date(str(row.get("date_text") or "")) for row in rows if row.get("date_text")})
    duplicate_keys = {}
    for row in rows:
        key = (
            row.get("cinema_name"),
            row.get("movie_title") or row.get("movie_title_en"),
            row.get("date_text"),
            row.get("showtime"),
        )
        duplicate_keys[key] = duplicate_keys.get(key, 0) + 1
    duplicates = [key for key, count in duplicate_keys.items() if count > 1]
    failed = len(future) < config.min_current_showings or bool(duplicates)
    return {
        "city": config.name,
        "kind": "data-freshness",
        "status": "failed" if failed else "ok",
        "total_showing_count": len(rows),
        "future_showing_count": len(future),
        "min_current_showings": config.min_current_showings,
        "date_sample": dates[:8],
        "duplicate_count": len(duplicates),
    }


def label_create(name: str, color: str, description: str) -> None:
    run(["gh", "label", "create", name, "--color", color, "--description", description], check=False)


def ensure_monitor_labels(city: str) -> None:
    label_create("monitoring", "fbca04", "Automated health monitoring issue")
    label_create("source-audit", "5319e7", "Sampled source pages did not match scraped data")
    label_create("data-freshness", "d4c5f9", "Scraped data is stale, empty, or duplicated")
    label_create("instagram", "c5def5", "Instagram output or API monitoring")
    label_create("manual-review", "b60205", "Needs human review rather than an automatic code fix")
    label_create("auto-fix-candidate", "0e8a16", "Candidate for local scraper auto-fix bot")
    label_create(city, "1d76db", f"City scraper: {city}")


def issue_search(title: str) -> str:
    completed = run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--search",
            f'"{title}" in:title',
            "--json",
            "number",
            "--jq",
            ".[0].number // empty",
        ],
        check=False,
    )
    return completed.stdout.strip()


def create_issue(title: str, body: str, labels: list[str], dry_run: bool) -> str | None:
    if dry_run:
        print(f"[dry-run] would create issue: {title} labels={','.join(labels)}")
        print(body)
        return None
    if issue_search(title):
        print(f"Open issue already exists: {title}")
        return None
    for city in CITIES:
        if city in labels:
            ensure_monitor_labels(city)
            break
    completed = run(["gh", "issue", "create", "--title", title, "--body", body, "--label", ",".join(labels)])
    return completed.stdout.strip()


def issue_body(result: dict[str, Any]) -> str:
    return (
        "Automated cinema health monitor found a problem.\n\n"
        f"City: {result.get('city')}\n"
        f"Check: {result.get('kind')}\n"
        f"Run week: {iso_week_key()}\n\n"
        "Details:\n"
        "```json\n"
        f"{json.dumps(result, indent=2, ensure_ascii=False)}\n"
        "```\n"
    )


def create_issues_for_failures(results: list[dict[str, Any]], dry_run: bool) -> list[str]:
    urls: list[str] = []
    for result in results:
        if result.get("status") != "failed":
            continue
        city = str(result["city"])
        kind = str(result["kind"])
        title = f"{city.title()} {kind} health check failed"
        labels = ["monitoring", city]
        if kind in {"source-audit", "data-freshness"}:
            labels.extend([kind, "auto-fix-candidate"])
        elif kind in {"instagram", "repo-output"}:
            labels.extend(["instagram", "manual-review"])
        url = create_issue(title, issue_body(result), labels, dry_run)
        if url:
            urls.append(url)
    return urls


def send_summary_email(results: list[dict[str, Any]]) -> None:
    smtp_email = os.environ.get("SMTP_EMAIL", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    recipient = os.environ.get("ALERT_RECIPIENT_EMAIL", "").strip() or smtp_email
    if not smtp_email or not smtp_password or not recipient:
        print("Skipping health summary email: missing SMTP_EMAIL, SMTP_PASSWORD, or recipient.")
        return

    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT") or "587")
    failed = [item for item in results if item.get("status") == "failed"]
    skipped = [item for item in results if item.get("status") == "skipped"]

    lines = [
        "Cinema health monitor summary",
        "",
        f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Failed checks: {len(failed)}",
        f"Skipped checks: {len(skipped)}",
        "",
    ]
    for item in results:
        lines.append(f"- {item.get('city')} {item.get('kind')}: {item.get('status')}")
        if item.get("summary"):
            lines.append(f"  {item['summary']}")
        if item.get("latest_permalink"):
            lines.append(f"  Latest IG post: {item['latest_permalink']}")
        if item.get("failure_count"):
            lines.append(f"  Source sample failures: {item['failure_count']}/{item.get('checked_count')}")

    msg = EmailMessage()
    msg["From"] = smtp_email
    msg["To"] = recipient
    msg["Subject"] = f"Cinema health monitor: {len(failed)} failed check(s)"
    msg.set_content("\n".join(lines), charset="utf-8")

    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.send_message(msg)


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor scraper data, sampled source pages, and Instagram output.")
    parser.add_argument("--city", action="append", choices=sorted(CITIES), help="City to check. Repeatable. Defaults to all cities.")
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--create-issues", action="store_true")
    parser.add_argument("--email-summary", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    selected = args.city or sorted(CITIES)
    results: list[dict[str, Any]] = []
    for city in selected:
        config = CITIES[city]
        try:
            rows = load_showtimes(config)
            results.append(audit_data_freshness(config, rows))
            results.append(audit_source_rows(config, rows, args.sample_size, args.timeout))
            if config.ig_user_env:
                results.append(audit_repo_output(config))
                results.append(audit_instagram(config, args.timeout))
        except Exception as exc:
            results.append({"city": city, "kind": "monitor", "status": "failed", "summary": str(exc)})

    issue_urls: list[str] = []
    if args.create_issues:
        issue_urls = create_issues_for_failures(results, args.dry_run)
    if args.email_summary:
        send_summary_email(results)

    payload = {"week": iso_week_key(), "results": results, "created_issues": issue_urls}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for item in results:
            print(f"{item.get('city')} {item.get('kind')}: {item.get('status')}")
    return 1 if any(item.get("status") == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
