import asyncio
import logging
from typing import Dict, Optional, Tuple, Set, Any
import discord
from discord.ext import commands

from music_service import MusicService, Track
from player import GuildPlayer

logger = logging.getLogger("player_manager")

class PlayerManager:
    def __init__(self, bot: commands.Bot, music_service: MusicService):
        self.bot = bot
        self.music_service = music_service
        self.players: Dict[int, GuildPlayer] = {}  # guild_id -> GuildPlayer
        self.dm_controller = None  # Will be assigned after DMController init
        self.ws_clients: Set[Any] = set()

    def set_dm_controller(self, dm_controller):
        self.dm_controller = dm_controller

    def get_or_create_player(self, guild: discord.Guild) -> GuildPlayer:
        if guild.id not in self.players:
            self.players[guild.id] = GuildPlayer(
                guild=guild,
                bot=self.bot,
                music_service=self.music_service,
                on_change_callback=self._on_player_state_change
            )
        return self.players[guild.id]

    def get_player_by_guild_id(self, guild_id: int) -> Optional[GuildPlayer]:
        return self.players.get(guild_id)

    def find_user_voice(self, user_id: int) -> Optional[Tuple[discord.Guild, discord.VoiceChannel, discord.Member]]:
        """Finds any guild and voice channel the user is currently connected to."""
        for guild in self.bot.guilds:
            member = guild.get_member(user_id)
            if member and member.voice and member.voice.channel:
                return guild, member.voice.channel, member
        return None

    def find_active_player_for_user(self, user_id: int) -> Optional[GuildPlayer]:
        """Finds the active GuildPlayer for the guild where the user is in voice, or where user requested tracks."""
        found = self.find_user_voice(user_id)
        if found:
            guild, _, _ = found
            return self.players.get(guild.id)

        # Fallback: check if user is requester of current track in any player
        for p in self.players.values():
            if p.current_track and p.current_track.requester_id == user_id:
                return p
        return None

    async def _on_player_state_change(self, player: GuildPlayer, track_started: bool = False):
        state = player.get_state()

        # Broadcast via WebSockets to Mini App clients
        await self.broadcast_event("player_update", state)

        # DM Notifications
        if self.dm_controller:
            req_id = player.current_track.requester_id if player.current_track else None
            if track_started and req_id:
                await self.dm_controller.notify_track_started(req_id, player.guild.id, player.current_track)
            elif req_id:
                await self.dm_controller.update_dm_message(req_id, player.guild.id)

    async def broadcast_event(self, event_type: str, data: Any):
        if not self.ws_clients:
            return

        payload = {"event": event_type, "data": data}
        disconnected = set()
        for ws in self.ws_clients:
            try:
                await ws.send_json(payload)
            except Exception:
                disconnected.add(ws)

        for dead_ws in disconnected:
            self.ws_clients.discard(dead_ws)
