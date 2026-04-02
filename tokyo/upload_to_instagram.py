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
GITHUB_PAGES_BASE_URL = "https://jakobng.github.io/website1/tokyo-cinema-scrapers/ig_posts/" 

API_VERSION = "v21.0"
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}"

# Define local paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "ig_posts")

# --- API Helper Functions ---

CAPTION_MAX_LEN = 2200  # Instagram caption limit

def normalize_caption(text):
    if not text:
        return ""
    return text.replace("\r\n", "\n").strip()

def enforce_caption_length(text, max_len=CAPTION_MAX_LEN):
    if len(text) <= max_len:
        return text
    print(f"⚠️ Caption too long ({len(text)} chars). Truncating to {max_len}.")
    return text[:max_len].rstrip()

def upload_single_image_container(image_url, caption):
    """Creates a media container for a single image post."""
    url = f"{GRAPH_URL}/{IG_USER_ID}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": IG_ACCESS_TOKEN
    }
    response = requests.post(url, data=payload)
    result = response.json()
    
    if "id" not in result:
        print(f"❌ Error creating single container: {result}")
        sys.exit(1)
    
    print(f"✅ Created Single Container ID: {result['id']}")
    return result["id"]

def upload_carousel_child_container(image_url):
    """Creates a child container for an item inside a carousel."""
    url = f"{GRAPH_URL}/{IG_USER_ID}/media"
    payload = {
        "image_url": image_url,
        "is_carousel_item": "true",
        "access_token": IG_ACCESS_TOKEN
    }
    response = requests.post(url, data=payload)
    result = response.json()

    if "id" not in result:
        print(f"❌ Error creating child container: {result}")

        # Check for authentication errors - fail immediately
        if "error" in result:
            error_code = result["error"].get("code")
            if error_code == 190:  # OAuth/Authentication error
                print("🚨 CRITICAL: Access token is invalid or expired!")
                print("   This is likely due to:")
                print("   - Token expiration (Instagram tokens need periodic renewal)")
                print("   - Password change on Instagram/Facebook account")
                print("   - Session invalidated by Facebook for security")
                print("\n   ACTION REQUIRED: Regenerate IG_ACCESS_TOKEN and update GitHub secrets")
                sys.exit(1)

        return None

    print(f"   - Child Container Created: {result['id']}")
    return result["id"]

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
    for _ in range(5): # Try 5 times
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

# --- Main Logic ---

def main():
    if not IG_USER_ID or not IG_ACCESS_TOKEN:
        print("⚠️ Missing Instagram credentials. Skipping upload.")
        sys.exit(0)

    # Usage: python upload_to_instagram.py --type cinema
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="cinema", help="Post type: cinema or movie")
    args = parser.parse_args()
    POST_TYPE = args.type

    print(f"🔍 Mode: {POST_TYPE}")
    print(f"📂 Looking for files in: {OUTPUT_DIR}")

    feed_files = []
    caption_text = "No caption found."

    # ---------------------------------------------------------
    # STRICT FILE SELECTION LOGIC
    # ---------------------------------------------------------
    
    if POST_TYPE == "cinema":
        # Cinema Daily (V1) -> Looks for 'post_image_XX.png'
        print("   -> Targeting V1 Files (Cinema Daily)")
        feed_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "post_image_*.png")))

        caption_path = os.path.join(OUTPUT_DIR, "post_caption.txt")
        if os.path.exists(caption_path):
            with open(caption_path, "r", encoding="utf-8") as f:
                caption_text = f.read()

    elif POST_TYPE == "movie":
        # Movie Spotlight (V2) -> Looks for 'post_v2_image_XX.png'
        print("   -> Targeting V2 Files (Movie Spotlight)")
        feed_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "post_v2_image_*.png")))

        caption_path = os.path.join(OUTPUT_DIR, "post_v2_caption.txt")
        if os.path.exists(caption_path):
            with open(caption_path, "r", encoding="utf-8") as f:
                caption_text = f.read()

    caption_text = enforce_caption_length(normalize_caption(caption_text))

    # --- Cache Buster for GitHub Pages ---
    # Appends a timestamp so Instagram fetches the fresh file, not the cached old one.
    cache_buster = int(time.time())

    # --- FEED MODE ---
    if feed_files:
        print(f"🔹 Detected {len(feed_files)} Feed Images.")
        
        child_ids = []
        for local_path in feed_files:
            filename = os.path.basename(local_path)
            # FIX: Added ?v=... to URL
            image_url = f"{GITHUB_PAGES_BASE_URL}{filename}?v={cache_buster}"
            print(f"   Uploading: {filename} -> {image_url}")
            
            if len(feed_files) == 1:
                # Single Image
                c_id = upload_single_image_container(image_url, caption_text)
                publish_media(c_id)
            else:
                # Carousel Item
                c_id = upload_carousel_child_container(image_url)
                if c_id:
                    child_ids.append(c_id)
                time.sleep(2) # Brief pause

        if child_ids:
            print("🔹 Creating Carousel Parent...")
            parent_id = upload_carousel_container(child_ids, caption_text)
            
            if check_media_status(parent_id):
                publish_media(parent_id)

    else:
        print(f"ℹ️ No feed images found for mode '{POST_TYPE}'. Skipping Feed upload.")

if __name__ == "__main__":
    main()
