"""
Music Search Engine
Searches across YouTube, SoundCloud, Spotify
Returns unified track objects with platform info.
"""

import asyncio
import re
import aiohttp
import yt_dlp
import os
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# Platform emoji mapping
PLATFORM_EMOJI = {
    "YouTube":    "<:youtube:1234567890>",   # кастомный emoji, можно заменить на :red_circle:
    "SoundCloud": "<:soundcloud:1234>",
    "Spotify":    "<:spotify:1234>",
    "Yandex":     "🎵",
}

PLATFORM_EMOJI_FALLBACK = {
    "YouTube":    "🔴",
    "SoundCloud": "🟠",
    "Spotify":    "🟢",
    "Yandex":     "🎵",
}


def format_duration(seconds: int) -> str:
    if not seconds:
        return "N/A"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class MusicSearchEngine:
    def __init__(self):
        self._spotify_token = None
        self._ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "default_search": "ytsearch",
        }

    # ─── SPOTIFY TOKEN ───────────────────────────────────────────────────────

    async def _get_spotify_token(self) -> str | None:
        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            return None
        try:
            import base64
            creds = base64.b64encode(
                f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
            ).decode()
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    "https://accounts.spotify.com/api/token",
                    headers={"Authorization": f"Basic {creds}"},
                    data={"grant_type": "client_credentials"},
                )
                data = await resp.json()
                self._spotify_token = data.get("access_token")
                return self._spotify_token
        except Exception as e:
            print(f"[Spotify] Token error: {e}")
            return None

    # ─── YOUTUBE SEARCH ──────────────────────────────────────────────────────

    async def _search_youtube(self, query: str, limit: int = 5) -> list[dict]:
        results = []
        try:
            opts = {
                **self._ydl_opts,
                "default_search": f"ytsearch{limit}",
                "extract_flat": True,
            }

            def _search():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(query, download=False)
                    return info

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _search)

            if not info:
                return []

            entries = info.get("entries", [info])
            for entry in entries[:limit]:
                if not entry:
                    continue
                duration = entry.get("duration", 0)
                results.append({
                    "id": entry.get("id", ""),
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader", entry.get("channel", "Unknown")),
                    "duration": duration,
                    "duration_str": format_duration(duration),
                    "thumbnail": entry.get("thumbnail") or f"https://i.ytimg.com/vi/{entry.get('id', '')}/hqdefault.jpg",
                    "url": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                    "platform": "YouTube",
                    "platform_emoji": PLATFORM_EMOJI_FALLBACK["YouTube"],
                    "platform_color": "#FF0000",
                    "platform_icon": "youtube",
                    "stream_url": None,  # загружается лениво
                })
        except Exception as e:
            print(f"[YouTube] Search error: {e}")
        return results

    # ─── SOUNDCLOUD SEARCH ───────────────────────────────────────────────────

    async def _search_soundcloud(self, query: str, limit: int = 5) -> list[dict]:
        results = []
        try:
            opts = {
                **self._ydl_opts,
                "default_search": f"scsearch{limit}",
                "extract_flat": True,
            }

            def _search():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(query, download=False)
                    return info

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _search)

            if not info:
                return []

            entries = info.get("entries", [info])
            for entry in entries[:limit]:
                if not entry:
                    continue
                duration = entry.get("duration", 0)
                results.append({
                    "id": entry.get("id", ""),
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader", "Unknown"),
                    "duration": duration,
                    "duration_str": format_duration(duration),
                    "thumbnail": entry.get("thumbnail", ""),
                    "url": entry.get("webpage_url", ""),
                    "platform": "SoundCloud",
                    "platform_emoji": PLATFORM_EMOJI_FALLBACK["SoundCloud"],
                    "platform_color": "#FF5500",
                    "platform_icon": "soundcloud",
                    "stream_url": None,
                })
        except Exception as e:
            print(f"[SoundCloud] Search error: {e}")
        return results

    # ─── SPOTIFY SEARCH ──────────────────────────────────────────────────────

    async def _search_spotify(self, query: str, limit: int = 5) -> list[dict]:
        results = []
        try:
            token = self._spotify_token or await self._get_spotify_token()
            if not token:
                return []

            async with aiohttp.ClientSession() as session:
                resp = await session.get(
                    "https://api.spotify.com/v1/search",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"q": query, "type": "track", "limit": limit},
                )
                if resp.status == 401:
                    # Token expired
                    self._spotify_token = None
                    token = await self._get_spotify_token()
                    if not token:
                        return []
                    resp = await session.get(
                        "https://api.spotify.com/v1/search",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"q": query, "type": "track", "limit": limit},
                    )

                data = await resp.json()
                tracks = data.get("tracks", {}).get("items", [])

                for track in tracks[:limit]:
                    duration_ms = track.get("duration_ms", 0)
                    duration_s = duration_ms // 1000
                    artists = ", ".join(a["name"] for a in track.get("artists", []))
                    images = track.get("album", {}).get("images", [])
                    thumbnail = images[0]["url"] if images else ""

                    results.append({
                        "id": track["id"],
                        "title": track["name"],
                        "artist": artists,
                        "duration": duration_s,
                        "duration_str": format_duration(duration_s),
                        "thumbnail": thumbnail,
                        "url": track.get("external_urls", {}).get("spotify", ""),
                        "spotify_id": track["id"],
                        "platform": "Spotify",
                        "platform_emoji": PLATFORM_EMOJI_FALLBACK["Spotify"],
                        "platform_color": "#1DB954",
                        "platform_icon": "spotify",
                        "stream_url": None,
                        # Spotify треки воспроизводим через YouTube поиск по названию
                        "yt_query": f"{track['name']} {artists} official audio",
                    })
        except Exception as e:
            print(f"[Spotify] Search error: {e}")
        return results

    # ─── MAIN SEARCH ─────────────────────────────────────────────────────────

    async def search(self, query: str, limit: int = 8) -> list[dict]:
        """
        Search across all platforms.
        Returns unified list sorted by relevance (YouTube first, then SC, then Spotify).
        """
        # Определяем тип запроса
        is_url = query.startswith("http")

        if is_url:
            return await self._resolve_url(query)

        # Параллельный поиск по всем платформам
        tasks = [
            self._search_youtube(query, limit=limit // 2 + 1),
            self._search_soundcloud(query, limit=limit // 3 + 1),
        ]
        if SPOTIFY_CLIENT_ID:
            tasks.append(self._search_spotify(query, limit=limit // 3 + 1))

        results_per_platform = await asyncio.gather(*tasks, return_exceptions=True)

        merged = []
        for res in results_per_platform:
            if isinstance(res, Exception):
                continue
            merged.extend(res)

        return merged[:limit]

    async def _resolve_url(self, url: str) -> list[dict]:
        """Resolve a direct URL."""
        results = []
        try:
            def _extract():
                with yt_dlp.YoutubeDL(self._ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _extract)

            if not info:
                return []

            # Определяем платформу по URL
            platform = "YouTube"
            platform_icon = "youtube"
            platform_color = "#FF0000"
            if "soundcloud.com" in url:
                platform = "SoundCloud"
                platform_icon = "soundcloud"
                platform_color = "#FF5500"
            elif "spotify.com" in url:
                platform = "Spotify"
                platform_icon = "spotify"
                platform_color = "#1DB954"

            entries = info.get("entries", [info])
            for entry in entries[:10]:
                if not entry:
                    continue
                duration = entry.get("duration", 0)
                results.append({
                    "id": entry.get("id", ""),
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader", entry.get("artist", "Unknown")),
                    "duration": duration,
                    "duration_str": format_duration(duration),
                    "thumbnail": entry.get("thumbnail", ""),
                    "url": entry.get("webpage_url", url),
                    "platform": platform,
                    "platform_emoji": PLATFORM_EMOJI_FALLBACK[platform],
                    "platform_color": platform_color,
                    "platform_icon": platform_icon,
                    "stream_url": None,
                })
        except Exception as e:
            print(f"[URL] Resolve error: {e}")
        return results

    async def get_stream_url(self, track: dict) -> str | None:
        """Get the actual audio stream URL for a track."""
        try:
            # Для Spotify — ищем на YouTube
            query = track.get("yt_query") or track.get("url")
            if not query:
                return None

            opts = {
                "format": "bestaudio[ext=webm]/bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
            }
            if track.get("platform") == "Spotify":
                opts["default_search"] = "ytsearch1"

            def _extract():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(query, download=False)
                    if "entries" in info:
                        info = info["entries"][0]
                    return info.get("url")

            loop = asyncio.get_event_loop()
            stream_url = await loop.run_in_executor(None, _extract)
            return stream_url
        except Exception as e:
            print(f"[Stream] Error getting stream URL: {e}")
            return None
