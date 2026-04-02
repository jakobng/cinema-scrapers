"""
Generate Instagram-ready image carousel (London Edition - Based on Tokyo V2.2).
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

# --- Timezone: London (UTC+0/+1 depending on DST) ---
# Note: In production, using zoneinfo is better, but keeping simple relative to UTC for now
# or using the system time if configured correctly.
# Here we will try to use the system local time if possible, or default to UTC.
def today_in_london() -> datetime:
    """Returns London datetime."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/London"))
    except ImportError:
        # Fallback if zoneinfo not available (Python < 3.9)
        return datetime.now(timezone.utc)

# --- API Setup ---
try:
    import replicate
    REPLICATE_AVAILABLE = True
except ImportError:
    print("⚠️ Replicate library not found. Run: pip install replicate")
    REPLICATE_AVAILABLE = False

# --- Configuration ---
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

# Font Updates - Using the fonts found in the London project fonts folder
BOLD_FONT_PATH = FONTS_DIR / "NotoSansJP-Bold.ttf"
REGULAR_FONT_PATH = FONTS_DIR / "NotoSansJP-Regular.ttf"

# Secrets
REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- Constants ---
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

# --- Database (London Cinemas) ---
CINEMA_ADDRESSES = {
    # Individual cinemas
    "BFI Southbank": "Belvedere Rd, London SE1 8XT",
    "BFI IMAX": "1 Charlie Chaplin Walk, London SE1 8XR",
    "Prince Charles Cinema": "7 Leicester Pl, London WC2H 7BY",
    "Rio Cinema": "107 Kingsland High St, London E8 2PB",
    "Genesis Cinema": "93-95 Mile End Rd, London E1 4UJ",
    "Barbican Cinema": "Silk St, London EC2Y 8DS",
    "Electric Cinema Portobello": "191 Portobello Rd, London W11 2ED",
    "Electric Cinema White City": "Television Centre, 101 Wood Ln, London W12 7FR",
    "ICA Cinema": "The Mall, St. James's, London SW1Y 5AH",
    "Phoenix Cinema": "52 High Rd, London N2 9PJ",
    "Regent Street Cinema": "309 Regent St, London W1B 2UW",
    "Ciné Lumière": "17 Queensberry Pl, London SW7 2DT",
    "Close-Up Film Centre": "97 Sclater St, London E1 6HR",
    "Rich Mix": "35-47 Bethnal Green Rd, London E1 6LA",
    "The Castle Cinema": "64-66 Brooksby's Walk, London E9 6DA",
    "The Garden Cinema": "39-41 Parker St, London WC2B 5PQ",
    "The Lexi Cinema": "194B Chamberlayne Rd, London NW10 3JU",
    "ArtHouse Crouch End": "159A Tottenham Ln, London N8 9BT",
    "Chiswick Cinema": "2 Power Rd, London W4 5PY",
    "JW3 Cinema": "341-351 Finchley Rd, London NW3 6ET",
    "Bertha DocHouse": "Curzon Bloomsbury, Brunswick Centre, London WC1N 1AW",
    "David Lean Cinema": "Croydon Clocktower, Katharine St, Croydon CR9 1ET",
    "Sands Films Cinema Club": "82 St Marychurch St, London SE16 4HZ",
    "The Cinema in the Arches": "Cambridge Heath Rd, London E2 9PA",
    "The Nickel": "49 Greenwich High Rd, London SE10 8JL",
    "ActOne Cinema & Cafe": "1 Centre Way, Acton, London W3 7LH",
    "Ciné-Real": "Above The Dolphin, 165 Mare St, London E8 3RH",
    "Coldharbour Blue": "St Matthew's Community Space, Brixton Hill, London SW2 1JF",
    "Olympic Studios (Barnes)": "117-123 Church Rd, Barnes, London SW13 9HL",
    "The Arzner": "18 Bermondsey Square, London SE1 3UN",
    "Kiln Theatre": "269 Kilburn High Rd, London NW6 7JR",
    "Riverside Studios": "101 Queen Caroline St, London W6 9BN",
    "Peckhamplex": "95A Rye Ln, London SE15 4ST",
    "The Cinema Museum": "2 Dugard Way, London SE11 4TH",
    # Curzon chain
    "Curzon Soho": "99 Shaftesbury Ave, London W1D 5DY",
    "Curzon Mayfair": "38 Curzon St, London W1J 7TY",
    "Curzon Bloomsbury": "Brunswick Centre, London WC1N 1AW",
    "Curzon Victoria": "58 Victoria St, London SW1E 6QP",
    "Curzon Camden": "Regent's Canal, Jamestown Rd, London NW1 7BY",
    "Curzon Hoxton": "56-58 Hoxton Square, London N1 6PB",
    "Curzon Aldgate": "2 Canter Way, London E1 8PS",
    "Curzon Sea Containers": "18 Upper Ground, London SE1 9PD",
    "Curzon Wimbledon": "23 The Broadway, London SW19 1PS",
    "Curzon Richmond": "3 Red Lion St, Richmond TW9 1RW",
    "Curzon Kingston": "Charter Quay, Kingston upon Thames KT1 1HR",
    # Everyman chain
    "Everyman Baker Street": "96-98 Baker St, London W1U 6TJ",
    "Everyman Barnet": "Great North Rd, Barnet EN5 1AB",
    "Everyman Belsize Park": "203 Haverstock Hill, London NW3 4QG",
    "Everyman Borough Yards": "2 Dirty Lane, London SE1 9PA",
    "Everyman Brentford": "20 High St, Brentford TW8 0AH",
    "Everyman Broadgate": "14 Appold St, London EC2A 2BD",
    "Everyman Canary Wharf": "Crossrail Place, London E14 5AR",
    "Everyman Chelsea": "279 King's Rd, London SW3 5EW",
    "Everyman Crystal Palace": "25 Church Rd, London SE19 2TE",
    "Everyman Hampstead": "5 Holly Bush Vale, London NW3 6TX",
    "Everyman King's Cross": "14 Handyside St, London N1C 4DN",
    "Everyman Maida Vale": "215 Sutherland Ave, London W9 1RU",
    "Everyman Muswell Hill": "Fortis Green Rd, London N10 3HP",
    "Everyman Screen on the Green": "83 Upper St, London N1 0NP",
    "Everyman Stratford International": "1 International Way, London E20 1DB",
    "Everyman The Whiteley": "Queensway, London W2 4YL",
    # Picturehouse chain
    "Clapham Picturehouse": "76 Venn St, London SW4 0AT",
    "Crouch End Picturehouse": "165 Tottenham Ln, London N8 9BY",
    "Ealing Picturehouse": "43 Mattock Ln, London W5 5BJ",
    "East Dulwich Picturehouse": "Lordship Ln, London SE22 8HZ",
    "Finsbury Park Picturehouse": "211 Stroud Green Rd, London N4 3PZ",
    "Greenwich Picturehouse": "180 Greenwich High Rd, London SE10 8NN",
    "Hackney Picturehouse": "270 Mare St, London E8 1HE",
    "Picturehouse Central": "Corner of Shaftesbury Ave & Great Windmill St, London W1D 7DH",
    "Ritzy Cinema": "Brixton Oval, Coldharbour Ln, London SW2 1JG",
    "The Gate": "87 Notting Hill Gate, London W11 3JZ",
    "West Norwood Picturehouse": "6 Norwood High St, London SE27 9NR",
}

