"""
render/queue_card.py - Frosted Glass Queue Screen Compositor
Renders an elegant visionOS glass card displaying upcoming tracks with rankings, durations, and requester info.
"""

import io
import asyncio
import logging
from typing import List, Optional, Tuple

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

logger = logging.getLogger("render.queue_card")


class QueueCardRenderer:
    def __init__(self):
        self.renderer = get_glass_renderer()

    async def render_queue_card(
        self,
        current_track: Optional[Any],
        queue_tracks: List[Any],
        theme_name: str = "auto",
        page: int = 1,
        per_page: int = 5,
    ) -> discord.File:
        """Asynchronously renders a frosted glass queue card."""
        thumb = current_track.thumbnail if current_track else None
        theme: GlassTheme = await get_track_palette(thumb, preset_theme_name=theme_name)
        artwork: Image.Image = await self.renderer.load_artwork(thumb)

        loop = asyncio.get_running_loop()
        buf = await loop.run_in_executor(
            None,
            self._render_worker,
            artwork,
            theme,
            current_track,
            queue_tracks,
            page,
            per_page,
        )
        buf.seek(0)
        return discord.File(fp=buf, filename="queue.png")

    def _render_worker(
        self,
        artwork: Image.Image,
        theme: GlassTheme,
        current_track: Optional[Any],
        queue_tracks: List[Any],
        page: int,
        per_page: int,
    ) -> io.BytesIO:
        canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (8, 10, 16, 255))

        # Blurred backdrop with noise
        art_w, art_h = artwork.size
        scale = max(CANVAS_WIDTH / art_w, CANVAS_HEIGHT / art_h) * 1.1
        scaled = artwork.resize((int(art_w * scale), int(art_h * scale)), Image.Resampling.BILINEAR)
        cx = (scaled.width - CANVAS_WIDTH) // 2
        cy = (scaled.height - CANVAS_HEIGHT) // 2
        bg = scaled.crop((cx, cy, cx + CANVAS_WIDTH, cy + CANVAS_HEIGHT)).filter(ImageFilter.GaussianBlur(radius=38))
        bg.alpha_composite(Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (10, 14, 22, 190)))
        bg.alpha_composite(get_noise_texture(CANVAS_WIDTH, CANVAS_HEIGHT))
        canvas.alpha_composite(bg)

        # Ambient Glow
        glow = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(glow)
        g_draw.ellipse((-50, -50, 400, 400), fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 50))
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
        f_header = get_font("bold", 14)
        f_row = get_font("medium", 15)
        f_sub = get_font("regular", 13)

        # Header Badge
        header_y = margin_y + 24
        total_q = len(queue_tracks)
        draw.text((margin_x + 36, header_y), f"📜 ОЧЕРЕДЬ ВОСПРОИЗВЕДЕНИЯ ({total_q} в очереди)", font=f_title, fill=(255, 255, 255, 245))

        # Now playing item
        curr_y = header_y + 40
        if current_track:
            draw.rounded_rectangle(
                (margin_x + 32, curr_y, margin_x + card_w - 32, curr_y + 54),
                radius=14,
                fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 35),
                outline=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 120),
                width=1
            )
            draw.text((margin_x + 48, curr_y + 10), "▶ СЕЙЧАС ИГРАЕТ:", font=get_font("bold", 12), fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 240))
            t_title = current_track.title[:45] + "..." if len(current_track.title) > 48 else current_track.title
            draw.text((margin_x + 48, curr_y + 26), f"{t_title} — {current_track.artist}", font=f_row, fill=(255, 255, 255, 250))
            dur_str = getattr(current_track, "duration_str", "00:00")
            draw.text((margin_x + card_w - 90, curr_y + 18), dur_str, font=f_row, fill=(210, 225, 245, 220))
            curr_y += 66

        # Upcoming Tracks
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_q)
        page_tracks = queue_tracks[start_idx:end_idx]

        row_y = curr_y + 8
        if not page_tracks:
            draw.text((margin_x + 48, row_y + 30), "Очередь пуста. Добавьте треки через /play!", font=f_row, fill=(160, 175, 195, 200))
        else:
            for idx, trk in enumerate(page_tracks, start=start_idx + 1):
                # Row glass pill
                draw.rounded_rectangle(
                    (margin_x + 32, row_y, margin_x + card_w - 32, row_y + 46),
                    radius=10,
                    fill=(255, 255, 255, 14),
                    outline=(255, 255, 255, 25),
                    width=1
                )
                # Number index
                draw.text((margin_x + 46, row_y + 13), f"#{idx}", font=get_font("bold", 14), fill=(theme.accent_rgb[0], theme.accent_rgb[1], theme.accent_rgb[2], 240))
                # Title
                tr_name = trk.title[:42] + "..." if len(trk.title) > 44 else trk.title
                draw.text((margin_x + 86, row_y + 8), tr_name, font=f_row, fill=(245, 248, 255, 240))
                # Artist & requester
                req_by = getattr(trk, "requester_name", "User")
                draw.text((margin_x + 86, row_y + 26), f"{trk.artist} • от {req_by}", font=f_sub, fill=(165, 180, 200, 210))
                # Duration
                dur = getattr(trk, "duration_str", "00:00")
                draw.text((margin_x + card_w - 90, row_y + 14), dur, font=f_row, fill=(180, 195, 215, 220))
                row_y += 52

        # Page indicator footer
        total_pages = max(1, (total_q + per_page - 1) // per_page)
        footer_text = f"Страница {page} из {total_pages} • Всего треков: {total_q}"
        draw.text((margin_x + 36, margin_y + card_h - 32), footer_text, font=f_sub, fill=(150, 165, 185, 200))

        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        return buf


_queue_renderer = QueueCardRenderer()


def get_queue_renderer() -> QueueCardRenderer:
    return _queue_renderer
