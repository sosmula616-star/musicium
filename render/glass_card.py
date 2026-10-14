"""
render/glass_card.py - High-Performance Liquid Glass / visionOS Card Compositor
Draws frosted glass cards with specular rim lighting, rotating vinyl, procedural equalizer,
and glowing progress capsules using pure Pillow for maximum speed, portability, and visual fidelity.
"""

import os
import io
import math
import random
import logging
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import urlparse

import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops, ImageEnhance

from theme import GlassTheme, THEMES, get_theme

logger = logging.getLogger("render.glass_card")

# Static asset paths
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(WORKSPACE_ROOT, "static")
DEFAULT_ICON = os.path.join(STATIC_DIR, "activity_icon.jpg")
DEFAULT_BANNER = os.path.join(STATIC_DIR, "activity_banner.jpg")

# Dimensions
CANVAS_WIDTH = 960
CANVAS_HEIGHT = 540

# Font cache
_FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


def get_font(font_type: str = "bold", size: int = 24) -> ImageFont.ImageFont:
    """
    Loads modern clean typography with fallbacks (Segoe UI / Arial / Roboto / DejaVu Sans).
    """
    key = (font_type, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    # Windows and Linux standard font candidates
    candidates = []
    if font_type == "bold":
        candidates = [
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "segoeuib.ttf",
            "arialbd.ttf",
        ]
    elif font_type == "medium":
        candidates = [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "segoeui.ttf",
            "arial.ttf",
        ]
    else:  # light / regular
        candidates = [
            "C:/Windows/Fonts/segoeuisl.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "segoeui.ttf",
        ]

    for path in candidates:
        if os.path.exists(path):
            try:
                f = ImageFont.truetype(path, size)
                _FONT_CACHE[key] = f
                return f
            except Exception:
                pass

    try:
        f = ImageFont.load_default()
        _FONT_CACHE[key] = f
        return f
    except Exception:
        return ImageFont.load_default()


def create_noise_texture(width: int, height: int, opacity: int = 14) -> Image.Image:
    """Creates a subtle procedural grain texture to give physical depth to frosted glass."""
    noise = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    # Sample every 2 pixels for fast generation
    draw = ImageDraw.Draw(noise)
    random.seed(42)  # Deterministic grain
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            val = random.randint(210, 255)
            alpha = random.randint(5, opacity)
            draw.point((x, y), fill=(val, val, val, alpha))
    return noise


# Cached noise texture
_CACHED_NOISE: Optional[Image.Image] = None


def get_noise_texture(width: int, height: int) -> Image.Image:
    global _CACHED_NOISE
    if _CACHED_NOISE is None or _CACHED_NOISE.size != (width, height):
        _CACHED_NOISE = create_noise_texture(width, height)
    return _CACHED_NOISE


def rounded_rectangle_mask(size: Tuple[int, int], radius: int) -> Image.Image:
    """Generates a high-precision anti-aliased mask for rounded corners."""
    w, h = size
    mask = Image.new("L", (w * 2, h * 2), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w * 2, h * 2), radius=radius * 2, fill=255)
    return mask.resize((w, h), Image.Resampling.LANCZOS)


def circular_mask(size: int) -> Image.Image:
    """Generates a smooth anti-aliased circular mask."""
    mask = Image.new("L", (size * 2, size * 2), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size * 2, size * 2), fill=255)
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def draw_linear_gradient(
    image: Image.Image,
    rect: Tuple[int, int, int, int],
    color1: Tuple[int, int, int, int],
    color2: Tuple[int, int, int, int],
    direction: str = "horizontal"
):
    """Draws a smooth linear gradient into a rectangular area."""
    x0, y0, x1, y1 = rect
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    draw = ImageDraw.Draw(image)

    if direction == "horizontal":
        for i in range(w):
            t = i / float(w)
            r = int(color1[0] * (1 - t) + color2[0] * t)
            g = int(color1[1] * (1 - t) + color2[1] * t)
            b = int(color1[2] * (1 - t) + color2[2] * t)
            a = int(color1[3] * (1 - t) + color2[3] * t)
            draw.line([(x0 + i, y0), (x0 + i, y1)], fill=(r, g, b, a))
    else:  # vertical
        for i in range(h):
            t = i / float(h)
            r = int(color1[0] * (1 - t) + color2[0] * t)
            g = int(color1[1] * (1 - t) + color2[1] * t)
            b = int(color1[2] * (1 - t) + color2[2] * t)
            a = int(color1[3] * (1 - t) + color2[3] * t)
            draw.line([(x0, y0 + i), (x1, y0 + i)], fill=(r, g, b, a))


