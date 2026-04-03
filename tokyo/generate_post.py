"""
Generate Instagram-ready image carousel (V4 - "Gemini Creative Director").
Focuses on "Raw Collage -> Gemini Director -> Gemini Generator" pipeline.
"""
from __future__ import annotations

import json
import math
import random
import re
import textwrap
import os
import requests
import glob
import time
import colorsys
import difflib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
import sys
import subprocess

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops, ImageOps

# --- Robust Auto-Install for Google GenAI ---
try:
    from google import genai
    from google.genai import types
except ImportError:
    print("📦 Library 'google-genai' not found. Installing...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "google-genai"])
        from google import genai
        from google.genai import types
    except Exception as e:
        print(f"⚠️ Critical: Failed to install 'google-genai'. Refinement will be skipped. Error: {e}")

# --- ⚡ FIX: Force JST (UTC+9) explicitly ---
JST = timezone(timedelta(hours=9))

def today_in_tokyo() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)

# Configuration
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FONTS_DIR = BASE_DIR / "fonts"
OUTPUT_DIR = BASE_DIR / "ig_posts"

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Path Updates
SHOWTIMES_PATH = DATA_DIR / "showtimes.json"
ASSETS_DIR = BASE_DIR / "cinema_assets"
CUTOUTS_DIR = ASSETS_DIR / "cutouts"
OUTPUT_CAPTION_PATH = OUTPUT_DIR / "post_caption.txt"
CREATIVE_HISTORY_PATH = DATA_DIR / "creative_direction_history.json"

# Font Updates
BOLD_FONT_PATH = FONTS_DIR / "NotoSansJP-Bold.ttf"
REGULAR_FONT_PATH = FONTS_DIR / "NotoSansJP-Regular.ttf"

# Secrets
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
print(f"[DEBUG] GEMINI_API_KEY available: {bool(GEMINI_API_KEY)}", flush=True)

# --- CONSTANTS ---
MINIMUM_FILM_THRESHOLD = 3
INSTAGRAM_SLIDE_LIMIT = 8 
MAX_FEED_VERTICAL_SPACE = 750 
MAX_STORY_VERTICAL_SPACE = 1150
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1350
STORY_CANVAS_HEIGHT = 1920
MARGIN = 60 
TITLE_WRAP_WIDTH = 30

# --- GLOBAL COLORS ---
WHITE = (255, 255, 255)
OFF_WHITE = (240, 240, 240)
LIGHT_GRAY = (230, 230, 230) 
DARK_SHADOW = (0, 0, 0, 180) 

