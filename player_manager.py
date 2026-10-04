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
        self.guild_volumes: Dict[int, float] = {}  # guild_id -> remembered volume float
        self.dm_controller = None  # Will be assigned after DMController init
        self.ws_clients: Set[Any] = set()
        self.ws_subscriptions: Dict[Any, Optional[int]] = {}  # ws -> guild_id

    def set_dm_controller(self, dm_controller):
        self.dm_controller = dm_controller

    def get_or_create_player(self, guild: discord.Guild) -> GuildPlayer:
        if guild.id not in self.players:
            p = GuildPlayer(
                guild=guild,
                bot=self.bot,
                music_service=self.music_service,
                on_change_callback=self._on_player_state_change
            )
            # Restore saved volume for this guild if previously set
            if guild.id in self.guild_volumes:
                p.volume = self.guild_volumes[guild.id]
            self.players[guild.id] = p
        return self.players[guild.id]

    def get_player_by_guild_id(self, guild_id: int) -> Optional[GuildPlayer]:
        if guild_id in self.players:
            return self.players[guild_id]
        guild = self.bot.get_guild(guild_id)
        if guild:
            return self.get_or_create_player(guild)
        return None

    def find_user_voice(self, user_id: int, guild_id: Optional[int] = None) -> Optional[Tuple[discord.Guild, discord.VoiceChannel, discord.Member]]:
        """Finds guild and voice channel the user is currently connected to, prioritizing guild_id if specified."""
        def _check_guild(g: discord.Guild):
            if not g:
                return None
            # 1. Fast check via guild._voice_states (gateway cache)
            if hasattr(g, '_voice_states') and user_id in g._voice_states:
                vs = g._voice_states[user_id]
                if vs:
                    ch = getattr(vs, 'channel', None)
                    if not ch and hasattr(vs, '_channel_id') and vs._channel_id:
                        ch = g.get_channel(vs._channel_id)
                    if ch:
                        mem = g.get_member(user_id) or (ch.guild.get_member(user_id) if hasattr(ch, 'guild') else None)
                        return g, ch, mem

            # 2. Iterate voice_channels
            for vc in getattr(g, 'voice_channels', []):
                for m in vc.members:
                    if m.id == user_id:
                        return g, vc, m
            # 3. Iterate stage_channels
            for sc in getattr(g, 'stage_channels', []):
                for m in sc.members:
                    if m.id == user_id:
                        return g, sc, m
            # 4. Check member.voice
            member = g.get_member(user_id)
            if member and member.voice and member.voice.channel:
                return g, member.voice.channel, member
            return None

        # Prioritize specified guild_id
        if guild_id:
            g = self.bot.get_guild(guild_id)
            found = _check_guild(g)
            if found:
                return found

        # Search all bot guilds
        for g in self.bot.guilds:
            if guild_id and g.id == guild_id:
                continue
            found = _check_guild(g)
            if found:
                return found

        return None

    def find_active_player_for_user(self, user_id: int, guild_id: Optional[int] = None) -> Optional[GuildPlayer]:
        """Finds the active GuildPlayer for the guild where the user is in voice, or where user requested tracks."""
        if guild_id:
            p = self.get_player_by_guild_id(guild_id)
            if p:
                return p

        found = self.find_user_voice(user_id, guild_id=guild_id)
        if found:
            guild, _, _ = found
            return self.get_player_by_guild_id(guild.id)

        # Fallback: check if user is requester of current track in any player
        for p in self.players.values():
            if p.current_track and p.current_track.requester_id == user_id:
                return p
        return None

    def get_all_guilds_info(self, current_user_id: Optional[int] = None) -> list:
        """Returns comprehensive info about all guilds the bot is on, their channels, and active room connections."""
        guilds_data = []
        for g in self.bot.guilds:
            bot_vc = getattr(g, 'voice_client', None)
            bot_in_voice = bool(bot_vc and bot_vc.is_connected())
            bot_channel_id = str(bot_vc.channel.id) if (bot_in_voice and bot_vc.channel) else None
            bot_channel_name = bot_vc.channel.name if (bot_in_voice and bot_vc.channel) else None

            player = self.players.get(g.id)
            is_playing = bool(player and player.is_playing)
            current_track = player.current_track.to_dict() if (player and player.current_track) else None

            channels_data = []
            all_voice = list(getattr(g, 'voice_channels', [])) + list(getattr(g, 'stage_channels', []))
            for vc in all_voice:
                members_list = []
                bot_is_here = False
                user_is_here = False
                for m in vc.members:
                    if self.bot.user and m.id == self.bot.user.id:
                        bot_is_here = True
                    if current_user_id and m.id == current_user_id:
                        user_is_here = True
                    members_list.append({
                        "id": str(m.id),
                        "name": m.name,
                        "display_name": m.display_name,
                        "avatar": m.display_avatar.url if hasattr(m, 'display_avatar') else None,
                        "bot": m.bot
                    })

                channels_data.append({
                    "id": str(vc.id),
                    "name": vc.name,
                    "type": "stage" if isinstance(vc, getattr(discord, 'StageChannel', ())) else "voice",
                    "user_count": len([m for m in vc.members if not m.bot]),
                    "members": members_list,
                    "bot_is_here": bot_is_here or (bot_channel_id == str(vc.id)),
                    "user_is_here": user_is_here,
                })

            guild_icon = g.icon.url if g.icon else None
            guilds_data.append({
                "id": str(g.id),
                "name": g.name,
                "icon": guild_icon,
                "member_count": g.member_count or len(g.members),
                "bot_in_voice": bot_in_voice,
                "bot_channel_id": bot_channel_id,
                "bot_channel_name": bot_channel_name,
                "is_playing": is_playing,
                "current_track": current_track,
                "channels": channels_data,
            })
        return guilds_data

    async def _on_player_state_change(self, player: GuildPlayer, track_started: bool = False):
        self.guild_volumes[player.guild.id] = player.volume
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

    def get_all_active_streams(self) -> list:
        active = []
        for g in self.bot.guilds:
            player = self.players.get(g.id)
            if not player and getattr(g, 'voice_client', None) and g.voice_client.is_connected():
                player = self.get_or_create_player(g)
            if player and player.is_playing and player.current_track:
                vc = player.voice_client or g.voice_client
                listeners = player.get_non_bot_listeners()
                active.append({
                    "guild_id": str(g.id),
                    "guild_name": g.name,
                    "channel_name": vc.channel.name if vc and vc.channel else None,
                    "channel_id": str(vc.channel.id) if vc and vc.channel else None,
                    "listeners_count": len(listeners),
                    "track": player.current_track.to_dict(),
                    "elapsed_seconds": player.get_elapsed_seconds(),
                    "duration": player.current_track.duration,
                })
        return active
