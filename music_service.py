import os
import re
import asyncio
import logging
from typing import List, Optional, Dict, Any
import yt_dlp

logger = logging.getLogger("music_service")

# Default placeholders
DEFAULT_THUMBNAIL = "/static/activity_icon.jpg"

def format_duration(seconds: Optional[int]) -> str:
    if not seconds or seconds <= 0:
        return "00:00"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

class Track:
    def __init__(
        self,
        id: str,
        title: str,
        artist: str,
        duration: int,
        thumbnail: str,
        url: str,
        source: str,
        stream_url: Optional[str] = None,
        requester_id: Optional[int] = None,
        requester_name: Optional[str] = None,
        raw_info: Optional[Dict[str, Any]] = None,
    ):
        self.id = id
        self.title = title
        self.artist = artist
        self.duration = duration
        self.duration_str = format_duration(duration)
        self.thumbnail = thumbnail or DEFAULT_THUMBNAIL
        self.url = url
        self.source = source  # 'youtube', 'soundcloud', 'yandex'
        self.stream_url = stream_url
        self.requester_id = requester_id
        self.requester_name = requester_name or "Пользователь"
        self.raw_info = raw_info or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "duration_str": self.duration_str,
            "thumbnail": self.thumbnail,
            "url": self.url,
            "source": self.source,
            "requester_id": str(self.requester_id) if self.requester_id else None,
            "requester_name": self.requester_name,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Track":
        return cls(
            id=data.get("id", ""),
            title=data.get("title", "Неизвестный трек"),
            artist=data.get("artist", "Неизвестный исполнитель"),
            duration=data.get("duration", 0),
            thumbnail=data.get("thumbnail", DEFAULT_THUMBNAIL),
            url=data.get("url", ""),
            source=data.get("source", "youtube"),
            stream_url=data.get("stream_url"),
            requester_id=int(data["requester_id"]) if data.get("requester_id") else None,
            requester_name=data.get("requester_name", "Пользователь"),
        )