# --- Database (Cinemas) ---
CINEMA_ADDRESSES = {
    "Bunkamura ル・シネマ 渋谷宮下": "東京都渋谷区渋谷1-23-16 6F",
    "K's Cinema (ケイズシネマ)": "東京都新宿区新宿3-35-13 3F",
    "シネマート新宿": "東京都新宿区新宿3-13-3 6F",
    "新宿武蔵野館": "東京都新宿区新宿3-27-10 3F",
    "テアトル新宿": "東京都新宿区新宿3-14-20 7F",
    "早稲田松竹": "東京都新宿区高田馬場1-5-16",
    "YEBISU GARDEN CINEMA": "東京都渋谷区恵比寿4-20-2",
    "シアター・イメージフォーラム": "東京都渋谷区渋谷2-10-2",
    "ユーロスペース": "東京都渋谷区円山町1-5 3F",
    "ヒューマントラストシネマ渋谷": "東京都渋谷区渋谷1-23-16 7F",
    "Stranger (ストレンジャー)": "東京都墨田区菊川3-7-1 1F",
    "新文芸坐": "東京都豊島区東池袋1-43-5 3F",
    "目黒シネマ": "東京都品川区上大崎2-24-15",
    "ポレポレ東中野": "東京都中野区東中野4-4-1 1F",
    "K2 Cinema": "東京都世田谷区北沢2-21-22 2F",
    "ヒューマントラストシネマ有楽町": "東京都千代田区有楽町2-7-1 8F",
    "ラピュタ阿佐ヶ谷": "東京都杉並区阿佐ヶ谷北2-12-21",
    "下高井戸シネマ": "東京都世田谷区松原3-30-15",
    "国立映画アーカイブ": "東京都中央区京橋3-7-6",
    "池袋シネマ・ロサ": "東京都豊島区西池袋1-37-12",
    "シネスイッチ銀座": "東京都中央区銀座4-4-5 3F",
    "シネマブルースタジオ": "東京都足立区千住3-92 2F",
    "CINEMA Chupki TABATA": "東京都北区東田端2-14-4",
    "シネクイント": "東京都渋谷区宇田川町20-11 8F",
    "アップリンク吉祥寺": "東京都武蔵野市吉祥寺本町1-5-1 4F",
    "下北沢トリウッド": "東京都世田谷区代沢5-32-5 2F",
    "Morc阿佐ヶ谷": "東京都杉並区阿佐谷北2-12-19 B1F",
    "シネマリス": "東京都千代田区神田小川町3-14-3 ilusa（イルサ）B1F",
    "アテネ・フランセ文化センター": "東京都千代田区神田駿河台2-11",
    "シネマ・ノヴェチェント": "神奈川県横浜市西区久保町26-1 2F",
    "シネマヴェーラ渋谷": "東京都渋谷区円山町1-5 4F",
    "アンスティチュ・フランセ東京": "東京都新宿区市谷船河原町15",
    "横浜シネマ・ジャック＆ベティ": "神奈川県横浜市中区若葉町3-51",
    "神保町シアター": "東京都千代田区神田神保町1-23",
    "角川シネマ有楽町": "東京都千代田区有楽町1-11-1 8F",
    "kino cinéma新宿": "東京都新宿区新宿3-13-3 4F",
    "kino cinéma立川髙島屋S.C.館": "東京都立川市曙町2-39-3 8F",
    "横浜シネマリン": "神奈川県横浜市中区長者町6-95",
    "Cinema Neko (シネマネコ)": "東京都青梅市西分町3-123"
}

CINEMA_ENGLISH_NAMES = {
    "Bunkamura ル・シネマ 渋谷宮下": "Bunkamura Le Cinéma",
    "K's Cinema (ケイズシネマ)": "K's Cinema",
    "シネマート新宿": "Cinemart Shinjuku",
    "新宿武蔵野館": "Shinjuku Musashino-kan",
    "テアトル新宿": "Theatre Shinjuku",
    "早稲田松竹": "Waseda Shochiku",
    "YEBISU GARDEN CINEMA": "Yebisu Garden Cinema",
    "シアター・イメージフォーラム": "Theatre Image Forum",
    "ユーロスペース": "Eurospace",
    "ヒューマントラストシネマ渋谷": "Human Trust Cinema Shibuya",
    "Stranger (ストレンジャー)": "Stranger",
    "新文芸坐": "Shin-Bungeiza",
    "目黒シネマ": "Meguro Cinema",
    "ポレポレ東中野": "Pole Pole Higashi-Nakano",
    "K2 Cinema": "K2 Cinema",
    "ヒューマントラストシネマ有楽町": "Human Trust Cinema Yurakucho",
    "ラピュタ阿佐ヶ谷": "Laputa Asagaya",
    "下高井戸シネマ": "Shimotakaido Cinema",
    "国立映画アーカイブ": "National Film Archive of Japan",
    "池袋シネマ・ロサ": "Ikebukuro Cinema Rosa",
    "シネスイッチ銀座": "Cine Switch Ginza",
    "シネマブルースタジオ": "Cinema Blue Studio",
    "CINEMA Chupki TABATA": "Cinema Chupki Tabata",
    "シネクイント": "Cine Quinto Shibuya",
    "アップリンク吉祥寺": "Uplink Kichijoji",
    "Morc阿佐ヶ谷": "Morc Asagaya",
    "下北沢トリウッド": "Tollywood",
    "シネマリス": "CineMalice",
    "アテネ・フランセ文化センター": "Athénée Français Cultural Center",
    "シネマ・ノヴェチェント": "Cinema Novecento",
    "シネマヴェーラ渋谷": "Cinema Vera Shibuya",
    "アンスティチュ・フランセ東京": "Institut Français Tokyo",
    "横浜シネマ・ジャック＆ベティ": "Cinema Jack & Betty",
    "神保町シアター": "Jinbocho Theatre",
    "角川シネマ有楽町": "Kadokawa Cinema Yurakucho",
    "kino cinéma新宿": "kino cinéma Shinjuku",
    "kino cinéma立川髙島屋S.C.館": "kino cinéma Tachikawa",
    "横浜シネマリン": "Yokohama Cinemarine",
    "Cinema Neko (シネマネコ)": "Cinema Neko",
    "ホワイト シネクイント": "White Cine Quinto",
    "シネ・リーブル池袋": "Cine Libre Ikebukuro",
    "キネカ大森": "Kineca Omori",
    "シネマシティ": "Cinema City",
    "東京都写真美術館": "Tokyo Photographic Art Museum",
    "吉祥寺オデヲン": "Kichijoji Odeon",
    "シアターギルド代官山": "Theater Guild Daikanyama",
    "シアターギルド下北沢": "Theater Guild Shimokitazawa",
    "シネマハウス大塚": "Cinema House Otsuka",
    "東劇": "Togeki"
}

