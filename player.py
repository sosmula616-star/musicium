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

FFMPEG_BEFORE_OPTIONS = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
    "-probesize 65536 -analyzeduration 0 "
    '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"'
)
FFMPEG_OPTIONS = "-vn"

class GuildPlayer:
    def __init__(self, guild: discord.Guild, bot: discord.Client, music_service: MusicService, on_change_callback: Optional[Callable] = None):
        self.guild = guild
        self.bot = bot
        self.music_service = music_service
        self.on_change_callback = on_change_callback

        self._voice_client: Optional[discord.VoiceClient] = getattr(guild, 'voice_client', None)
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
        self._play_generation: int = 0
        self._consecutive_failures: int = 0
        self._retried_current: bool = False
        self._explicit_stop: bool = False
        self._lock = asyncio.Lock()

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        if self._voice_client and self._voice_client.is_connected():
            return self._voice_client
        guild_vc = getattr(self.guild, 'voice_client', None)
        if guild_vc and guild_vc.is_connected():
            self._voice_client = guild_vc
            return self._voice_client
        return self._voice_client if (self._voice_client and self._voice_client.is_connected()) else None

    @voice_client.setter
    def voice_client(self, vc: Optional[discord.VoiceClient]):
        self._voice_client = vc

    @property
    def is_playing(self) -> bool:
        vc = self.voice_client
        return bool(vc and vc.is_playing())

    @property
    def is_connected(self) -> bool:
        vc = self.voice_client
        return bool(vc and vc.is_connected())

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
        vc = self.voice_client
        if not vc or not vc.channel:
            return []
        return [m for m in vc.channel.members if not m.bot]

    def get_required_votes(self) -> int:
        listeners = self.get_non_bot_listeners()
        count = len(listeners)
        if count <= 1:
            return 1
        return max(1, math.ceil(count * 0.6))  # 60% of listeners in room (excluding bot)

    async def connect_to_channel(self, channel: discord.VoiceChannel):
        guild_vc = self.guild.voice_client
        if guild_vc and guild_vc.channel:
            if guild_vc.channel.id == channel.id:
                if guild_vc.is_connected():
                    self.voice_client = guild_vc
                    return
            else:
                if guild_vc.is_connected():
                    raise RuntimeError(f"Бот уже находится в канале «{guild_vc.channel.name}». Перемещение бота по серверу запрещено!")

        if self.voice_client and self.voice_client.channel:
            if self.voice_client.channel.id == channel.id:
                if self.voice_client.is_connected():
                    return
            else:
                if self.voice_client.is_connected():
                    raise RuntimeError(f"Бот уже находится в канале «{self.voice_client.channel.name}». Перемещение бота по серверу запрещено!")

        if guild_vc:
            try:
                await guild_vc.disconnect(force=True)
                await asyncio.sleep(0.4)
            except Exception as e:
                logger.warning(f"Error disconnecting stale voice client in guild {self.guild.id}: {e}")

        last_err = None
        for attempt in range(1, 3):
            try:
                self.voice_client = await channel.connect(timeout=15.0, reconnect=True, self_deaf=True, self_mute=False)
                return
            except (asyncio.TimeoutError, TimeoutError) as te:
                last_err = te
                logger.warning(f"Voice connection to {channel.name} timed out (attempt {attempt}/2). Cleaning up and retrying...")
                g_vc = self.guild.voice_client
                if g_vc:
                    try:
                        await g_vc.disconnect(force=True)
                    except Exception:
                        pass
                await asyncio.sleep(0.8)
            except discord.ClientException as ce:
                logger.warning(f"ClientException connecting to {channel.id}: {ce}. Attempting to use existing guild.voice_client...")
                g_vc = self.guild.voice_client
                if g_vc and g_vc.is_connected() and g_vc.channel:
                    self.voice_client = g_vc
                    if self.voice_client.channel.id != channel.id:
                        raise RuntimeError(f"Бот уже находится в канале «{self.voice_client.channel.name}». Перемещение бота по серверу запрещено!")
                    return
                else:
                    raise
        if last_err:
            raise last_err

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
                # Prefetch stream for the next track in background so it starts instantly
                asyncio.create_task(self._prefetch_next())
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

            self._play_generation += 1
            current_gen = self._play_generation

            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()
                for _ in range(25):
                    if not self.voice_client.is_playing() and not self.voice_client.is_paused():
                        break
                    await asyncio.sleep(0.02)

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

            self._explicit_stop = False

            def _after_play(err):
                if current_gen != self._play_generation:
                    return
                elapsed = (time.time() - self.start_time) if self.start_time > 0 else 0
                is_failed = bool(err) or (elapsed < 3.0)

                if err:
                    logger.error(f"Playback error in {self.guild.name}: {err}")
                coro = self._handle_track_finished_or_failed(is_failed=is_failed, track=track)
                asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

            for _ in range(10):
                try:
                    self.voice_client.play(self.audio_source, after=_after_play)
                    break
                except discord.ClientException as ce:
                    if "Already playing" in str(ce):
                        await asyncio.sleep(0.03)
                    else:
                        raise

            logger.info(f"Started playing: {track.title} in {self.guild.name}")
            try:
                import db
                uid = str(track.requester_id) if track.requester_id else "bot_user"
                asyncio.create_task(db.add_user_history(uid, track.to_dict()))
            except Exception as e_hist:
                logger.debug(f"History logging failed: {e_hist}")

            await self._notify_change(track_started=True)
            # Preload the next track's stream in background
            asyncio.create_task(self._prefetch_next())

        except Exception as e:
            logger.error(f"Error starting track {track.title}: {e}", exc_info=True)
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                logger.error(f"Stopping playback in {self.guild.name}: 3 consecutive track start errors.")
                self.current_track = None
                self.queue.clear()
                self._consecutive_failures = 0
                await self._notify_change()
                return
            await self._play_next()

    async def _handle_track_finished_or_failed(self, is_failed: bool, track: Track):
        async with self._lock:
            if not self.current_track:
                return

            if is_failed:
                logger.warning(f"Track '{track.title}' finished prematurely (<3s) or errored.")
                # Attempt 1 fresh retry with invalidated cache
                if not self._retried_current:
                    self._retried_current = True
                    logger.info(f"Retrying '{track.title}' with freshly resolved stream URL...")
                    self.music_service.invalidate_stream_cache(track)
                    new_stream = await self.music_service.get_stream_url(track, force_refresh=True)
                    if new_stream:
                        track.stream_url = new_stream
                        await self._start_track(track)
                        return

                self._consecutive_failures += 1
                if self._consecutive_failures >= 3:
                    logger.error(f"Stopping playback loop in {self.guild.name}: 3 consecutive stream failures.")
                    self.current_track = None
                    self.queue.clear()
                    self._consecutive_failures = 0
                    self._retried_current = False
                    if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
                        self.voice_client.stop()
                    await self._notify_change()
                    return
            else:
                self._consecutive_failures = 0
                self._retried_current = False

                # Add to history
                self.history.insert(0, track)
                if len(self.history) > 25:
                    self.history.pop()

                # Handle repeat modes
                if self.loop_mode == "track":
                    await self._start_track(track)
                    return
                elif self.loop_mode == "queue":
                    self.queue.append(track)

            self._retried_current = False
            await self._play_next()

    async def _prefetch_next(self):
        """Pre-resolves stream URL for the upcoming track in queue to eliminate gap/latency."""
        try:
            if self.queue:
                next_t = self.queue[0]
                if not next_t.stream_url:
                    stream = await self.music_service.get_stream_url(next_t)
                    if stream:
                        next_t.stream_url = stream
                        logger.debug(f"Prefetched stream URL for: {next_t.title}")
        except Exception as e:
            logger.debug(f"Prefetch error: {e}")

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
            self._play_generation += 1
            self.vote_skips.clear()
            if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
                self.voice_client.stop()
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
            self._play_generation += 1
            self.vote_skips.clear()
            if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
                self.voice_client.stop()
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

            self._play_generation += 1
            current_gen = self._play_generation

            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()
                for _ in range(25):
                    if not self.voice_client.is_playing() and not self.voice_client.is_paused():
                        break
                    await asyncio.sleep(0.02)

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
                if current_gen != self._play_generation:
                    return
                elapsed = (time.time() - self.start_time) if self.start_time > 0 else 0
                is_failed = bool(err) or (elapsed < 3.0)

                if err:
                    logger.error(f"Playback error after seek: {err}")
                coro = self._handle_track_finished_or_failed(is_failed=is_failed, track=self.current_track)
                asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

            for _ in range(10):
                try:
                    self.voice_client.play(self.audio_source, after=_after_play)
                    break
                except discord.ClientException as ce:
                    if "Already playing" in str(ce):
                        await asyncio.sleep(0.03)
                    else:
                        raise

            logger.info(f"Seeked to {seconds}s in track: {self.current_track.title}")
            await self._notify_change()
            return True

    async def stop(self):
        async with self._lock:
            self._explicit_stop = True
            self.queue.clear()
            self.current_track = None
            self.vote_skips.clear()
            if self.voice_client:
                if self.voice_client.is_playing() or self.voice_client.is_paused():
                    self.voice_client.stop()
                await self.voice_client.disconnect(force=True)
                self.voice_client = None
            await self._notify_change()

    async def reconnect_and_resume(self, channel: discord.VoiceChannel):
        """Attempts to reconnect to the voice channel after an unexpected drop and resume playback."""
        for attempt in range(1, 4):
            try:
                await asyncio.sleep(2.0 * attempt)
                if self._explicit_stop or not self.current_track:
                    return
                logger.info(f"Reconnecting to voice channel '{channel.name}' (attempt {attempt}/3)...")
                await self.connect_to_channel(channel)
                if self.voice_client and self.voice_client.is_connected():
                    elapsed = self.get_elapsed_seconds()
                    logger.info(f"Resuming track '{self.current_track.title}' at {elapsed}s...")
                    await self.seek(max(0, elapsed - 1))
                    return
            except Exception as e:
                logger.warning(f"Reconnect attempt {attempt} failed: {e}")

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
        vc = self.voice_client
        listeners = self.get_non_bot_listeners()
        channel_name = vc.channel.name if vc and vc.channel else None
        channel_id = str(vc.channel.id) if vc and vc.channel else None

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
