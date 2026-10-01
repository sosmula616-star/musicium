"""
Player Manager
Handles per-guild Discord audio playback, queues, volume, state, and position tracking.
"""

import os
import time
import shutil
import asyncio
from collections import deque
from typing import Optional, Dict, Any, List
import discord

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 32M",
    "options": "-vn -b:a 192k",
}


def find_ffmpeg_executable() -> str:
    """Find system ffmpeg or fallback to imageio_ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            exe_dir = os.path.dirname(exe)
            curr_path = os.environ.get("PATH", "")
            if exe_dir not in curr_path:
                os.environ["PATH"] = exe_dir + os.pathsep + curr_path
            return exe
    except Exception as e:
        print(f"[FFmpeg] imageio_ffmpeg resolution note: {e}")
    return "ffmpeg"


class GuildPlayer:
    """Manages audio playback and queue for a specific Discord Guild."""

    def __init__(self, guild_id: int, text_channel: Optional[discord.TextChannel], bot: discord.Client):
        self.guild_id = guild_id
        self.text_channel = text_channel
        self.bot = bot

        self.voice_client: Optional[discord.VoiceClient] = None
        self.queue: deque[Dict[str, Any]] = deque()
        self.history: deque[Dict[str, Any]] = deque(maxlen=40)
        self.current_track: Optional[Dict[str, Any]] = None

        self.volume: float = 0.5
        self.loop_mode: str = "none"  # "none", "track", "queue"
        self.is_paused: bool = False

        self._play_lock = asyncio.Lock()
        self._skip_flag = False

        # Elapsed time calculation
        self._start_playback_time: Optional[float] = None
        self._paused_at: Optional[float] = None
        self._total_paused_duration: float = 0.0
        self._seek_offset: float = 0.0

    @property
    def elapsed_seconds(self) -> int:
        """Calculate elapsed seconds of the current track."""
        if not self.current_track or not self._start_playback_time:
            return 0
        now = time.monotonic()
        if self.is_paused and self._paused_at:
            active_duration = self._paused_at - self._start_playback_time - self._total_paused_duration
        else:
            active_duration = now - self._start_playback_time - self._total_paused_duration

        elapsed = int(max(0, active_duration + self._seek_offset))
        duration = self.current_track.get("duration", 0)
        if duration and duration > 0:
            return min(elapsed, duration)
        return elapsed

    async def connect(self, channel: discord.VoiceChannel):
        """Connect or move to the specified voice channel."""
        if self.voice_client:
            if self.voice_client.is_connected():
                if self.voice_client.channel.id != channel.id:
                    await self.voice_client.move_to(channel)
                return
            else:
                try:
                    await self.voice_client.disconnect(force=True)
                except Exception:
                    pass
                self.voice_client = None

        self.voice_client = await channel.connect(reconnect=True, timeout=25.0)
        print(f"[Player] Connected to voice channel '{channel.name}' (Guild: {self.guild_id})")

    async def add_to_queue(self, track: Dict[str, Any], requester: Optional[discord.Member] = None):
        """Add a track to queue and start playing if currently idle."""
        track_item = dict(track)
        if requester:
            track_item["requester"] = requester.display_name
        elif "requester" not in track_item:
            track_item["requester"] = "Web Player"

        self.queue.append(track_item)
        if not self.is_playing():
            await self._play_next()

    async def _play_next(self, seek_seconds: float = 0.0):
        """Advance queue and start audio stream."""
        async with self._play_lock:
            if seek_seconds > 0.0 and self.current_track:
                # Seek in current track
                track = self.current_track
            else:
                if self.current_track and not self._skip_flag:
                    self.history.append(self.current_track)

                if self.loop_mode == "track" and self.current_track and not self._skip_flag:
                    track = self.current_track
                elif self.queue:
                    track = self.queue.popleft()
                    if self.loop_mode == "queue" and self.current_track and not self._skip_flag:
                        self.queue.append(self.current_track)
                else:
                    self.current_track = None
                    self.is_paused = False
                    self._start_playback_time = None
                    self._seek_offset = 0.0
                    return

                self.current_track = track
                self.is_paused = False
                self._skip_flag = False

            self._seek_offset = seek_seconds
            self._start_playback_time = time.monotonic()
            self._paused_at = None
            self._total_paused_duration = 0.0

        # Resolve stream URL if not cached
        stream_url = track.get("stream_url")
        if not stream_url:
            from music_search import MusicSearchEngine
            engine = MusicSearchEngine()
            stream_url = await engine.get_stream_url(track)
            track["stream_url"] = stream_url

        if not stream_url:
            title = track.get("title", "Unknown")
            print(f"[Player] Stream unavailable for '{title}'")
            if self.text_channel:
                asyncio.create_task(self.text_channel.send(f"❌ Не удалось воспроизвести: **{title}**"))
            asyncio.create_task(self._play_next())
            return

        try:
            ffmpeg_exe = find_ffmpeg_executable()
            opts = dict(FFMPEG_OPTIONS)
            if seek_seconds > 0:
                opts["before_options"] = f"-ss {int(seek_seconds)} " + opts["before_options"]

            audio_src = discord.FFmpegPCMAudio(stream_url, executable=ffmpeg_exe, **opts)
            volume_src = discord.PCMVolumeTransformer(audio_src, volume=self.volume)

            def _after_callback(err):
                if err and not self._skip_flag:
                    print(f"[Player] Playback error: {err}")
                asyncio.run_coroutine_threadsafe(self._play_next(), self.bot.loop)

            if self.voice_client and self.voice_client.is_connected():
                if self.voice_client.is_playing() or self.voice_client.is_paused():
                    self.voice_client.stop()
                self.voice_client.play(volume_src, after=_after_callback)
                print(f"[Player] Playing: {track.get('title')} ({track.get('platform')})")
            else:
                print(f"[Player] Voice client not connected for guild {self.guild_id}")
        except Exception as e:
            print(f"[Player] Failed to start audio playback: {e}")
            asyncio.create_task(self._play_next())

    def is_playing(self) -> bool:
        """Check if audio source is playing or paused."""
        return (
            self.voice_client is not None
            and self.voice_client.is_connected()
            and (self.voice_client.is_playing() or self.voice_client.is_paused())
        )

    async def skip(self):
        """Skip to next track."""
        self._skip_flag = True
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        else:
            await self._play_next()

    async def prev(self) -> bool:
        """Return to previous track from history."""
        if not self.history:
            return False
        prev_track = self.history.pop()
        if self.current_track:
            self.queue.appendleft(self.current_track)
        self.queue.appendleft(prev_track)
        self._skip_flag = True
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        else:
            await self._play_next()
        return True

    async def stop(self):
        """Stop playback and clear active queue."""
        self._skip_flag = True
        self.queue.clear()
        self.current_track = None
        self.is_paused = False
        self._start_playback_time = None
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()

    async def pause(self):
        """Pause current playback."""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.is_paused = True
            self._paused_at = time.monotonic()

    async def resume(self):
        """Resume current playback or start next."""
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            self.is_paused = False
            if self._paused_at:
                self._total_paused_duration += time.monotonic() - self._paused_at
                self._paused_at = None
        elif not self.is_playing() and (self.queue or self.current_track):
            await self._play_next()

    async def seek(self, seconds: float):
        """Seek to a position in current track."""
        if not self.current_track:
            return
        await self._play_next(seek_seconds=max(0.0, seconds))

    def set_volume(self, volume: float):
        """Set volume level (0.0 to 2.0)."""
        self.volume = max(0.0, min(2.0, volume))
        if self.voice_client and self.voice_client.source:
            if hasattr(self.voice_client.source, "volume"):
                self.voice_client.source.volume = self.volume

    def get_state(self) -> Dict[str, Any]:
        """Serialize state for Web and API consumers."""
        queue_items = []
        for t in list(self.queue)[:50]:
            queue_items.append({
                "id": str(t.get("id", "")),
                "title": t.get("title", ""),
                "artist": t.get("artist", ""),
                "duration": t.get("duration", 0),
                "duration_str": t.get("duration_str", ""),
                "thumbnail": t.get("thumbnail", ""),
                "platform": t.get("platform", ""),
                "platform_icon": t.get("platform_icon", ""),
                "platform_color": t.get("platform_color", "#8b5cf6"),
                "requester": t.get("requester", ""),
                "url": t.get("url", ""),
            })

        curr = None
        if self.current_track:
            curr = {
                "id": str(self.current_track.get("id", "")),
                "title": self.current_track.get("title", ""),
                "artist": self.current_track.get("artist", ""),
                "duration": self.current_track.get("duration", 0),
                "duration_str": self.current_track.get("duration_str", ""),
                "thumbnail": self.current_track.get("thumbnail", ""),
                "platform": self.current_track.get("platform", ""),
                "platform_icon": self.current_track.get("platform_icon", ""),
                "platform_color": self.current_track.get("platform_color", "#8b5cf6"),
                "requester": self.current_track.get("requester", ""),
                "url": self.current_track.get("url", ""),
            }

        return {
            "playing": self.is_playing() and not self.is_paused,
            "paused": self.is_paused,
            "volume": self.volume,
            "loop_mode": self.loop_mode,
            "elapsed": self.elapsed_seconds,
            "current": curr,
            "queue": queue_items,
            "queue_count": len(self.queue),
            "history_count": len(self.history),
        }


class PlayerManager:
    """Manages GuildPlayer instances for all connected Discord guilds."""

    def __init__(self, bot: discord.Client):
        self.bot = bot
        self._players: Dict[int, GuildPlayer] = {}

    def get_player(self, guild_id: int) -> Optional[GuildPlayer]:
        return self._players.get(guild_id)

    def get_or_create(self, guild_id: int, text_channel: Optional[discord.TextChannel] = None) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer(guild_id, text_channel, self.bot)
        elif text_channel and not self._players[guild_id].text_channel:
            self._players[guild_id].text_channel = text_channel
        return self._players[guild_id]

    def remove_player(self, guild_id: int):
        self._players.pop(guild_id, None)

    def get_all_states(self) -> Dict[str, Any]:
        return {str(gid): p.get_state() for gid, p in self._players.items()}