CINEMA_FILENAME_OVERRIDES = {
    "国立映画アーカイブ": "nfaj",
    "シネマリス": "cinemalice",
    "ポレポレ東中野": "polepole",
    "新宿武蔵野館": "musashino_kan",
    "池袋シネマ・ロサ": "rosa",
    "シアター・イメージフォーラム": "image_forum",
    "シネマブルースタジオ": "blue_studio",
    "ヒューマントラストシネマ渋谷": "human_shibuya",
    "ヒューマントラストシネマ有楽町": "human_yurakucho",
    "アップリンク吉祥寺": "uplink",
    "新文芸坐": "shin_bungeiza",
    "早稲田松竹": "waseda_shochiku",
    "ホワイト シネクイント": "cine_quinto",
    "シネクイント": "cine_quinto",
    "渋谷シネクイント": "cine_quinto",
    "K's Cinema": "ks_cinema",
    "K's Cinema (ケイズシネマ)": "ks_cinema",
    "下高井戸シネマ": "shimotakaido",
    "アテネ・フランセ文化センター": "Athenee",
    "シネマ・ノヴェチェント": "novecento",
    "シネマヴェーラ渋谷": "vera",
    "アンスティチュ・フランセ東京": "francais",
    "横浜シネマ・ジャック＆ベティ": "jackandbetty",
    "神保町シアター": "jimbocho",
    "角川シネマ有楽町": "kadokawa",
    "kino cinéma新宿": "kinoshinjuku",
    "kino cinéma立川髙島屋S.C.館": "kinotachikawa",
    "横浜シネマリン": "cinemarine",
    "Cinema Neko (シネマネコ)": "neko",
    "キネカ大森": "cinekaomori",
    "シネマシティ": "cinemacity",
    "シネマハウス大塚": "cinemahouse",
    "シネ・リーブル池袋": "cinelibre",
    "吉祥寺オデヲン": "kichijojiodean",
    "シアターギルド代官山": "theatreguild",
    "東劇": "tokegi"
}

# --- Utility Functions ---
def is_probably_not_japanese(text: str | None) -> bool:
    if not text: return False
    if not re.search(r'[a-zA-Z]', text): return False 
    japanese_chars = re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text)
    latin_chars = re.findall(r'[a-zA-Z]', text)
    if not japanese_chars: return True
    if latin_chars:
        if len(latin_chars) > len(japanese_chars) * 2: return True
        if len(japanese_chars) <= 2 and len(latin_chars) > len(japanese_chars): return True
    return False

def clean_search_title(title: str) -> str:
    if not title: return ""
    title = re.sub(r'[\(（].*?[\)）]', '', title)
    title = re.sub(r'[\\\[\u3010].*?[\\\]\u3011]', '', title)
    keywords = ["4K", "2K", "3D", "IMAX", "Dolby", "Atmos", "レストア", "デジタル", "リマスター", "完全版", "ディレクターズカット", "劇場版", "特別上映", "特集", "上映後トーク", "舞台挨拶"]
    for kw in keywords:
        title = title.replace(kw, "")
    return title.strip()

def find_best_english_title(showing: dict) -> str | None:
    jp_title = showing.get('movie_title', '').lower()
    def get_clean_title(title_key: str) -> str | None:
        title = showing.get(title_key)
        if not is_probably_not_japanese(title): return None
        cleaned_title = title.split(' (')[0].strip()
        if cleaned_title.lower() in jp_title: return None
        return cleaned_title
    if en_title := get_clean_title('letterboxd_english_title'): return en_title
    if en_title := get_clean_title('tmdb_display_title'): return en_title
    if en_title := get_clean_title('movie_title_en'): return en_title
    return None

