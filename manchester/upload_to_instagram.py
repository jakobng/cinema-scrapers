import os
import requests
import glob
import time
import sys
import argparse
import hashlib

# --- Configuration ---
MANCHESTER_IG_USER_ID = os.environ.get("MANCHESTER_IG_USER_ID")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")

PUBLIC_IMAGE_BASE_URL = os.environ.get(
    "PUBLIC_IMAGE_BASE_URL",
    "https://raw.githubusercontent.com/jakobng/cinema-scrapers/main/manchester/ig_posts/",
)

API_VERSION = "v21.0"
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "ig_posts")


def dedupe_files_by_content(file_paths):
    """Drop duplicate images (same bytes) while preserving order."""
    seen_hashes = set()
    unique_files = []

    for path in file_paths:
        try:
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            print(f"   ⚠️ Could not hash {os.path.basename(path)}: {e}")
            unique_files.append(path)
            continue

        if digest in seen_hashes:
            print(f"   ⚠️ Skipping duplicate slide: {os.path.basename(path)}")
            continue

        seen_hashes.add(digest)
        unique_files.append(path)

    return unique_files


def verify_target_account():
    """Validates that the configured MANCHESTER_IG_USER_ID is reachable with the access token."""
    url = f"{GRAPH_URL}/{MANCHESTER_IG_USER_ID}"
    params = {
        "fields": "id,username",
        "access_token": IG_ACCESS_TOKEN,
    }

    try:
        response = requests.get(url, params=params)
        result = response.json()
    except Exception as e:
        print(f"❌ Failed to validate Instagram account: {e}")
        sys.exit(1)

    if "error" in result:
        print("❌ Instagram credential/account mismatch.")
        print(f"   MANCHESTER_IG_USER_ID configured: {MANCHESTER_IG_USER_ID}")
        print(f"   API error: {result['error'].get('message', 'Unknown error')}")
        sys.exit(1)

    resolved_id = str(result.get("id", ""))
    resolved_username = result.get("username", "unknown")
    if resolved_id != str(MANCHESTER_IG_USER_ID):
        print("❌ Instagram account validation failed.")
        print(f"   MANCHESTER_IG_USER_ID configured: {MANCHESTER_IG_USER_ID}")
        print(f"   MANCHESTER_IG_USER_ID resolved: {resolved_id}")
        sys.exit(1)

    print(f"✅ Target Instagram account verified: @{resolved_username} ({resolved_id})")


def upload_carousel_child_container(image_url):
    """Creates a child container for an item inside a carousel with retries."""
    url = f"{GRAPH_URL}/{MANCHESTER_IG_USER_ID}/media"
    payload = {
        "image_url": image_url,
        "is_carousel_item": "true",
        "access_token": IG_ACCESS_TOKEN
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, data=payload)
            result = response.json()

            if "id" in result:
                print(f"   - Child Container Created: {result['id']}")
                return result["id"]
            else:
                print(f"   ⚠️ Attempt {attempt+1} failed: {result.get('error', {}).get('message', 'Unknown error')}")
                if attempt < max_retries - 1:
                    time.sleep(10)
        except Exception as e:
            print(f"   ⚠️ Attempt {attempt+1} exception: {e}")
            if attempt < max_retries - 1:
                time.sleep(10)

    print(f"❌ Failed to create child container after {max_retries} attempts for: {image_url}")
    return None


def upload_carousel_container(child_ids, caption):
    """Creates the parent container for the carousel."""
    url = f"{GRAPH_URL}/{MANCHESTER_IG_USER_ID}/media"
    payload = {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": IG_ACCESS_TOKEN
    }
    response = requests.post(url, data=payload)
    result = response.json()

    if "id" not in result:
        print(f"❌ Error creating parent container: {result}")
        sys.exit(1)

    print(f"✅ Created Carousel Parent ID: {result['id']}")
    return result["id"]


def publish_media(creation_id):
    """Publishes a container."""
    url = f"{GRAPH_URL}/{MANCHESTER_IG_USER_ID}/media_publish"
    payload = {
        "creation_id": creation_id,
        "access_token": IG_ACCESS_TOKEN
    }
    response = requests.post(url, data=payload)
    result = response.json()

    if "id" in result:
        print(f"🚀 Published Successfully! Media ID: {result['id']}")
        return True
    else:
        print(f"❌ Publish Failed: {result}")
        return False


def check_media_status(container_id):
    """Checks if the container is ready to publish."""
    url = f"{GRAPH_URL}/{container_id}"
    params = {
        "fields": "status_code,status",
        "access_token": IG_ACCESS_TOKEN
    }

    print("   ⏳ Checking processing status...", end="", flush=True)
    for _ in range(5):
        response = requests.get(url, params=params)
        data = response.json()
        status = data.get("status_code")

        if status == "FINISHED":
            print(" Ready!")
            return True
        elif status == "ERROR":
            print(" Failed processing.")
            return False

        print(".", end="", flush=True)
        time.sleep(5)

    print(" Timeout.")
    return False


def main():
    if not MANCHESTER_IG_USER_ID or not IG_ACCESS_TOKEN:
        print("⚠️ Missing Instagram credentials. Skipping upload.")
        sys.exit(0)

    verify_target_account()
    print(f"🌐 Public image base URL: {PUBLIC_IMAGE_BASE_URL}")

    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="cinema", help="Post type: cinema or movie")
    args = parser.parse_args()
    post_type = args.type

    print(f"🔍 Mode: {post_type}")
    print(f"📂 Looking for files in: {OUTPUT_DIR}")

    feed_files = []
    caption_text = "No caption found."

    if post_type == "cinema":
        print("   -> Targeting V1 Files (Cinema Daily)")
        feed_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "post_image_*.png")))

        caption_path = os.path.join(OUTPUT_DIR, "post_caption.txt")
        if os.path.exists(caption_path):
            with open(caption_path, "r", encoding="utf-8") as f:
                caption_text = f.read()

    elif post_type == "movie":
        print("   -> Targeting V2 Files (Movie Spotlight)")
        feed_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "post_v2_image_*.png")))

        caption_path = os.path.join(OUTPUT_DIR, "post_v2_caption.txt")
        if os.path.exists(caption_path):
            with open(caption_path, "r", encoding="utf-8") as f:
                caption_text = f.read()

    cache_buster = int(time.time())
    feed_files = dedupe_files_by_content(feed_files)

    if feed_files:
        print(f"🔹 Detected {len(feed_files)} Feed Images.")

        child_ids = []
        for local_path in feed_files:
            filename = os.path.basename(local_path)
            image_url = f"{PUBLIC_IMAGE_BASE_URL}{filename}?v={cache_buster}"
            child_id = upload_carousel_child_container(image_url)
            if child_id:
                child_ids.append(child_id)
            time.sleep(2)

        if not child_ids:
            print("⚠️ No child containers created. Aborting feed post.")
            sys.exit(1)
        else:
            parent_id = upload_carousel_container(child_ids, caption_text)
            if not check_media_status(parent_id):
                print("❌ Instagram carousel container did not finish processing.")
                sys.exit(1)
            if not publish_media(parent_id):
                sys.exit(1)
    else:
        print("ℹ️ No feed images found.")


if __name__ == "__main__":
    main()