def draw_glass_border(
    target: Image.Image,
    rect: Tuple[int, int, int, int],
    radius: int,
    border_color_top: Tuple[int, int, int, int],
    border_color_bottom: Tuple[int, int, int, int],
    thickness: int = 2
):
    """
    Renders visionOS specular rim light:
    Top & left edges are brighter to simulate ceiling light reflections,
    bottom & right edges have a subtle shadow/dim edge.
    """
    w = target.width
    h = target.height

    border_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(border_img)

    # Draw gradient border on a temporary layer
    b_draw.rounded_rectangle(
        rect,
        radius=radius,
        outline=border_color_top,
        width=thickness
    )

    # Apply vertical gradient fade to darken bottom border
    gradient_mask = Image.new("L", (w, h), 255)
    g_draw = ImageDraw.Draw(gradient_mask)
    x0, y0, x1, y1 = rect
    for y in range(y0, y1):
        ratio = (y - y0) / max(1, (y1 - y0))
        # Fade from 255 at top to 70 at bottom
        alpha = int(255 * (1 - ratio * 0.72))
        g_draw.line([(x0, y), (x1, y)], fill=alpha)

    # Composite border
    border_img.putalpha(ImageChops.multiply(border_img.getchannel("A"), gradient_mask))
    target.alpha_composite(border_img)


