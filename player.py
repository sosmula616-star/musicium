import os
import sys
import time
import math
import random
import shutil
import asyncio
import logging
from typing import Optional, List, Set, Dict, Any, Callable
import discord
import static_ffmpeg

from music_service import Track, MusicService, format_duration

logger = logging.getLogger("player")

def find_ffmpeg() -> str:
    # 1. On Linux, prefer system ffmpeg if available
    if sys.platform != "win32":
        for p in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg"]:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                logger.info(f"Using system ffmpeg from: {p}")
                return p

    # 2. Try static_ffmpeg initialization
    try:
        static_ffmpeg.add_paths()
        try:
            from static_ffmpeg import run
            run.check_or_set_filtered_ffmpeg_ffmpeg_download()
        except Exception:
            pass
    except Exception:
        pass

    # 3. Check shutil.which but verify it is a real file on disk
    w = shutil.which("ffmpeg")
    if w and os.path.isfile(w):
        return w

    # 4. Check Linux system paths again
    if sys.platform != "win32":
        if os.path.isfile("/usr/bin/ffmpeg"):
            return "/usr/bin/ffmpeg"

    return "ffmpeg"

FFMPEG_EXECUTABLE = find_ffmpeg()

# Ensure Opus is loaded for Discord voice streaming
def ensure_opus_loaded():
    if not discord.opus.is_loaded():
        if sys.platform == "win32":
            for path in [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "opus.dll"),
                os.path.join(os.path.dirname(discord.__file__), "bin", "libopus-0.x64.dll"),
                "opus.dll",
                "libopus-0.dll"
            ]:
                if os.path.exists(path):
                    try:
                        discord.opus.load_opus(path)
                        logger.info(f"Loaded Opus voice encoder from: {path}")
                        break
                    except Exception as e:
                        logger.warning(f"Could not load opus from {path}: {e}")
        else:
            for path in [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "libopus.so.0"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "libopus.so"),
                "libopus.so.0",
                "libopus.so",
                "/usr/lib/libopus.so.0",
                "/usr/lib/libopus.so",
                "/usr/lib/x86_64-linux-gnu/libopus.so.0"
            ]:
                if os.path.exists(path):
                    try:
                        discord.opus.load_opus(path)
                        logger.info(f"Loaded Opus voice encoder from: {path}")
                        return
                    except Exception as e:
                        logger.warning(f"Could not load opus from {path}: {e}")

            import ctypes.util
            lib = ctypes.util.find_library("opus")
            if lib:
                try:
                    discord.opus.load_opus(lib)
                    logger.info(f"Loaded Opus voice encoder via find_library: {lib}")
                    return
                except Exception as e:
                    logger.warning(f"Could not load opus from find_library ({lib}): {e}")

ensure_opus_loaded()

FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"

