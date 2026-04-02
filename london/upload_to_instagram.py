import os
import requests
import glob
import time
import sys
import argparse

# --- Configuration ---
# 1. Get secrets from GitHub Actions environment
IG_USER_ID = os.environ.get("IG_USER_ID")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")

# Point to the new folder in the URL so Instagram can download them
GITHUB_PAGES_BASE_URL = "https://jakobng.github.io/website1/london-cinema-scrapers/ig_posts/"

API_VERSION = "v21.0"
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}"

# Define local paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "ig_posts")


def upload_single_image_container(image_url, caption):
    """Creates a media container for a single image post with retries."""
    url = f"{GRAPH_URL}/{IG_USER_ID}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": IG_ACCESS_TOKEN
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, data=payload)
            result = response.json()

            if "id" in result:
                print(f"✅ Created Single Container ID: {result['id']}")
                return result["id"]
            else:
                print(f"   ⚠️ Attempt {attempt+1} failed: {result.get('error', {}).get('message', 'Unknown error')}")
                if attempt < max_retries - 1:
                    time.sleep(10)
        except Exception as e:
            print(f"   ⚠️ Attempt {attempt+1} exception: {e}")
            if attempt < max_retries - 1:
                time.sleep(10)

    print(f"❌ Error creating single container after {max_retries} attempts")
    sys.exit(1)


def upload_carousel_child_container(image_url):
    """Creates a child container for an item inside a carousel with retries."""

    """Creates a child container for an item inside a carousel with retries."""
    url = f"{GRAPH_URL}/{IG_USER_ID}/media"
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
                    time.sleep(10) # Wait longer between retries
        except Exception as e:
            print(f"   ⚠️ Attempt {attempt+1} exception: {e}")
            if attempt < max_retries - 1:
                time.sleep(10)

    print(f"❌ Failed to create child container after {max_retries} attempts for: {image_url}")
    return None


def upload_carousel_container(child_ids, caption):
    """Creates the parent container for the carousel."""
    url = f"{GRAPH_URL}/{IG_USER_ID}/media"
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
    """Publishes a container (Feed or Story)."""
    url = f"{GRAPH_URL}/{IG_USER_ID}/media_publish"
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
    for _ in range(5):  # Try 5 times
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
    if not IG_USER_ID or not IG_ACCESS_TOKEN:
        print("⚠️ Missing Instagram credentials. Skipping upload.")
        sys.exit(0)

    # Usage: python upload_to_instagram.py --type cinema
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

    if feed_files:
        print(f"🔹 Detected {len(feed_files)} Feed Images.")

        child_ids = []
        for local_path in feed_files:
            filename = os.path.basename(local_path)
            image_url = f"{GITHUB_PAGES_BASE_URL}{filename}?v={cache_buster}"
            child_id = upload_carousel_child_container(image_url)
            if child_id:
                child_ids.append(child_id)
            time.sleep(2)

        if not child_ids:
            print("⚠️ No child containers created. Aborting feed post.")
        else:
            parent_id = upload_carousel_container(child_ids, caption_text)
            if check_media_status(parent_id):
                publish_media(parent_id)
    else:
        print("ℹ️ No feed images found.")


if __name__ == "__main__":
    main()
