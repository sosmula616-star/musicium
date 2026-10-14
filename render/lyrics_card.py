"""
render/lyrics_card.py - Frosted Glass Lyrics Display
Renders karaoke-style synchronized lyrics with glowing visionOS highlight on the active line.
"""

import re
import io
import asyncio
import logging
from typing import List, Tuple, Optional, Dict, Any

import discord
from PIL import Image, ImageDraw, ImageFilter

from theme import GlassTheme, get_theme
from render.palette import get_track_palette
from render.glass_card import (
    get_glass_renderer,
    get_font,
    CANVAS_WIDTH,
    CANVAS_HEIGHT,
    get_noise_texture,
    draw_glass_border,
)

logger = logging.getLogger("render.lyrics_card")


def parse_lrc_lyrics(lrc_text: str) -> List[Tuple[float, str]]:
    """Parses LRC format into a list of (timestamp_seconds, text)."""
    lines = []
    pattern = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
    for raw in lrc_text.splitlines():
        m = pattern.match(raw.strip())
        if m:
            mins = int(m.group(1))
            secs = float(m.group(2))
            text = m.group(3).strip()
            if text:
                lines.append((mins * 60.0 + secs, text))
    return sorted(lines, key=lambda x: x[0])


class LyricsCardRenderer:
    def __init__(self):
        self.renderer = get_glass_renderer()

    async def render_lyrics_card(
        self,
        title: str,
        artist: str,
        thumbnail_url: Optional[str],
        lyrics_text: str,
        is_synced: bool,
        elapsed_sec: int,
        theme_name: str = "auto"
    ) -> discord.File:
        """Asynchronously renders a frosted glass lyrics card."""
        theme: GlassTheme = await get_track_palette(thumbnail_url, preset_theme_name=theme_name)
        artwork: Image.Image = await self.renderer.load_artwork(thumbnail_url)

        loop = asyncio.get_running_loop()
        buf = await loop.run_in_executor(
            None,
            self._render_worker,
            artwork,
            theme,
            title,
            artist,
            lyrics_text,
            is_synced,
            elapsed_sec,
        )
        buf.seek(0)
        return discord.File(fp=buf, filename="lyrics.png")

    def _render_worker(
        self,
        artwork: Image.Image,
        theme: GlassTheme,
        title: str,
        artist: str,
        lyrics_text: str,
        is_synced: bool,
        elapsed_sec: int,
    ) -> io.BytesIO:
        canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (8, 10, 16, 255))

        # Blurred backdrop
        art_w, art_h = artwork.size
        scale = max(CANVAS_WIDTH / art_w, CANVAS_HEIGHT / art_h) * 1.1
        scaled = artwork.resize((int(art_w * scale), int(art_h * scale)), Image.Resampling.BILINEAR)
        cx = (scaled.width - CANVAS_WIDTH) // 2
        cy = (scaled.height - CANVAS_HEIGHT) // 2
        bg = scaled.crop((cx, cy, cx + CANVAS_WIDTH, cy + CANVAS_HEIGHT)).filter(ImageFilter.GaussianBlur(radius=40))
        bg.alpha_composite(Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (10, 14, 22, 195)))
        bg.alpha_composite(get_noise_texture(CANVAS_WIDTH, CANVAS_HEIGHT))
        canvas.alpha_composite(bg)

        # Ambient Glow
        glow = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(glow)
        g_draw.ellipse((-40, -40, 380, 380), fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 50))
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=60)))

        # Main Glass Container
        margin_x, margin_y = 42, 34
        card_w = CANVAS_WIDTH - margin_x * 2
        card_h = CANVAS_HEIGHT - margin_y * 2
        card_rect = (margin_x, margin_y, margin_x + card_w, margin_y + card_h)

        glass = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        draw_g = ImageDraw.Draw(glass)
        draw_g.rounded_rectangle(card_rect, radius=28, fill=theme.glass_tint_rgba)
        draw_glass_border(glass, card_rect, radius=28, border_color_top=theme.glass_border_rgba, border_color_bottom=(255, 255, 255, 20))
        canvas.alpha_composite(glass)

        # Typography
        draw = ImageDraw.Draw(canvas)
        f_title = get_font("bold", 22)
        f_artist = get_font("medium", 15)
        f_active = get_font("bold", 24)
        f_inactive = get_font("medium", 16)
        f_badge = get_font("bold", 12)

        # Header Badge
        header_y = margin_y + 24
        draw.text((margin_x + 36, header_y), f"🎤 ТЕКСТ ПЕСНИ: {title[:36]}", font=f_title, fill=(255, 255, 255, 250))
        draw.text((margin_x + 36, header_y + 32), f"Исполнитель: {artist} • Режим: {'Синхронизированный' if is_synced else 'Обычный'}", font=f_artist, fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 220))

        # Parse and display lines
        content_y = header_y + 80
        if is_synced:
            parsed = parse_lrc_lyrics(lyrics_text)
            if not parsed:
                parsed = [(0.0, l) for l in lyrics_text.splitlines() if l.strip()]

            # Find active line index based on elapsed_sec
            active_idx = 0
            for i, (ts, _) in enumerate(parsed):
                if elapsed_sec >= ts:
                    active_idx = i
                else:
                    break

            # Show lines centered around active line
            display_start = max(0, active_idx - 2)
            display_end = min(len(parsed), active_idx + 4)

            curr_y = content_y
            for idx in range(display_start, display_end):
                _, text = parsed[idx]
                clean_text = text[:60] + "..." if len(text) > 64 else text
                if idx == active_idx:
                    # Glowing active line pill
                    draw.rounded_rectangle(
                        (margin_x + 32, curr_y - 6, margin_x + card_w - 32, curr_y + 36),
                        radius=12,
                        fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 40),
                        outline=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 130),
                        width=1
                    )
                    draw.text((margin_x + 48, curr_y), clean_text, font=f_active, fill=(255, 255, 255, 255))
                    curr_y += 46
                else:
                    draw.text((margin_x + 48, curr_y), clean_text, font=f_inactive, fill=(160, 175, 195, 170))
                    curr_y += 34
        else:
            # Plain text mode: show first 7 lines
            lines = [l.strip() for l in lyrics_text.splitlines() if l.strip()]
            curr_y = content_y
            for line in lines[:8]:
                draw.text((margin_x + 48, curr_y), line[:65], font=f_inactive, fill=(210, 220, 235, 220))
                curr_y += 32

        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        return buf


_lyrics_renderer = LyricsCardRenderer()


def get_lyrics_renderer() -> LyricsCardRenderer:
    return _lyrics_renderer
