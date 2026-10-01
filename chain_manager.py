"""
Chain Manager
Maintains follower-to-leader voice channel bindings.
When a leader moves between voice channels, followers are automatically moved.
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
        """Bind follower to leader."""
        if guild_id not in self._chains:
            self._chains[guild_id] = {}
        self._chains[guild_id][follower_id] = leader_id
        print(f"[Chain] Registered binding: Guild {guild_id}, {follower_id} -> {leader_id}")

    def remove_chain(self, guild_id: int, follower_id: int) -> bool:
        """Remove binding for follower. Returns True if existed."""
        if guild_id in self._chains and follower_id in self._chains[guild_id]:
            del self._chains[guild_id][follower_id]
            if not self._chains[guild_id]:
                del self._chains[guild_id]
            return True
        return False

    def get_guild_chains(self, guild_id: int) -> Dict[int, int]:
        """Return all chains for a given guild."""
        return self._chains.get(guild_id, {})

    def clear_guild_chains(self, guild_id: int):
        """Clear all chains for a guild."""
        self._chains.pop(guild_id, None)

    async def handle_voice_move(
        self,
        member: discord.Member,
        before_channel: Optional[discord.VoiceChannel],
        after_channel: Optional[discord.VoiceChannel],
    ):
        """Handle voice channel switch for leader and relocate followers."""
        guild_id = member.guild.id
        guild_chains = self._chains.get(guild_id, {})
        if not guild_chains:
            return

        # Check if current member is a leader for any followers
        followers = [
            fid for fid, lid in guild_chains.items()
            if lid == member.id
        ]
        if not followers:
            return

        # If leader disconnected entirely from voice, do not drag followers into limbo
        if after_channel is None:
            return

        guild = member.guild
        bot_member = guild.get_member(self.bot.user.id)
        if not bot_member:
            return

        perms = after_channel.permissions_for(bot_member)
        if not perms.move_members:
            print(f"[Chain] Missing 'Move Members' permission in channel '{after_channel.name}'")
            return

        for follower_id in followers:
            follower = guild.get_member(follower_id)
            if not follower:
                continue

            if not follower.voice or not follower.voice.channel:
                continue

            if follower.voice.channel.id == after_channel.id:
                continue

            try:
                await follower.move_to(after_channel)
                print(f"[Chain] Relocated {follower.display_name} -> {after_channel.name} (following {member.display_name})")
                await asyncio.sleep(0.4)
            except discord.Forbidden:
                print(f"[Chain] Forbidden: could not move {follower.display_name}")
            except discord.HTTPException as err:
                print(f"[Chain] HTTP error while moving {follower.display_name}: {err}")