def parse_showtime_to_minutes(time_str: str) -> int:
    match = re.match(r'^\s*(\d{1,2})\s*:\s*(\d{2})\s*$', time_str)
    if not match:
        return 24 * 60 + 1
    hours, minutes = match.groups()
    return (int(hours) * 60) + int(minutes)

def load_showtimes(today_str: str) -> list[dict]:
    try:
        with SHOWTIMES_PATH.open("r", encoding="utf-8") as handle:
            all_showings = json.load(handle)
    except FileNotFoundError:
        print(f"showtimes.json not found at {SHOWTIMES_PATH}")
        raise
    except json.JSONDecodeError as exc:
        print("Unable to decode showtimes.json")
        raise exc
    todays_showings = [show for show in all_showings if show.get("date_text") == today_str]
    return todays_showings
    
def format_listings(showings: list[dict]) -> list[dict[str, str | None]]:
    movies: defaultdict[tuple[str, str | None], list[str]] = defaultdict(list)
    title_map: dict[str, str | None] = {}
    for show in showings:
        title = show.get("movie_title") or "タイトル未定"
        if title not in title_map:
            title_map[title] = find_best_english_title(show)
    for show in showings:
        title = show.get("movie_title") or "タイトル未定"
        en_title = title_map[title]
        time_str = show.get("showtime") or ""
        if time_str: movies[(title, en_title)].append(time_str)
    
    formatted = []
    for (title, en_title), times in movies.items():
        times.sort(key=parse_showtime_to_minutes)
        formatted.append({
            "title": title, 
            "en_title": en_title,
            "times": ", ".join(times),
            "first_showtime": times[0] if times else "23:59"
        })
    
    formatted.sort(key=lambda x: parse_showtime_to_minutes(x['first_showtime']))
    return formatted

def segment_listings(listings: list[dict[str, str | None]], max_height: int, spacing: dict[str, int]) -> list[list[dict]]:
    SEGMENTED_LISTS = []
    current_segment = []
    current_height = 0
    for listing in listings:
        required_height = spacing['jp_line'] + spacing['time_line']
        if listing.get('en_title'):
             required_height += spacing['en_line']
        if current_height + required_height > max_height:
            if current_segment:
                SEGMENTED_LISTS.append(current_segment)
                current_segment = [listing]
                current_height = required_height
            else:
                 SEGMENTED_LISTS.append([listing])
                 current_height = 0
        else:
            current_segment.append(listing)
            current_height += required_height
    if current_segment:
        SEGMENTED_LISTS.append(current_segment)
    return SEGMENTED_LISTS

def normalize_name(s):
    s = str(s).lower()
    return re.sub(r'[^a-z0-9_]', '', s)

def get_cinema_image_path(cinema_name: str) -> Path | None:
    if not ASSETS_DIR.exists(): return None
    if cinema_name in CINEMA_FILENAME_OVERRIDES:
        target = CINEMA_FILENAME_OVERRIDES[cinema_name]
    else:
        en_name = CINEMA_ENGLISH_NAMES.get(cinema_name, "")
        if en_name:
            target = normalize_name(en_name).replace("cinema", "").replace("theatre", "").strip()
        else:
            target = normalize_name(cinema_name)

    candidates = list(ASSETS_DIR.glob("*"))
    matches = []
    for f in candidates:
        if f.suffix.lower() not in ['.jpg', '.jpeg', '.png']: continue
        f_name_norm = normalize_name(f.stem)
        if target == f_name_norm: return f
        if target in f_name_norm or f_name_norm in target:
            matches.append(f)
        else:
            ratio = difflib.SequenceMatcher(None, target, f_name_norm).ratio()
            if ratio > 0.6: 
                matches.append(f)
    return random.choice(matches) if matches else None

