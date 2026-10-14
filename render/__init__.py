"""
render package - Liquid Glass / visionOS Visual Compositor & Motion Graphics
"""

from render.palette import get_track_palette, extract_dominant_color_from_image
from render.glass_card import GlassCardRenderer, get_glass_renderer
from render.animation import GlassAnimationEngine, get_animation_engine
from render.queue_card import QueueCardRenderer, get_queue_renderer
from render.lyrics_card import LyricsCardRenderer, get_lyrics_renderer

__all__ = [
    "get_track_palette",
    "extract_dominant_color_from_image",
    "GlassCardRenderer",
    "get_glass_renderer",
    "GlassAnimationEngine",
    "get_animation_engine",
    "QueueCardRenderer",
    "get_queue_renderer",
    "LyricsCardRenderer",
    "get_lyrics_renderer",
]