CINEMA_FILENAME_OVERRIDES = {
    # Individual cinemas
    "BFI Southbank": "bfi",
    "BFI IMAX": "bfiimax",
    "Prince Charles Cinema": "princecharles",
    "Rio Cinema": "rio",
    "Genesis Cinema": "genesis",
    "Barbican Cinema": "barbican",
    "Electric Cinema Portobello": "electric",
    "Electric Cinema White City": "electricwhitecity",
    "ICA Cinema": "ica",
    "Phoenix Cinema": "phoenix",
    "Regent Street Cinema": "regentstreet",
    "Ciné Lumière": "cinelumiere",
    "Close-Up Film Centre": "closeup",
    "Rich Mix": "richmix",
    "The Castle Cinema": "castle",
    "The Garden Cinema": "garden",
    "The Lexi Cinema": "lexi",
    "ArtHouse Crouch End": "arthouse",
    "Chiswick Cinema": "chiswick",
    "JW3 Cinema": "jw3",
    "Bertha DocHouse": "dochouse",
    "David Lean Cinema": "davidlean",
    "Sands Films Cinema Club": "sands",
    "The Cinema in the Arches": "arches",
    "The Nickel": "nickel",
    "ActOne Cinema & Cafe": "actone",
    "Ciné-Real": "cinereal",
    "Coldharbour Blue": "coldharbourblue",
    "Olympic Studios (Barnes)": "olympicbarnes",
    "The Arzner": "arzner",
    "Kiln Theatre": "kiln",
    "Riverside Studios": "riversidestudios",
    "Peckhamplex": "peckhamplex",
    "The Cinema Museum": "cinemamuseum",
    # Curzon chain
    "Curzon Soho": "curzon",
    "Curzon Mayfair": "curzonmayfair",
    "Curzon Bloomsbury": "curzonbloomsbury",
    "Curzon Victoria": "curzonvictoria",
    "Curzon Camden": "curzoncamden",
    "Curzon Hoxton": "curzonhoxton",
    "Curzon Aldgate": "curzonaldgate",
    "Curzon Sea Containers": "curzonseacontainers",
    "Curzon Wimbledon": "curzonwimbledon",
    "Curzon Richmond": "curzonrichmond",
    "Curzon Kingston": "curzonkingston",
    # Everyman chain
    "Everyman Baker Street": "everymanbakerstreet",
    "Everyman Barnet": "everymanbarnet",
    "Everyman Belsize Park": "everymanbelsizepark",
    "Everyman Borough Yards": "everymanboroughyards",
    "Everyman Brentford": "everymanbrentford",
    "Everyman Broadgate": "everymanbroadgate",
    "Everyman Canary Wharf": "everymancanarywharf",
    "Everyman Chelsea": "everymanchelsea",
    "Everyman Crystal Palace": "everymancrystalpalace",
    "Everyman Hampstead": "everymanhampstead",
    "Everyman King's Cross": "everymankingscross",
    "Everyman Maida Vale": "everymanmaidavale",
    "Everyman Muswell Hill": "everymanmuswellhill",
    "Everyman Screen on the Green": "everymanscreenonthegreen",
    "Everyman Stratford International": "everymanstratford",
    "Everyman The Whiteley": "everymanwhiteley",
    # Picturehouse chain
    "Clapham Picturehouse": "clapham",
    "Crouch End Picturehouse": "crouchendpicturehouse",
    "Ealing Picturehouse": "ealing",
    "East Dulwich Picturehouse": "eastdulwich",
    "Finsbury Park Picturehouse": "finsburypark",
    "Greenwich Picturehouse": "greenwich",
    "Hackney Picturehouse": "hackney",
    "Picturehouse Central": "picturehousecentral",
    "Ritzy Cinema": "ritzy",
    "The Gate": "gate",
    "West Norwood Picturehouse": "westnorwood",
}