def get_cutout_path(cinema_name: str) -> Path | None:
    if not CUTOUTS_DIR.exists(): return None
    if cinema_name in CINEMA_FILENAME_OVERRIDES:
        target = CINEMA_FILENAME_OVERRIDES[cinema_name]
    else:
        en_name = CINEMA_ENGLISH_NAMES.get(cinema_name, "")
        if en_name:
            target = normalize_name(en_name).replace("cinema", "").replace("theatre", "").strip()
        else:
            target = normalize_name(cinema_name)
    candidates = list(CUTOUTS_DIR.glob("*"))
    matches = []
    for f in candidates:
        if f.suffix.lower() not in ['.jpg', '.jpeg', '.png']: continue
        f_name_norm = normalize_name(f.stem)
        if target == f_name_norm: return f
        if target in f_name_norm or f_name_norm in target:
            matches.append(f)
        else:
            ratio = difflib.SequenceMatcher(None, target, f_name_norm).ratio()
            if ratio > 0.6:
                matches.append(f)
    return random.choice(matches) if matches else None

def convert_white_to_transparent(img: Image.Image, threshold: int = 240) -> Image.Image:
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    mask = ImageChops.darker(ImageChops.darker(r.point(lambda x: 255 if x > threshold else 0),
                                               g.point(lambda x: 255 if x > threshold else 0)),
                             b.point(lambda x: 255 if x > threshold else 0))
    new_alpha = ImageChops.subtract(a, mask)
    img.putalpha(new_alpha)
    return img

