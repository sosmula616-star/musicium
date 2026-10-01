"""
Player Manager
Handles audio playback, queue management, volume, loops, and voice states per guild.
"""

import os
import time
import random
import shutil
import asyncio
from collections import deque
from typing import Optional, Dict, Any, List
import discord

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 32M",
    "options": "-vn -b:a 192k",
}


def get_ffmpeg_binary() -> str:
    """Find ffmpeg from PATH or imageio_ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            exe_dir = os.path.dirname(exe)
            cur_path = os.environ.get("PATH", "")
            if exe_dir not in cur_path:
                os.environ["PATH"] = exe_dir + os.pathsep + cur_path
            return exe
    except Exception:
        pass
    return "ffmpeg"


class GuildPlayer:
    def __init__(self, guild_id: int, bot: discord.Client):
        self.guild_id = guild_id
        self.bot = bot

        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.TextChannel] = None
        self.queue: deque[Dict[str, Any]] = deque()
        self.history: deque[Dict[str, Any]] = deque(maxlen=30)
        self.current_track: Optional[Dict[str, Any]] = None

        self.volume: float = 0.5
        self.loop_mode: str = "none"  # "none", "track", "queue"
        self.is_paused: bool = False

        self._play_lock = asyncio.Lock()
        self._skip_flag = False

        # Elapsed tracking
        self._start_playback_time: Optional[float] = None
        self._paused_at: Optional[float] = None
        self._total_paused_duration: float = 0.0
        self._seek_offset: float = 0.0

    @property
    def elapsed_seconds(self) -> int:
        """Return elapsed playback time in seconds."""
        if not self.current_track or not self._start_playback_time:
            return 0
        now = time.monotonic()
        if self.is_paused and self._paused_at:
            active_duration = self._paused_at - self._start_playback_time - self._total_paused_duration
        else:
            active_duration = now - self._start_playback_time - self._total_paused_duration

        elapsed = int(max(0, active_duration + self._seek_offset))
        dur = self.current_track.get("duration", 0)
        if dur and dur > 0:
            return min(elapsed, dur)
        return elapsed

    async def connect(self, channel: discord.VoiceChannel):
        """Connect or move to voice channel."""
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

        self.voice_client = await channel.connect(reconnect=True, timeout=20.0)

    async def add_to_queue(self, track: Dict[str, Any], requester: Optional[discord.Member] = None):
        """Add track to queue and play if idle."""
        item = dict(track)
        if requester:
            item["requester"] = requester.display_name
        else:
            item["requester"] = "Discord User"

        self.queue.append(item)
        if not self.is_playing():
            await self._play_next()

    async def _play_next(self, seek_seconds: float = 0.0):
        """Play next track or repeat according to loop mode."""
        async with self._play_lock:
            if seek_seconds > 0.0 and self.current_track:
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

        # Get stream URL
        stream_url = track.get("stream_url")
        if not stream_url:
            from music_search import MusicSearchEngine
            search = MusicSearchEngine()
            stream_url = await search.get_stream_url(track)
            track["stream_url"] = stream_url

        if not stream_url:
            title = track.get("title", "Unknown")
            print(f"[Player] Failed to load stream for: {title}")
            if self.text_channel:
                asyncio.create_task(self.text_channel.send(f"❌ Не удалось воспроизвести: **{title}**"))
            asyncio.create_task(self._play_next())
            return

        try:
            ffmpeg_exe = get_ffmpeg_binary()
            opts = dict(FFMPEG_OPTS)
            if seek_seconds > 0:
                opts["before_options"] = f"-ss {int(seek_seconds)} " + opts["before_options"]

            src = discord.FFmpegPCMAudio(stream_url, executable=ffmpeg_exe, **opts)
            volume_src = discord.PCMVolumeTransformer(src, volume=self.volume)

            def _after_play(err):
                if err and not self._skip_flag:
                    print(f"[Player] Audio error: {err}")
                asyncio.run_coroutine_threadsafe(self._play_next(), self.bot.loop)

            if self.voice_client and self.voice_client.is_connected():
                if self.voice_client.is_playing() or self.voice_client.is_paused():
                    self.voice_client.stop()
                self.voice_client.play(volume_src, after=_after_play)
                print(f"[Player] Playing: {track.get('title')} ({track.get('platform')})")
        except Exception as e:
            print(f"[Player] Playback error: {e}")
            asyncio.create_task(self._play_next())

    def is_playing(self) -> bool:
        return (
            self.voice_client is not None
            and self.voice_client.is_connected()
            and (self.voice_client.is_playing() or self.voice_client.is_paused())
        )

    async def skip(self):
        """Skip current track."""
        self._skip_flag = True
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        else:
            await self._play_next()

    async def pause(self):
        """Pause playback."""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.is_paused = True
            self._paused_at = time.monotonic()

    async def resume(self):
        """Resume playback."""
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            self.is_paused = False
            if self._paused_at:
                self._total_paused_duration += time.monotonic() - self._paused_at
                self._paused_at = None
        elif not self.is_playing() and (self.queue or self.current_track):
            await self._play_next()

    async def stop(self):
        """Stop playback and clear queue."""
        self._skip_flag = True
        self.queue.clear()
        self.history.clear()
        self.current_track = None
        self.is_paused = False
        self._start_playback_time = None
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()

    async def seek(self, seconds: float):
        """Seek position in track."""
        if not self.current_track:
            return
        await self._play_next(seek_seconds=max(0.0, seconds))

    def shuffle(self):
        """Shuffle upcoming queue."""
        items = list(self.queue)
        random.shuffle(items)
        self.queue = deque(items)

    def set_volume(self, volume: float):
        """Set volume 0.0 to 2.0."""
        self.volume = max(0.0, min(2.0, volume))
        if self.voice_client and self.voice_client.source:
            if hasattr(self.voice_client.source, "volume"):
                self.voice_client.source.volume = self.volume


class PlayerManager:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self._players: Dict[int, GuildPlayer] = {}

    def get_player(self, guild_id: int) -> Optional[GuildPlayer]:
        return self._players.get(guild_id)

    def get_or_create(self, guild_id: int, text_channel: Optional[discord.TextChannel] = None) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer(guild_id, self.bot)
        if text_channel:
            self._players[guild_id].text_channel = text_channel
        return self._players[guild_id]

    def remove_player(self, guild_id: int):
        self._players.pop(guild_id, None)
