"""
render/animation.py - Motion Engine for Liquid Glass / visionOS Cards
Generates animated WebP/GIF Now Playing cards with smooth rotating vinyl, dancing equalizer,
and glowing progress capsule. Asynchronous & non-blocking.
"""

import io
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple

from PIL import Image
import discord

from theme import GlassTheme, THEMES, get_theme
from render.palette import get_track_palette
from render.glass_card import get_glass_renderer, CANVAS_WIDTH, CANVAS_HEIGHT, get_font

logger = logging.getLogger("render.animation")

# In-memory card cache: (cache_key) -> bytes
_CARD_CACHE: Dict[str, Tuple[float, bytes]] = {}
CACHE_TTL = 30.0  # seconds


class GlassAnimationEngine:
    """Async motion graphics renderer for Discord music cards."""

    def __init__(self):
        self.renderer = get_glass_renderer()

    async def render_now_playing_card(
        self,
        title: str,
        artist: str,
        thumbnail_url: Optional[str],
        elapsed_sec: int,
        duration_sec: int,
        is_playing: bool = True,
        loop_mode: str = "off",
        requester: str = "Пользователь",
        theme_name: str = "auto",
        animated: bool = True,
        fps: int = 16,
        loop_duration_sec: float = 2.0
    ) -> discord.File:
        """
        Renders a Liquid Glass Now Playing card (animated WebP if animated=True, else static PNG).
        Executes entirely in a background thread to prevent blocking Discord bot and voice stream.
        """
        # 1. Determine theme
        theme: GlassTheme = await get_track_palette(thumbnail_url, preset_theme_name=theme_name)

        # 2. Fetch or load artwork
        artwork: Image.Image = await self.renderer.load_artwork(thumbnail_url)

        # 3. Offload CPU-bound rendering to thread pool
        loop = asyncio.get_running_loop()
        file_bytes, filename = await loop.run_in_executor(
            None,
            self._render_worker,
            artwork,
            theme,
            title,
            artist,
            elapsed_sec,
            duration_sec,
            is_playing,
            loop_mode,
            requester,
            animated,
            fps,
            loop_duration_sec,
        )

        file_bytes.seek(0)
        return discord.File(fp=file_bytes, filename=filename)

    def _render_worker(
        self,
        artwork: Image.Image,
        theme: GlassTheme,
        title: str,
        artist: str,
        elapsed_sec: int,
        duration_sec: int,
        is_playing: bool,
        loop_mode: str,
        requester: str,
        animated: bool,
        fps: int,
        loop_duration_sec: float
    ) -> Tuple[io.BytesIO, str]:
        """Synchronous CPU worker running in executor thread."""
        total_frames = int(fps * loop_duration_sec) if (animated and is_playing) else 1

        frames = []
        for f_idx in range(total_frames):
            frame = self.renderer.render_now_playing_frame(
                artwork=artwork,
                theme=theme,
                title=title,
                artist=artist,
                elapsed_sec=elapsed_sec,
                duration_sec=duration_sec,
                is_playing=is_playing,
                loop_mode=loop_mode,
                requester=requester,
                frame_idx=f_idx,
                total_frames=total_frames,
            )
            # Convert to RGB with high-fidelity for WebP
            frames.append(frame)

        out_buffer = io.BytesIO()

        if animated and is_playing and len(frames) > 1:
            frame_duration_ms = int(1000 / fps)
            # Save as animated WebP (native support in Discord, high quality, tiny file size < 1MB)
            frames[0].save(
                out_buffer,
                format="WEBP",
                save_all=True,
                append_images=frames[1:],
                duration=frame_duration_ms,
                loop=0,
                quality=82,
                method=4,
            )
            filename = "now_playing.webp"
        else:
            # Static PNG frame
            frames[0].save(out_buffer, format="PNG", optimize=True)
            filename = "now_playing.png"

        return out_buffer, filename

    async def render_loading_card(self, query: str, theme_name: str = "auto") -> discord.File:
        """Renders an animated/shimmer visionOS loading card while searching for track."""
        theme: GlassTheme = THEMES.get(theme_name.lower(), THEMES["auto"])
        artwork = self.renderer._get_fallback_artwork()

        loop = asyncio.get_running_loop()
        file_bytes = await loop.run_in_executor(
            None,
            self._render_loading_worker,
            artwork,
            theme,
            query,
        )
        file_bytes.seek(0)
        return discord.File(fp=file_bytes, filename="loading.png")

    def _render_loading_worker(self, artwork: Image.Image, theme: GlassTheme, query: str) -> io.BytesIO:
        canvas = self.renderer.render_now_playing_frame(
            artwork=artwork,
            theme=theme,
            title="🔍 Ищем трек...",
            artist=f"Запрос: {query}",
            elapsed_sec=0,
            duration_sec=0,
            is_playing=False,
            requester="Поиск",
            frame_idx=0,
            total_frames=1,
        )
        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        return buf


# Global animation engine singleton
_engine = GlassAnimationEngine()


def get_animation_engine() -> GlassAnimationEngine:
    return _engine
