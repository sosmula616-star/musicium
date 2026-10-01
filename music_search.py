"""
Music Search & Stream Resolution Module
Supports YouTube, SoundCloud, and direct URLs via yt-dlp.
"""

import asyncio
from typing import List, Dict, Any, Optional
import yt_dlp

_SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "ignoreerrors": True,
    "extract_flat": True,
    "source_address": "0.0.0.0",
}

_STREAM_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "format": "bestaudio/best",
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}


def format_duration(seconds: Optional[int]) -> str:
    """Format seconds into MM:SS or HH:MM:SS string."""
    if not seconds or seconds < 0:
        return "Live / N/A"
    try:
        sec = int(seconds)
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
    except (ValueError, TypeError):
        return "N/A"


def extract_thumbnail(info: Dict[str, Any]) -> str:
    """Extract best thumbnail URL from track info."""
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
    async def _search_youtube(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        def _fetch():
            with yt_dlp.YoutubeDL(_SEARCH_OPTS) as ydl:
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
                    "stream_url": None,
                })
                if len(results) >= limit:
                    break
            return results
        except Exception as e:
            print(f"[Search] YouTube search error: {e}")
            return []

    async def _search_soundcloud(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        def _fetch():
            with yt_dlp.YoutubeDL(_SEARCH_OPTS) as ydl:
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
                    "stream_url": None,
                })
                if len(results) >= limit:
                    break
            return results
        except Exception as e:
            print(f"[Search] SoundCloud search error: {e}")
            return []

    async def _resolve_url(self, url: str) -> List[Dict[str, Any]]:
        def _fetch():
            opts = dict(_SEARCH_OPTS)
            opts["extract_flat"] = True
            opts["noplaylist"] = False
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)

        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, _fetch)
            if not data:
                return []

            platform = "SoundCloud" if "soundcloud.com" in url else "YouTube"
            p_emoji = "🟠" if platform == "SoundCloud" else "🔴"

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
                    "stream_url": None,
                })
                if len(results) >= 25:
                    break
            return results
        except Exception as e:
            print(f"[Search] URL resolution error for {url}: {e}")
            return []

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search tracks by query across platforms or resolve URL."""
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
        """Extract high-quality direct audio stream URL."""
        track_url = track.get("url")
        if not track_url and track.get("id"):
            track_url = f"https://www.youtube.com/watch?v={track['id']}"

        if not track_url:
            return None

        def _fetch():
            with yt_dlp.YoutubeDL(_STREAM_OPTS) as ydl:
                info = ydl.extract_info(track_url, download=False)
                if not info:
                    return None
                if "entries" in info and info["entries"]:
                    info = info["entries"][0]
                return info.get("url")

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _fetch)
        except Exception as e:
            print(f"[Stream] Failed to get audio stream for {track_url}: {e}")
            return None