class MusicService:
    def __init__(self):
        self.yandex_client = None
        self.yandex_token = os.getenv("YANDEX_MUSIC_TOKEN", "").strip()
        self._init_yandex_client()

        # yt-dlp configuration for fast and reliable searching & streaming
        self.ydl_opts = {
            "format": "bestaudio/best",
            "noplaylist": False,
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch",
            "skip_download": True,
            "extract_flat": False,
            "ignoreerrors": True,
            "source_address": "0.0.0.0",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "visionos"]
                }
            },
        }

        cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
        if os.path.exists(cookie_path):
            self.ydl_opts["cookiefile"] = cookie_path

    def _init_yandex_client(self):
        if not self.yandex_token:
            logger.info("YANDEX_MUSIC_TOKEN is not configured in .env yet.")
            return

        try:
            from yandex_music import Client
            self.yandex_client = Client(self.yandex_token).init()
            logger.info("Yandex Music client initialized successfully!")
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Music client: {e}")
            self.yandex_client = None

    def reload_yandex_token(self, token: Optional[str] = None):
        if token:
            self.yandex_token = token.strip()
        else:
            self.yandex_token = os.getenv("YANDEX_MUSIC_TOKEN", "").strip()
        self._init_yandex_client()

    async def search(self, query: str, source: str = "all", limit: int = 10) -> List[Track]:
        query = query.strip()
        if not query:
            return []

        # Check if query is a direct URL
        if query.startswith("http://") or query.startswith("https://"):
            return await self._resolve_direct_url(query)

        source = source.lower()
        tasks = []

        if source == "yt_albums":
            tasks.append(self._search_youtube_albums(query, limit=limit))
        elif source == "youtube":
            tasks.append(self._search_youtube(query, limit=limit))
        elif source == "soundcloud":
            tasks.append(self._search_soundcloud(query, limit=limit))
        else:
            tasks.append(self._search_youtube(query, limit=min(limit, 30)))
            tasks.append(self._search_soundcloud(query, limit=min(limit, 20)))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_tracks: List[Track] = []
        for res in results:
            if isinstance(res, list):
                all_tracks.extend(res)
            elif isinstance(res, Exception):
                logger.warning(f"Error during search: {res}")

        return all_tracks

    async def _resolve_direct_url(self, url: str) -> List[Track]:
        # Handle Yandex Music track link
        if "music.yandex" in url:
            track = await asyncio.to_thread(self._resolve_yandex_url, url)
            return [track] if track else []

        # Otherwise yt-dlp handles YouTube, SoundCloud, and hundreds of other sites
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_url_info, url)

    def _extract_url_info(self, url: str) -> List[Track]:
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return []
                if "entries" in info:
                    tracks = []
                    for entry in info["entries"][:50]:
                        if entry:
                            tracks.append(self._parse_ytdlp_entry(entry))
                    return tracks
                return [self._parse_ytdlp_entry(info)]
        except Exception as e:
            logger.error(f"Error extracting url info ({url}): {e}")
            return []

    def _parse_ytdlp_entry(self, entry: Dict[str, Any], default_source: str = "youtube") -> Track:
        webpage_url = entry.get("webpage_url") or entry.get("url") or ""
        extractor = (entry.get("extractor") or entry.get("extractor_key") or "").lower()

        source = "youtube"
        if "soundcloud" in extractor or "soundcloud.com" in webpage_url:
            source = "soundcloud"
        elif "yandex" in extractor:
            source = "yandex"

        title = entry.get("title") or "Неизвестный трек"
        artist = entry.get("uploader") or entry.get("channel") or entry.get("artist") or "Неизвестный автор"
        duration = int(entry.get("duration") or 0)
        vid_id = str(entry.get("id") or "")
        if source == "youtube" and vid_id:
            thumbnail = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
        else:
            thumbnail = entry.get("thumbnail") or DEFAULT_THUMBNAIL
        stream_url = entry.get("url") if entry.get("acodec") != "none" else None

        return Track(
            id=f"{source}_{entry.get('id', hash(title))}",
            title=title,
            artist=artist,
            duration=duration,
            thumbnail=thumbnail,
            url=webpage_url,
            source=source,
            stream_url=stream_url,
            raw_info=entry,
        )

    def _parse_flat_entry(self, entry: Dict[str, Any], default_source: str = "youtube") -> Track:
        entry_id = str(entry.get("id") or "")
        webpage_url = entry.get("url") or entry.get("webpage_url") or ""
        
        source = default_source
        if not webpage_url.startswith("http"):
            if default_source == "youtube":
                webpage_url = f"https://www.youtube.com/watch?v={entry_id}"
            elif default_source == "soundcloud":
                webpage_url = entry.get("url") or ""

        extractor = (entry.get("extractor") or entry.get("extractor_key") or "").lower()
        if "soundcloud" in extractor or "soundcloud" in webpage_url:
            source = "soundcloud"
        elif "yandex" in extractor:
            source = "yandex"

        title = entry.get("title") or "Неизвестный трек"
        artist = entry.get("uploader") or entry.get("channel") or entry.get("artist") or "Неизвестный автор"
        duration = int(entry.get("duration") or 0)
        
        if source == "youtube" and entry_id:
            thumbnail = f"https://i.ytimg.com/vi/{entry_id}/hqdefault.jpg"
        else:
            thumbnail = entry.get("thumbnail")
            if not thumbnail and entry.get("thumbnails"):
                thumbnail = entry["thumbnails"][-1].get("url")
            if not thumbnail:
                thumbnail = DEFAULT_THUMBNAIL

        return Track(
            id=f"{source}_{entry_id}",
            title=title,
            artist=artist,
            duration=duration,
            thumbnail=thumbnail,
            url=webpage_url,
            source=source,
            stream_url=None,
            raw_info=entry,
        )

    async def _search_youtube(self, query: str, limit: int = 6) -> List[Track]:
        def _search():
            opts = dict(self.ydl_opts)
            opts["extract_flat"] = True
            search_query = f"ytsearch{limit}:{query}"
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if not info or "entries" not in info:
                    return []
                tracks = []
                for entry in info["entries"]:
                    if entry:
                        t = self._parse_flat_entry(entry, default_source="youtube")
                        tracks.append(t)
                return tracks

        return await asyncio.to_thread(_search)

    async def _search_soundcloud(self, query: str, limit: int = 6) -> List[Track]:
        def _search():
            opts = dict(self.ydl_opts)
            opts["extract_flat"] = True
            search_query = f"scsearch{limit}:{query}"
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if not info or "entries" not in info:
                    return []
                filtered_tracks = []
                all_sc_tracks = []
                clean_query_words = [w.lower() for w in re.findall(r'[\w]+', query) if len(w) >= 3]
                for entry in info["entries"]:
                    if entry:
                        t = self._parse_flat_entry(entry, default_source="soundcloud")
                        all_sc_tracks.append(t)
                        if clean_query_words:
                            text = f"{t.title} {t.artist}".lower()
                            # Ensure at least one word from the query appears in the track title/artist
                            if any(w in text for w in clean_query_words):
                                filtered_tracks.append(t)
                        else:
                            filtered_tracks.append(t)
                return filtered_tracks if filtered_tracks else all_sc_tracks

        return await asyncio.to_thread(_search)

    async def _search_youtube_albums(self, query: str, limit: int = 15) -> List[Track]:
        def _search():
            opts = dict(self.ydl_opts)
            opts["extract_flat"] = True
            opts["noplaylist"] = False
            search_query = f"ytsearch{limit}:{query} album"
            info = None
            with yt_dlp.YoutubeDL(opts) as ydl:
                try:
                    info = ydl.extract_info(search_query, download=False)
                except Exception:
                    info = None
                if not info or "entries" not in info or not info["entries"]:
                    try:
                        search_query = f"ytsearch{limit}:{query} full album"
                        info = ydl.extract_info(search_query, download=False)
                    except Exception:
                        info = None
                if not info or "entries" not in info:
                    return []
                tracks = []
                for entry in info["entries"]:
                    if entry:
                        t = self._parse_flat_entry(entry, default_source="youtube")
                        t.title = f"💿 {t.title}"
                        tracks.append(t)
                return tracks

        return await asyncio.to_thread(_search)

    async def _search_yandex(self, query: str, limit: int = 6) -> List[Track]:
        if not self.yandex_client:
            logger.debug("Yandex client not initialized, skipping Yandex Music search.")
            return []

        def _search():
            try:
                res = self.yandex_client.search(query, type_="track")
                if not res or not res.tracks or not res.tracks.results:
                    return []

                tracks = []
                for item in res.tracks.results[:limit]:
                    artists_names = ", ".join([a.name for a in item.artists]) if item.artists else "Неизвестный исполнитель"
                    thumbnail = DEFAULT_THUMBNAIL
                    if item.cover_uri:
                        thumbnail = "https://" + item.cover_uri.replace("%%", "400x400")

                    duration_sec = int((item.duration_ms or 0) / 1000)
                    url = f"https://music.yandex.ru/track/{item.id}"
                    track = Track(
                        id=f"yandex_{item.id}",
                        title=item.title,
                        artist=artists_names,
                        duration=duration_sec,
                        thumbnail=thumbnail,
                        url=url,
                        source="yandex",
                        raw_info={"yandex_id": item.id},
                    )
                    tracks.append(track)
                return tracks
            except Exception as e:
                logger.error(f"Yandex Music search error: {e}")
                return []

        return await asyncio.to_thread(_search)

    def _resolve_yandex_url(self, url: str) -> Optional[Track]:
        if not self.yandex_client:
            return None
        try:
            # extract track id from e.g. https://music.yandex.ru/album/123/track/456 or /track/456
            parts = url.rstrip("/").split("/")
            if "track" in parts:
                idx = parts.index("track")
                if idx + 1 < len(parts):
                    track_id = parts[idx + 1]
                    tracks = self.yandex_client.tracks([track_id])
                    if tracks:
                        item = tracks[0]
                        artists_names = ", ".join([a.name for a in item.artists]) if item.artists else "Неизвестный исполнитель"
                        thumbnail = "https://" + item.cover_uri.replace("%%", "400x400") if item.cover_uri else DEFAULT_THUMBNAIL
                        duration_sec = int((item.duration_ms or 0) / 1000)
                        return Track(
                            id=f"yandex_{item.id}",
                            title=item.title,
                            artist=artists_names,
                            duration=duration_sec,
                            thumbnail=thumbnail,
                            url=url,
                            source="yandex",
                            raw_info={"yandex_id": item.id},
                        )
        except Exception as e:
            logger.error(f"Error resolving Yandex URL: {e}")
        return None

    async def get_stream_url(self, track: Track) -> Optional[str]:
        """Resolves the direct playable audio stream URL for a Track."""
        if track.source == "yandex":
            return await self._get_yandex_stream(track)
        else:
            return await self._get_ytdlp_stream(track)

    async def _get_yandex_stream(self, track: Track) -> Optional[str]:
        if not self.yandex_client:
            logger.error("Cannot resolve Yandex stream: Yandex Music client is not authenticated.")
            return None

        def _get():
            try:
                track_id = track.raw_info.get("yandex_id")
                if not track_id and "_" in track.id:
                    track_id = track.id.split("_", 1)[1]

                tracks = self.yandex_client.tracks([track_id])
                if not tracks:
                    return None
                t = tracks[0]
                download_info = t.get_download_info()
                if not download_info:
                    return None
                # Prefer mp3 or highest bitrate
                best_info = max(download_info, key=lambda d: d.bitrate_in_kbps or 0)
                return best_info.get_direct_link()
            except Exception as e:
                logger.error(f"Error getting Yandex download link: {e}")
                return None

        return await asyncio.to_thread(_get)

    async def _get_ytdlp_stream(self, track: Track) -> Optional[str]:
        def _get():
            target_url = track.url
            if not target_url:
                if track.id and "_" in track.id and not track.id.startswith("yandex_"):
                    target_url = f"https://www.youtube.com/watch?v={track.id.split('_', 1)[1]}"
                else:
                    target_url = f"ytsearch1:{track.title} {track.artist}"

            opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "noplaylist": True,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android", "visionos"]
                    }
                },
            }

            cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
            if os.path.exists(cookie_file):
                opts["cookiefile"] = cookie_file

            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    if not info:
                        raise ValueError("No video info returned")
                    if "entries" in info and info["entries"]:
                        info = info["entries"][0]
                    stream = info.get("url")
                    if stream:
                        return stream
                    raise ValueError("No audio stream URL in info")
            except Exception as e:
                logger.warning(f"Primary YouTube stream extraction failed ({e}), attempting secondary client...")
                try:
                    sec_opts = dict(opts)
                    sec_opts["extractor_args"] = {"youtube": {"player_client": ["web_embedded"]}}
                    with yt_dlp.YoutubeDL(sec_opts) as ydl:
                        sec_info = ydl.extract_info(target_url, download=False)
                        if sec_info:
                            if "entries" in sec_info and sec_info["entries"]:
                                sec_info = sec_info["entries"][0]
                            sec_stream = sec_info.get("url")
                            if sec_stream:
                                return sec_stream
                except Exception:
                    pass

                logger.warning(f"YouTube stream extraction failed, attempting SoundCloud fallback...")
                # Automatic fallback: search track title on SoundCloud
                try:
                    sc_opts = {
                        "format": "bestaudio/best",
                        "quiet": True,
                        "extract_flat": False,
                        "noplaylist": True,
                    }
                    search_query = f"{track.title} {track.artist}".strip()
                    with yt_dlp.YoutubeDL(sc_opts) as ydl:
                        sc_info = ydl.extract_info(f"scsearch1:{search_query}", download=False)
                        if sc_info and "entries" in sc_info and sc_info["entries"]:
                            sc_entry = sc_info["entries"][0]
                            sc_stream = sc_entry.get("url")
                            if sc_stream:
                                logger.info(f"SoundCloud fallback stream resolved for: {track.title}")
                                return sc_stream
                except Exception as sc_err:
                    logger.error(f"SoundCloud fallback failed as well: {sc_err}")
                return None

        return await asyncio.to_thread(_get)
