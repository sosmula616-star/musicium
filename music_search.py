"""
Music Search Engine — YouTube + SoundCloud
Provides search and stream URL extraction with robust thumbnail handling.
"""

import asyncio
import yt_dlp


def format_duration(seconds) -> str:
    if not seconds:
        return "N/A"
    try:
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
    except (ValueError, TypeError):
        return "N/A"


def get_best_thumbnail(entry: dict) -> str:
    """Extract highest quality thumbnail URL or generate YouTube fallback."""
    if not entry:
        return ""

    vid_id = entry.get("id", "")
    if vid_id and len(vid_id) == 11 and not str(entry.get("webpage_url", "")).startswith("https://soundcloud.com"):
        return f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

    thumb = entry.get("thumbnail")
    if thumb and isinstance(thumb, str) and thumb.strip():
        thumb = thumb.strip()
        if thumb.startswith("//"):
            return "https:" + thumb
        if thumb.startswith("http://"):
            return "https://" + thumb[7:]
        return thumb

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
    "ignoreerrors": True,
}


class MusicSearchEngine:
    def __init__(self):
        pass

    async def _search_youtube(self, query: str, limit: int = 5) -> list[dict]:
        results = []
        try:
            opts = {
                **_BASE_OPTS,
                "extract_flat": True,
            }

            def _run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _run)
            if not info:
                return []

            entries = info.get("entries") or []
            for entry in entries:
                if not entry or not isinstance(entry, dict) or not entry.get("title"):
                    continue
                vid_id = entry.get("id", "")
                thumb = get_best_thumbnail(entry)
                url = entry.get("url") or f"https://www.youtube.com/watch?v={vid_id}"
                if not url.startswith("http") and vid_id:
                    url = f"https://www.youtube.com/watch?v={vid_id}"

                title = entry.get("title", "Unknown")
                results.append({
                    "id": vid_id,
                    "title": title,
                    "artist": entry.get("channel") or entry.get("uploader") or "Unknown",
                    "duration": entry.get("duration", 0),
                    "duration_str": format_duration(entry.get("duration", 0)),
                    "thumbnail": thumb,
                    "url": url,
                    "platform": "YouTube",
                    "platform_emoji": "🔴",
                    "platform_color": "#FF0000",
                    "platform_icon": "youtube",
                    "stream_url": None,
                })
                if len(results) >= limit:
                    break
        except Exception as e:
            print(f"[YouTube] Search error: {e}")
        return results

    async def _search_soundcloud(self, query: str, limit: int = 5) -> list[dict]:
        results = []
        if limit < 1:
            limit = 1
        try:
            opts = {
                **_BASE_OPTS,
                "extract_flat": True,
            }

            def _run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(f"scsearch{limit}:{query}", download=False)

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _run)
            if not info:
                return []

            entries = info.get("entries") or []
            for entry in entries:
                if not entry or not isinstance(entry, dict) or not entry.get("title"):
                    continue
                thumb = get_best_thumbnail(entry)
                results.append({
                    "id": str(entry.get("id", "")),
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader") or "Unknown",
                    "duration": entry.get("duration", 0),
                    "duration_str": format_duration(entry.get("duration", 0)),
                    "thumbnail": thumb,
                    "url": entry.get("webpage_url") or entry.get("url") or "",
                    "platform": "SoundCloud",
                    "platform_emoji": "🟠",
                    "platform_color": "#FF5500",
                    "platform_icon": "soundcloud",
                    "stream_url": None,
                })
                if len(results) >= limit:
                    break
        except Exception as e:
            print(f"[SoundCloud] Search error: {e}")
        return results

    async def _resolve_url(self, url: str) -> list[dict]:
        results = []
        try:
            opts = {
                **_BASE_OPTS,
                "extract_flat": True,
            }

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

            entries = info.get("entries") if "entries" in info else [info]
            for entry in (entries or []):
                if not entry or not isinstance(entry, dict) or not entry.get("title"):
                    continue
                thumb = get_best_thumbnail(entry)
                entry_url = entry.get("webpage_url") or entry.get("url") or url
                if not entry_url.startswith("http") and entry.get("id"):
                    entry_url = f"https://www.youtube.com/watch?v={entry['id']}"

                results.append({
                    "id": str(entry.get("id", "")),
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader") or entry.get("channel") or "Unknown",
                    "duration": entry.get("duration", 0),
                    "duration_str": format_duration(entry.get("duration", 0)),
                    "thumbnail": thumb,
                    "url": entry_url,
                    "platform": platform,
                    "platform_emoji": "🔴" if platform == "YouTube" else "🟠",
                    "platform_color": platform_color,
                    "platform_icon": platform_icon,
                    "stream_url": None,
                })
                if len(results) >= 15:
                    break
        except Exception as e:
            print(f"[URL] Resolve error: {e}")
        return results

    async def search(self, query: str, limit: int = 8) -> list[dict]:
        """Search YouTube and SoundCloud in parallel."""
        if query.startswith("http://") or query.startswith("https://"):
            return await self._resolve_url(query)

        yt_limit = max(1, (limit // 2) + 1)
        sc_limit = max(1, limit - yt_limit)

        yt_task, sc_task = await asyncio.gather(
            self._search_youtube(query, limit=yt_limit),
            self._search_soundcloud(query, limit=sc_limit),
            return_exceptions=True,
        )

        merged = []
        if isinstance(yt_task, list):
            merged.extend(yt_task)
        if isinstance(sc_task, list):
            merged.extend(sc_task)

        return merged[:limit]

    async def get_stream_url(self, track: dict) -> str | None:
        """Get direct audio stream URL with best audio format."""
        url = track.get("url")
        if not url and track.get("id"):
            url = f"https://www.youtube.com/watch?v={track['id']}"
        if not url:
            return None
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "format": "bestaudio/best",
            }

            def _run():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        return None
                    if "entries" in info and info["entries"]:
                        info = info["entries"][0]
                    return info.get("url")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _run)
            if result:
                track_title = track.get("title") or url[:40]
                print(f"[Stream] OK: {track_title}")
            return result
        except Exception as e:
            print(f"[Stream] Error for {url[:60]}: {e}")
            return None
