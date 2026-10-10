import os
import re
import time
import json
import base64
import asyncio
import logging
import urllib.parse
from typing import List, Optional, Dict, Any, Tuple, Set
import yt_dlp
import db

logger = logging.getLogger("music_service")

# Default placeholders
DEFAULT_THUMBNAIL = "/static/activity_icon.jpg"
STREAMING_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "streaming_settings.json")

def clean_youtube_url(url: str) -> str:
    """
    Cleans YouTube / YouTube Music URLs: strips radio/mix params (&list=RD..., &index=, &si=)
    which cause yt-dlp to hang or play random mix tracks.
    Preserves standalone playlists (/playlist?list=...).
    """
    if not url:
        return ""
    url = url.strip().strip("<>").strip('"').strip("'")
    if url.startswith("youtu.be/") or url.startswith("youtube.com/") or url.startswith("music.youtube.com/"):
        url = "https://" + url

    # Short youtu.be/<id>
    m_short = re.match(r'https?://(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})', url)
    if m_short:
        return f"https://www.youtube.com/watch?v={m_short.group(1)}"

    if "youtube.com" in url or "music.youtube.com" in url:
        try:
            parsed = urllib.parse.urlparse(url)
            # Standalone playlist (no video id)
            if "/playlist" in parsed.path and "v=" not in parsed.query:
                qs = urllib.parse.parse_qs(parsed.query)
                list_id = qs.get("list", [""])[0]
                if list_id:
                    return f"https://www.youtube.com/playlist?list={list_id}"
                return url

            qs = urllib.parse.parse_qs(parsed.query)
            v_id = qs.get("v", [""])[0]
            if v_id and len(v_id) == 11:
                return f"https://www.youtube.com/watch?v={v_id}"
        except Exception:
            pass
    return url

def is_title_similar(original: Optional[str], candidate: Optional[str]) -> bool:
    """Verifies that an alternative track or fallback search candidate actually matches the requested track title."""
    if not original or not candidate:
        return False
    def get_words(s: str) -> Set[str]:
        cleaned = re.sub(r'\[.*?\]|\(.*?\)|ft\.?|feat\.?|official|video|audio|remix|hd|hq|4k|lyric|lyrics', '', s, flags=re.IGNORECASE)
        words = re.findall(r'[\w]+', cleaned.lower())
        return {w for w in words if len(w) >= 2}

    orig_words = get_words(original)
    cand_words = get_words(candidate)
    if not orig_words:
        return True
    overlap = len(orig_words & cand_words)
    if overlap >= 2:
        return True
    if len(orig_words) == 1:
        return overlap >= 1
    return (overlap / len(orig_words)) >= 0.4