# --- Utility Functions ---

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
    movies: defaultdict[str, list[str]] = defaultdict(list)
    for show in showings:
        title = show.get("movie_title") or "Untitled"
        time_str = show.get("showtime") or ""
        if time_str: movies[title].append(time_str)
    
    formatted = []
    for title, times in movies.items():
        times.sort()
        formatted.append({
            "title": title, 
            "times": ", ".join(times),
            "first_showtime": times[0] if times else "23:59"
        })
    
    formatted.sort(key=lambda x: x['first_showtime'])
    return formatted

def segment_listings(listings: list[dict[str, str | None]], max_height: int, spacing: dict[str, int]) -> list[list[dict]]:
    SEGMENTED_LISTS = []
    current_segment = []
    current_height = 0
    for listing in listings:
        required_height = spacing['title_line'] + spacing['time_line']
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

def get_recently_featured(caption_path: Path) -> list[str]:
    if not caption_path.exists(): return []
    try:
        content = caption_path.read_text(encoding="utf-8")
        names = re.findall(r"--- 【(.*?)】 ---", content)
        return names
    except Exception as e:
        print(f"   [WARN] Could not read previous caption: {e}")
        return []

# --- ASSET & REPLICATE LOGIC ---

def normalize_name(s):
    s = str(s).lower()
    return re.sub(r'[^a-z0-9]', '', s)

