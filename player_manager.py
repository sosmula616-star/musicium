"""
Player Manager
Manages per-guild music players (queue, playback, volume, voice connection, history).
"""

import os
import shutil
import asyncio
import discord
from collections import deque
from typing import Optional


FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5 "
        "-probesize 200M"
    ),
    "options": "-vn -bufsize 512k",
}


def get_ffmpeg_cmd() -> str:
    """Find system ffmpeg or fallback to imageio_ffmpeg."""
    ffmpeg_exe = shutil.which("ffmpeg")
    if ffmpeg_exe:
        return ffmpeg_exe
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            exe_dir = os.path.dirname(exe)
            if exe_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = exe_dir + os.pathsep + os.environ.get("PATH", "")
            return exe
    except Exception as e:
        print(f"[PlayerManager] imageio_ffmpeg warning: {e}")
    return "ffmpeg"


class GuildPlayer:
    """Manages playback for a single guild."""

    def __init__(self, guild_id: int, text_channel: Optional[discord.TextChannel], bot: discord.Client):
        self.guild_id = guild_id
        self.text_channel = text_channel
        self.bot = bot

        self.voice_client: Optional[discord.VoiceClient] = None
        self.queue: deque[dict] = deque()
        self.history: deque[dict] = deque(maxlen=30)
        self.current_track: Optional[dict] = None
        self.is_paused: bool = False
        self.volume: float = 0.5
        self.loop_mode: str = "none"  # none | track | queue
        self._play_lock = asyncio.Lock()
        self._skip_flag = False

    async def connect(self, channel: discord.VoiceChannel):
        """Connect or move to a voice channel."""
        if self.voice_client:
            if self.voice_client.is_connected():
                if self.voice_client.channel.id != channel.id:
                    await self.voice_client.move_to(channel)
                return
            else:
                try:
                    await self.voice_client.disconnect(force=True)
                except Exception as e:
                    print(f"[Player] Voice disconnect warning: {e}")
                self.voice_client = None

        try:
            self.voice_client = await channel.connect(reconnect=True, timeout=20.0)
            print(f"[Player] Connected to voice channel: {channel.name} (ID: {channel.id})")
        except Exception as e:
            print(f"[Player] Voice connect error: {e}")
            raise e

    async def add_to_queue(self, track: dict, requester: discord.Member = None):
        """Add a track to the queue and start playing if idle."""
        track_copy = dict(track)
        if requester:
            track_copy["requester"] = requester.display_name
        elif "requester" not in track_copy:
            track_copy["requester"] = "Web App"

        self.queue.append(track_copy)
        if not self.is_playing():
            await self._play_next()

    async def _play_next(self):
        """Play the next track in queue."""
        async with self._play_lock:
            if self.current_track and not self._skip_flag:
                self.history.append(self.current_track)

            if not self.queue and self.loop_mode != "track":
                self.current_track = None
                self.is_paused = False
                return

            if self.loop_mode == "track" and self.current_track:
                track = self.current_track
            elif self.queue:
                track = self.queue.popleft()
                if self.loop_mode == "queue" and self.current_track:
                    self.queue.append(self.current_track)
            else:
                self.current_track = None
                self.is_paused = False
                return

            self.current_track = track
            self.is_paused = False
            self._skip_flag = False

        # Get stream URL
        stream_url = track.get("stream_url")
        if not stream_url:
            from music_search import MusicSearchEngine
            search = MusicSearchEngine()
            stream_url = await search.get_stream_url(track)
            track["stream_url"] = stream_url

        if not stream_url:
            if self.text_channel:
                asyncio.create_task(self.text_channel.send(f"❌ Не удалось загрузить трек: **{track.get('title', 'Unknown')}**"))
            asyncio.create_task(self._play_next())
            return

        # Play audio using PCMVolumeTransformer
        try:
            ffmpeg_exe = get_ffmpeg_cmd()
            
            headers = track.get("http_headers") or {}
            before_opts = (
                "-reconnect 1 "
                "-reconnect_streamed 1 "
                "-reconnect_delay_max 5 "
                "-probesize 200M"
            )
            if headers:
                headers_str = "".join([f"{k}: {v}\r\n" for k, v in headers.items()])
                before_opts += f' -headers "{headers_str}"'

            ffmpeg_opts = {
                "before_options": before_opts,
                "options": "-vn -bufsize 512k",
            }

            audio_source = discord.FFmpegPCMAudio(
                stream_url,
                executable=ffmpeg_exe,
                **ffmpeg_opts
            )
            volume_source = discord.PCMVolumeTransformer(
                audio_source,
                volume=self.volume
            )

            def after_play(error):
                if error and not self._skip_flag:
                    print(f"[Player] Playback error: {error}")
                asyncio.run_coroutine_threadsafe(self._play_next(), self.bot.loop)

            if self.voice_client and self.voice_client.is_connected():
                if self.voice_client.is_playing() or self.voice_client.is_paused():
                    self.voice_client.stop()
                self.voice_client.play(volume_source, after=after_play)
                print(f"▶️ Playing: {track.get('title', '')} [{track.get('platform', '')}]")
            else:
                print("[Player] Voice client not connected!")
        except Exception as e:
            print(f"[Player] Error starting playback: {e}")
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

    async def prev(self) -> bool:
        """Go back to previous track if history available."""
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
        """Stop playback and clear queue."""
        self._skip_flag = True
        self.queue.clear()
        self.history.clear()
        self.current_track = None
        self.is_paused = False
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()

    async def pause(self):
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self.is_paused = True

    async def resume(self):
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            self.is_paused = False
        elif not self.is_playing() and (self.queue or self.current_track):
            await self._play_next()

    def set_volume(self, volume: float):
        """Set volume (0.0 - 2.0)."""
        self.volume = max(0.0, min(2.0, volume))
        if self.voice_client and self.voice_client.source:
            if hasattr(self.voice_client.source, "volume"):
                self.voice_client.source.volume = self.volume

    def get_state(self) -> dict:
        """Return current player state as JSON-serializable dict."""
        queue_list = []
        for t in list(self.queue)[:30]:
            queue_list.append({
                "id": t.get("id", ""),
                "title": t.get("title", ""),
                "artist": t.get("artist", ""),
                "duration": t.get("duration", 0),
                "duration_str": t.get("duration_str", ""),
                "thumbnail": t.get("thumbnail", ""),
                "platform": t.get("platform", ""),
                "platform_icon": t.get("platform_icon", ""),
                "platform_color": t.get("platform_color", "#999"),
                "requester": t.get("requester", ""),
                "url": t.get("url", ""),
            })

        current = None
        if self.current_track:
            current = {
                "id": self.current_track.get("id", ""),
                "title": self.current_track.get("title", ""),
                "artist": self.current_track.get("artist", ""),
                "duration": self.current_track.get("duration", 0),
                "duration_str": self.current_track.get("duration_str", ""),
                "thumbnail": self.current_track.get("thumbnail", ""),
                "platform": self.current_track.get("platform", ""),
                "platform_icon": self.current_track.get("platform_icon", ""),
                "platform_color": self.current_track.get("platform_color", "#999"),
                "requester": self.current_track.get("requester", ""),
                "url": self.current_track.get("url", ""),
            }

        return {
            "playing": self.is_playing() and not self.is_paused,
            "paused": self.is_paused,
            "volume": self.volume,
            "loop_mode": self.loop_mode,
            "current": current,
            "queue": queue_list,
            "queue_count": len(self.queue),
            "history_count": len(self.history),
        }


class PlayerManager:
    """Manages GuildPlayer instances per guild."""

    def __init__(self, bot: discord.Client):
        self.bot = bot
        self._players: dict[int, GuildPlayer] = {}

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

    def get_all_states(self) -> dict:
        return {str(gid): p.get_state() for gid, p in self._players.items()}
