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
        self.ws_subscriptions: Dict[Any, Optional[int]] = {}  # ws -> guild_id

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

    def find_user_voice(self, user_id: int, guild_id: Optional[int] = None) -> Optional[Tuple[discord.Guild, discord.VoiceChannel, discord.Member]]:
        """Finds guild and voice channel the user is currently connected to, prioritizing guild_id if specified."""
        # 1. If guild_id is provided, search that guild first!
        if guild_id:
            guild = self.bot.get_guild(guild_id)
            if guild:
                for vc in guild.voice_channels:
                    for m in vc.members:
                        if m.id == user_id:
                            return guild, vc, m
                for sc in getattr(guild, 'stage_channels', []):
                    for m in sc.members:
                        if m.id == user_id:
                            return guild, sc, m
                member = guild.get_member(user_id)
                if member and member.voice and member.voice.channel:
                    return guild, member.voice.channel, member

        # 2. Search all guilds the bot is currently in
        for guild in self.bot.guilds:
            if guild_id and guild.id == guild_id:
                continue
            for vc in guild.voice_channels:
                for m in vc.members:
                    if m.id == user_id:
                        return guild, vc, m
            for sc in getattr(guild, 'stage_channels', []):
                for m in sc.members:
                    if m.id == user_id:
                        return guild, sc, m
            member = guild.get_member(user_id)
            if member and member.voice and member.voice.channel:
                return guild, member.voice.channel, member
        return None

    def find_active_player_for_user(self, user_id: int, guild_id: Optional[int] = None) -> Optional[GuildPlayer]:
        """Finds the active GuildPlayer for the guild where the user is in voice, or where user requested tracks."""
        if guild_id and guild_id in self.players:
            return self.players[guild_id]

        found = self.find_user_voice(user_id, guild_id=guild_id)
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

        # Broadcast via WebSockets only to clients connected to this guild (or unassigned)
        await self.broadcast_event("player_update", state, target_guild_id=player.guild.id)

        # DM Notifications
        if self.dm_controller:
            req_id = player.current_track.requester_id if player.current_track else None
            if track_started and req_id:
                await self.dm_controller.notify_track_started(req_id, player.guild.id, player.current_track)
            elif req_id:
                await self.dm_controller.update_dm_message(req_id, player.guild.id)

    async def broadcast_event(self, event_type: str, data: Any, target_guild_id: Optional[int] = None):
        if not self.ws_clients:
            return

        payload = {"event": event_type, "data": data}
        disconnected = set()
        for ws in list(self.ws_clients):
            try:
                # If target_guild_id is specified, only send if client has subscribed to this guild or not yet assigned
                if target_guild_id is not None:
                    client_guild = self.ws_subscriptions.get(ws)
                    if client_guild is not None and client_guild != target_guild_id:
                        continue
                await ws.send_json(payload)
            except Exception:
                disconnected.add(ws)

        for dead_ws in disconnected:
            self.ws_clients.discard(dead_ws)
            self.ws_subscriptions.pop(dead_ws, None)