def is_major_chain(cinema_name: str) -> bool:
    """Returns True if the cinema belongs to a major chain."""
    if not cinema_name: return False
    name = cinema_name.lower()
    if "everyman" in name or "picturehouse" in name or "curzon" in name:
        return True
    if name in ["ritzy cinema", "the gate"]:
        return True
    return False

def get_cinema_image_path(cinema_name: str) -> Path | None:
    """Get full cinema image for slide backgrounds from ASSETS_DIR."""
    if not ASSETS_DIR.exists(): return None
    if cinema_name in CINEMA_FILENAME_OVERRIDES:
        target = CINEMA_FILENAME_OVERRIDES[cinema_name]
    else:
        target = normalize_name(cinema_name)

    if not target: return None

    candidates = list(ASSETS_DIR.glob("*"))
    matches = []
    for f in candidates:
        if f.suffix.lower() not in ['.jpg', '.jpeg', '.png']: continue
        f_name = normalize_name(f.stem)
        if target == f_name:
            matches.append(f)

    if matches:
        return random.choice(matches)
    return None

def get_cutout_path(cinema_name: str) -> Path | None:
    """Get cutout image for hero collage from CUTOUTS_DIR subfolder."""
    if not CUTOUTS_DIR.exists(): return None
    if cinema_name in CINEMA_FILENAME_OVERRIDES:
        target = CINEMA_FILENAME_OVERRIDES[cinema_name]
    else:
        target = normalize_name(cinema_name)

    if not target: return None

    candidates = list(CUTOUTS_DIR.glob("*"))
    matches = []
    for f in candidates:
        if f.suffix.lower() not in ['.jpg', '.jpeg', '.png']: continue
        f_name = normalize_name(f.stem)
        if target == f_name:
            matches.append(f)

    if matches:
        return random.choice(matches)
    return None

def convert_white_to_transparent(img: Image.Image, threshold: int = 240) -> Image.Image:
    """Convert white/near-white pixels to transparent for cutouts with white backgrounds."""
    img = img.convert("RGBA")
    data = img.getdata()
    new_data = []
    for item in data:
        # If pixel is white-ish (all RGB values above threshold), make transparent
        if item[0] > threshold and item[1] > threshold and item[2] > threshold:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    img.putdata(new_data)
    return img

