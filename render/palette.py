"""
render/palette.py - Dominant Color & visionOS Glass Palette Extractor
Fast, lightweight palette calculation using Pillow with fallback to preset themes.
"""

import os
import io
import math
import logging
import colorsys
from typing import Tuple, Optional, Dict, Any
from urllib.parse import urlparse

import aiohttp
from PIL import Image

from theme import GlassTheme, derive_dynamic_theme, THEMES

logger = logging.getLogger("render.palette")

# In-memory palette cache: key -> GlassTheme
_PALETTE_CACHE: Dict[str, GlassTheme] = {}


def _is_valid_url(url: Optional[str]) -> bool:
    if not url:
        return False
    try:
        res = urlparse(url)
        return bool(res.scheme and res.netloc)
    except Exception:
        return False


def extract_dominant_color_from_image(image: Image.Image) -> Tuple[int, int, int]:
    """
    Extracts the most vibrant/dominant color from a PIL Image.
    Downscales to 48x48 for sub-millisecond execution and filters out near-black/near-white pixels.
    """
    # Convert to RGB and resize small
    img = image.convert("RGB").resize((48, 48), Image.Resampling.BILINEAR)

    # Quantize to 16 dominant colors
    quantized = img.quantize(colors=16, method=Image.Quantize.FASTOCTREE)
    palette = quantized.getpalette()
    if not palette:
        return (0, 242, 254)  # Fallback cyan

    color_counts = quantized.getcolors(maxcolors=256)
    if not color_counts:
        return (0, 242, 254)

    best_color = None
    best_score = -1.0

    for count, idx in color_counts:
        r = palette[idx * 3]
        g = palette[idx * 3 + 1]
        b = palette[idx * 3 + 2]

        # Convert to HLS to measure vibrancy and avoid extreme dark/bright backgrounds
        h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)

        # Ignore pure black, dark gray or pure white (common letterboxing)
        if l < 0.12 or l > 0.92:
            continue
        if s < 0.15:
            # Low saturation penalty
            saturation_weight = 0.3
        else:
            saturation_weight = s * 1.5

        # Score balances prevalence in artwork with color saturation
        score = count * saturation_weight

        if score > best_score:
            best_score = score
            best_color = (r, g, b)

    if not best_color:
        # Fallback to most frequent non-extreme color
        best_color = (palette[0], palette[1], palette[2])

    return best_color


async def get_track_palette(
    thumbnail_url: Optional[str],
    preset_theme_name: str = "auto",
    session: Optional[aiohttp.ClientSession] = None
) -> GlassTheme:
    """
    Asynchronously extracts or derives a GlassTheme for the specified track thumbnail.
    If preset_theme_name != 'auto', returns the corresponding static theme.
    Otherwise, extracts dominant color and derives dynamic visionOS theme.
    """
    preset_clean = (preset_theme_name or "auto").strip().lower()
    if preset_clean in THEMES and preset_clean != "auto":
        return THEMES[preset_clean]

    cache_key = f"{thumbnail_url or 'default'}_{preset_clean}"
    if cache_key in _PALETTE_CACHE:
        return _PALETTE_CACHE[cache_key]

    # If no thumbnail or invalid, use default auto theme
    if not thumbnail_url or not _is_valid_url(thumbnail_url):
        # Try local static fallback
        local_icon = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "activity_icon.jpg")
        if os.path.exists(local_icon):
            try:
                with Image.open(local_icon) as img:
                    dom_rgb = extract_dominant_color_from_image(img)
                    theme = derive_dynamic_theme(dom_rgb)
                    _PALETTE_CACHE[cache_key] = theme
                    return theme
            except Exception:
                pass
        return THEMES["auto"]

    # Fetch image bytes asynchronously
    try:
        close_session = False
        if session is None:
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4.0))
            close_session = True

        try:
            async with session.get(thumbnail_url) as resp:
                if resp.status == 200:
                    raw_data = await resp.read()
                    with Image.open(io.BytesIO(raw_data)) as img:
                        dom_rgb = extract_dominant_color_from_image(img)
                        theme = derive_dynamic_theme(dom_rgb)
                        _PALETTE_CACHE[cache_key] = theme
                        return theme
        finally:
            if close_session:
                await session.close()
    except Exception as e:
        logger.debug(f"Palette extraction error for {thumbnail_url}: {e}")

    # Fallback
    theme = THEMES["auto"]
    _PALETTE_CACHE[cache_key] = theme
    return theme
