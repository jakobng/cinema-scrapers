"""
Testing entry point for generate_post.py (London).
Adds cutout locking without modifying the original file.
"""

from PIL import Image

import generate_post as base


CUTOUT_LOCK_PROMPT = (
    "ABSOLUTE CONSTRAINTS:\n"
    "- Preserve the original cinema cutout pixels exactly; treat them as locked.\n"
    "- Do not redraw, reinterpret, or replace the cutout buildings.\n"
    "- Only generate new content in the empty/transparent areas around the cutouts.\n"
    "- Keep cutouts in the exact same position, size, and orientation.\n"
)


def apply_cutout_lock(final_image: Image.Image, layout_rgba: Image.Image) -> Image.Image:
    """
    Ensures original cutouts remain untouched after generation.
    """
    base_img = final_image.convert("RGBA")
    overlay = layout_rgba.convert("RGBA")
    return Image.alpha_composite(base_img, overlay).convert("RGB")


_original_generate_final_hero = base.generate_final_hero


def generate_final_hero(original_layout: Image.Image, prompt: str) -> Image.Image:
    locked_prompt = f"{CUTOUT_LOCK_PROMPT}\n{prompt}".strip()
    result = _original_generate_final_hero(original_layout, locked_prompt)
    return apply_cutout_lock(result, original_layout)


base.generate_final_hero = generate_final_hero


if __name__ == "__main__":
    base.main()