def create_layout_and_mask(cinemas: list[tuple[str, Path]], target_width: int, target_height: int) -> tuple[Image.Image, Image.Image]:
    """
    Creates a collage of cinema cutouts and a mask for inpainting.
    Mask: White = Area to Inpaint (Space), Black = Keep (Cutouts).
    The mask is slightly dilated (Space grows into Cutout) to ensure blending.
    """
    width = target_width
    height = target_height
    layout_rgba = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    # Inpaint mask: Start with White (Inpaint Everything)
    mask = Image.new("L", (width, height), 255)

    # Use 4 cutouts as requested (if available)
    imgs_to_process = cinemas[:4]
    
    random.shuffle(imgs_to_process)

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
            raw = Image.open(path).convert("RGBA")
            cutout = convert_white_to_transparent(raw)
            bbox = cutout.getbbox()
            if bbox: cutout = cutout.crop(bbox)

            # Resize reasonably
            scale_variance = random.uniform(0.8, 1.2)
            max_dim = int(500 * scale_variance)
            cutout.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            cx, cy = anchors[i] if i < len(anchors) else (width//2, height//2)
            # Jitter
            cx += random.randint(-50, 50)
            cy += random.randint(-50, 50)

            x = cx - (cutout.width // 2)
            y = cy - (cutout.height // 2)

            # Paste onto layout
            layout_rgba.paste(cutout, (x, y), mask=cutout)
            
            # Update Mask: Paste Black (0) where the cutout is opaque
            alpha = cutout.split()[3]
            # Threshold alpha to be sure
            alpha_mask = alpha.point(lambda p: 255 if p > 10 else 0)
            # Invert alpha for the mask (Solid part -> Black/0 = Protected)
            mask.paste(0, (x, y), mask=alpha_mask)

        except Exception as e:
            print(f"Error processing cutout {name}: {e}")

    # Expand White (Space) into Black (Cutout)
    mask = mask.filter(ImageFilter.MaxFilter(9))

    return layout_rgba, mask

def load_recent_direction_history(limit: int = 4) -> list[dict]:
    if not CREATIVE_HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(CREATIVE_HISTORY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[-limit:]
    except Exception as e:
        print(f"   ⚠️ Could not read creative history: {e}")
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
        print(f"   ⚠️ Could not save creative history: {e}")

def creative_director_review(original_layout: Image.Image, date_text: str) -> str:
    """
    Uses Gemini to look at the layout and write a prompt for the final generation.
    """
    print("   🧐 Creative Director (Gemini 3 Flash) reviewing...", flush=True)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return "Make a cool cinema collage."

    client = genai.Client(api_key=api_key)
    
    # Prepare inputs: Original Layout
    inputs = []
    inputs.append("Role: Creative Director. Task: Analyze this image to guide the creation of a final masterpiece.")
    inputs.append("Image: Original Collage (Reference for cutouts).")
    inputs.append(original_layout)
    recent_history = load_recent_direction_history(limit=4)
    if recent_history:
        recent_lines = []
        for item in recent_history:
            short_prompt = (item.get("director_prompt") or "").replace("\n", " ")[:300]
            recent_lines.append(f"- {item.get('date', 'unknown date')}: {short_prompt}")
        inputs.append(
            "Recent creative direction (avoid repeating these moods/forms):\n" +
            "\n".join(recent_lines)
        )
        
    prompt = f"""
        You are a Visionary Architect specializing in impossible geometry and avant-garde structural synthesis.
        You are looking at a collage of cinema buildings (exteriors and interiors) floating in space.
        
        Your Goal: Write a prompt for a Generative AI that will fuse these isolated elements into a SINGLE, SOPHISTICATED, IMPOSSIBLE ARCHITECTURAL STRUCTURE for a LONDON cinema post.
        
        CRITICAL INSTRUCTIONS FOR THE PROMPT YOU WRITE:
        1.  **Format**: EXPLICITLY specify "Vertical Aspect Ratio (4:5)". The output must be a vertical poster composition.
        2.  **PRESERVE THE CORES**: Explicitly tell the generator: "The *centers* of the building photos are IMMUTABLE ANCHORS and must not be moved. HOWEVER, you MUST aggressively blend, melt, and fuse their *edges* into the new structure. Do not treat them as floating stickers; they must feel physically embedded in the new architecture."
        3.  **Derive the Style**: Look at the collage. Are the cinemas retro? Modern? Wooden? Concrete? Colorful? **Create a visual style for the connecting structure that complements or strikingly contrasts with these specific buildings.** Do not default to one style; let the input images dictate the vibe.
        4.  **Sophisticated Fusion**: Avoid cheesy tropes. NO film reels, NO movie projectors, NO popcorn, NO generic "Cyberpunk". 
        5.  **Structure**: Describe a structure where gravity and perspective are subjective. The roof of one building should morph seamlessly into the staircase of another, or the steps into a doorway. Use whatever language makes the most sense for the images you are seeing.
        6.  **Melt the Edges**: The *centers* of the photos are immutable, but their *edges* must dissolve naturally into the new structure. A brick wall should twist into a steel beam; a floor should curve up to become a ceiling.
        7.  **Atmosphere**: again, you look at the cutout images and you decide the vibe. But nothing cartoonish or unrealistic in texture. It should all be roughly photographic. But do play around widely within that.
        8.  **Variation Rule**: Compare with the recent creative direction list. Pick a clearly different formal language (e.g. blocky vs flowy, compressed vs sprawling), a different lighting mood, and a different material/colour strategy.
        9.  **Cutout Protection Rule**: Treat the central area of each cutout as locked source photography. Never paint over those core regions. Only transform the edge transition zones.
        10. **Text**: Include the text "LONDON CINEMA" and "{date_text}" integrated subtly (e.g., engraved, projected, or as a structural element).

        Negative constraints: Do NOT move, resize, rotate, warp, or repaint the cutout centers. Do NOT replace the building interiors. Do NOT hallucinate completely new replacement buildings. Only dissolve/blend edges.
        
        Output ONLY the prompt text.
        """
    inputs.append(prompt)
    
    try:
        response = client.models.generate_content(
            model="gemini-3-flash-preview", 
            contents=inputs,
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
        print(f"   📝 Director's Full Prompt:\n{director_prompt}\n" + "-"*40, flush=True)
        return director_prompt
    except Exception as e:
        print(f"   ⚠️ Director failed: {e}", flush=True)
        return "Surreal cinema architecture collage, high quality, cinematic lighting."

def generate_final_hero(original_layout: Image.Image, prompt: str) -> Image.Image:
    """
    Generates the final image using Gemini 3 Pro Image Preview.
    """
    print("   ✨ Generating Final Hero (Gemini 3 Pro)...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return original_layout.convert("RGB")

    client = genai.Client(api_key=api_key)
    
    try:
        response = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=[prompt, original_layout], 
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            )
        )
        for part in response.parts:
            if part.inline_data:
                return Image.open(BytesIO(part.inline_data.data)).convert("RGB")
    except Exception as e:
        print(f"   ⚠️ Final Generation Failed: {e}")
    
    return original_layout.convert("RGB")

def create_hero_image_workflow(selected_cinemas: list[str], date_str: str) -> Image.Image | None:
    # 1. Gather Assets (Prioritize Cutouts)
    cinema_cutouts = []
    
    # First pass: Look for cutouts ONLY
    for c in selected_cinemas:
        if path := get_cutout_path(c):
            cinema_cutouts.append((c, path))
    
    # If no cutouts found at all, fall back to full images (but try to avoid)
    if not cinema_cutouts:
        print("   ⚠️ No cutouts found for selected cinemas. Falling back to standard images.")
        for c in selected_cinemas:
            if path := get_cinema_image_path(c):
                cinema_cutouts.append((c, path))

    if not cinema_cutouts:
        return None

    # 2. Preprocess (Collage + Mask)
    print("   🎨 Creating Layout & Mask...")
    layout_rgba, mask = create_layout_and_mask(cinema_cutouts, CANVAS_WIDTH, CANVAS_HEIGHT)
    layout_rgba.save(OUTPUT_DIR / "debug_00_layout.png")
    mask.save(OUTPUT_DIR / "debug_00_mask.png")
    
    # 3. Creative Direction
    final_prompt = creative_director_review(layout_rgba, date_str)
    
    # 4. Final Generation
    final_image = generate_final_hero(layout_rgba, final_prompt)
    
    return final_image.resize((CANVAS_WIDTH, CANVAS_HEIGHT), Image.Resampling.LANCZOS)

def create_blurred_cinema_bg(cinema_name: str, width: int, height: int) -> Image.Image:
    full_path = get_cinema_image_path(cinema_name)
    base = Image.new("RGB", (width, height), (30, 30, 30))
    if not full_path or not full_path.exists():
        return base
    try:
        img = Image.open(full_path).convert("RGB")
        target_ratio = width / height
        img_ratio = img.width / img.height
        if img_ratio > target_ratio:
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        else:
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(8))
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 120))
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay).convert("RGB")
        return img
    except Exception as e:
        print(f"Error creating background for {cinema_name}: {e}")
        return base

