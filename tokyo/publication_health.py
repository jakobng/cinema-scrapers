"""Check the age and coverage of collected listings, independently of site builds."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen

JST = timezone(timedelta(hours=9))
MAX_AGE_HOURS = 36
MIN_SHOWINGS = 100
MIN_CINEMAS = 20


def collection_status(rows, sources, *, now=None, run_id=None):
    collected = now or datetime.now(timezone.utc)
    today = collected.astimezone(JST).date().isoformat()
    current = [row for row in rows if str(row.get("date_text") or "") >= today]
    return {
        "scraped_at": collected.isoformat(timespec="seconds"),
        "run_id": run_id or os.environ.get("GITHUB_RUN_ID", ""),
        "current_showings": len(current),
        "current_cinemas": len({row["cinema_name"] for row in current}),
        "source_issues": [source for source in sources
                          if source["status"] in ("FAILURE", "WARNING")],
    }


def audit_publication(rows, status, *, now=None, run_id=None):
    current_time = now or datetime.now(timezone.utc)
    today = current_time.astimezone(JST).date().isoformat()
    current = [row for row in rows if str(row.get("date_text") or "") >= today]
    cinemas = {row.get("cinema_name") for row in current if row.get("cinema_name")}
    try:
        collected = datetime.fromisoformat(str(status.get("scraped_at", "")).replace("Z", "+00:00"))
        age = (current_time - collected).total_seconds() / 3600
    except (ValueError, TypeError):
        age = None
    problems = [message for condition, message in (
        (age is None, "The last successful collection time is missing or invalid."),
        (age is not None and age > MAX_AGE_HOURS,
         f"Listings have not been collected within {MAX_AGE_HOURS} hours."),
        (age is not None and age < -0.1, "The collection time is in the future."),
        (bool(run_id) and str(status.get("run_id")) != str(run_id),
         "This scraper run did not produce a new collection."),
        (len(current) < MIN_SHOWINGS,
         f"Only {len(current)} upcoming showings remain; expected at least {MIN_SHOWINGS}."),
        (len(cinemas) < MIN_CINEMAS,
         f"Only {len(cinemas)} cinemas have upcoming listings; expected at least {MIN_CINEMAS}."),
    ) if condition]
    return {
        "city": "tokyo", "kind": "published-listings",
        "status": "failed" if problems else "ok",
        "summary": " ".join(problems) or "Collected listings are fresh and have broad cinema coverage.",
        "scraped_at": status.get("scraped_at"),
        "age_hours": round(age, 1) if age is not None else None,
        "future_showing_count": len(current), "cinema_count": len(cinemas),
        "source_issues": status.get("source_issues", []),
    }


def load_status(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--email-on-failure", action="store_true")
    parser.add_argument("--data", default="data/showtimes.json")
    parser.add_argument("--status", default="data/scrape_status.json")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        if args.live:
            # Read actual published files: a successful deployment is not a freshness check.
            with urlopen("https://cinematokyo.com/data/scrape_status.json", timeout=30) as response:
                status = json.load(response)
            with urlopen("https://cinematokyo.com/data/showtimes_slim.json", timeout=30) as response:
                rows = json.load(response)["showings"]
        else:
            status = load_status(args.status)
            rows = json.loads(Path(args.data).read_text(encoding="utf-8"))
        result = audit_publication(rows, status, run_id=args.run_id)
    except Exception as exc:
        result = {"city": "tokyo", "kind": "published-listings", "status": "failed",
                  "summary": f"Could not check published listings: {exc}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "failed":
        print(f"::error title=Tokyo listings need attention::{result['summary']}")
        if args.email_on_failure:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from tools.cinema_health_monitor import send_summary_email
            send_summary_email([result])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
