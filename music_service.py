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
        self.source = source  # 'youtube', 'soundcloud'
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
        # yt-dlp configuration for fast searching
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
        }

        # YouTube cookie path strictly for YouTube playback
        self.youtube_cookie_path = None
        cookie_path = os.getenv("YOUTUBE_COOKIES_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
        env_cookies = os.getenv("YOUTUBE_COOKIES", "").strip()
        env_cookies_b64 = os.getenv("YOUTUBE_COOKIES_BASE64", "").strip()

        if env_cookies_b64:
            try:
                import base64
                decoded = base64.b64decode(env_cookies_b64).decode("utf-8")
                target_cf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
                with open(target_cf, "w", encoding="utf-8") as cf:
                    cf.write(decoded)
                cookie_path = target_cf
                logger.info("Saved cookies from YOUTUBE_COOKIES_BASE64 env var to cookies.txt")
            except Exception as ce:
                logger.warning(f"Could not decode YOUTUBE_COOKIES_BASE64: {ce}")
        elif env_cookies:
            try:
                target_cf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
                with open(target_cf, "w", encoding="utf-8") as cf:
                    cf.write(env_cookies)
                cookie_path = target_cf
                logger.info("Saved cookies from YOUTUBE_COOKIES env var to cookies.txt")
            except Exception as ce:
                logger.warning(f"Could not write YOUTUBE_COOKIES to cookies.txt: {ce}")

        if os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0:
            self.youtube_cookie_path = cookie_path
            logger.info(f"YouTube cookies configured from: {cookie_path}")

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
        # yt-dlp handles YouTube, SoundCloud, and hundreds of other sites
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

    async def get_stream_url(self, track: Track) -> Optional[str]:
        """Resolves the direct playable audio stream URL for a Track."""
        if track.source == "soundcloud" or (track.url and "soundcloud.com" in track.url) or (track.id and track.id.startswith("soundcloud_")):
            return await self._get_soundcloud_stream(track)
        return await self._get_youtube_stream(track)

    async def _get_soundcloud_stream(self, track: Track) -> Optional[str]:
        def _get():
            target_url = track.url
            if not target_url or not target_url.startswith("http"):
                target_url = track.raw_info.get("webpage_url") or track.raw_info.get("url")
            if not target_url or not str(target_url).startswith("http"):
                if track.id and "_" in track.id and track.id.split("_", 1)[1].isdigit():
                    target_url = f"https://api.soundcloud.com/tracks/soundcloud%3Atracks%3A{track.id.split('_', 1)[1]}"
                else:
                    target_url = f"scsearch1:{track.title} {track.artist}"

            sc_opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "noplaylist": True,
                "source_address": "0.0.0.0",
            }

            try:
                with yt_dlp.YoutubeDL(sc_opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    if info:
                        if "entries" in info and info["entries"]:
                            info = info["entries"][0]
                        stream = info.get("url")
                        if stream:
                            return stream
            except Exception as e:
                logger.warning(f"Direct SoundCloud extraction failed for {target_url}: {e}")

            # Fallback search on SoundCloud
            try:
                clean_title = re.sub(r'[\U00010000-\U0010ffff]', '', track.title)
                clean_title = re.sub(r'#\w+', '', clean_title)
                clean_title = re.sub(r'\|.*', '', clean_title)
                clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', clean_title).strip()
                clean_artist = track.artist if track.artist and track.artist != "Неизвестный автор" else ""
                search_q = f"scsearch1:{clean_title} {clean_artist}".strip()
                with yt_dlp.YoutubeDL(sc_opts) as ydl:
                    info = ydl.extract_info(search_q, download=False)
                    if info and "entries" in info and info["entries"]:
                        sc_entry = info["entries"][0]
                        return sc_entry.get("url")
            except Exception as e2:
                logger.error(f"SoundCloud fallback search failed: {e2}")

            return None

        return await asyncio.to_thread(_get)

    async def _get_youtube_stream(self, track: Track) -> Optional[str]:
        def _get():
            target_url = track.url
            if not target_url or not target_url.startswith("http"):
                if track.id and "_" in track.id:
                    vid_id = track.id.split("_", 1)[1]
                    target_url = f"https://www.youtube.com/watch?v={vid_id}"
                else:
                    target_url = f"ytsearch1:{track.title} {track.artist}"

            opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "noplaylist": True,
                "source_address": "0.0.0.0",
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android"],
                        "player_skip": ["webpage", "configs"],
                    },
                    "youtubetab": {
                        "skip": ["webpage"],
                    },
                },
            }

            # STRICT RULE: Cookies are ONLY used for YouTube stream playback to avoid bot detection
            if self.youtube_cookie_path and os.path.exists(self.youtube_cookie_path):
                opts["cookiefile"] = self.youtube_cookie_path

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
                logger.warning(f"Primary YouTube stream extraction failed ({e}), attempting fallback client...")
                try:
                    sec_opts = dict(opts)
                    sec_opts["extractor_args"] = {
                        "youtube": {
                            "player_client": ["android_vr"],
                            "player_skip": ["webpage", "configs"],
                        },
                        "youtubetab": {
                            "skip": ["webpage"],
                        },
                    }
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

                logger.warning("YouTube stream extraction failed, attempting SoundCloud fallback...")
                try:
                    sc_opts = {
                        "format": "bestaudio/best",
                        "quiet": True,
                        "extract_flat": False,
                        "noplaylist": True,
                    }
                    clean_title = re.sub(r'[\U00010000-\U0010ffff]', '', track.title)
                    clean_title = re.sub(r'#\w+', '', clean_title)
                    clean_title = re.sub(r'\|.*', '', clean_title)
                    clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', clean_title).strip()
                    clean_artist = track.artist if track.artist and track.artist != "Неизвестный автор" else ""
                    search_query = f"{clean_title} {clean_artist}".strip()
                    if not search_query:
                        search_query = track.title

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