def draw_text_with_shadow(draw, xy, text, font, fill, shadow_color=DARK_SHADOW, offset=(3,3), anchor=None):
    x, y = xy
    draw.text((x + offset[0], y + offset[1]), text, font=font, fill=shadow_color, anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)

def draw_cinema_slide(cinema_name: str, listings: list[dict[str, str | None]], bg_template: Image.Image) -> Image.Image:
    img = bg_template.copy()
    draw = ImageDraw.Draw(img)
    try:
        # Load fonts - using the Japanese fonts as they are available in the folder
        title_font = ImageFont.truetype(str(BOLD_FONT_PATH), 55)
        regular_font = ImageFont.truetype(str(REGULAR_FONT_PATH), 34)
        small_font = ImageFont.truetype(str(REGULAR_FONT_PATH), 28)
        footer_font = ImageFont.truetype(str(REGULAR_FONT_PATH), 24)
    except Exception:
        # Fallback
        title_font = ImageFont.load_default()
        regular_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
        footer_font = ImageFont.load_default()
        
    content_left = MARGIN + 20
    y_pos = MARGIN + 40
    
    draw_text_with_shadow(draw, (content_left, y_pos), cinema_name, title_font, WHITE)
    y_pos += 70
        
    address = CINEMA_ADDRESSES.get(cinema_name, "")
    if address:
        draw_text_with_shadow(draw, (content_left, y_pos), f"📍 {address}", small_font, LIGHT_GRAY)
        y_pos += 60
    else:
        y_pos += 30
        
    draw.line([(MARGIN, y_pos), (CANVAS_WIDTH - MARGIN, y_pos)], fill=WHITE, width=3)
    y_pos += 40
    
    for listing in listings:
        wrapped_title = textwrap.wrap(f"■ {listing['title']}", width=TITLE_WRAP_WIDTH) or [f"■ {listing['title']}"]
        for line in wrapped_title:
            draw_text_with_shadow(draw, (content_left, y_pos), line, regular_font, WHITE)
            y_pos += 40
        if listing['times']:
            draw_text_with_shadow(draw, (content_left + 40, y_pos), listing["times"], regular_font, LIGHT_GRAY)
            y_pos += 55
            
    footer_text_final = "Full schedule online"
    draw_text_with_shadow(draw, (CANVAS_WIDTH // 2, CANVAS_HEIGHT - MARGIN - 20), footer_text_final, footer_font, LIGHT_GRAY, anchor="mm")
    return img

def write_caption_for_multiple_cinemas(date_str: str, all_featured_cinemas: list[dict]) -> None:
    header = f"🎬 London Cinema Showtimes ({date_str})\n"
    lines = [header]
    for item in all_featured_cinemas:
        cinema_name = item['cinema_name']
        address = CINEMA_ADDRESSES.get(cinema_name, "")
        lines.append(f"\n--- 【{cinema_name}】 ---")
        if address:
            lines.append(f"📍 {address}") 
        for listing in item['listings']:
            lines.append(f"• {listing['title']}")
    dynamic_hashtag = "IndieCinema"
    if all_featured_cinemas:
         first_cinema_name = all_featured_cinemas[0]['cinema_name']
         # Clean hashtag creation for English names
         dynamic_hashtag = "".join(ch for ch in first_cinema_name if ch.isalnum())

    footer = f"""
#LondonCinema #{dynamic_hashtag} #IndependentCinema #FilmListings
Link in bio for full schedule
"""
    lines.append(footer)
    with OUTPUT_CAPTION_PATH.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def main() -> None:
    # 1. Basic Setup
    today = today_in_london().date()
    today_str = today.isoformat()
    
    date_display = today.strftime("%d.%m.%Y")
    date_day = today.strftime("%A")
    full_date_str = f"{date_display} {date_day}"
    
    print(f"🕒 Generator Time (London): {today} (String: {today_str})")

    # 🧹 TARGETED CLEANUP
    print("🧹 Cleaning old images...")
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.glob("post_image_*.png"):
            try: os.remove(f)
            except: pass
        for f in OUTPUT_DIR.glob("story_image_*.png"):
            try: os.remove(f)
            except: pass

    try:
        todays_showings = load_showtimes(today_str)
    except Exception as e:
        print(f"❌ Error loading showtimes: {e}")
        todays_showings = []

    if not todays_showings:
        print(f"❌ No showings found for date: {today_str}")
        return
    else:
        print(f"✅ Found {len(todays_showings)} showings for {today_str}")

    # 3. Group Cinemas
    grouped: defaultdict[str, list[dict]] = defaultdict(list)
    for show in todays_showings:
        if show.get("cinema_name"):
            grouped[show.get("cinema_name")].append(show)
            
    # 4. Selection Logic
    featured_names = get_recently_featured(OUTPUT_CAPTION_PATH)
    valid_cinemas = []
    for c_name, shows in grouped.items():
        if len(shows) >= MINIMUM_FILM_THRESHOLD:
            # Prefer non-major chains if possible, or include all valid ones
            # The logic here is flexible. Let's filter out major chains for the "indie" feel unless sparse.
            if not is_major_chain(c_name):
                 valid_cinemas.append(c_name)
    
    # If not enough indie cinemas, allow major chains
    if len(valid_cinemas) < INSTAGRAM_SLIDE_LIMIT:
        for c_name, shows in grouped.items():
            if len(shows) >= MINIMUM_FILM_THRESHOLD and c_name not in valid_cinemas:
                valid_cinemas.append(c_name)

    candidates = [c for c in valid_cinemas if c not in featured_names]
    if not candidates:
        candidates = valid_cinemas
        
    random.shuffle(candidates)
    selected_cinemas = candidates[:INSTAGRAM_SLIDE_LIMIT]
    
    if not selected_cinemas:
        print("No cinemas met criteria.")
        return

    # 5. Generate Images
    print(f"Generating for: {selected_cinemas}")
    
    # Hero Image Generation
    if REPLICATE_AVAILABLE:
        try:
            hero_img = create_hero_image_workflow(selected_cinemas, full_date_str)
            if hero_img:
                hero_img.save(OUTPUT_DIR / "post_image_00.png")
            else:
                print("   ⚠️ Failed to generate hero image. Skipping.")
        except Exception as e:
            print(f"   ⚠️ Hero Generation Error: {e}")
    else:
        print("   ⚠️ Replicate not available. Skipping Hero.")

    # SLIDES
    slide_counter = 0
    all_featured_for_caption = []
    
    for cinema_name in selected_cinemas:
        if slide_counter >= 9:
            break

        shows = grouped[cinema_name]
        listings = format_listings(shows)
        # Simplified spacing since we don't have dual language titles
        segmented = segment_listings(listings, MAX_FEED_VERTICAL_SPACE, spacing={'title_line': 40, 'time_line': 55})
        bg_img = create_blurred_cinema_bg(cinema_name, CANVAS_WIDTH, CANVAS_HEIGHT)
        
        all_featured_for_caption.append({
            'cinema_name': cinema_name, 
            'listings': [l for sublist in segmented for l in sublist]
        })

        for segment in segmented:
            if slide_counter >= 9: break
            slide_counter += 1
            slide_img = draw_cinema_slide(cinema_name, segment, bg_img)
            slide_img.save(OUTPUT_DIR / f"post_image_{slide_counter:02}.png")
            
    write_caption_for_multiple_cinemas(today_str, all_featured_for_caption)
    print("Done. Generated posts.")

if __name__ == "__main__":
    main()
