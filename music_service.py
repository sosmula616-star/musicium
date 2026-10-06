import os
import re
import time
import base64
import asyncio
import logging
from typing import List, Optional, Dict, Any, Tuple
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
        raw_dur = data.get("duration", 0)
        dur = 0
        try:
            dur = int(raw_dur or 0)
        except Exception:
            dur = 0
        if dur <= 0 and data.get("duration_str"):
            parts = str(data["duration_str"]).strip().split(":")
            try:
                if len(parts) == 2:
                    dur = int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 3:
                    dur = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            except Exception:
                dur = 0

        return cls(
            id=data.get("id", ""),
            title=data.get("title", "Неизвестный трек"),
            artist=data.get("artist", "Неизвестный исполнитель"),
            duration=dur,
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
            "format": "ba/b/bestaudio/best",
            "noplaylist": False,
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch",
            "skip_download": True,
            "extract_flat": True,
            "ignoreerrors": True,
            "socket_timeout": 5,
            "retries": 1,
            "source_address": "0.0.0.0",
        }

        # Ultra-fast Innertube extractor options for stream resolution (Android / iOS)
        # Avoids JavaScript n-sig decryption and bot challenges; resolves direct audio in ~0.3-0.8s
        self.fast_yt_opts = {
            "format": "ba[acodec^=opus]/ba[ext=webm]/ba[ext=m4a]/ba/b/bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "noplaylist": True,
            "skip_download": True,
            "check_formats": False,
            "youtube_include_dash_manifest": False,
            "youtube_include_hls_manifest": False,
            "lazy_playlist": True,
            "socket_timeout": 5,
            "retries": 1,
            "fragment_retries": 1,
            "source_address": "0.0.0.0",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "mweb"],
                    "player_skip": ["configs", "webpage"],
                }
            }
        }

        # Cache for resolved audio stream URLs: {key: (stream_url, expire_timestamp)}
        self._stream_cache: Dict[str, Tuple[str, float]] = {}

        # Comprehensive search and auto-repair for cookies.txt
        self.youtube_cookie_path = None
        self._load_and_sanitize_cookies()

    @staticmethod
    def _sanitize_cookie_text(text: str) -> Optional[str]:
        if not text:
            return None
        text = text.strip()

        # Handle escaped literals e.g. \n or \t from misconfigured env strings
        if "\\n" in text and "\n" not in text:
            text = text.replace("\\n", "\n").replace("\\t", "\t")

        # Check if text is Base64 encoded
        cleaned_candidate = re.sub(r'[^A-Za-z0-9+/=]', '', text)
        if text.startswith("IyB") or ("\t" not in text and len(cleaned_candidate) > 20):
            try:
                dec = base64.b64decode(cleaned_candidate).decode("utf-8", errors="ignore")
                if "youtube.com" in dec or "\t" in dec or "# Netscape" in dec:
                    text = dec.strip()
                    logger.info("Successfully decoded Base64 cookie content to Netscape text format.")
            except Exception as b64_err:
                logger.debug(f"Base64 cookie decoding check: {b64_err}")

        lines = [l.strip("\r") for l in text.splitlines() if l.strip("\r")]
        valid = []
        for l in lines:
            if l.startswith("#"):
                valid.append(l)
            elif "\t" in l:
                if len(l.split("\t")) >= 6:
                    valid.append(l)

        if not valid:
            return None

        # Ensure standard Netscape header is present
        if not any(v.startswith("# Netscape HTTP Cookie File") for v in valid[:3]):
            valid.insert(0, "# Netscape HTTP Cookie File\n# https://curl.haxx.se/rfc/cookie_spec.html\n# This is a generated file! Do not edit.")

        return "\n".join(valid) + "\n"

    def _load_and_sanitize_cookies(self):
        """
        Comprehensive search for cookies.txt / env vars, with automatic Base64
        decoding, validation, and in-place repair for yt-dlp compatibility.
        """
        self.youtube_cookie_path = None

        cookie_candidates = [
            os.getenv("YOUTUBE_COOKIES_PATH"),
            "/app/data/cookies.txt",
            "/home/container/cookies.txt",
            "/app/cookies.txt",
            "cookies.txt",
            os.path.join(os.getcwd(), "cookies.txt"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt"),
            "data/cookies.txt",
        ]

        # Scan potential bot directories for any variant of cookies.txt
        for search_dir in [os.getcwd(), "/home/container", "/app", "/app/data", os.path.dirname(os.path.abspath(__file__))]:
            if os.path.isdir(search_dir):
                try:
                    for fname in os.listdir(search_dir):
                        if fname.lower() == "cookies.txt":
                            candidate = os.path.abspath(os.path.join(search_dir, fname))
                            if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                                if candidate not in cookie_candidates:
                                    cookie_candidates.append(candidate)
                except Exception:
                    pass

        raw_content = ""
        source_path = None

        # 1. Check environment variables
        env_b64 = os.getenv("YOUTUBE_COOKIES_BASE64", "").strip()
        env_plain = os.getenv("YOUTUBE_COOKIES", "").strip()

        if env_b64:
            raw_content = env_b64
            logger.info("Found YouTube cookies in YOUTUBE_COOKIES_BASE64 env var")
        elif env_plain:
            raw_content = env_plain
            logger.info("Found YouTube cookies in YOUTUBE_COOKIES env var")

        # 2. Check candidate files on disk if not found in env
        if not raw_content:
            for cp in cookie_candidates:
                if cp and os.path.exists(cp) and os.path.isfile(cp) and os.path.getsize(cp) > 0:
                    try:
                        with open(cp, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read().strip()
                        if text:
                            raw_content = text
                            source_path = cp
                            logger.info(f"Loaded YouTube cookies candidate from {cp} ({len(text)} chars)")
                            break
                    except Exception as e:
                        logger.debug(f"Failed to read cookie candidate {cp}: {e}")

        if not raw_content:
            logger.warning("No cookies.txt or cookie environment variable found for YouTube!")
            return

        # 3. Sanitize and decode if Base64
        sanitized = self._sanitize_cookie_text(raw_content)
        if not sanitized:
            logger.warning("Failed to sanitize cookie content into valid Netscape format")
            return

        # 4. Save sanitized content to primary targets and overwrite the source file if it was Base64
        app_cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
        write_targets = [app_cookie_path]
        if source_path and source_path not in write_targets:
            write_targets.append(source_path)
        write_targets.append("/tmp/youtube_cookies.txt")

        valid_file = None
        for target in write_targets:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    f.write(sanitized)
                if not valid_file:
                    valid_file = os.path.abspath(target)
            except Exception as e:
                logger.debug(f"Could not write sanitized cookies to {target}: {e}")

        if valid_file and os.path.exists(valid_file):
            self.youtube_cookie_path = valid_file
            self.ydl_opts["cookiefile"] = valid_file
            self.fast_yt_opts["cookiefile"] = valid_file
            cookie_count = sum(1 for line in sanitized.splitlines() if line and not line.startswith("#"))
            logger.info(f"YouTube cookies successfully configured from: {valid_file} ({cookie_count} cookies)")
        else:
            logger.warning("Could not persist sanitized cookies file to disk!")

    def update_cookies(self, content_or_b64: str) -> Tuple[bool, str, int]:
        sanitized = self._sanitize_cookie_text(content_or_b64)
        if not sanitized:
            return False, "Неверный формат cookies", 0
        app_cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
        try:
            with open(app_cookie_path, "w", encoding="utf-8") as f:
                f.write(sanitized)
            self.youtube_cookie_path = app_cookie_path
            self.ydl_opts["cookiefile"] = app_cookie_path
            self.fast_yt_opts["cookiefile"] = app_cookie_path
            count = sum(1 for l in sanitized.splitlines() if l and not l.startswith("#"))
            return True, app_cookie_path, count
        except Exception as e:
            return False, str(e), 0

    @staticmethod
    def _rank_and_filter_tracks(tracks: List[Track], original_query: str) -> List[Track]:
        if not tracks:
            return []

        q_lower = original_query.lower().strip()
        q_words = set(re.findall(r'[\w]+', q_lower))

        # Words that indicate interviews, podcasts, reactions, or 10-hour spam
        PENALTY_WORDS = {
            "интервью", "interview", "реакция", "reaction", "подкаст", "podcast",
            "разбор", "обзор", "тизер", "teaser", "трейлер", "trailer",
            "документальный", "слив", "1 hour", "10 hours", "1 час", "10 часов",
            "10hour", "1hour", "loop", "караоке", "karaoke", "минус", "instrumental"
        }
        active_penalties = [w for w in PENALTY_WORDS if w not in q_lower]

        scored_tracks = []
        for t in tracks:
            score = 100
            title_lower = (t.title or "").lower()
            artist_lower = (t.artist or "").lower()
            combined = f"{title_lower} {artist_lower}"

            # 1. Heavy penalty for non-music/interview/reaction videos
            for pw in active_penalties:
                if pw in combined:
                    score -= 80

            # 2. Duration check: standard musical tracks are 60s - 480s (1:00 - 8:00)
            dur = t.duration or 0
            if 70 <= dur <= 450:
                score += 25
            elif 450 < dur <= 600:
                score += 10
            elif 0 < dur < 45:
                score -= 60  # Short ringtone / snippet / meme sound
            elif dur > 700:
                score -= 60  # Long interview / full discography / 1-hour loop unless query asked for it

            # 3. Official Music & Release quality boost
            if "- topic" in artist_lower or "topic" in artist_lower:
                score += 45  # Official YouTube Music release channel
            if any(k in combined for k in ["official audio", "official music video", "official video", "vevo", "official visualizer", "премьера трека"]):
                score += 30
            if "remix" in combined and "remix" not in q_lower:
                score -= 15  # Prefer original track over fan remixes

            # 4. Relevance: match user query words
            matched_words = sum(1 for w in q_words if w in combined)
            score += matched_words * 15

            # 5. YouTube over SoundCloud by default for consistency and stability
            if t.source == "youtube":
                score += 15

            scored_tracks.append((score, t))

        scored_tracks.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored_tracks]

    async def search(self, query: str, source: str = "all", limit: int = 10) -> List[Track]:
        query = query.strip()
        if not query:
            return []

        # Check if query is a direct URL
        if query.startswith("http://") or query.startswith("https://"):
            return await self._resolve_direct_url(query)

        source = source.lower()
        tasks = []
        fetch_limit = max(limit, 8)

        if source == "yt_albums":
            tasks.append(self._search_youtube_albums(query, limit=fetch_limit))
        elif source == "youtube":
            tasks.append(self._search_youtube(query, limit=fetch_limit))
        elif source == "soundcloud":
            tasks.append(self._search_soundcloud(query, limit=fetch_limit))
        else:
            tasks.append(self._search_youtube(query, limit=fetch_limit))
            tasks.append(self._search_soundcloud(query, limit=max(4, limit // 2)))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_tracks: List[Track] = []
        for res in results:
            if isinstance(res, list):
                all_tracks.extend(res)
            elif isinstance(res, Exception):
                logger.warning(f"Error during search: {res}")

        ranked = self._rank_and_filter_tracks(all_tracks, query)
        return ranked[:limit] if ranked else all_tracks[:limit]

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

            clean_q = query.strip()
            queries = [f"ytsearch{limit}:{clean_q}"]
            # If query looks like a short artist name (1-3 words), also query official audio to guarantee finding their top tracks
            q_words = clean_q.split()
            if len(q_words) <= 3 and not any(w in clean_q.lower() for w in ["audio", "music", "song", "песня", "трек", "клип", "remix", "album"]):
                queries.append(f"ytsearch{min(limit, 6)}:{clean_q} official audio")

            tracks = []
            seen_ids = set()
            with yt_dlp.YoutubeDL(opts) as ydl:
                for sq in queries:
                    try:
                        info = ydl.extract_info(sq, download=False)
                        if info and "entries" in info:
                            for entry in info["entries"]:
                                if entry:
                                    eid = str(entry.get("id") or "")
                                    if eid and eid not in seen_ids:
                                        seen_ids.add(eid)
                                        t = self._parse_flat_entry(entry, default_source="youtube")
                                        tracks.append(t)
                    except Exception as ex:
                        logger.warning(f"Error querying {sq}: {ex}")

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

    def invalidate_stream_cache(self, track: Track):
        """Invalidates cached audio stream URL for a given track."""
        cache_key = track.id or track.url
        if cache_key:
            self._stream_cache.pop(cache_key, None)
        track.stream_url = None

    async def get_stream_url(self, track: Track, force_refresh: bool = False) -> Optional[str]:
        """Resolves the direct playable audio stream URL for a Track, with in-memory TTL caching."""
        cache_key = track.id or track.url
        now = time.time()
        if not force_refresh and cache_key and cache_key in self._stream_cache:
            cached_url, expire_at = self._stream_cache[cache_key]
            if now < expire_at:
                return cached_url
            else:
                self._stream_cache.pop(cache_key, None)

        if track.source == "soundcloud" or (track.url and "soundcloud.com" in track.url) or (track.id and track.id.startswith("soundcloud_")):
            stream = await self._get_soundcloud_stream(track)
        else:
            stream = await self._get_youtube_stream(track)

        if stream and cache_key:
            # URLs are typically valid for 6h+, cache for 2.5h (9000s)
            self._stream_cache[cache_key] = (stream, now + 9000)
            if len(self._stream_cache) > 300:
                self._stream_cache = {k: v for k, v in self._stream_cache.items() if v[1] > now}

        return stream

    async def _get_soundcloud_stream(self, track: Track) -> Optional[str]:
        def _get():
            target_url = track.url
            if not target_url or not target_url.startswith("http"):
                target_url = track.raw_info.get("webpage_url") or track.raw_info.get("url")
            if not target_url or not str(target_url).startswith("http"):
                if track.id and "_" in track.id and track.id.split("_", 1)[1].isdigit():
                    target_url = f"https://api.soundcloud.com/tracks/soundcloud%3Atracks%3A{track.id.split('_', 1)[1]}"
                else:
                    target_url = None

            sc_opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "noplaylist": True,
                "ignoreerrors": True,
                "source_address": "0.0.0.0",
            }

            if target_url:
                try:
                    with yt_dlp.YoutubeDL(sc_opts) as ydl:
                        info = ydl.extract_info(target_url, download=False)
                        if info and not track.duration and info.get("duration"):
                            track.duration = int(info["duration"])
                            track.duration_str = format_duration(track.duration)
                        stream = self._extract_audio_stream_url(info)
                        if stream:
                            return stream
                except Exception as e:
                    logger.warning(f"Direct SoundCloud extraction failed for {target_url}: {e}")

            # Fallback search on SoundCloud with multi-result check
            try:
                clean_title = re.sub(r'[\U00010000-\U0010ffff]', '', track.title)
                clean_title = re.sub(r'#\w+', '', clean_title)
                clean_title = re.sub(r'\|.*', '', clean_title)
                clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', clean_title).strip()
                clean_artist = track.artist if track.artist and track.artist != "Неизвестный автор" else ""
                search_q = f"scsearch5:{clean_title} {clean_artist}".strip()
                with yt_dlp.YoutubeDL(sc_opts) as ydl:
                    info = ydl.extract_info(search_q, download=False)
                    stream = self._extract_audio_stream_url(info)
                    if stream:
                        return stream
            except Exception as e2:
                logger.error(f"SoundCloud fallback search failed: {e2}")

            return None

        return await asyncio.to_thread(_get)

    def _extract_audio_stream_url(self, info: Optional[Dict[str, Any]]) -> Optional[str]:
        """Extracts the direct playable audio stream URL from yt-dlp info dictionary."""
        if not info:
            return None

        if "entries" in info and info["entries"]:
            for entry in info["entries"]:
                url = self._extract_audio_stream_url(entry)
                if url:
                    return url
            return None

        # 1. Top-level url (ensure it is a media stream, not a YouTube watch page)
        url = info.get("url")
        if url and not info.get("has_drm"):
            str_url = str(url)
            if not str_url.startswith("https://www.youtube.com/watch") and not str_url.startswith("https://youtu.be/"):
                return str_url

        # 2. requested_formats selected by yt-dlp format selector
        for f in info.get("requested_formats") or []:
            f_url = f.get("url")
            if f_url and not f.get("has_drm"):
                acodec = f.get("acodec")
                vcodec = f.get("vcodec")
                if acodec and acodec != "none" and (vcodec is None or vcodec == "none"):
                    return str(f_url)
        for f in info.get("requested_formats") or []:
            f_url = f.get("url")
            if f_url and not f.get("has_drm") and f.get("acodec") != "none":
                return str(f_url)

        # 3. formats list, prefer highest quality audio-only
        formats = info.get("formats") or []
        audio_only = []
        audio_video = []

        for f in formats:
            f_url = f.get("url")
            if not f_url or f.get("has_drm"):
                continue
            acodec = f.get("acodec")
            vcodec = f.get("vcodec")
            if acodec and acodec != "none":
                bitrate = f.get("abr") or f.get("tbr") or 0
                if vcodec in (None, "none", ""):
                    audio_only.append((bitrate, str(f_url)))
                else:
                    audio_video.append((bitrate, str(f_url)))

        if audio_only:
            audio_only.sort(key=lambda x: x[0], reverse=True)
            return audio_only[0][1]

        if audio_video:
            audio_video.sort(key=lambda x: x[0], reverse=True)
            return audio_video[0][1]

        # 4. Fallback to any valid format with a url
        for f in reversed(formats):
            if f.get("url") and not f.get("has_drm"):
                return str(f["url"])

        return None

    async def _get_youtube_stream(self, track: Track) -> Optional[str]:
        def _get():
            target_url = track.url
            if not target_url or not target_url.startswith("http"):
                if track.id and "_" in track.id:
                    vid_id = track.id.split("_", 1)[1]
                    target_url = f"https://www.youtube.com/watch?v={vid_id}"
                else:
                    target_url = f"ytsearch1:{track.title} {track.artist}"

            cookie_file = self.youtube_cookie_path if (self.youtube_cookie_path and os.path.exists(self.youtube_cookie_path)) else None

            # Strategy 1: High-performance yt-dlp client configuration prioritizing direct Opus/WebM audio
            base_opts = {
                "format": "ba[acodec^=opus]/ba[ext=webm]/ba[ext=m4a]/ba*/b*/bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "noplaylist": True,
                "skip_download": True,
                "check_formats": False,
                "youtube_include_dash_manifest": False,
                "youtube_include_hls_manifest": False,
                "lazy_playlist": True,
                "source_address": "0.0.0.0",
            }
            if cookie_file:
                base_opts["cookiefile"] = cookie_file

            try:
                with yt_dlp.YoutubeDL(base_opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    if info and not track.duration and info.get("duration"):
                        track.duration = int(info["duration"])
                        track.duration_str = format_duration(track.duration)
                    stream = self._extract_audio_stream_url(info)
                    if stream:
                        logger.info(f"Resolved YouTube stream (standard) for: {track.title}")
                        return stream
            except Exception as e_base:
                logger.debug(f"Standard YouTube extraction failed for {track.title}: {e_base}")

            # Strategy 2: Alternate player clients to bypass datacenter/bot verification
            client_fallbacks = [
                ["web", "default"],
                ["ios", "web"],
                ["web_embedded", "tv_embedded"],
            ]
            for clients in client_fallbacks:
                try:
                    alt_opts = dict(base_opts)
                    alt_opts["extractor_args"] = {
                        "youtube": {
                            "player_client": clients,
                        }
                    }
                    with yt_dlp.YoutubeDL(alt_opts) as ydl:
                        info = ydl.extract_info(target_url, download=False)
                        if info and not track.duration and info.get("duration"):
                            track.duration = int(info["duration"])
                            track.duration_str = format_duration(track.duration)
                        stream = self._extract_audio_stream_url(info)
                        if stream:
                            logger.info(f"Resolved YouTube stream with clients {clients} for: {track.title}")
                            return stream
                except Exception as e_client:
                    logger.debug(f"YouTube client {clients} failed: {e_client}")
                    continue

            # Strategy 3: Search alternative YouTube uploads if direct video URL is restricted
            clean_title = re.sub(r'[\U00010000-\U0010ffff]', '', track.title)
            clean_title = re.sub(r'#\w+', '', clean_title)
            clean_title = re.sub(r'\|.*', '', clean_title)
            clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', clean_title).strip()
            clean_artist = track.artist if track.artist and track.artist != "Неизвестный автор" else ""
            search_query = f"{clean_title} {clean_artist}".strip() or track.title

            try:
                search_opts = dict(base_opts)
                search_opts["ignoreerrors"] = True
                with yt_dlp.YoutubeDL(search_opts) as ydl:
                    alt_info = ydl.extract_info(f"ytsearch3:{search_query}", download=False)
                    stream = self._extract_audio_stream_url(alt_info)
                    if stream:
                        logger.info(f"Resolved alternative YouTube stream for: {track.title}")
                        return stream
            except Exception as alt_err:
                logger.debug(f"Alternative YouTube search failed: {alt_err}")

            # Strategy 4: SoundCloud fallback search
            logger.warning(f"All YouTube stream extraction attempts failed for '{track.title}', attempting SoundCloud fallback...")
            try:
                sc_opts = {
                    "format": "bestaudio/best",
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": False,
                    "noplaylist": True,
                    "ignoreerrors": True,
                    "source_address": "0.0.0.0",
                }
                with yt_dlp.YoutubeDL(sc_opts) as ydl:
                    sc_info = ydl.extract_info(f"scsearch5:{search_query}", download=False)
                    stream = self._extract_audio_stream_url(sc_info)
                    if stream:
                        logger.info(f"Resolved SoundCloud fallback stream for: {track.title}")
                        return stream
            except Exception as sc_err:
                logger.error(f"SoundCloud fallback search failed: {sc_err}")

            return None

        return await asyncio.to_thread(_get)
