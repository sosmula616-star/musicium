"""
Music Search Engine — YouTube + SoundCloud
Provides search and stream URL extraction with robust thumbnail handling.
"""

import asyncio
import yt_dlp


def format_duration(seconds) -> str:
    if not seconds:
        return "N/A"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def get_best_thumbnail(entry: dict) -> str:
    """Extract highest quality thumbnail URL or generate YouTube fallback."""
    if not entry:
        return ""

    vid_id = entry.get("id", "")
    # For YouTube videos, use clean permanent hqdefault thumbnail to prevent expired token / broken images
    if vid_id and len(vid_id) == 11 and not str(entry.get("webpage_url", "")).startswith("https://soundcloud.com"):
        return f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

    # Check direct thumbnail
    thumb = entry.get("thumbnail")
    if thumb and isinstance(thumb, str) and thumb.strip():
        thumb = thumb.strip()
        if thumb.startswith("//"):
            return "https:" + thumb
        if thumb.startswith("http://"):
            return "https://" + thumb[7:]
        return thumb

    # Check thumbnails list
    thumbs = entry.get("thumbnails")
    if isinstance(thumbs, list) and thumbs:
        for t in reversed(thumbs):
            if isinstance(t, dict) and t.get("url"):
                u = t["url"].strip()
                if u.startswith("//"):
                    return "https:" + u
                if u.startswith("http://"):
                    return "https://" + u[7:]
                return u

    if vid_id and len(vid_id) == 11:
        return f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

    return ""


_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "js_runtimes": {"node": {}},
}


class MusicSearchEngine:
    def __init__(self):
        pass

    # ── YouTube ──────────────────────────────────────────────────────────────

    async def _search_youtube(self, query: str, limit: int = 5) -> list[dict]:
        results = []
        try:
            opts = {
                **_BASE_OPTS,
                "extract_flat": True,
                "playlist_items": f"1-{limit}",
            }

            def _run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _run)
            if not info:
                return []

            for entry in (info.get("entries") or [info])[:limit]:
                if not entry or not entry.get("title"):
                    continue
                vid_id = entry.get("id", "")
                thumb = get_best_thumbnail(entry)
                results.append({
                    "id": vid_id,
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader") or entry.get("channel") or "Unknown",
                    "duration": entry.get("duration", 0),
                    "duration_str": format_duration(entry.get("duration", 0)),
                    "thumbnail": thumb,
                    "url": entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                    "platform": "YouTube",
                    "platform_emoji": "🔴",
                    "platform_color": "#FF0000",
                    "platform_icon": "youtube",
                    "stream_url": None,
                })
        except Exception as e:
            print(f"[YouTube] Search error: {e}")
        return results

    # ── SoundCloud ───────────────────────────────────────────────────────────

    async def _search_soundcloud(self, query: str, limit: int = 5) -> list[dict]:
        results = []
        if limit < 1:
            limit = 1
        try:
            opts = {
                **_BASE_OPTS,
                "extract_flat": False,
                "playlist_items": f"1-{limit}",
            }

            def _run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(f"scsearch{limit}:{query}", download=False)

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _run)
            if not info:
                return []

            for entry in (info.get("entries") or [info])[:limit]:
                if not entry or not entry.get("title"):
                    continue
                thumb = get_best_thumbnail(entry)
                results.append({
                    "id": entry.get("id", ""),
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader") or "Unknown",
                    "duration": entry.get("duration", 0),
                    "duration_str": format_duration(entry.get("duration", 0)),
                    "thumbnail": thumb,
                    "url": entry.get("webpage_url", ""),
                    "platform": "SoundCloud",
                    "platform_emoji": "🟠",
                    "platform_color": "#FF5500",
                    "platform_icon": "soundcloud",
                    "stream_url": None,
                })
        except Exception as e:
            print(f"[SoundCloud] Search error: {e}")
        return results

    # ── URL resolve ──────────────────────────────────────────────────────────

    async def _resolve_url(self, url: str) -> list[dict]:
        results = []
        try:
            opts = {**_BASE_OPTS, "extract_flat": False}

            def _run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False)

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _run)
            if not info:
                return []

            platform = "YouTube"
            platform_icon = "youtube"
            platform_color = "#FF0000"
            if "soundcloud.com" in url:
                platform, platform_icon, platform_color = "SoundCloud", "soundcloud", "#FF5500"

            for entry in (info.get("entries") or [info])[:15]:
                if not entry or not entry.get("title"):
                    continue
                thumb = get_best_thumbnail(entry)
                results.append({
                    "id": entry.get("id", ""),
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader") or "Unknown",
                    "duration": entry.get("duration", 0),
                    "duration_str": format_duration(entry.get("duration", 0)),
                    "thumbnail": thumb,
                    "url": entry.get("webpage_url", url),
                    "platform": platform,
                    "platform_emoji": "🔴" if platform == "YouTube" else "🟠",
                    "platform_color": platform_color,
                    "platform_icon": platform_icon,
                    "stream_url": None,
                })
        except Exception as e:
            print(f"[URL] Resolve error: {e}")
        return results

    # ── MAIN SEARCH ──────────────────────────────────────────────────────────

    async def search(self, query: str, limit: int = 8) -> list[dict]:
        """Search YouTube and SoundCloud in parallel."""
        if query.startswith("http"):
            return await self._resolve_url(query)

        yt_limit = max(1, (limit // 2) + 1)
        sc_limit = max(1, limit - yt_limit)

        yt_task, sc_task = await asyncio.gather(
            self._search_youtube(query, limit=yt_limit),
            self._search_soundcloud(query, limit=sc_limit),
            return_exceptions=True,
        )

        merged = []
        for res in (yt_task, sc_task):
            if isinstance(res, list):
                merged.extend(res)

        return merged[:limit]

    # ── STREAM URL ───────────────────────────────────────────────────────────

    async def get_stream_url(self, track: dict) -> str | None:
        """Get direct audio stream URL with best audio format."""
        url = track.get("url")
        if not url and track.get("id"):
            url = f"https://www.youtube.com/watch?v={track['id']}"
        if not url:
            return None
        try:
            opts = {
                **_BASE_OPTS,
                "format": "bestaudio/best",
                "extract_flat": False,
            }

            def _run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if "entries" in info:
                        info = info["entries"][0]
                    track["http_headers"] = info.get("http_headers", {})
                    return info.get("url")

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _run)
        except Exception as e:
            print(f"[Stream] Error: {e}")
            return None
