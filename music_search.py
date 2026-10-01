"""
Music Search & Stream Extraction Engine
Supports YouTube, SoundCloud, and Direct Audio Streams.
"""

import asyncio
from typing import List, Dict, Any, Optional
import yt_dlp

_COMMON_YTDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "ignoreerrors": True,
    "extract_flat": True,
    "source_address": "0.0.0.0",
}

_STREAM_YTDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "format": "bestaudio/best",
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}


def format_duration(seconds: Optional[int]) -> str:
    """Format duration in seconds to MM:SS or HH:MM:SS."""
    if not seconds or seconds < 0:
        return "N/A"
    try:
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
    except (ValueError, TypeError):
        return "N/A"


def extract_thumbnail(info: Dict[str, Any]) -> str:
    """Extract best thumbnail URL from yt-dlp dictionary."""
    if not info:
        return ""

    # Check for direct id on YouTube
    vid_id = str(info.get("id", ""))
    url = str(info.get("url") or info.get("webpage_url") or "")
    if len(vid_id) == 11 and "soundcloud" not in url:
        return f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

    thumb = info.get("thumbnail")
    if thumb and isinstance(thumb, str):
        t = thumb.strip()
        if t.startswith("//"):
            return "https:" + t
        if t.startswith("http://"):
            return "https://" + t[7:]
        return t

    thumbs = info.get("thumbnails")
    if isinstance(thumbs, list) and thumbs:
        for t in reversed(thumbs):
            if isinstance(t, dict) and t.get("url"):
                u = str(t["url"]).strip()
                if u.startswith("//"):
                    return "https:" + u
                if u.startswith("http://"):
                    return "https://" + u[7:]
                return u

    if len(vid_id) == 11:
        return f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

    return ""


