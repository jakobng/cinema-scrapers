#!/usr/bin/env python3
# main_scraper.py
# North of England Art Exhibitions - aggregates exhibition listings from Northern galleries/museums.

import json
import os
import sys
import smtplib
import ssl
import concurrent.futures
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

# --- Configuration ---
DATA_DIR = "data"
OUTPUT_JSON = os.path.join(DATA_DIR, "exhibitions.json")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)


# --- ScrapeReport (health checks and optional email alert) ---
class ScrapeReport:
    def __init__(self):
        self.results = []
        self.total_exhibitions = 0

    def add(self, venue_name, status, count, error=None):
        self.results.append({
            "venue": venue_name,
            "status": status,
            "count": count,
            "error": str(error) if error else None
        })
        if count:
            self.total_exhibitions += count

    def print_summary(self):
        print("\n" + "=" * 50)
        print("SCRAPE HEALTH REPORT")
        print("=" * 50)
        failures = []
        warnings = []
        print(f"{'STATUS':<4} | {'VENUE':<35} | {'COUNT':<5} | {'NOTES'}")
        print("-" * 70)
        for r in self.results:
            if r["status"] == "SUCCESS" and r["count"] == 0:
                r["status"] = "WARNING"
                warnings.append(r)
            elif r["status"] == "FAILURE":
                failures.append(r)
            icon = "[OK]" if r["status"] == "SUCCESS" else ("[!!]" if r["status"] == "WARNING" else "[XX]")
            error_msg = r["error"] or ("0 exhibitions" if r["status"] == "WARNING" else "")
            print(f"{icon:<4} | {r['venue']:<35} | {r['count']:<5} | {error_msg}")
        print("-" * 70)
        print(f"Total Exhibitions: {self.total_exhibitions}")
        return failures, warnings

    def send_email_alert(self, failures, warnings):
        if not failures and not warnings:
            return
        smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", 465))
        sender_email = os.environ.get("SMTP_EMAIL")
        sender_password = os.environ.get("SMTP_PASSWORD")
        recipient_email = os.environ.get("ALERT_RECIPIENT_EMAIL")
        if not (sender_email and sender_password and recipient_email):
            print("Skipping email alert: missing SMTP credentials.")
            return
        subject = f"North Exhibitions Scraper Alert: {len(failures)} failures, {len(warnings)} empty"
        body_lines = ["North Art Exhibitions scraper encountered issues:\n"]
        if failures:
            body_lines.append(f"FAILURES ({len(failures)}):")
            for f in failures:
                body_lines.append(f"  - {f['venue']}: {f['error']}")
            body_lines.append("")
        if warnings:
            body_lines.append("WARNINGS (0 exhibitions):")
            for w in warnings:
                body_lines.append(f"  - {w['venue']}")
        msg = EmailMessage()
        msg.set_content("\n".join(body_lines))
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = recipient_email
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)
            print("Alert email sent.")
        except Exception as e:
            print(f"Failed to send alert: {e}")


report = ScrapeReport()


def _run_scraper_task(name, func):
    """Run a single venue scraper. Returns (name, status, rows, error)."""
    try:
        rows = func() or []
        return name, "SUCCESS", rows, None
    except Exception as e:
        return name, "FAILURE", [], e