class GuildPlayer:
    def __init__(self, guild: discord.Guild, bot: discord.Client, music_service: MusicService, on_change_callback: Optional[Callable] = None):
        self.guild = guild
        self.bot = bot
        self.music_service = music_service
        self.on_change_callback = on_change_callback

        self.voice_client: Optional[discord.VoiceClient] = None
        self.current_track: Optional[Track] = None
        self.queue: List[Track] = []
        self.history: List[Track] = []

        self.volume: float = 1.0  # 0.0 to 2.0
        self.is_paused: bool = False
        self.loop_mode: str = "off"  # "off", "track", "queue"

        self.vote_skips: Set[int] = set()

        self.start_time: float = 0.0
        self.pause_start_time: float = 0.0
        self.total_paused_duration: float = 0.0

        self.audio_source: Optional[discord.PCMVolumeTransformer] = None
        self._is_seeking: bool = False
        self._lock = asyncio.Lock()

    @property
    def is_playing(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_playing())

    @property
    def is_connected(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_connected())

    def get_elapsed_seconds(self) -> int:
        if not self.current_track or self.start_time == 0:
            return 0
        if self.is_paused and self.pause_start_time > 0:
            current_pause = time.time() - self.pause_start_time
            elapsed = self.pause_start_time - self.start_time - self.total_paused_duration
        else:
            elapsed = time.time() - self.start_time - self.total_paused_duration
        return max(0, int(elapsed))

    def get_non_bot_listeners(self) -> List[discord.Member]:
        if not self.voice_client or not self.voice_client.channel:
            return []
        return [m for m in self.voice_client.channel.members if not m.bot]

    def get_required_votes(self) -> int:
        listeners = self.get_non_bot_listeners()
        count = len(listeners)
        if count <= 1:
            return 1
        return math.ceil(count / 2)  # Strict majority (e.g. 2 of 3, 2 of 2, 3 of 4)

    async def connect_to_channel(self, channel: discord.VoiceChannel):
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel.id != channel.id:
                await self.voice_client.move_to(channel)
        else:
            self.voice_client = await channel.connect(timeout=20.0, reconnect=True, self_deaf=True, self_mute=False)

    async def enqueue(self, track: Track, play_now: bool = False) -> Dict[str, Any]:
        async with self._lock:
            if play_now:
                # Insert at beginning
                self.queue.insert(0, track)
                if self.is_playing or self.is_paused:
                    await self.skip(forced=True)
                    return {"action": "playing_now", "track": track.to_dict()}
            else:
                self.queue.append(track)

            if not self.current_track and not self.is_playing:
                await self._play_next()
                return {"action": "started", "track": track.to_dict()}
            else:
                await self._notify_change()
                return {"action": "queued", "position": len(self.queue), "track": track.to_dict()}

    async def _play_next(self):
        if not self.queue:
            self.current_track = None
            self.vote_skips.clear()
            self.start_time = 0
            self.pause_start_time = 0
            self.total_paused_duration = 0
            await self._notify_change()
            return

        next_track = self.queue.pop(0)
        await self._start_track(next_track)

    async def _start_track(self, track: Track):
        if not self.voice_client or not self.voice_client.is_connected():
            logger.warning("Voice client is not connected when starting track.")
            return

        try:
            # Resolve stream URL if not already present
            stream_url = track.stream_url
            if not stream_url:
                stream_url = await self.music_service.get_stream_url(track)
                track.stream_url = stream_url

            if not stream_url:
                logger.error(f"Failed to resolve stream URL for track: {track.title}")
                # Try next track
                await self._play_next()
                return

            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()

            # Create audio source
            ffmpeg_opts = {
                "before_options": FFMPEG_BEFORE_OPTIONS,
                "options": FFMPEG_OPTIONS,
            }
            exec_bin = FFMPEG_EXECUTABLE
            if not os.path.isfile(exec_bin):
                if sys.platform != "win32" and os.path.isfile("/usr/bin/ffmpeg"):
                    exec_bin = "/usr/bin/ffmpeg"
                elif sys.platform != "win32" and os.path.isfile("/usr/local/bin/ffmpeg"):
                    exec_bin = "/usr/local/bin/ffmpeg"
                else:
                    exec_bin = "ffmpeg"

            audio = discord.FFmpegPCMAudio(
                stream_url,
                executable=exec_bin,
                **ffmpeg_opts
            )
            self.audio_source = discord.PCMVolumeTransformer(audio, volume=self.volume)

            self.current_track = track
            self.vote_skips.clear()
            self.is_paused = False
            self.start_time = time.time()
            self.pause_start_time = 0.0
            self.total_paused_duration = 0.0

            def _after_play(err):
                if self._is_seeking:
                    return
                if err:
                    logger.error(f"Playback error: {err}")
                coro = self._on_track_finished()
                asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

            self.voice_client.play(self.audio_source, after=_after_play)
            logger.info(f"Started playing: {track.title} in {self.guild.name}")

            await self._notify_change(track_started=True)

        except Exception as e:
            logger.error(f"Error starting track {track.title}: {e}", exc_info=True)
            await self._play_next()

    async def _on_track_finished(self):
        async with self._lock:
            if not self.current_track:
                return

            # Add to history
            self.history.insert(0, self.current_track)
            if len(self.history) > 25:
                self.history.pop()

            finished_track = self.current_track

            # Handle repeat modes
            if self.loop_mode == "track":
                # Replay same track
                await self._start_track(finished_track)
                return
            elif self.loop_mode == "queue":
                # Add to back of queue
                self.queue.append(finished_track)

            await self._play_next()

    async def pause(self) -> bool:
        if self.voice_client and self.voice_client.is_playing() and not self.is_paused:
            self.voice_client.pause()
            self.is_paused = True
            self.pause_start_time = time.time()
            await self._notify_change()
            return True
        return False

    async def resume(self) -> bool:
        if self.voice_client and self.voice_client.is_paused() and self.is_paused:
            self.voice_client.resume()
            self.is_paused = False
            if self.pause_start_time > 0:
                self.total_paused_duration += time.time() - self.pause_start_time
                self.pause_start_time = 0.0
            await self._notify_change()
            return True
        return False

    async def toggle_play_pause(self) -> bool:
        if self.is_paused:
            await self.resume()
            return False
        else:
            await self.pause()
            return True

    async def skip(self, forced: bool = False, user_id: Optional[int] = None) -> Dict[str, Any]:
        if not self.current_track:
            return {"skipped": False, "message": "Сейчас ничего не играет"}

        listeners = self.get_non_bot_listeners()
        required_votes = self.get_required_votes()

        # If requester or admin or forced or alone in channel -> instant skip
        is_requester = user_id and (self.current_track.requester_id == user_id)
        is_solo = len(listeners) <= 1

        if forced or is_requester or is_solo or user_id is None:
            self.vote_skips.clear()
            if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
                self.voice_client.stop()
            else:
                await self._play_next()
            return {
                "skipped": True,
                "forced": True,
                "message": "Трек пропущен!",
                "votes": 0,
                "required": required_votes,
            }

        # Otherwise add vote
        self.vote_skips.add(user_id)
        current_votes = len(self.vote_skips)

        if current_votes >= required_votes:
            self.vote_skips.clear()
            if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
                self.voice_client.stop()
            else:
                await self._play_next()
            return {
                "skipped": True,
                "forced": False,
                "message": f"Голосование завершено ({current_votes}/{required_votes}). Трек пропущен!",
                "votes": current_votes,
                "required": required_votes,
            }
        else:
            await self._notify_change()
            return {
                "skipped": False,
                "forced": False,
                "message": f"Ваш голос учтён! ({current_votes}/{required_votes})",
                "votes": current_votes,
                "required": required_votes,
            }

    async def seek(self, seconds: int) -> bool:
        async with self._lock:
            if not self.current_track or not self.voice_client or not self.voice_client.is_connected():
                return False

            duration = self.current_track.duration or 0
            seconds = max(0, min(seconds, duration - 1 if duration > 0 else seconds))

            stream_url = self.current_track.stream_url
            if not stream_url:
                stream_url = await self.music_service.get_stream_url(self.current_track)
                self.current_track.stream_url = stream_url

            if not stream_url:
                return False

            self._is_seeking = True
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()

            seek_before = f"{FFMPEG_BEFORE_OPTIONS} -ss {seconds}"
            ffmpeg_opts = {
                "before_options": seek_before,
                "options": FFMPEG_OPTIONS,
            }
            exec_bin = FFMPEG_EXECUTABLE
            if not os.path.isfile(exec_bin):
                if sys.platform != "win32" and os.path.isfile("/usr/bin/ffmpeg"):
                    exec_bin = "/usr/bin/ffmpeg"
                elif sys.platform != "win32" and os.path.isfile("/usr/local/bin/ffmpeg"):
                    exec_bin = "/usr/local/bin/ffmpeg"
                else:
                    exec_bin = "ffmpeg"

            audio = discord.FFmpegPCMAudio(
                stream_url,
                executable=exec_bin,
                **ffmpeg_opts
            )
            self.audio_source = discord.PCMVolumeTransformer(audio, volume=self.volume)

            self.is_paused = False
            self.start_time = time.time() - seconds
            self.pause_start_time = 0.0
            self.total_paused_duration = 0.0

            def _after_play(err):
                if self._is_seeking:
                    return
                if err:
                    logger.error(f"Playback error after seek: {err}")
                coro = self._on_track_finished()
                asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

            self.voice_client.play(self.audio_source, after=_after_play)
            self._is_seeking = False
            logger.info(f"Seeked to {seconds}s in track: {self.current_track.title}")
            await self._notify_change()
            return True

    async def stop(self):
        async with self._lock:
            self.queue.clear()
            self.current_track = None
            self.vote_skips.clear()
            if self.voice_client:
                if self.voice_client.is_playing() or self.voice_client.is_paused():
                    self.voice_client.stop()
                await self.voice_client.disconnect(force=True)
                self.voice_client = None
            await self._notify_change()

    def set_volume(self, volume: float) -> float:
        self.volume = max(0.0, min(2.0, volume))
        if self.audio_source:
            self.audio_source.volume = self.volume
        asyncio.create_task(self._notify_change())
        return self.volume

    def set_loop_mode(self, mode: str) -> str:
        if mode in ("off", "track", "queue"):
            self.loop_mode = mode
        else:
            # Cycle through modes
            modes = ["off", "track", "queue"]
            idx = modes.index(self.loop_mode) if self.loop_mode in modes else 0
            self.loop_mode = modes[(idx + 1) % len(modes)]
        asyncio.create_task(self._notify_change())
        return self.loop_mode

    def shuffle_queue(self) -> int:
        random.shuffle(self.queue)
        asyncio.create_task(self._notify_change())
        return len(self.queue)

    def remove_from_queue(self, index: int) -> Optional[Track]:
        if 0 <= index < len(self.queue):
            removed = self.queue.pop(index)
            asyncio.create_task(self._notify_change())
            return removed
        return None

    def clear_queue(self):
        self.queue.clear()
        asyncio.create_task(self._notify_change())

    def get_state(self) -> Dict[str, Any]:
        listeners = self.get_non_bot_listeners()
        channel_name = self.voice_client.channel.name if self.voice_client and self.voice_client.channel else None
        channel_id = str(self.voice_client.channel.id) if self.voice_client and self.voice_client.channel else None

        return {
            "guild_id": str(self.guild.id),
            "guild_name": self.guild.name,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "is_connected": self.is_connected,
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "volume": int(self.volume * 100),
            "loop_mode": self.loop_mode,
            "current_track": self.current_track.to_dict() if self.current_track else None,
            "elapsed_seconds": self.get_elapsed_seconds(),
            "queue": [t.to_dict() for t in self.queue],
            "history": [t.to_dict() for t in self.history[:10]],
            "votes": {
                "count": len(self.vote_skips),
                "required": self.get_required_votes(),
                "users": [str(uid) for uid in self.vote_skips],
            },
            "listeners_count": len(listeners),
        }

    async def _notify_change(self, track_started: bool = False):
        if self.on_change_callback:
            try:
                res = self.on_change_callback(self, track_started=track_started)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error(f"Error in on_change_callback: {e}")