def create_layout_and_mask(cinemas: list[tuple[str, Path]], target_width: int, target_height: int) -> Image.Image:
    """
    Creates a simple collage of 4 cinema cutouts spread out.
    """
    width, height = target_width, target_height
    layout_rgba = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    
    # Use 4 cutouts as requested (if available)
    imgs_to_process = cinemas[:4]
    random.shuffle(imgs_to_process)
    
    # Simple logic to spread them out
    anchors = []
    if len(imgs_to_process) == 1:
        anchors = [(width//2, height//2)]
    elif len(imgs_to_process) == 2:
        anchors = [(width//2, height//3), (width//2, 2*height//3)]
    elif len(imgs_to_process) == 4:
        anchors = [
            (random.randint(int(width * 0.2), int(width * 0.45)), random.randint(int(height * 0.1), int(height * 0.4))),
            (random.randint(int(width * 0.55), int(width * 0.85)), random.randint(int(height * 0.1), int(height * 0.4))),
            (random.randint(int(width * 0.2), int(width * 0.45)), random.randint(int(height * 0.6), int(height * 0.9))),
            (random.randint(int(width * 0.55), int(width * 0.85)), random.randint(int(height * 0.6), int(height * 0.9)))
        ]
    else:
        # spread out more
        anchors = [
            (random.randint(int(width * 0.2), int(width * 0.8)), random.randint(int(height * 0.1), int(height * 0.4))),
            (random.randint(int(width * 0.1), int(width * 0.5)), random.randint(int(height * 0.4), int(height * 0.7))),
            (random.randint(int(width * 0.5), int(width * 0.9)), random.randint(int(height * 0.6), int(height * 0.9)))
        ]

    for i, (name, path) in enumerate(imgs_to_process):
        try:
            print(f"   ✂️ Processing: {name} ({path.name})", flush=True)
            raw = Image.open(path).convert("RGBA")
            # Assume white background and convert
            cutout = convert_white_to_transparent(raw)
            bbox = cutout.getbbox()
            if bbox: cutout = cutout.crop(bbox)
            
            # Fix: Ensure cutout isn't too small
            if min(cutout.size) < 5: continue
            
            scale = random.uniform(0.7, 1.1)
            max_dim = int(600 * scale)
            cutout.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            
            cx, cy = anchors[i] if i < len(anchors) else (width//2, height//2)
            # Jitter
            cx += random.randint(-50, 50)
            cy += random.randint(-50, 50)

            x = cx - (cutout.width // 2)
            y = cy - (cutout.height // 2)
            
            layout_rgba.paste(cutout, (x, y), mask=cutout)
                
        except Exception as e:
            print(f"Error processing {name}: {e}", flush=True)
            
    return layout_rgba

def load_recent_direction_history(limit: int = 4) -> list[dict]:
    if not CREATIVE_HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(CREATIVE_HISTORY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[-limit:]
    except Exception as e:
        print(f"   ⚠️ Could not read creative history: {e}", flush=True)
    return []

def save_direction_history_entry(date_text: str, director_prompt: str) -> None:
    history = load_recent_direction_history(limit=30)
    history.append({
        "date": date_text,
        "director_prompt": director_prompt,
    })
    try:
        CREATIVE_HISTORY_PATH.write_text(
            json.dumps(history[-30:], ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"   ⚠️ Could not save creative history: {e}", flush=True)

def gemini_creative_director(collage_img: Image.Image, cinema_names: list[str], date_text: str) -> str:
    """
    Step A: Creative Director Review.
    """
    print("   🧐 Creative Director (Gemini 3 Flash) reviewing...", flush=True)
    if not GEMINI_API_KEY:
        print("   ⚠️ No API Key found.")
        return ""

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        recent_history = load_recent_direction_history(limit=4)
        history_context = ""
        if recent_history:
            recent_lines = []
            for item in recent_history:
                short_prompt = (item.get("director_prompt") or "").replace("\n", " ")[:300]
                recent_lines.append(f"- {item.get('date', 'unknown date')}: {short_prompt}")
            history_context = "\nRecent creative direction (avoid repeating these moods/forms):\n" + "\n".join(recent_lines)
        
        prompt = f"""
        You are a Visionary Architect specializing in impossible geometry and avant-garde structural synthesis.
        You are looking at a collage of cinema buildings (exteriors and interiors) floating in space.

        {history_context}

        Your Goal: Write a prompt for a Generative AI that will fuse these isolated elements into a SINGLE, SOPHISTICATED, IMPOSSIBLE ARCHITECTURAL STRUCTURE.

        CRITICAL INSTRUCTIONS FOR THE PROMPT YOU WRITE:
        1.  **Format**: EXPLICITLY specify "Vertical Aspect Ratio (4:5)". The output must be a vertical poster composition.
        2.  **PRESERVE THE CORES**: Explicitly tell the generator these exact words: "The *centers* of the building cutouts are IMMUTABLE ANCHORS and must not be moved or alterered or drawn over. HOWEVER, you MUST aggressively blend, melt, and fuse their *edges* into the new structure. Do not treat them as floating stickers; they must feel physically embedded in the new architecture."
        3.  **Derive the Style**: Look at the collage with an observant, generous, imaginative eye. **Create a visual style for the connecting structure that complements or strikingly contrasts with these specific buildings.** Do not default to one style; let the input images dictate the vibe, but be inventive with it, try to see the best possible opportunity within this collage. 
        4.  **Sophisticated Fusion**: Avoid cheesy tropes. NO film reels, NO movie projectors, NO popcorn, NO generic "Cyberpunk".
        5.  **Structure**: Describe a structure where gravity and perspective are subjective. The roof of one building should morph seamlessly into the staircase of another, or the steps into a doorway. Use whatever language makes the most sense for the images you are seeing.
        6.  **Melt the Edges**: The *centers* of the photos are immutable, but their *edges* must dissolve naturally into the new structure. A brick wall should twist into a steel beam; a floor should curve up to become a ceiling.
        7.  **Atmosphere**: again, you look at the cutout images and you decide the vibe. But nothing cartoonish or unrealistic in texture. It should all be roughly photographic. But do play around widely within that.
        8.  **Variation Rule**: Compare with the recent creative direction list. Pick a clearly different formal language (e.g. blocky vs flowy, compressed vs sprawling), a different lighting mood, and a different material/colour strategy.
        9.  **Cutout Protection Rule**: Treat the central area of each cutout as locked source photography. Never paint over those core regions. Only transform the edge transition zones.
        10. **Text Integration**: The following text must be integrated subtly but legibly into the architecture (e.g., engraved in stone, projected on glass, or as stylish signage):
            - "Today's Cinema Selection"
            - "今日の上映" (Japanese for Today's Screening)
            - "{date_text}"

        Negative constraints: Do NOT move, resize, rotate, warp, or repaint the cutout centers. Do NOT replace the building interiors. Do NOT hallucinate completely new replacement buildings. Only dissolve/blend edges. Do NOT add cinema brands or signage not present in the source images.

        Output ONLY the prompt text.
        """
        
        response = client.models.generate_content(
            model="gemini-3-flash-preview", 
            contents=[prompt, collage_img],
            config=types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                ]
            )
        )
        director_prompt = response.text.strip()
        save_direction_history_entry(date_text, director_prompt)
        print(f"   📝 Director's Prompt: {director_prompt[:100]}...", flush=True)
        return director_prompt
    except Exception as e:
        print(f"   ⚠️ Director failed: {e}", flush=True)
        return ""

def generate_final_image(collage_img: Image.Image, prompt: str) -> Image.Image | None:
    """
    Step B: Final Generation.
    """
    print("   ✨ Generating Final Hero (Gemini 3 Pro Image)...", flush=True)
    if not GEMINI_API_KEY or not prompt: return None

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # We feed the collage image as input to guide the structure (ControlNet-like behavior expected from "Nano Banana Pro")
        response = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=[prompt, collage_img],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                safety_settings=[
                    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                ]
            )
        )
        
        for part in response.parts:
            if part.inline_data:
                return Image.open(BytesIO(part.inline_data.data)).convert("RGB")
        
        print("   ⚠️ No image returned in response.", flush=True)
    except Exception as e:
        print(f"   ⚠️ Generation Failed: {e}", flush=True)
        
    return None

def create_blurred_cinema_bg(cinema_name: str, width: int, height: int) -> Image.Image:
    full_path = get_cinema_image_path(cinema_name)
    base = Image.new("RGB", (width, height), (30, 30, 30))
    if not full_path: return base
    try:
        img = Image.open(full_path).convert("RGB")
        img = ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(10))
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 140))
        return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    except: return base

def draw_text_with_shadow(draw, xy, text, font, fill, shadow_color=DARK_SHADOW, offset=(3,3), anchor=None):
    draw.text((xy[0]+offset[0], xy[1]+offset[1]), text, font=font, fill=shadow_color, anchor=anchor)
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)

def draw_cinema_slide(cinema_name: str, cinema_name_en: str, listings: list[dict], bg_template: Image.Image) -> Image.Image:
    img = bg_template.copy(); draw = ImageDraw.Draw(img)
    title_jp_f = ImageFont.truetype(str(BOLD_FONT_PATH), 55); title_en_f = ImageFont.truetype(str(BOLD_FONT_PATH), 32)
    reg_f = ImageFont.truetype(str(REGULAR_FONT_PATH), 34); en_f = ImageFont.truetype(str(REGULAR_FONT_PATH), 28)
    y = MARGIN + 40
    draw_text_with_shadow(draw, (MARGIN+20, y), cinema_name, title_jp_f, WHITE); y += 70
    if cinema_name_en or CINEMA_ENGLISH_NAMES.get(cinema_name):
        draw_text_with_shadow(draw, (MARGIN+20, y), cinema_name_en or CINEMA_ENGLISH_NAMES[cinema_name], title_en_f, LIGHT_GRAY); y += 55
    draw.line([(MARGIN, y), (CANVAS_WIDTH-MARGIN, y)], fill=WHITE, width=2); y += 40
    for l in listings:
        for line in textwrap.wrap(f"■ {l['title']}", width=TITLE_WRAP_WIDTH):
            draw_text_with_shadow(draw, (MARGIN+20, y), line, reg_f, WHITE); y += 42
        if l['en_title']:
            for line in textwrap.wrap(f"({l['en_title']})", width=38):
                draw_text_with_shadow(draw, (MARGIN+30, y), line, en_f, LIGHT_GRAY); y += 32
        if l['times']:
            draw_text_with_shadow(draw, (MARGIN+60, y), l['times'], reg_f, LIGHT_GRAY); y += 60
    return img

def write_caption_for_multiple_cinemas(
    date_str: str,
    all_featured_cinemas: list[dict],
    cinema_address_overrides: dict[str, str] | None = None
) -> None:
    lines = [f"🗓️ 本日の東京ミニシアター上映情報 / Today's Featured Showtimes ({date_str})\n"]
    for item in all_featured_cinemas:
        cinema_name = item['cinema_name']
        address = CINEMA_ADDRESSES.get(cinema_name, "")
        if not address and cinema_address_overrides:
            address = cinema_address_overrides.get(cinema_name, "")
        lines.append(f"\n--- 【{cinema_name}】 ---")
        if address:
            jp_address = address.split('\n')[0]
            lines.append(f"📍 {jp_address}") 
        for listing in item['listings']:
            lines.append(f"• {listing['title']}")
    
    lines.append("\nCheck Bio for Full Schedule")
    with OUTPUT_CAPTION_PATH.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def main():
    today = today_in_tokyo().date(); today_str = today.isoformat()
    print(f"🕒 Today: {today_str}"); [f.unlink() for f in OUTPUT_DIR.glob("*.png")]
    
    showings = load_showtimes(today_str)
    if not showings: print("❌ No showings."); return
    
    grouped = defaultdict(list)
    for s in showings: grouped[s['cinema_name']].append(s)
    valid = [c for c, s in grouped.items() if len(s) >= MINIMUM_FILM_THRESHOLD]; random.shuffle(valid)
    selected = valid[:INSTAGRAM_SLIDE_LIMIT]
    if not selected: return

    # --- New Hero Workflow ---
    cinema_images = []
    for c in selected:
        if path := get_cutout_path(c):
            cinema_images.append((c, path))
        elif path := get_cinema_image_path(c):
             # Fallback if no cutout exists
             cinema_images.append((c, path))
    
    if cinema_images:
        print(f"   🎨 Found {len(cinema_images)} images. Starting Creative Director Pipeline...", flush=True)
        
        # 1. Create Raw Collage (Keep RGBA for transparency)
        raw_collage = create_layout_and_mask(cinema_images, CANVAS_WIDTH, CANVAS_HEIGHT)
        
        # For the Director (Analysis), flattened on white is usually clearer to "see" the composition
        raw_collage_flat = Image.new("RGB", raw_collage.size, (255, 255, 255))
        raw_collage_flat.paste(raw_collage, mask=raw_collage)
        
        # Save Raw for debugging
        raw_collage.save(OUTPUT_DIR / "debug_raw_collage.png")
        
        # Prepare date string for the prompt
        # today is already a datetime.date object from earlier in main
        date_text_jp = today.strftime("%Y.%m.%d")
        
        # 2. Creative Director (Flash) - Analyze the layout
        director_prompt = gemini_creative_director(raw_collage_flat, [c[0] for c in cinema_images], date_text_jp)
        
        if director_prompt:
            # 3. Final Generator (Pro Image)
            # CRITICAL CHANGE: Pass the RGBA image. 
            # We hope the model interprets alpha=0 as "fill this" and alpha=255 as "keep this".
            final_hero = generate_final_image(raw_collage, director_prompt)
            
            if final_hero:
                final_hero = final_hero.resize((CANVAS_WIDTH, CANVAS_HEIGHT), Image.Resampling.LANCZOS)
                final_hero.save(OUTPUT_DIR / "post_image_00.png")
                print(f"   ✅ Hero Image Generated and Resized to {CANVAS_WIDTH}x{CANVAS_HEIGHT}!", flush=True)
            else:
                print("   ❌ Final Generation failed. Using Raw Collage as fallback.")
                raw_collage_flat.save(OUTPUT_DIR / "post_image_00.png")
        else:
             print("   ❌ Director failed. Using Raw Collage as fallback.")
             raw_collage_flat.save(OUTPUT_DIR / "post_image_00.png")

    # --- Slide Generation ---
    slide_idx = 0; all_featured = []
    cinema_address_overrides = {}
    for s in showings:
        if s.get("cinema_address") and s.get("cinema_name") not in cinema_address_overrides:
            cinema_address_overrides[s["cinema_name"]] = s["cinema_address"]
    for c_name in selected:
        if slide_idx >= 9: break
        listings = format_listings(grouped[c_name])
        segmented = segment_listings(listings, MAX_FEED_VERTICAL_SPACE, {'jp_line': 40, 'time_line': 55, 'en_line': 30})
        bg = create_blurred_cinema_bg(c_name, CANVAS_WIDTH, CANVAS_HEIGHT)
        all_featured.append({'cinema_name': c_name, 'listings': [l for sub in segmented for l in sub]})
        for seg in segmented:
            slide_idx += 1
            if slide_idx >= 10: break
            draw_cinema_slide(c_name, "", seg, bg).save(OUTPUT_DIR / f"post_image_{slide_idx:02}.png")
            
    write_caption_for_multiple_cinemas(today_str, all_featured, cinema_address_overrides)
    print(f"✅ Done. Generated {slide_idx} slides.")

if __name__ == "__main__": main()