def main():
    # Import venue modules and define scrapers to run
    from venue_modules import (
        whitworth_module,
        manchester_art_gallery_module,
        hepworth_module,
        tate_liverpool_module,
        ysp_module,
        laing_module,
        york_art_gallery_module,
        fact_module,
        cartwright_hall_module,
        baltic_module,
        sheffield_museums_module,
        open_eye_module,
        liverpool_museums_module,
        leeds_art_gallery_module,
        ferens_module,
        iwm_north_module,
        esea_contemporary_module,
        salts_mill_module,
        harris_preston_module,
        lowry_module,
        hatton_module,
        mima_module,
        ngca_module,
        shipley_module,
        sunderland_museum_module,
        castlefield_module,
        bluecoat_module,
        henry_moore_module,
        site_gallery_module,
        humber_street_module,
        cooper_gallery_module,
        danum_module,
        grundy_module,
        abbot_hall_module,
        tullie_house_module,
        home_manchester_module,
        nsmm_module,
        impressions_module,
        bowes_module,
        nottingham_contemporary_module,
    )

    scrapers_to_run = [
        ("The Whitworth", whitworth_module.scrape_whitworth),
        ("Manchester Art Gallery", manchester_art_gallery_module.scrape_manchester_art_gallery),
        ("The Hepworth Wakefield", hepworth_module.scrape_hepworth),
        ("Tate Liverpool", tate_liverpool_module.scrape_tate_liverpool),
        ("Yorkshire Sculpture Park", ysp_module.scrape_ysp),
        ("Laing Art Gallery", laing_module.scrape_laing),
        ("York Art Gallery", york_art_gallery_module.scrape_york_art_gallery),
        ("FACT", fact_module.scrape_fact),
        ("Cartwright Hall", cartwright_hall_module.scrape_cartwright_hall),
        ("Bradford Industrial Museum", cartwright_hall_module.scrape_bradford_industrial_museum),
        ("Bolling Hall Museum", cartwright_hall_module.scrape_bolling_hall),
        ("Cliffe Castle Museum", cartwright_hall_module.scrape_cliffe_castle),
        ("Baltic", baltic_module.scrape_baltic),
        ("Sheffield Museums", sheffield_museums_module.scrape_sheffield_museums),
        ("Open Eye Gallery", open_eye_module.scrape_open_eye),
        ("Walker Art Gallery", liverpool_museums_module.scrape_walker_art_gallery),
        ("Lady Lever Art Gallery", liverpool_museums_module.scrape_lady_lever),
        ("Sudley House", liverpool_museums_module.scrape_sudley_house),
        ("World Museum", liverpool_museums_module.scrape_world_museum),
        ("Museum of Liverpool", liverpool_museums_module.scrape_museum_of_liverpool),
        ("Leeds Art Gallery", leeds_art_gallery_module.scrape_leeds_art_gallery),
        ("Ferens Art Gallery", ferens_module.scrape_ferens),
        ("IWM North", iwm_north_module.scrape_iwm_north),
        ("esea contemporary", esea_contemporary_module.scrape_esea_contemporary),
        ("Salts Mill", salts_mill_module.scrape_salts_mill),
        ("The Harris Preston", harris_preston_module.scrape_harris_preston),
        ("The Lowry", lowry_module.scrape_lowry),
        ("Hatton Gallery", hatton_module.scrape_hatton),
        ("MIMA", mima_module.scrape_mima),
        ("Northern Gallery for Contemporary Art", ngca_module.scrape_ngca),
        ("Shipley Art Gallery", shipley_module.scrape_shipley),
        ("Sunderland Museum & Winter Gardens", sunderland_museum_module.scrape_sunderland_museum),
        ("Castlefield Gallery", castlefield_module.scrape_castlefield),
        ("Bluecoat", bluecoat_module.scrape_bluecoat),
        ("Henry Moore Institute", henry_moore_module.scrape_henry_moore),
        ("Site Gallery", site_gallery_module.scrape_site_gallery),
        ("Humber Street Gallery", humber_street_module.scrape_humber_street),
        ("Cooper Gallery", cooper_gallery_module.scrape_cooper_gallery),
        ("Danum Gallery, Library and Museum", danum_module.scrape_danum),
        ("Grundy Art Gallery", grundy_module.scrape_grundy),
        ("Abbot Hall Art Gallery", abbot_hall_module.scrape_abbot_hall),
        ("Tullie House Museum and Art Gallery", tullie_house_module.scrape_tullie_house),
        ("HOME", home_manchester_module.scrape_home),
        ("National Science and Media Museum", nsmm_module.scrape_nsmm),
        ("Impressions Gallery", impressions_module.scrape_impressions),
        ("The Bowes Museum", bowes_module.scrape_bowes),
        ("Nottingham Contemporary", nottingham_contemporary_module.scrape_nottingham_contemporary),
    ]

    print(f"Running {len(scrapers_to_run)} venue scrapers...")
    listings = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_to_venue = {}
        for name, func in scrapers_to_run:
            future = executor.submit(_run_scraper_task, name, func)
            future_to_venue[future] = name
        for future in concurrent.futures.as_completed(future_to_venue):
            name, status, rows, error = future.result()
            n = len(rows)
            if status == "SUCCESS":
                print(f"  {name}: {n} exhibitions")
                listings.extend(rows)
                report.add(name, "SUCCESS", n)
            else:
                print(f"  {name}: ERROR - {error}")
                report.add(name, "FAILURE", 0, error=error)

    print(f"\nTotal exhibitions: {len(listings)}")

    # Drop navigation/CTA text that venue scrapers picked up as titles
    import re
    junk_title_re = re.compile(
        r"^(?:what.?s on|next|previous|exhibitions?|events?|read more|find out more|"
        r"view all|book now|more info|archive|past exhibitions?)$",
        re.IGNORECASE,
    )
    before_junk = len(listings)
    listings = [i for i in listings if not junk_title_re.match((i.get("exhibition_title") or "").strip())]
    if len(listings) < before_junk:
        print(f"  Removed {before_junk - len(listings)} junk titles.")

    # Dedupe by (venue, title) before doing any detail-page fetches
    seen_keys = set()
    deduped = []
    for item in listings:
        key = (item.get("venue_name", ""), (item.get("exhibition_title") or "").strip().lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)
    if len(deduped) < len(listings):
        print(f"  Removed {len(listings) - len(deduped)} duplicate listings.")
    listings = deduped

    # Enrich listings missing an image or dates from their detail pages (improves cards)
    need_meta = [
        item for item in listings
        if item.get("detail_page_url")
        and (not item.get("image_url") or not item.get("end_date"))
    ]
    if need_meta:
        from venue_modules._utils import get_page_meta
        HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}

        def enrich(item):
            try:
                meta = get_page_meta(item["detail_page_url"], headers=HEADERS, timeout=10)
                if not item.get("image_url") and meta.get("image_url"):
                    item["image_url"] = meta["image_url"]
                if not item.get("description") and meta.get("description"):
                    item["description"] = meta["description"]
                if not item.get("start_date") and meta.get("start_date"):
                    item["start_date"] = meta["start_date"]
                if not item.get("end_date") and meta.get("end_date"):
                    item["end_date"] = meta["end_date"]
            except Exception:
                pass

        print(f"Enriching {len(need_meta)} listings from detail pages (images/dates)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(enrich, need_meta))
        still_no_image = sum(1 for i in listings if not i.get("image_url"))
        still_no_end = sum(1 for i in listings if not i.get("end_date"))
        print(f"  After enrichment: {still_no_image} without image, {still_no_end} without end date.")

    # Drop exhibitions that ended more than 21 days ago to keep the file lean
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=21)).isoformat()
    before = len(listings)
    listings = [i for i in listings if not (i.get("end_date") and i["end_date"] < cutoff)]
    if len(listings) < before:
        print(f"  Dropped {before - len(listings)} long-ended exhibitions.")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exhibitions": listings,
    }
    print(f"Writing {OUTPUT_JSON} ({len(listings)} exhibitions)...")
    try:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print("Done.")
    except Exception as e:
        print(f"Error saving JSON: {e}")
        sys.exit(1)

    failures, warnings = report.print_summary()
    report.send_email_alert(failures, warnings)


if __name__ == "__main__":
    main()