class MusicSearchEngine:
    def __init__(self):
        pass

    async def _search_youtube(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search YouTube for tracks."""
        def _fetch():
            with yt_dlp.YoutubeDL(_COMMON_YTDL_OPTS) as ydl:
                return ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, _fetch)
            if not data or "entries" not in data:
                return []

            results = []
            for item in data.get("entries", []):
                if not item or not isinstance(item, dict) or not item.get("title"):
                    continue

                vid_id = str(item.get("id", ""))
                track_url = item.get("url") or f"https://www.youtube.com/watch?v={vid_id}"
                if not track_url.startswith("http") and vid_id:
                    track_url = f"https://www.youtube.com/watch?v={vid_id}"

                results.append({
                    "id": vid_id,
                    "title": item.get("title", "Unknown Title"),
                    "artist": item.get("channel") or item.get("uploader") or "YouTube",
                    "duration": item.get("duration", 0),
                    "duration_str": format_duration(item.get("duration", 0)),
                    "thumbnail": extract_thumbnail(item),
                    "url": track_url,
                    "platform": "YouTube",
                    "platform_emoji": "🔴",
                    "platform_color": "#ef4444",
                    "platform_icon": "youtube",
                    "stream_url": None,
                })
                if len(results) >= limit:
                    break
            return results
        except Exception as err:
            print(f"[Search Engine] YouTube search error: {err}")
            return []

    async def _search_soundcloud(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search SoundCloud for tracks."""
        def _fetch():
            with yt_dlp.YoutubeDL(_COMMON_YTDL_OPTS) as ydl:
                return ydl.extract_info(f"scsearch{limit}:{query}", download=False)

        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, _fetch)
            if not data or "entries" not in data:
                return []

            results = []
            for item in data.get("entries", []):
                if not item or not isinstance(item, dict) or not item.get("title"):
                    continue

                results.append({
                    "id": str(item.get("id", "")),
                    "title": item.get("title", "Unknown Title"),
                    "artist": item.get("uploader") or "SoundCloud",
                    "duration": item.get("duration", 0),
                    "duration_str": format_duration(item.get("duration", 0)),
                    "thumbnail": extract_thumbnail(item),
                    "url": item.get("webpage_url") or item.get("url") or "",
                    "platform": "SoundCloud",
                    "platform_emoji": "🟠",
                    "platform_color": "#f97316",
                    "platform_icon": "soundcloud",
                    "stream_url": None,
                })
                if len(results) >= limit:
                    break
            return results
        except Exception as err:
            print(f"[Search Engine] SoundCloud search error: {err}")
            return []

    async def _resolve_url(self, url: str) -> List[Dict[str, Any]]:
        """Resolve a direct URL (YouTube, SoundCloud, direct stream)."""
        def _fetch():
            opts = dict(_COMMON_YTDL_OPTS)
            opts["extract_flat"] = True
            opts["noplaylist"] = False  # allow playlist extraction if given
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)

        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, _fetch)
            if not data:
                return []

            platform = "SoundCloud" if "soundcloud.com" in url else "YouTube"
            p_color = "#f97316" if platform == "SoundCloud" else "#ef4444"
            p_emoji = "🟠" if platform == "SoundCloud" else "🔴"
            p_icon = "soundcloud" if platform == "SoundCloud" else "youtube"

            entries = data.get("entries") if "entries" in data else [data]
            results = []
            for item in (entries or []):
                if not item or not isinstance(item, dict) or not item.get("title"):
                    continue

                item_url = item.get("webpage_url") or item.get("url") or url
                item_id = str(item.get("id", ""))
                if not item_url.startswith("http") and item_id:
                    item_url = f"https://www.youtube.com/watch?v={item_id}"

                results.append({
                    "id": item_id,
                    "title": item.get("title", "Unknown Title"),
                    "artist": item.get("uploader") or item.get("channel") or platform,
                    "duration": item.get("duration", 0),
                    "duration_str": format_duration(item.get("duration", 0)),
                    "thumbnail": extract_thumbnail(item),
                    "url": item_url,
                    "platform": platform,
                    "platform_emoji": p_emoji,
                    "platform_color": p_color,
                    "platform_icon": p_icon,
                    "stream_url": None,
                })
                if len(results) >= 20:
                    break
            return results
        except Exception as err:
            print(f"[Search Engine] URL resolve error for {url}: {err}")
            return []

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search query across platforms or resolve URL."""
        query = query.strip()
        if not query:
            return []

        if query.startswith("http://") or query.startswith("https://"):
            return await self._resolve_url(query)

        yt_limit = max(1, (limit // 2) + 1)
        sc_limit = max(1, limit - yt_limit)

        yt_res, sc_res = await asyncio.gather(
            self._search_youtube(query, limit=yt_limit),
            self._search_soundcloud(query, limit=sc_limit),
            return_exceptions=True,
        )

        merged: List[Dict[str, Any]] = []
        if isinstance(yt_res, list):
            merged.extend(yt_res)
        if isinstance(sc_res, list):
            merged.extend(sc_res)

        return merged[:limit]

    async def get_stream_url(self, track: Dict[str, Any]) -> Optional[str]:
        """Extract a playable audio stream URL from track metadata."""
        track_url = track.get("url")
        if not track_url and track.get("id"):
            track_url = f"https://www.youtube.com/watch?v={track['id']}"

        if not track_url:
            return None

        def _fetch():
            with yt_dlp.YoutubeDL(_STREAM_YTDL_OPTS) as ydl:
                info = ydl.extract_info(track_url, download=False)
                if not info:
                    return None
                if "entries" in info and info["entries"]:
                    info = info["entries"][0]
                return info.get("url")

        loop = asyncio.get_running_loop()
        try:
            stream_url = await loop.run_in_executor(None, _fetch)
            if stream_url:
                title = track.get("title", track_url[:30])
                print(f"[Stream] Successfully resolved audio stream for: {title}")
            return stream_url
        except Exception as err:
            print(f"[Stream] Failed to extract audio stream for {track_url}: {err}")
            return None