def create_vinyl_record(
    artwork: Image.Image,
    disc_size: int = 260,
    rotation_deg: float = 0.0
) -> Image.Image:
    """
    Generates a realistic vinyl record with glossy grooves, circular album artwork sticker,
    center spindle hole, and specular light reflection reflections.
    """
    # High-res canvas for anti-aliasing
    scale = 2
    s_size = disc_size * scale
    vinyl = Image.new("RGBA", (s_size, s_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(vinyl)
    center = s_size // 2

    # 1. Outer black vinyl disc with drop shadow
    draw.ellipse((0, 0, s_size, s_size), fill=(18, 19, 23, 255))

    # 2. Concentric grooved rings
    for r in range(center - 10, int(center * 0.44), -8):
        c_val = random.randint(28, 42)
        draw.ellipse((center - r, center - r, center + r, center + r), outline=(c_val, c_val, c_val + 2, 180), width=2)

    # 3. Specular rim highlight arcs (simulating physical lighting on the record surface)
    draw.arc((10, 10, s_size - 10, s_size - 10), start=30, end=75, fill=(255, 255, 255, 45), width=6)
    draw.arc((10, 10, s_size - 10, s_size - 10), start=210, end=255, fill=(255, 255, 255, 45), width=6)

    # 4. Circular artwork label in center
    label_size = int(s_size * 0.42)
    label_x = center - label_size // 2
    label_y = center - label_size // 2

    art_resized = artwork.convert("RGBA").resize((label_size, label_size), Image.Resampling.LANCZOS)
    c_mask = circular_mask(label_size)
    label_crop = Image.new("RGBA", (label_size, label_size), (0, 0, 0, 0))
    label_crop.paste(art_resized, (0, 0), c_mask)

    vinyl.alpha_composite(label_crop, (label_x, label_y))

    # 5. Center spindle hole & silver ring
    hole_radius = int(s_size * 0.04)
    draw.ellipse(
        (center - hole_radius - 4, center - hole_radius - 4, center + hole_radius + 4, center + hole_radius + 4),
        fill=(190, 195, 205, 220),
        outline=(255, 255, 255, 240),
        width=2
    )
    draw.ellipse(
        (center - hole_radius, center - hole_radius, center + hole_radius, center + hole_radius),
        fill=(10, 12, 16, 255)
    )

    # 6. Apply rotation for animation
    if rotation_deg != 0.0:
        vinyl = vinyl.rotate(rotation_deg, resample=Image.Resampling.BILINEAR, center=(center, center))

    # Downscale smoothly
    return vinyl.resize((disc_size, disc_size), Image.Resampling.LANCZOS)


class GlassCardRenderer:
    """Composites stunning visionOS / Liquid Glass Discord cards."""

    def __init__(self):
        self._fallback_art: Optional[Image.Image] = None

    def _get_fallback_artwork(self) -> Image.Image:
        if self._fallback_art is not None:
            return self._fallback_art.copy()

        for p in [DEFAULT_BANNER, DEFAULT_ICON]:
            if os.path.exists(p):
                try:
                    self._fallback_art = Image.open(p).convert("RGBA")
                    return self._fallback_art.copy()
                except Exception:
                    pass

        # Procedural fallback gradient
        bg = Image.new("RGBA", (500, 500), (20, 24, 40, 255))
        self._fallback_art = bg
        return bg.copy()

    async def load_artwork(self, thumbnail_url: Optional[str], session: Optional[aiohttp.ClientSession] = None) -> Image.Image:
        """Loads artwork from URL or falls back to local static bot assets."""
        if thumbnail_url and thumbnail_url.startswith("http"):
            try:
                close = False
                if session is None:
                    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4.0))
                    close = True
                try:
                    async with session.get(thumbnail_url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            return Image.open(io.BytesIO(data)).convert("RGBA")
                finally:
                    if close:
                        await session.close()
            except Exception as e:
                logger.debug(f"Failed to fetch artwork from {thumbnail_url}: {e}")

        # Local fallback
        return self._get_fallback_artwork()

    def render_now_playing_frame(
        self,
        artwork: Image.Image,
        theme: GlassTheme,
        title: str,
        artist: str,
        elapsed_sec: int,
        duration_sec: int,
        is_playing: bool = True,
        loop_mode: str = "off",
        requester: str = "Пользователь",
        frame_idx: int = 0,
        total_frames: int = 24
    ) -> Image.Image:
        """
        Renders a single high-definition Liquid Glass / visionOS Now Playing card frame.
        """
        # Canvas
        canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (8, 10, 16, 255))

        # ----------------- 1. Blurred Backdrop with Depth Tint -----------------
        # Crop & scale artwork to fill canvas with zoom
        art_w, art_h = artwork.size
        scale = max(CANVAS_WIDTH / art_w, CANVAS_HEIGHT / art_h) * 1.15
        new_w, new_h = int(art_w * scale), int(art_h * scale)
        scaled_art = artwork.resize((new_w, new_h), Image.Resampling.BILINEAR)

        # Center crop
        cx = (new_w - CANVAS_WIDTH) // 2
        cy = (new_h - CANVAS_HEIGHT) // 2
        cropped_art = scaled_art.crop((cx, cy, cx + CANVAS_WIDTH, cy + CANVAS_HEIGHT))

        # Heavy Gaussian blur for frosted spatial backdrop
        blurred_bg = cropped_art.filter(ImageFilter.GaussianBlur(radius=38))

        # Darken and tint backdrop with theme colors
        dark_overlay = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (10, 14, 22, 185))
        blurred_bg.alpha_composite(dark_overlay)

        # Subtle noise texture for physical glass texture
        noise = get_noise_texture(CANVAS_WIDTH, CANVAS_HEIGHT)
        blurred_bg.alpha_composite(noise)
        canvas.alpha_composite(blurred_bg)

        # ----------------- 2. Ambient Soft Glows -----------------
        # Top-left and bottom-right colored atmosphere orbs
        glow_layer = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)

        # Left accent glow orb
        glow_color = (theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 55)
        glow_draw.ellipse((-80, -80, 420, 420), fill=glow_color)

        # Right secondary glow orb
        sec_color = (theme.secondary_rgb[0], theme.secondary_rgb[1], theme.secondary_rgb[2], 45)
        glow_draw.ellipse((CANVAS_WIDTH - 360, CANVAS_HEIGHT - 360, CANVAS_WIDTH + 100, CANVAS_HEIGHT + 100), fill=sec_color)

        glow_blurred = glow_layer.filter(ImageFilter.GaussianBlur(radius=65))
        canvas.alpha_composite(glow_blurred)

        # ----------------- 3. Main Floating Liquid Glass Container -----------------
        card_margin_x = 42
        card_margin_y = 36
        card_w = CANVAS_WIDTH - (card_margin_x * 2)
        card_h = CANVAS_HEIGHT - (card_margin_y * 2)
        card_rect = (card_margin_x, card_margin_y, card_margin_x + card_w, card_margin_y + card_h)
        corner_radius = 32

        # Card Drop Shadow
        shadow = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shadow)
        s_draw.rounded_rectangle(
            (card_margin_x + 4, card_margin_y + 12, card_margin_x + card_w - 4, card_margin_y + card_h + 16),
            radius=corner_radius,
            fill=(0, 0, 0, 160)
        )
        shadow_blurred = shadow.filter(ImageFilter.GaussianBlur(radius=22))
        canvas.alpha_composite(shadow_blurred)

        # Glass Panel Body Fill (Frosted tinted glass)
        glass_card = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(glass_card)
        g_draw.rounded_rectangle(
            card_rect,
            radius=corner_radius,
            fill=theme.glass_tint_rgba
        )

        # Top specular diagonal light sweep
        sweep_layer = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        sw_draw = ImageDraw.Draw(sweep_layer)
        sw_draw.polygon(
            [
                (card_margin_x, card_margin_y),
                (card_margin_x + int(card_w * 0.65), card_margin_y),
                (card_margin_x, card_margin_y + int(card_h * 0.55)),
            ],
            fill=(255, 255, 255, 18)
        )
        # Mask sweep to card shape
        c_mask = rounded_rectangle_mask((CANVAS_WIDTH, CANVAS_HEIGHT), corner_radius)
        # Apply to glass card
        glass_card.alpha_composite(sweep_layer)

        # Rim light specular border (visionOS 1.5px highlight)
        draw_glass_border(
            glass_card,
            card_rect,
            radius=corner_radius,
            border_color_top=theme.glass_border_rgba,
            border_color_bottom=(255, 255, 255, 20),
            thickness=2
        )
        canvas.alpha_composite(glass_card)

        # ----------------- 4. Rotating Vinyl Record / Artwork -----------------
        vinyl_size = 250
        vinyl_x = card_margin_x + 42
        vinyl_y = card_margin_y + (card_h - vinyl_size) // 2

        # Rotation angle based on animation frame
        rot_deg = (frame_idx / total_frames) * 360.0 if is_playing else 0.0
        vinyl_img = create_vinyl_record(artwork, disc_size=vinyl_size, rotation_deg=rot_deg)

        # Vinyl floating shadow
        v_shadow = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        vs_draw = ImageDraw.Draw(v_shadow)
        vs_draw.ellipse(
            (vinyl_x + 6, vinyl_y + 12, vinyl_x + vinyl_size + 6, vinyl_y + vinyl_size + 12),
            fill=(0, 0, 0, 140)
        )
        v_shadow = v_shadow.filter(ImageFilter.GaussianBlur(radius=14))
        canvas.alpha_composite(v_shadow)
        canvas.alpha_composite(vinyl_img, (vinyl_x, vinyl_y))

        # ----------------- 5. Metadata Typography & Badges -----------------
        content_x = vinyl_x + vinyl_size + 42
        content_max_w = (card_margin_x + card_w - 38) - content_x
        draw = ImageDraw.Draw(canvas)

        # Header Badge (visionOS pill: ✦ MUSICIUM • THEME)
        theme_emoji = theme.emoji
        brand_text = f"✦ MUSICIUM  •  {theme.display_name.upper()}"
        font_brand = get_font("bold", 13)
        font_main_bold = get_font("bold", 28)
        font_artist = get_font("medium", 18)
        font_time = get_font("medium", 14)
        font_badge = get_font("bold", 12)

        # Pill badge background
        badge_y = card_margin_y + 36
        draw.rounded_rectangle(
            (content_x, badge_y, content_x + 230, badge_y + 24),
            radius=12,
            fill=(255, 255, 255, 22),
            outline=(255, 255, 255, 45),
            width=1
        )
        # Glowing green/cyan dot
        status_dot_color = (16, 185, 129, 255) if is_playing else (245, 158, 11, 255)
        draw.ellipse((content_x + 10, badge_y + 7, content_x + 20, badge_y + 17), fill=status_dot_color)
        draw.text((content_x + 28, badge_y + 4), brand_text, font=font_brand, fill=(225, 235, 250, 230))

        # Track Title (clean truncation if too long)
        title_y = badge_y + 38
        clean_title = title if len(title) <= 32 else (title[:30] + "...")
        draw.text((content_x, title_y), clean_title, font=font_main_bold, fill=(255, 255, 255, 250))

        # Artist name
        artist_y = title_y + 38
        clean_artist = artist if len(artist) <= 38 else (artist[:36] + "...")
        draw.text((content_x, artist_y), clean_artist, font=font_artist, fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 240))

        # ----------------- 6. Animated Procedural Sound Equalizer -----------------
        eq_x = content_x
        eq_y = artist_y + 34
        eq_bars = 16
        eq_bar_width = 6
        eq_bar_gap = 4
        eq_max_height = 28

        # Draw dancing spectrum bars
        for b_idx in range(eq_bars):
            # Harmonic frequency wave calculation
            freq = 0.45 + (b_idx * 0.12)
            phase = b_idx * 0.55
            # Smooth cyclic motion over total_frames
            t_angle = (frame_idx / total_frames) * math.pi * 2
            if is_playing:
                raw_wave = math.sin(t_angle * 2.0 + phase) * 0.5 + math.cos(t_angle * 3.0 + phase * 1.5) * 0.4
                norm_height = max(0.18, min(1.0, 0.55 + raw_wave * 0.45))
            else:
                norm_height = 0.20  # Flatline when paused

            bar_h = int(eq_max_height * norm_height)
            bx0 = eq_x + b_idx * (eq_bar_width + eq_bar_gap)
            by0 = eq_y + (eq_max_height - bar_h)
            bx1 = bx0 + eq_bar_width
            by1 = eq_y + eq_max_height

            # Gradient bar color from accent to secondary
            b_ratio = b_idx / float(eq_bars)
            br = int(theme.accent_rgb[0] * (1 - b_ratio) + theme.secondary_rgb[0] * b_ratio)
            bg_val = int(theme.accent_rgb[1] * (1 - b_ratio) + theme.secondary_rgb[1] * b_ratio)
            bb = int(theme.accent_rgb[2] * (1 - b_ratio) + theme.secondary_rgb[2] * b_ratio)

            draw.rounded_rectangle((bx0, by0, bx1, by1), radius=3, fill=(br, bg_val, bb, 235))

        # Status text next to equalizer
        state_str = "ИГРАЕТ СЕЙЧАС" if is_playing else "ПАУЗА"
        draw.text((eq_x + eq_bars * (eq_bar_width + eq_bar_gap) + 14, eq_y + 6), state_str, font=font_badge, fill=(180, 195, 215, 200))

        # Loop badge if active
        if loop_mode in ("track", "queue"):
            loop_label = "🔂 ТРЕК" if loop_mode == "track" else "🔁 ОЧЕРЕДЬ"
            loop_pill_x = eq_x + eq_bars * (eq_bar_width + eq_bar_gap) + 115
            draw.rounded_rectangle(
                (loop_pill_x, eq_y + 4, loop_pill_x + 85, eq_y + 22),
                radius=9,
                fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 45),
                outline=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 120),
                width=1
            )
            draw.text((loop_pill_x + 8, eq_y + 5), loop_label, font=font_badge, fill=(255, 255, 255, 230))

        # ----------------- 7. Glowing Progress Bar Capsule -----------------
        progress_y = eq_y + 48
        progress_w = content_max_w
        progress_h = 8
        progress_radius = 4

        # Calculate progress ratio
        if duration_sec and duration_sec > 0:
            prog_ratio = max(0.0, min(1.0, elapsed_sec / float(duration_sec)))
        else:
            prog_ratio = 0.42

        # Progress Background Pill
        draw.rounded_rectangle(
            (content_x, progress_y, content_x + progress_w, progress_y + progress_h),
            radius=progress_radius,
            fill=(255, 255, 255, 30)
        )

        # Progress Fill Bar
        fill_w = max(int(progress_w * prog_ratio), 8)
        draw.rounded_rectangle(
            (content_x, progress_y, content_x + fill_w, progress_y + progress_h),
            radius=progress_radius,
            fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 255)
        )

        # Glowing Playhead Dot
        dot_cx = content_x + fill_w
        dot_cy = progress_y + (progress_h // 2)
        dot_radius = 6

        # Halo Glow around playhead
        glow_dot_layer = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        gd_draw = ImageDraw.Draw(glow_dot_layer)
        gd_draw.ellipse(
            (dot_cx - 14, dot_cy - 14, dot_cx + 14, dot_cy + 14),
            fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 140)
        )
        glow_dot_blurred = glow_dot_layer.filter(ImageFilter.GaussianBlur(radius=6))
        canvas.alpha_composite(glow_dot_blurred)

        # Solid playhead circle
        draw = ImageDraw.Draw(canvas)
        draw.ellipse((dot_cx - dot_radius, dot_cy - dot_radius, dot_cx + dot_radius, dot_cy + dot_radius), fill=(255, 255, 255, 255))

        # Time labels below progress
        time_y = progress_y + 14
        m_el, s_el = divmod(elapsed_sec, 60)
        m_tot, s_tot = divmod(duration_sec or 0, 60)
        time_elapsed_str = f"{m_el:02d}:{s_el:02d}"
        time_total_str = f"{m_tot:02d}:{s_tot:02d}"

        draw.text((content_x, time_y), time_elapsed_str, font=font_time, fill=(220, 230, 245, 220))
        # Right-aligned duration
        draw.text((content_x + progress_w - 42, time_y), time_total_str, font=font_time, fill=(160, 175, 195, 200))

        # ----------------- 8. Bottom Requester Pill -----------------
        footer_y = time_y + 32
        req_clean = requester if len(requester) <= 25 else (requester[:23] + "..")
        req_text = f"👤 Заказал: {req_clean}"
        draw.rounded_rectangle(
            (content_x, footer_y, content_x + 190, footer_y + 24),
            radius=12,
            fill=(255, 255, 255, 18),
            outline=(255, 255, 255, 35),
            width=1
        )
        draw.text((content_x + 12, footer_y + 4), req_text, font=font_badge, fill=(200, 215, 235, 210))

        return canvas


# Global singleton renderer
_renderer = GlassCardRenderer()


def get_glass_renderer() -> GlassCardRenderer:
    return _renderer
