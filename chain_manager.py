"""
Chain Manager
Maintains follower-to-leader voice channel tracking.
"""

import asyncio
from typing import Optional, Dict
import discord


class ChainManager:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        # {guild_id: {follower_id: leader_id}}
        self._chains: Dict[int, Dict[int, int]] = {}

    def add_chain(self, guild_id: int, follower_id: int, leader_id: int):
        if guild_id not in self._chains:
            self._chains[guild_id] = {}
        self._chains[guild_id][follower_id] = leader_id

    def remove_chain(self, guild_id: int, follower_id: int) -> bool:
        if guild_id in self._chains and follower_id in self._chains[guild_id]:
            del self._chains[guild_id][follower_id]
            if not self._chains[guild_id]:
                del self._chains[guild_id]
            return True
        return False

    def get_guild_chains(self, guild_id: int) -> Dict[int, int]:
        return self._chains.get(guild_id, {})

    async def handle_voice_move(
        self,
        member: discord.Member,
        before_channel: Optional[discord.VoiceChannel],
        after_channel: Optional[discord.VoiceChannel],
    ):
        guild_id = member.guild.id
        guild_chains = self._chains.get(guild_id, {})
        if not guild_chains:
            return

        followers = [
            fid for fid, lid in guild_chains.items()
            if lid == member.id
        ]
        if not followers or after_channel is None:
            return

        guild = member.guild
        bot_member = guild.me
        if not bot_member:
            return

        perms = after_channel.permissions_for(bot_member)
        if not perms.move_members:
            return

        for fid in followers:
            f = guild.get_member(fid)
            if not f or not f.voice or not f.voice.channel:
                continue
            if f.voice.channel.id == after_channel.id:
                continue
            try:
                await f.move_to(after_channel)
                await asyncio.sleep(0.3)
            except Exception:
                pass
