"""
Chain Manager
Manages user-to-user voice channel chains.
When the "leader" moves to another channel, "follower" is auto-moved too.
"""

import discord
import asyncio
from typing import Optional


class ChainManager:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        # {guild_id: {follower_id: leader_id}}
        self._chains: dict[int, dict[int, int]] = {}

    def add_chain(self, guild_id: int, follower_id: int, leader_id: int):
        """Bind follower to leader."""
        if guild_id not in self._chains:
            self._chains[guild_id] = {}
        self._chains[guild_id][follower_id] = leader_id
        print(f"[Chain] Guild {guild_id}: {follower_id} → {leader_id}")

    def remove_chain(self, guild_id: int, follower_id: int) -> bool:
        """Remove a chain for follower. Returns True if existed."""
        if guild_id in self._chains and follower_id in self._chains[guild_id]:
            del self._chains[guild_id][follower_id]
            if not self._chains[guild_id]:
                del self._chains[guild_id]
            return True
        return False

    def get_guild_chains(self, guild_id: int) -> dict[int, int]:
        """Return all chains for a guild {follower_id: leader_id}."""
        return self._chains.get(guild_id, {})

    def clear_guild_chains(self, guild_id: int):
        self._chains.pop(guild_id, None)

    async def handle_voice_move(
        self,
        member: discord.Member,
        before_channel: Optional[discord.VoiceChannel],
        after_channel: Optional[discord.VoiceChannel],
    ):
        """
        Called on voice state update.
        If 'member' is a leader, move all followers to the new channel.
        """
        guild_id = member.guild.id
        guild_chains = self._chains.get(guild_id, {})

        if not guild_chains:
            return

        # Найти всех, кто следует за этим участником
        followers = [
            follower_id
            for follower_id, leader_id in guild_chains.items()
            if leader_id == member.id
        ]

        if not followers:
            return

        # Если лидер вышел из канала — не перемещаем (только при смене канала)
        if after_channel is None:
            return

        guild = member.guild
        for follower_id in followers:
            follower = guild.get_member(follower_id)
            if not follower:
                continue

            # Follower должен быть в голосовом канале
            if not follower.voice or not follower.voice.channel:
                continue

            # Уже там
            if follower.voice.channel.id == after_channel.id:
                continue

            # Проверяем права на перемещение
            bot_member = guild.get_member(self.bot.user.id)
            if not bot_member:
                continue

            perms = after_channel.permissions_for(bot_member)
            if not perms.move_members:
                print(f"[Chain] No permission to move {follower.display_name}")
                continue

            try:
                await follower.move_to(after_channel)
                print(
                    f"[Chain] Moved {follower.display_name} → {after_channel.name} "
                    f"(following {member.display_name})"
                )
                await asyncio.sleep(0.5)  # антифлуд
            except discord.Forbidden:
                print(f"[Chain] Forbidden: cannot move {follower.display_name}")
            except discord.HTTPException as e:
                print(f"[Chain] HTTP error moving {follower.display_name}: {e}")
