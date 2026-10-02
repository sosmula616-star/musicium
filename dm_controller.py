import os
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple
import discord
from discord.ext import commands

from music_service import Track, format_duration

logger = logging.getLogger("dm_controller")

class PlayerControlView(discord.ui.View):
    def __init__(self, dm_controller: "DMController", guild_id: int, user_id: int):
        super().__init__(timeout=None)
        self.dm_controller = dm_controller
        self.guild_id = guild_id
        self.user_id = user_id
        self._update_buttons()

    def _update_buttons(self):
        player = self.dm_controller.get_player(self.guild_id)
        if not player:
            return

        # Update play/pause label and style
        play_btn = self.children[0]
        if player.is_paused:
            play_btn.label = "▶️ Продолжить"
            play_btn.style = discord.ButtonStyle.success
        else:
            play_btn.label = "⏸️ Пауза"
            play_btn.style = discord.ButtonStyle.primary

        # Update skip button with vote count
        skip_btn = self.children[1]
        req = player.get_required_votes()
        votes = len(player.vote_skips)
        if votes > 0:
            skip_btn.label = f"⏭️ Скип ({votes}/{req})"
        else:
            skip_btn.label = "⏭️ Пропустить"

        # Update loop mode label
        loop_btn = self.children[2]
        mode_labels = {
            "off": "🔁 Повтор: Выкл",
            "track": "🔂 Повтор: Трек",
            "queue": "🔁 Повтор: Очередь"
        }
        loop_btn.label = mode_labels.get(player.loop_mode, "🔁 Повтор")

    @discord.ui.button(label="⏸️ Пауза", style=discord.ButtonStyle.primary, row=0, custom_id="dm_play_pause")
    async def play_pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = self.dm_controller.get_player(self.guild_id)
        if not player:
            await interaction.followup.send("Плеер сейчас не активен.", ephemeral=True)
            return

        await player.toggle_play_pause()
        await self.dm_controller.update_dm_message(self.user_id, self.guild_id)

    @discord.ui.button(label="⏭️ Пропустить", style=discord.ButtonStyle.secondary, row=0, custom_id="dm_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = self.dm_controller.get_player(self.guild_id)
        if not player:
            await interaction.followup.send("Плеер сейчас не активен.", ephemeral=True)
            return

        result = await player.skip(user_id=interaction.user.id)
        await self.dm_controller.update_dm_message(self.user_id, self.guild_id)
        if result.get("skipped"):
            await interaction.followup.send(f"⏭️ {result.get('message', 'Трек пропущен!')}", ephemeral=True)
        else:
            await interaction.followup.send(f"🗳️ {result.get('message')}", ephemeral=True)

    @discord.ui.button(label="🔁 Повтор: Выкл", style=discord.ButtonStyle.secondary, row=0, custom_id="dm_loop")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = self.dm_controller.get_player(self.guild_id)
        if not player:
            await interaction.followup.send("Плеер сейчас не активен.", ephemeral=True)
            return

        new_mode = player.set_loop_mode("")
        await self.dm_controller.update_dm_message(self.user_id, self.guild_id)

    @discord.ui.button(label="🔀 Перемешать", style=discord.ButtonStyle.secondary, row=1, custom_id="dm_shuffle")
    async def shuffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = self.dm_controller.get_player(self.guild_id)
        if not player:
            await interaction.followup.send("Плеер сейчас не активен.", ephemeral=True)
            return

        count = player.shuffle_queue()
        await interaction.followup.send(f"🔀 Очередь перемешана ({count} треков)!", ephemeral=True)
        await self.dm_controller.update_dm_message(self.user_id, self.guild_id)

    @discord.ui.button(label="📜 Очередь", style=discord.ButtonStyle.secondary, row=1, custom_id="dm_queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.dm_controller.get_player(self.guild_id)
        if not player or not player.queue:
            await interaction.response.send_message("📜 Очередь пуста! Добавьте треки через Мини-Приложение.", ephemeral=True)
            return

        lines = []
        for i, t in enumerate(player.queue[:10], 1):
            lines.append(f"**{i}.** [{t.title}]({t.url}) - `{t.duration_str}`")

        embed = discord.Embed(
            title=f"📜 Очередь воспроизведения ({len(player.queue)} треков)",
            description="\n".join(lines),
            color=0x5865F2,
        )
        if len(player.queue) > 10:
            embed.set_footer(text=f"И ещё {len(player.queue) - 10} треков...")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="⏹️ Стоп", style=discord.ButtonStyle.danger, row=1, custom_id="dm_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = self.dm_controller.get_player(self.guild_id)
        if not player:
            await interaction.followup.send("Плеер сейчас не активен.", ephemeral=True)
            return

        await player.stop()
        await interaction.followup.send("⏹️ Воспроизведение остановлено, бот отключился от канала.", ephemeral=True)
        await self.dm_controller.update_dm_message(self.user_id, self.guild_id)


class DMController:
    def __init__(self, bot: commands.Bot, player_manager):
        self.bot = bot
        self.player_manager = player_manager
        self.user_dm_messages: Dict[int, discord.Message] = {}  # user_id -> Message
        self.public_url = os.getenv("PUBLIC_URL", "http://localhost:3000")

    def get_player(self, guild_id: int):
        return self.player_manager.get_player_by_guild_id(guild_id)

    def create_embed(self, player, track: Track) -> discord.Embed:
        # Determine accent color by source
        source_colors = {
            "youtube": 0xFF0000,
            "soundcloud": 0xFF5500,
            "yandex": 0xFFCC00,
        }
        color = source_colors.get(track.source, 0x5865F2)

        source_icons = {
            "youtube": "🔴 YouTube Music",
            "soundcloud": "🟠 SoundCloud",
            "yandex": "🟡 Яндекс Музыка",
        }
        source_name = source_icons.get(track.source, "🎵 Музыка")

        status_icon = "⏸️ Пауза" if player.is_paused else "▶️ Играет"

        embed = discord.Embed(
            title=f"🎶 Сейчас играет: {track.title}",
            url=track.url,
            color=color,
        )

        embed.add_field(name="👤 Исполнитель", value=track.artist or "Неизвестен", inline=True)
        embed.add_field(name="⏱ Длительность", value=track.duration_str, inline=True)
        embed.add_field(name="📡 Источник", value=source_name, inline=True)

        channel_name = player.voice_client.channel.name if player.voice_client and player.voice_client.channel else "Голосовой канал"
        embed.add_field(name="🔊 Канал", value=f"`{channel_name}`", inline=True)
        embed.add_field(name="Статус", value=f"`{status_icon}`", inline=True)

        req_votes = player.get_required_votes()
        votes = len(player.vote_skips)
        embed.add_field(name="🗳️ Голоса за скип", value=f"`{votes}/{req_votes}`", inline=True)

        embed.add_field(
            name="📱 Управление через Мини-Приложение",
            value=f"[✨ **Открыть Discord Mini App Плеер**]({self.public_url})",
            inline=False,
        )

        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)

        embed.set_footer(
            text=f"Запросил: {track.requester_name} • Громкость: {int(player.volume * 100)}%",
            icon_url=f"{self.public_url}/static/activity_icon.jpg"
        )
        return embed

    async def notify_track_started(self, user_id: int, guild_id: int, track: Track):
        """Sends or updates DM message to the user with the interactive player menu."""
        player = self.get_player(guild_id)
        if not player:
            return

        try:
            user = self.bot.get_user(user_id)
            if not user:
                user = await self.bot.fetch_user(user_id)

            if not user:
                logger.warning(f"Could not find user with id {user_id} to send DM.")
                return

            embed = self.create_embed(player, track)
            view = PlayerControlView(self, guild_id, user_id)

            # Add Link Button to view
            view.add_item(discord.ui.Button(
                label="🌐 Открыть Mini App",
                style=discord.ButtonStyle.link,
                url=self.public_url,
                row=1
            ))

            existing_msg = self.user_dm_messages.get(user_id)
            if existing_msg:
                try:
                    await existing_msg.edit(embed=embed, view=view)
                    return
                except discord.NotFound:
                    self.user_dm_messages.pop(user_id, None)
                except Exception as e:
                    logger.debug(f"Could not edit DM, sending new message: {e}")

            msg = await user.send(embed=embed, view=view)
            self.user_dm_messages[user_id] = msg

        except discord.Forbidden:
            logger.warning(f"Cannot send DM to user {user_id}: DMs are closed/blocked.")
        except Exception as e:
            logger.error(f"Error in notify_track_started: {e}", exc_info=True)

    async def update_dm_message(self, user_id: int, guild_id: int):
        """Updates the active DM controller message for the user."""
        player = self.get_player(guild_id)
        existing_msg = self.user_dm_messages.get(user_id)
        if not existing_msg:
            return

        if not player or not player.current_track:
            embed = discord.Embed(
                title="⏹️ Плеер остановлен",
                description=f"Музыка больше не играет. Чтобы выбрать новые треки, откройте [Мини-Приложение]({self.public_url})!",
                color=0x2b2d31,
            )
            try:
                await existing_msg.edit(embed=embed, view=None)
            except Exception:
                pass
            return

        try:
            embed = self.create_embed(player, player.current_track)
            view = PlayerControlView(self, guild_id, user_id)
            view.add_item(discord.ui.Button(
                label="🌐 Открыть Mini App",
                style=discord.ButtonStyle.link,
                url=self.public_url,
                row=1
            ))
            await existing_msg.edit(embed=embed, view=view)
        except Exception as e:
            logger.debug(f"Failed to update DM message for {user_id}: {e}")