def format_duration(seconds: Optional[int]) -> str:
    if not seconds or seconds <= 0:
        return "00:00"
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
        self.ydl_opts: Dict[str, Any] = {
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

        # Multi-client Innertube extractor options for stream resolution (Android / iOS / Embedded / VR)
        # Avoids JavaScript n-sig decryption and bot challenges; resolves direct audio in ~0.3-0.8s
        self.fast_yt_opts: Dict[str, Any] = {
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
            "socket_timeout": 4,
            "retries": 1,
            "fragment_retries": 1,
            "source_address": "0.0.0.0",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "web_embedded", "android_vr"],
                    "player_skip": ["configs", "webpage"],
                }
            }
        }

        # Optional Proxy configuration (YTDLP_PROXY / HTTP_PROXY)
        proxy_url = os.getenv("YTDLP_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
        if proxy_url:
            self.ydl_opts["proxy"] = proxy_url
            self.fast_yt_opts["proxy"] = proxy_url
            logger.info(f"Configured yt-dlp proxy: {proxy_url}")

        # Optional PO Token / POT provider URL (e.g. http://127.0.0.1:4416 via bgutil Docker)
        pot_url = os.getenv("POT_PROVIDER_URL", "http://127.0.0.1:4416")
        po_token = os.getenv("YT_PO_TOKEN")
        if po_token:
            self.fast_yt_opts["extractor_args"]["youtube"]["po_token"] = [po_token]
        elif pot_url:
            self.fast_yt_opts["extractor_args"]["youtube"]["po_token_server"] = [pot_url]

        # Cache for resolved audio stream URLs: {key: (stream_url, expire_timestamp)}
        self._stream_cache: Dict[str, Tuple[str, float]] = {}

        # Streaming & Cookies Mode configuration
        self.streaming_settings: Dict[str, Any] = {
            "mode": "cookieless",  # "cookieless" | "youtube_cookies" | "soundcloud_first"
            "proxy": "",
            "pot_provider_url": "http://127.0.0.1:4416",
            "pot_token": ""
        }
        self._sc_trending_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}
        self.youtube_cookie_path: Optional[str] = None
        self._load_streaming_settings()

        use_cookies = os.getenv("USE_COOKIES", "true").lower() not in ("false", "0", "no")
        if use_cookies and self.streaming_settings.get("mode") == "youtube_cookies":
            self._load_and_sanitize_cookies()
        else:
            logger.info(f"MusicService running in mode: {self.streaming_settings.get('mode', 'cookieless')}")

    def _load_streaming_settings(self):
        try:
            if os.path.exists(STREAMING_SETTINGS_FILE):
                with open(STREAMING_SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.streaming_settings.update(data)
                        logger.info(f"Loaded streaming settings from disk: {self.streaming_settings}")
        except Exception as e:
            logger.warning(f"Could not load streaming settings from disk: {e}")
        self._apply_streaming_settings()

    def _save_streaming_settings(self):
        try:
            with open(STREAMING_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.streaming_settings, f, ensure_ascii=False, indent=2)
            logger.info("Saved streaming settings to disk.")
        except Exception as e:
            logger.warning(f"Could not save streaming settings to disk: {e}")

    def _apply_streaming_settings(self):
        mode = self.streaming_settings.get("mode", "cookieless")
        proxy = self.streaming_settings.get("proxy", "").strip()
        pot_url = self.streaming_settings.get("pot_provider_url", "http://127.0.0.1:4416").strip()
        pot_token = self.streaming_settings.get("pot_token", "").strip()

        # Cookies handling based on mode
        if mode == "youtube_cookies":
            if not self.youtube_cookie_path or not os.path.exists(self.youtube_cookie_path):
                self._load_and_sanitize_cookies()
            if self.youtube_cookie_path and os.path.exists(self.youtube_cookie_path):
                self.ydl_opts["cookiefile"] = self.youtube_cookie_path
                self.fast_yt_opts["cookiefile"] = self.youtube_cookie_path
        else:
            self.ydl_opts.pop("cookiefile", None)
            self.fast_yt_opts.pop("cookiefile", None)

        # Proxy handling
        if proxy:
            self.ydl_opts["proxy"] = proxy
            self.fast_yt_opts["proxy"] = proxy
        else:
            env_proxy = os.getenv("YTDLP_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
            if env_proxy:
                self.ydl_opts["proxy"] = env_proxy
                self.fast_yt_opts["proxy"] = env_proxy
            else:
                self.ydl_opts.pop("proxy", None)
                self.fast_yt_opts.pop("proxy", None)

        # POT provider handling
        if pot_token:
            self.fast_yt_opts["extractor_args"]["youtube"]["po_token"] = [pot_token]
        elif pot_url:
            self.fast_yt_opts["extractor_args"]["youtube"]["po_token_server"] = [pot_url]

    async def ensure_streaming_settings_loaded(self):
        try:
            db_val = await db.get_bot_setting("streaming_settings")
            if db_val:
                data = json.loads(db_val)
                if isinstance(data, dict):
                    self.streaming_settings.update(data)
                    self._save_streaming_settings()
                    self._apply_streaming_settings()
            else:
                await db.set_bot_setting("streaming_settings", json.dumps(self.streaming_settings))
        except Exception as e:
            logger.debug(f"ensure_streaming_settings_loaded db check: {e}")

    def get_streaming_settings(self) -> Dict[str, Any]:
        return dict(self.streaming_settings)

    async def update_streaming_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        if "mode" in new_settings:
            mode = str(new_settings["mode"]).strip()
            if mode in ("cookieless", "youtube_cookies", "soundcloud_first"):
                self.streaming_settings["mode"] = mode
        if "proxy" in new_settings:
            self.streaming_settings["proxy"] = str(new_settings["proxy"]).strip()
        if "pot_provider_url" in new_settings:
            self.streaming_settings["pot_provider_url"] = str(new_settings["pot_provider_url"]).strip()
        if "pot_token" in new_settings:
            self.streaming_settings["pot_token"] = str(new_settings["pot_token"]).strip()

        self._save_streaming_settings()
        self._apply_streaming_settings()
        try:
            await db.set_bot_setting("streaming_settings", json.dumps(self.streaming_settings))
        except Exception as e:
            logger.warning(f"Could not persist streaming settings to DB: {e}")
        return dict(self.streaming_settings)

    def clear_cookies(self) -> Tuple[bool, str]:
        app_cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
        try:
            if os.path.exists(app_cookie_path):
                os.remove(app_cookie_path)
        except Exception as e:
            logger.warning(f"Failed to remove cookies file {app_cookie_path}: {e}")

        self.youtube_cookie_path = None
        self.ydl_opts.pop("cookiefile", None)
        self.fast_yt_opts.pop("cookiefile", None)
        self.streaming_settings["mode"] = "cookieless"
        self._save_streaming_settings()
        try:
            asyncio.create_task(db.set_bot_setting("streaming_settings", json.dumps(self.streaming_settings)))
        except Exception:
            pass
        return True, "Cookies успешно удалены, активирован режим Cookieless"

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
            self.streaming_settings["mode"] = "youtube_cookies"
            self._save_streaming_settings()
            try:
                asyncio.create_task(db.set_bot_setting("streaming_settings", json.dumps(self.streaming_settings)))
            except Exception:
                pass
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
        final_tracks = ranked[:limit] if ranked else all_tracks[:limit]

        # Background stream cache pre-warming: resolve top result so playback starts instantly (0s wait)
        if final_tracks:
            asyncio.create_task(self._safe_preload_stream(final_tracks[0]))
            if len(final_tracks) > 1:
                asyncio.create_task(self._safe_preload_stream(final_tracks[1]))

        return final_tracks

    async def _safe_preload_stream(self, track: Track):
        """Silently pre-resolves stream in background to warm in-memory cache."""
        try:
            if track and not track.stream_url:
                await self.get_stream_url(track)
        except Exception:
            pass

    async def _resolve_direct_url(self, url: str) -> List[Track]:
        cleaned = clean_youtube_url(url)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._extract_url_info, cleaned)

    def _extract_url_info(self, raw_url: str) -> List[Track]:
        url = clean_youtube_url(raw_url)
        is_playlist = ("/playlist" in url or "/sets/" in url)
        is_single_yt = (not is_playlist) and ("youtube.com" in url or "youtu.be" in url)

        # Single YouTube / YouTube Music track: resolve metadata AND direct audio stream in ONE fast shot (~1.2s)
        opts = dict(self.fast_yt_opts if is_single_yt else self.ydl_opts)
        cookie_file = None
        if self.streaming_settings.get("mode") == "youtube_cookies":
            cookie_file = self.youtube_cookie_path if (self.youtube_cookie_path and os.path.exists(self.youtube_cookie_path)) else None
        if cookie_file:
            opts["cookiefile"] = cookie_file
        else:
            opts.pop("cookiefile", None)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return []
                if "entries" in info:
                    tracks = []
                    entries = list(info.get("entries") or [])
                    for entry in entries[:50]:
                        if entry:
                            tracks.append(self._parse_flat_entry(entry, default_source="youtube"))
                    return tracks

                track = self._parse_ytdlp_entry(info)
                # If stream URL was extracted in this single request, store and cache it immediately
                stream = self._extract_audio_stream_url(info)
                if stream:
                    track.stream_url = stream
                    cache_key = track.id or track.url
                    if cache_key:
                        self._stream_cache[cache_key] = (stream, time.time() + 9000)
                return [track]
        except Exception as e:
            logger.error(f"Error extracting url info ({url}): {e}")
            return []

    def _parse_ytdlp_entry(self, entry: Any, default_source: str = "youtube") -> Track:
        webpage_url = entry.get("webpage_url") or entry.get("url") or ""
        extractor = (entry.get("extractor") or entry.get("extractor_key") or "").lower()

        source = "youtube"
        if "soundcloud" in extractor or "soundcloud.com" in webpage_url:
            source = "soundcloud"

        title = entry.get("title") or "Неизвестный трек"
        artist = entry.get("uploader") or entry.get("channel") or entry.get("artist") or "Неизвестный автор"
        duration = int(entry.get("duration") or 0)
        vid_id = str(entry.get("id") or "")
        # Extract best thumbnail from entry
        tb = None
        if entry.get("thumbnail") and isinstance(entry["thumbnail"], str) and entry["thumbnail"].startswith("http"):
            tb = entry["thumbnail"]
        elif entry.get("artwork_url") and isinstance(entry["artwork_url"], str) and entry["artwork_url"].startswith("http"):
            tb = entry["artwork_url"]

        if (not tb or "hqdefault" in tb) and entry.get("thumbnails") and isinstance(entry["thumbnails"], list):
            valid_tbs = [x.get("url") for x in entry["thumbnails"] if isinstance(x, dict) and x.get("url") and str(x.get("url")).startswith("http")]
            if valid_tbs:
                tb = valid_tbs[-1]

        if not tb:
            if entry.get("user") and isinstance(entry["user"], dict):
                tb = entry["user"].get("avatar_url")
            elif entry.get("uploader_avatar"):
                tb = entry["uploader_avatar"]

        if not tb and source == "youtube" and vid_id and len(vid_id) == 11 and not vid_id.startswith(("OLAK", "PL", "RD", "alb_", "MPRE")):
            tb = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

        if tb and isinstance(tb, str):
            if "sndcdn.com" in tb and "/artworks-" in tb:
                if "-large." in tb:
                    tb = tb.replace("-large.", "-t500x500.")
                elif "-badge." in tb:
                    tb = tb.replace("-badge.", "-t500x500.")

        thumbnail = tb or DEFAULT_THUMBNAIL
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

    def _parse_flat_entry(self, entry: Any, default_source: str = "youtube") -> Track:
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
        
        # Extract best thumbnail from entry
        tb = None
        if entry.get("thumbnail") and isinstance(entry["thumbnail"], str) and entry["thumbnail"].startswith("http"):
            tb = entry["thumbnail"]
        elif entry.get("artwork_url") and isinstance(entry["artwork_url"], str) and entry["artwork_url"].startswith("http"):
            tb = entry["artwork_url"]

        if (not tb or "hqdefault" in tb) and entry.get("thumbnails") and isinstance(entry["thumbnails"], list):
            valid_tbs = [x.get("url") for x in entry["thumbnails"] if isinstance(x, dict) and x.get("url") and str(x.get("url")).startswith("http")]
            if valid_tbs:
                tb = valid_tbs[-1]

        if not tb:
            if entry.get("user") and isinstance(entry["user"], dict):
                tb = entry["user"].get("avatar_url")
            elif entry.get("uploader_avatar"):
                tb = entry["uploader_avatar"]

        if not tb and source == "youtube" and entry_id and len(entry_id) == 11 and not entry_id.startswith(("OLAK", "PL", "RD", "alb_", "MPRE")):
            tb = f"https://i.ytimg.com/vi/{entry_id}/hqdefault.jpg"

        if tb and isinstance(tb, str):
            if "sndcdn.com" in tb and "/artworks-" in tb:
                if "-large." in tb:
                    tb = tb.replace("-large.", "-t500x500.")
                elif "-badge." in tb:
                    tb = tb.replace("-badge.", "-t500x500.")

        thumbnail = tb or DEFAULT_THUMBNAIL

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
            opts["socket_timeout"] = 4
            opts["retries"] = 1

            clean_q = query.strip()
            sq = f"ytsearch{limit}:{clean_q}"
            tracks = []
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(sq, download=False)
                    if info and "entries" in info:
                        for entry in info["entries"]:
                            if entry:
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

        if self.streaming_settings.get("mode") == "soundcloud_first":
            stream = await self._get_soundcloud_stream(track)
            if not stream:
                stream = await self._get_youtube_stream(track)
        elif track.source == "soundcloud" or (track.url and "soundcloud.com" in track.url) or (track.id and track.id.startswith("soundcloud_")):
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

            # Fallback search on SoundCloud with multi-result similarity check
            try:
                clean_title = re.sub(r'[\U00010000-\U0010ffff]', '', track.title)
                clean_title = re.sub(r'#\w+', '', clean_title)
                clean_title = re.sub(r'\|.*', '', clean_title)
                clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', clean_title).strip()
                clean_artist = track.artist if track.artist and track.artist != "Неизвестный автор" else ""
                search_q = f"scsearch5:{clean_title} {clean_artist}".strip()
                with yt_dlp.YoutubeDL(sc_opts) as ydl:
                    info = ydl.extract_info(search_q, download=False)
                    if info and "entries" in info:
                        entries = list(info.get("entries") or [])
                        for entry in entries:
                            if entry and is_title_similar(track.title, entry.get("title", "")):
                                stream = self._extract_audio_stream_url(entry)
                                if stream:
                                    logger.info(f"Resolved verified SoundCloud fallback stream for: {track.title} -> {entry.get('title')}")
                                    return stream
                    elif info and is_title_similar(track.title, info.get("title", "")):
                        stream = self._extract_audio_stream_url(info)
                        if stream:
                            return stream
            except Exception as e2:
                logger.error(f"SoundCloud fallback search failed: {e2}")

            return None

        return await asyncio.to_thread(_get)

    def _extract_audio_stream_url(self, info: Any) -> Optional[str]:
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
            target_url = clean_youtube_url(track.url)
            if not target_url or not target_url.startswith("http"):
                if track.id and "_" in track.id:
                    vid_id = track.id.split("_", 1)[1]
                    target_url = f"https://www.youtube.com/watch?v={vid_id}"
                else:
                    target_url = f"ytsearch1:{track.title} {track.artist}"

            cookie_file = None
            if self.streaming_settings.get("mode") == "youtube_cookies":
                cookie_file = self.youtube_cookie_path if (self.youtube_cookie_path and os.path.exists(self.youtube_cookie_path)) else None

            # Strategy 1 (MAX SPEED): Direct Innertube Android Client
            # Completely bypasses JavaScript n-sig decryption and downloads in ~1.0-1.5s
            fast_opts = dict(self.fast_yt_opts)
            if cookie_file:
                fast_opts["cookiefile"] = cookie_file
            else:
                fast_opts.pop("cookiefile", None)

            t0 = time.time()
            try:
                with yt_dlp.YoutubeDL(fast_opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    if info and not track.duration and info.get("duration"):
                        track.duration = int(info["duration"])
                        track.duration_str = format_duration(track.duration)
                    stream = self._extract_audio_stream_url(info)
                    if stream:
                        elapsed = time.time() - t0
                        logger.info(f"Resolved YouTube stream (Ultra-Fast Innertube, {elapsed:.2f}s) for: {track.title}")
                        return stream
            except Exception as e_fast:
                logger.debug(f"Ultra-fast Innertube extraction failed for {track.title}: {e_fast}")

            # Strategy 2: iOS / Web Embedded client fallback with flexible format and 3.0s timeout
            try:
                alt_opts = dict(fast_opts)
                alt_opts["format"] = "ba/b/bestaudio/best"
                alt_opts["socket_timeout"] = 3.0
                alt_opts["extractor_args"] = {
                    "youtube": {
                        "player_client": ["ios", "web_embedded"],
                    }
                }
                with yt_dlp.YoutubeDL(alt_opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    stream = self._extract_audio_stream_url(info)
                    if stream:
                        logger.info(f"Resolved YouTube stream (iOS fallback) for: {track.title}")
                        return stream
            except Exception as e_alt:
                logger.debug(f"iOS fallback failed for {track.title}: {e_alt}")

            # Strategy 3: Alternative YouTube upload search with 3.5s timeout
            clean_title = re.sub(r'[\U00010000-\U0010ffff]', '', track.title)
            clean_title = re.sub(r'#\w+', '', clean_title)
            clean_title = re.sub(r'\|.*', '', clean_title)
            clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', clean_title).strip()
            clean_artist = track.artist if track.artist and track.artist != "Неизвестный автор" else ""
            search_query = f"{clean_title} {clean_artist}".strip() or track.title

            try:
                search_opts = dict(fast_opts)
                search_opts["socket_timeout"] = 3.5
                with yt_dlp.YoutubeDL(search_opts) as ydl:
                    alt_info = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                    entries = list(alt_info.get("entries") or []) if alt_info else []
                    cand_title = ""
                    if entries:
                        cand_title = entries[0].get("title", "")
                    elif alt_info:
                        cand_title = alt_info.get("title", "")

                    if not cand_title or not is_title_similar(track.title, cand_title):
                        logger.warning(f"Rejecting alternative YouTube stream '{cand_title}' because it does not match '{track.title}'")
                    else:
                        stream = self._extract_audio_stream_url(alt_info)
                        if stream:
                            logger.info(f"Resolved verified alternative YouTube stream for: {track.title}")
                            return stream
            except Exception as alt_err:
                logger.debug(f"Alternative YouTube search failed: {alt_err}")

            # Strategy 4: SoundCloud fallback search with 3s timeout
            logger.warning(f"All YouTube extraction attempts failed for '{track.title}', attempting SoundCloud fallback...")
            try:
                sc_opts: Dict[str, Any] = {
                    "format": "bestaudio/best",
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": False,
                    "noplaylist": True,
                    "ignoreerrors": True,
                    "socket_timeout": 3.0,
                    "retries": 1,
                    "source_address": "0.0.0.0",
                }
                with yt_dlp.YoutubeDL(sc_opts) as ydl:
                    sc_info = ydl.extract_info(f"scsearch1:{search_query}", download=False)
                    entries = list(sc_info.get("entries") or []) if sc_info else []
                    cand_title = ""
                    if entries:
                        cand_title = entries[0].get("title", "")
                    elif sc_info:
                        cand_title = sc_info.get("title", "")

                    if not cand_title or not is_title_similar(track.title, cand_title):
                        logger.warning(f"Rejecting fallback SoundCloud stream '{cand_title}' because it does not match '{track.title}'")
                    else:
                        stream = self._extract_audio_stream_url(sc_info)
                        if stream:
                            logger.info(f"Resolved verified SoundCloud fallback stream for: {track.title}")
                            return stream
            except Exception as sc_err:
                logger.error(f"SoundCloud fallback search failed: {sc_err}")

            return None

        return await asyncio.to_thread(_get)

    async def get_soundcloud_trending(self, genre: str = "all", limit: int = 15, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Dynamically fetches trending / recommended tracks from SoundCloud by genre,
        with 30-minute in-memory caching and rich curated fallback catalog.
        """
        genre_key = (genre or "all").lower().strip()
        now = time.time()

        GENRE_QUERIES = {
            "all": "trending hot edm electronic hits 2024 2025",
            "electronic": "electronic dance music edm festival anthem",
            "hiphop": "hip hop rap trap drill trending",
            "house": "tech house deep house club vibes",
            "dnb": "drum and bass dnb rave jungle phonk",
            "chill": "lo-fi chill beats ambient chillhop",
        }
        query = GENRE_QUERIES.get(genre_key, GENRE_QUERIES["all"])

        # Check in-memory 30-min cache
        if genre_key in self._sc_trending_cache:
            cached_tracks, expire_at = self._sc_trending_cache[genre_key]
            if now < expire_at and len(cached_tracks) > 0:
                return cached_tracks[offset : offset + limit]

        # Fetch up to 50 tracks from SoundCloud via scsearch
        fetch_limit = 50
        search_query = f"scsearch{fetch_limit}:{query}"

        loop = asyncio.get_event_loop()
        def _fetch():
            try:
                opts = dict(self.ydl_opts)
                opts["extract_flat"] = True
                opts["socket_timeout"] = 5.0
                opts["retries"] = 1
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(search_query, download=False)
                    if not info or "entries" not in info:
                        return []
                    entries = list(info.get("entries") or [])
                    res = []
                    for idx, entry in enumerate(entries):
                        if not entry:
                            continue
                        e_id = entry.get("id") or str(idx + 1)
                        title = entry.get("title") or "SoundCloud Track"
                        uploader = entry.get("uploader") or entry.get("channel") or "SoundCloud Artist"
                        dur = int(entry.get("duration") or 210)
                        thumb = entry.get("thumbnail") or DEFAULT_THUMBNAIL
                        webpage = entry.get("url") or entry.get("webpage_url") or f"https://soundcloud.com/search?q={urllib.parse.quote(title)}"
                        views = entry.get("view_count")
                        plays_str = f"{round(views / 1_000_000, 1)}M" if views and views >= 1_000_000 else (f"{round(views / 1_000)}K" if views and views >= 1_000 else "Hot")
                        res.append({
                            "rank": idx + 1,
                            "id": f"soundcloud_{e_id}",
                            "title": title,
                            "artist": uploader,
                            "duration": dur,
                            "duration_str": format_duration(dur),
                            "thumbnail": thumb,
                            "source": "soundcloud",
                            "url": webpage,
                            "plays": plays_str,
                        })
                    return res
            except Exception as e:
                logger.warning(f"Error fetching SoundCloud trending for genre '{genre_key}': {e}")
                return []

        tracks = await loop.run_in_executor(None, _fetch)

        # Fallback to rich curated catalog if empty
        if not tracks:
            tracks = self._get_default_soundcloud_tracks(genre_key)

        self._sc_trending_cache[genre_key] = (tracks, now + 1800)  # 30 mins TTL
        return tracks[offset : offset + limit]

    @staticmethod
    def _get_default_soundcloud_tracks(genre: str = "all") -> List[Dict[str, Any]]:
        base_charts = [
            {"rank": 1, "id": "soundcloud_sc1", "title": "Rumble", "artist": "Skrillex, Fred again.. & Flowdan", "duration_str": "2:26", "duration": 146, "thumbnail": "https://i1.sndcdn.com/artworks-9V7b7jN0sEhy-0-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/skrillex/rumble", "plays": "42M"},
            {"rank": 2, "id": "soundcloud_sc2", "title": "leavemealone", "artist": "Fred again.. & Baby Keem", "duration_str": "3:43", "duration": 223, "thumbnail": "https://i1.sndcdn.com/artworks-sIe87uG23rI4-0-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/fredagain/leavemealone", "plays": "31M"},
            {"rank": 3, "id": "soundcloud_sc3", "title": "(It Goes Like) Nanana", "artist": "Peggy Gou", "duration_str": "3:51", "duration": 231, "thumbnail": "https://i1.sndcdn.com/artworks-PqG8U7s8H4mJ-0-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/peggygou/it-goes-like-nanana", "plays": "58M"},
            {"rank": 4, "id": "soundcloud_sc4", "title": "Where You Are", "artist": "John Summit & Hayla", "duration_str": "3:58", "duration": 238, "thumbnail": "https://i1.sndcdn.com/artworks-5z1sO5aFqH4g-0-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/johnsummit/where-you-are", "plays": "37M"},
            {"rank": 5, "id": "soundcloud_sc5", "title": "Rhyme Dust", "artist": "MK & Dom Dolla", "duration_str": "3:01", "duration": 181, "thumbnail": "https://i1.sndcdn.com/artworks-V02X4d0z3h4G-0-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/domdolla/rhyme-dust", "plays": "29M"},
            {"rank": 6, "id": "soundcloud_sc6", "title": "Baddadan", "artist": "Chase & Status, Bou ft. Trigga & Flowdan", "duration_str": "2:45", "duration": 165, "thumbnail": "https://i1.sndcdn.com/artworks-8J2xZ0c2N4kK-0-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/chaseandstatus/baddadan", "plays": "34M"},
            {"rank": 7, "id": "soundcloud_sc7", "title": "Bangarang", "artist": "Skrillex ft. Sirah", "duration_str": "3:35", "duration": 215, "thumbnail": "https://i1.sndcdn.com/artworks-000015949826-p24s0h-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/skrillex/bangarang-feat-sirah", "plays": "120M"},
            {"rank": 8, "id": "soundcloud_sc8", "title": "Alone", "artist": "Marshmello", "duration_str": "3:19", "duration": 199, "thumbnail": "https://i1.sndcdn.com/artworks-000164805728-66236b-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/marshmellomusic/marshmello-alone", "plays": "95M"},
            {"rank": 9, "id": "soundcloud_sc9", "title": "Faded", "artist": "Alan Walker", "duration_str": "3:32", "duration": 212, "thumbnail": "https://i1.sndcdn.com/artworks-000138246104-q1m5k5-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/alanwalker/faded", "plays": "88M"},
            {"rank": 10, "id": "soundcloud_sc10", "title": "Animals", "artist": "Martin Garrix", "duration_str": "2:56", "duration": 176, "thumbnail": "https://i1.sndcdn.com/artworks-000050868843-g4l0w7-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/martingarrix/martin-garrix-animals", "plays": "115M"},
            {"rank": 11, "id": "soundcloud_sc11", "title": "The Nights", "artist": "Avicii", "duration_str": "2:56", "duration": 176, "thumbnail": "https://i1.sndcdn.com/artworks-000100781702-86s0d8-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/aviciiofficial/the-nights", "plays": "110M"},
            {"rank": 12, "id": "soundcloud_sc12", "title": "Strobe", "artist": "deadmau5", "duration_str": "10:37", "duration": 637, "thumbnail": "https://i1.sndcdn.com/artworks-000030588647-h06h98-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/deadmau5/strobe", "plays": "46M"},
            {"rank": 13, "id": "soundcloud_sc13", "title": "Cinema (Skrillex Remix)", "artist": "Benny Benassi", "duration_str": "5:07", "duration": 307, "thumbnail": "https://i1.sndcdn.com/artworks-000007842606-d2qg5t-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/benny-benassi/cinema-skrillex-remix", "plays": "82M"},
            {"rank": 14, "id": "soundcloud_sc14", "title": "Levels", "artist": "Avicii", "duration_str": "3:19", "duration": 199, "thumbnail": "https://i1.sndcdn.com/artworks-000014760416-24k6m0-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/aviciiofficial/levels", "plays": "140M"},
            {"rank": 15, "id": "soundcloud_sc15", "title": "Titanium", "artist": "David Guetta ft. Sia", "duration_str": "4:05", "duration": 245, "thumbnail": "https://i1.sndcdn.com/artworks-000011504993-9qfdf8-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/davidguetta/titanium-feat-sia", "plays": "98M"},
            {"rank": 16, "id": "soundcloud_sc16", "title": "Clarity", "artist": "Zedd ft. Foxes", "duration_str": "4:31", "duration": 271, "thumbnail": "https://i1.sndcdn.com/artworks-000031853609-b4qg9u-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/zedd/clarity-feat-foxes", "plays": "76M"},
            {"rank": 17, "id": "soundcloud_sc17", "title": "Midnight City", "artist": "M83", "duration_str": "4:03", "duration": 243, "thumbnail": "https://i1.sndcdn.com/artworks-000010992381-80r176-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/m83/midnight-city", "plays": "64M"},
            {"rank": 18, "id": "soundcloud_sc18", "title": "Lean On", "artist": "Major Lazer & DJ Snake", "duration_str": "2:56", "duration": 176, "thumbnail": "https://i1.sndcdn.com/artworks-000108398460-7053r1-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/majorlazer/lean-on-feat-m", "plays": "135M"},
            {"rank": 19, "id": "soundcloud_sc19", "title": "One More Time", "artist": "Daft Punk", "duration_str": "5:20", "duration": 320, "thumbnail": "https://i1.sndcdn.com/artworks-000031804297-fghq4t-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/daft-punk/one-more-time", "plays": "89M"},
            {"rank": 20, "id": "soundcloud_sc20", "title": "Language", "artist": "Porter Robinson", "duration_str": "6:08", "duration": 368, "thumbnail": "https://i1.sndcdn.com/artworks-000021666498-84221a-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/porter-robinson/language", "plays": "41M"},
            {"rank": 21, "id": "soundcloud_sc21", "title": "Spectrum", "artist": "Zedd ft. Matthew Koma", "duration_str": "4:03", "duration": 243, "thumbnail": "https://i1.sndcdn.com/artworks-000025176161-q8fdf9-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/zedd/spectrum", "plays": "52M"},
            {"rank": 22, "id": "soundcloud_sc22", "title": "Wake Me Up", "artist": "Avicii", "duration_str": "4:09", "duration": 249, "thumbnail": "https://i1.sndcdn.com/artworks-000051833509-f8s0d8-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/aviciiofficial/wake-me-up", "plays": "165M"},
            {"rank": 23, "id": "soundcloud_sc23", "title": "First of the Year (Equinox)", "artist": "Skrillex", "duration_str": "4:22", "duration": 262, "thumbnail": "https://i1.sndcdn.com/artworks-000014277730-1qf2o1-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/skrillex/first-of-the-year-equinox", "plays": "73M"},
            {"rank": 24, "id": "soundcloud_sc24", "title": "Satisfaction", "artist": "Benny Benassi", "duration_str": "3:11", "duration": 191, "thumbnail": "https://i1.sndcdn.com/artworks-000008546102-k1e87u-t500x500.jpg", "source": "soundcloud", "url": "https://soundcloud.com/benny-benassi/satisfaction", "plays": "61M"}
        ]
        return base_charts
