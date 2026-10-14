"""
theme.py - Liquid Glass / visionOS Theme System
Provides dynamic palette generation, dominant color extraction, and preset glassmorphism themes.
"""

import math
import colorsys
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass


@dataclass
class GlassTheme:
    name: str
    display_name: str
    emoji: str
    accent_hex: str
    accent_rgb: Tuple[int, int, int]
    secondary_hex: str
    secondary_rgb: Tuple[int, int, int]
    glass_tint_rgba: Tuple[int, int, int, int]
    glass_border_rgba: Tuple[int, int, int, int]
    glow_rgba: Tuple[int, int, int, int]
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "emoji": self.emoji,
            "accent_hex": self.accent_hex,
            "secondary_hex": self.secondary_hex,
            "description": self.description,
        }


# Preset color palettes tuned for visionOS / Glassmorphism
THEMES: Dict[str, GlassTheme] = {
    "auto": GlassTheme(
        name="auto",
        display_name="Adaptive Artwork",
        emoji="🪄",
        accent_hex="#00f2fe",
        accent_rgb=(0, 242, 254),
        secondary_hex="#4facfe",
        secondary_rgb=(79, 172, 254),
        glass_tint_rgba=(15, 23, 42, 170),
        glass_border_rgba=(255, 255, 255, 55),
        glow_rgba=(0, 242, 254, 90),
        description="Динамическое стекло подстраивается под цвета обложки трека",
    ),
    "aurora": GlassTheme(
        name="aurora",
        display_name="Aurora Borealis",
        emoji="🌌",
        accent_hex="#10b981",
        accent_rgb=(16, 185, 129),
        secondary_hex="#8b5cf6",
        secondary_rgb=(139, 92, 246),
        glass_tint_rgba=(10, 25, 22, 180),
        glass_border_rgba=(52, 211, 153, 70),
        glow_rgba=(16, 185, 129, 110),
        description="Полярное сияние: изумрудно-бирюзовое стекло с фиолетовым отливом",
    ),
    "sunset": GlassTheme(
        name="sunset",
        display_name="Sunset Glow",
        emoji="🌅",
        accent_hex="#f43f5e",
        accent_rgb=(244, 63, 94),
        secondary_hex="#fb923c",
        secondary_rgb=(251, 146, 60),
        glass_tint_rgba=(30, 15, 25, 180),
        glass_border_rgba=(244, 63, 94, 75),
        glow_rgba=(244, 63, 94, 110),
        description="Закатный горизонт: тёплые неоновые блики коралла и фуксии",
    ),
    "midnight": GlassTheme(
        name="midnight",
        display_name="Midnight visionOS",
        emoji="🌑",
        accent_hex="#3b82f6",
        accent_rgb=(59, 130, 246),
        secondary_hex="#6366f1",
        secondary_rgb=(99, 102, 241),
        glass_tint_rgba=(8, 12, 24, 200),
        glass_border_rgba=(96, 165, 250, 60),
        glow_rgba=(59, 130, 246, 100),
        description="Глубокий обсидиановый visionOS: космический синий и электрический индиго",
    ),
    "frost": GlassTheme(
        name="frost",
        display_name="Crystal Frost",
        emoji="❄️",
        accent_hex="#38bdf8",
        accent_rgb=(56, 189, 248),
        secondary_hex="#e2e8f0",
        secondary_rgb=(226, 232, 240),
        glass_tint_rgba=(14, 24, 38, 175),
        glass_border_rgba=(226, 232, 240, 85),
        glow_rgba=(56, 189, 248, 100),
        description="Ледяной кристалл: чистое матовое стекло со сверкающим серебристым кантом",
    ),
}

# In-memory per-guild or global active theme preference
_guild_themes: Dict[int, str] = {}


def get_guild_theme_name(guild_id: Optional[int]) -> str:
    if not guild_id:
        return "auto"
    return _guild_themes.get(guild_id, "auto")


def set_guild_theme(guild_id: int, theme_name: str) -> bool:
    clean_name = theme_name.strip().lower()
    if clean_name in THEMES:
        _guild_themes[guild_id] = clean_name
        return True
    return False


def get_theme(theme_name: str) -> GlassTheme:
    clean = theme_name.strip().lower()
    return THEMES.get(clean, THEMES["auto"])


def derive_dynamic_theme(dominant_rgb: Tuple[int, int, int]) -> GlassTheme:
    """
    Creates a dynamic GlassTheme tailored specifically to the dominant color of the track.
    Uses HSL transformations to guarantee vibrant contrast, visionOS glass readability and luminous rim lighting.
    """
    r, g, b = dominant_rgb
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)

    # Boost saturation and normalize luminance for modern UI glow
    s = min(1.0, max(0.65, s * 1.3))
    l_accent = 0.58
    l_sec = 0.68

    # Primary accent color
    ar, ag, ab = colorsys.hls_to_rgb(h, l_accent, s)
    accent_rgb = (int(ar * 255), int(ag * 255), int(ab * 255))
    accent_hex = f"#{accent_rgb[0]:02x}{accent_rgb[1]:02x}{accent_rgb[2]:02x}"

    # Complementary secondary accent (shifted +35 degrees on color wheel)
    h_sec = (h + 0.10) % 1.0
    sr, sg, sb = colorsys.hls_to_rgb(h_sec, l_sec, s)
    sec_rgb = (int(sr * 255), int(sg * 255), int(sb * 255))
    sec_hex = f"#{sec_rgb[0]:02x}{sec_rgb[1]:02x}{sec_rgb[2]:02x}"

    # Frosted glass background tint with deep dark base
    tint_r = int(r * 0.12 + 10)
    tint_g = int(g * 0.12 + 12)
    tint_b = int(b * 0.12 + 20)
    glass_tint = (tint_r, tint_g, tint_b, 175)

    # Rim border highlight with subtle tint of the accent
    glass_border = (min(255, accent_rgb[0] + 50), min(255, accent_rgb[1] + 50), min(255, accent_rgb[2] + 50), 75)
    glow_rgba = (accent_rgb[0], accent_rgb[1], accent_rgb[2], 115)

    return GlassTheme(
        name="adaptive",
        display_name="Adaptive Glass",
        emoji="✨",
        accent_hex=accent_hex,
        accent_rgb=accent_rgb,
        secondary_hex=sec_hex,
        secondary_rgb=sec_rgb,
        glass_tint_rgba=glass_tint,
        glass_border_rgba=glass_border,
        glow_rgba=glow_rgba,
        description="Сгенерировано на основе спектра обложки",
    )
