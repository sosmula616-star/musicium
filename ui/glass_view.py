"""
ui/glass_view.py - Dynamic Liquid Glass visionOS Interactive Controller
Switches layouts (Compact, Full, Queue, Lyrics) in-place without sending new messages.
Dynamically alters button styles, badges, and emojis based on active playback state.
"""

import time
import asyncio
import logging
from typing import Optional, Any

import discord

from theme import get_guild_theme_name, THEMES
from render.animation import get_animation_engine
from render.queue_card import get_queue_renderer
from render.lyrics_card import get_lyrics_renderer
from ui.components import VolumeModal, SeekModal, SearchModal, ThemeSelect

logger = logging.getLogger("ui.glass_view")


class GlassPlayerView(discord.ui.View):
    """
    Main interactive visionOS controller for Discord.
    Supports in-place layout switching (Compact, Full, Queue, Lyrics) and dynamic button state reflection.
    """

    def __init__(self, bot: discord.Client, player: Any, initial_mode: str = "full"):
        super().__init__(timeout=300)
        self.bot = bot
        self.player = player
        self.current_mode = initial_mode  # "compact", "full", "queue", "lyrics"
        self.queue_page = 1
        self.message: Optional[discord.Message] = None
        self._last_edit_time: float = 0.0
        self._edit_lock = asyncio.Lock()

        # Build initial buttons
        self.rebuild_components()

    def rebuild_components(self):
        """Clears and rebuilds interactive components based on self.current_mode."""
        self.clear_items()
        is_playing = bool(self.player and self.player.is_playing)
        is_paused = bool(self.player and self.player.is_paused)
        has_current = bool(self.player and self.player.current_track)
        queue_len = len(self.player.queue) if self.player else 0
        loop_mode = getattr(self.player, "loop_mode", "off")

        if self.current_mode == "compact":
            self._build_compact_layout(is_playing, is_paused, has_current, queue_len, loop_mode)
        elif self.current_mode == "full":
            self._build_full_layout(is_playing, is_paused, has_current, queue_len, loop_mode)
        elif self.current_mode == "queue":
            self._build_queue_layout(queue_len)
        elif self.current_mode == "lyrics":
            self._build_lyrics_layout()

    def _build_compact_layout(self, is_playing: bool, is_paused: bool, has_current: bool, queue_len: int, loop_mode: str):
        # Row 0: Essential controls
        # Play / Pause
        if is_paused:
            self.add_item(self._create_btn("play_pause", "▶ Возобновить", discord.ButtonStyle.success, "▶️", 0))
        elif is_playing:
            self.add_item(self._create_btn("play_pause", "⏸ Пауза", discord.ButtonStyle.primary, "⏸️", 0))
        else:
            self.add_item(self._create_btn("play_pause", "▶ Играть", discord.ButtonStyle.secondary, "▶️", 0, disabled=not has_current))

        # Skip
        self.add_item(self._create_btn("skip", "Скип", discord.ButtonStyle.secondary, "⏭️", 0, disabled=not has_current))

        # Loop
        loop_label = "Выкл" if loop_mode == "off" else ("Трек" if loop_mode == "track" else "Очередь")
        loop_style = discord.ButtonStyle.primary if loop_mode != "off" else discord.ButtonStyle.secondary
        loop_emoji = "🔂" if loop_mode == "track" else "🔁"
        self.add_item(self._create_btn("loop", f"Повтор: {loop_label}", loop_style, loop_emoji, 0))

        # Mode Cycler
        self.add_item(self._create_btn("cycle_mode", "Вид: Компактный", discord.ButtonStyle.secondary, "🔄", 0))

        # Mini App Launcher
        self.add_item(self._create_btn("launch_app", "Mini App", discord.ButtonStyle.primary, "🚀", 0))

    def _build_full_layout(self, is_playing: bool, is_paused: bool, has_current: bool, queue_len: int, loop_mode: str):
        # Row 0: Playback row
        self.add_item(self._create_btn("previous", "Назад", discord.ButtonStyle.secondary, "⏮️", 0, disabled=not has_current))

        if is_paused:
            self.add_item(self._create_btn("play_pause", "Возобновить", discord.ButtonStyle.success, "▶️", 0))
        elif is_playing:
            self.add_item(self._create_btn("play_pause", "Пауза", discord.ButtonStyle.primary, "⏸️", 0))
        else:
            self.add_item(self._create_btn("play_pause", "Играть", discord.ButtonStyle.secondary, "▶️", 0, disabled=not has_current))

        self.add_item(self._create_btn("skip", "Скип", discord.ButtonStyle.secondary, "⏭️", 0, disabled=not has_current))
        self.add_item(self._create_btn("stop", "Стоп", discord.ButtonStyle.danger, "⏹️", 0, disabled=not has_current and not is_playing))

        loop_label = "Выкл" if loop_mode == "off" else ("Трек" if loop_mode == "track" else "Очередь")
        loop_style = discord.ButtonStyle.primary if loop_mode != "off" else discord.ButtonStyle.secondary
        loop_emoji = "🔂" if loop_mode == "track" else "🔁"
        self.add_item(self._create_btn("loop", f"{loop_label}", loop_style, loop_emoji, 0))

        # Row 1: Actions & Modal Triggers
        self.add_item(self._create_btn("volume_modal", "Громкость", discord.ButtonStyle.secondary, "🔊", 1))
        self.add_item(self._create_btn("seek_modal", "Перемотка", discord.ButtonStyle.secondary, "⏩", 1, disabled=not has_current))
        self.add_item(self._create_btn("shuffle", "Перемешать", discord.ButtonStyle.secondary, "🔀", 1, disabled=queue_len < 2))
        self.add_item(self._create_btn("search_modal", "Поиск", discord.ButtonStyle.secondary, "🔍", 1))
        self.add_item(self._create_btn("cycle_mode", "Вид: Полный", discord.ButtonStyle.secondary, "🔄", 1))

        # Row 2: Theme Selector Dropdown
        guild_id = self.player.guild.id if (self.player and self.player.guild) else None
        current_theme = get_guild_theme_name(guild_id)
        self.add_item(ThemeSelect(current_theme=current_theme, on_theme_change=self.on_theme_changed))

    def _build_queue_layout(self, queue_len: int):
        # Row 0: Queue Navigation
        self.add_item(self._create_btn("queue_prev", "◀ Пред.", discord.ButtonStyle.secondary, None, 0, disabled=self.queue_page <= 1))
        self.add_item(self._create_btn("queue_next", "След. ▶", discord.ButtonStyle.secondary, None, 0, disabled=(self.queue_page * 5) >= queue_len))
        self.add_item(self._create_btn("shuffle", "Перемешать", discord.ButtonStyle.secondary, "🔀", 0, disabled=queue_len < 2))
        self.add_item(self._create_btn("queue_clear", "Очистить", discord.ButtonStyle.danger, "🗑️", 0, disabled=queue_len == 0))
        self.add_item(self._create_btn("cycle_mode", "Вид: Очередь", discord.ButtonStyle.primary, "📜", 0))

        # Row 1: Quick Return & Mini App
        self.add_item(self._create_btn("switch_player", "К плееру", discord.ButtonStyle.secondary, "🎵", 1))
        self.add_item(self._create_btn("launch_app", "Открыть Mini App", discord.ButtonStyle.primary, "🚀", 1))

    def _build_lyrics_layout(self):
        # Row 0: Lyrics Actions
        self.add_item(self._create_btn("lyrics_refresh", "Обновить строку", discord.ButtonStyle.primary, "🔄", 0))
        self.add_item(self._create_btn("switch_player", "К плееру", discord.ButtonStyle.secondary, "🎵", 0))
        self.add_item(self._create_btn("cycle_mode", "Вид: Текст", discord.ButtonStyle.secondary, "🎤", 0))
        self.add_item(self._create_btn("launch_app", "Mini App", discord.ButtonStyle.secondary, "🚀", 0))

    def _create_btn(self, custom_id: str, label: str, style: discord.ButtonStyle, emoji: Optional[str] = None, row: int = 0, disabled: bool = False) -> discord.ui.Button:
        btn = discord.ui.Button(label=label, style=style, emoji=emoji, row=row, disabled=disabled)
        btn.callback = lambda inter: self.handle_button_click(inter, custom_id)
        return btn

    async def on_theme_changed(self, new_theme: str):
        """Called when user selects a new theme in the ThemeSelect dropdown."""
        await self.refresh_view_and_message()

    async def handle_button_click(self, interaction: discord.Interaction, action: str):
        """Central dispatcher for all visionOS interactive buttons."""
        if not self.player:
            await interaction.response.send_message("❌ Плеер не активен.", ephemeral=True)
            return

        # Play / Pause
        if action == "play_pause":
            await interaction.response.defer()
            await self.player.toggle_play_pause()
            await self.refresh_view_and_message()

        # Skip
        elif action == "skip":
            await interaction.response.defer()
            res = await self.player.skip(user_id=interaction.user.id)
            msg = res.get("message", "Трек пропущен")
            if not res.get("skipped"):
                await interaction.followup.send(f"🗳️ {msg}", ephemeral=True)
            await self.refresh_view_and_message()

        # Previous
        elif action == "previous":
            await interaction.response.defer()
            # If past 5s, rewind to start, otherwise pop from history if available
            elapsed = self.player.get_elapsed_seconds()
            if elapsed > 4:
                await self.player.seek(0)
            elif self.player.history:
                prev_t = self.player.history.pop(0)
                await self.player.enqueue(prev_t, play_now=True)
            else:
                await self.player.seek(0)
            await self.refresh_view_and_message()

        # Stop
        elif action == "stop":
            await interaction.response.defer()
            await self.player.stop()
            self.clear_items()
            self.add_item(discord.ui.Button(label="Плеер остановлен", style=discord.ButtonStyle.secondary, disabled=True))
            if self.message:
                try:
                    await self.message.edit(view=self)
                except Exception:
                    pass

        # Loop Cycle
        elif action == "loop":
            await interaction.response.defer()
            self.player.set_loop_mode("cycle")
            await self.refresh_view_and_message()

        # Shuffle
        elif action == "shuffle":
            await interaction.response.defer()
            self.player.shuffle_queue()
            await self.refresh_view_and_message()

        # Modals
        elif action == "volume_modal":
            await interaction.response.send_modal(VolumeModal(self.player, on_complete=self.refresh_view_and_message))

        elif action == "seek_modal":
            await interaction.response.send_modal(SeekModal(self.player, on_complete=self.refresh_view_and_message))

        elif action == "search_modal":
            async def _on_search(inter: discord.Interaction, query: str):
                tracks = await self.player.music_service.search(query, source="all", limit=1)
                if tracks:
                    t = tracks[0]
                    t.requester_id = inter.user.id
                    t.requester_name = inter.user.display_name
                    await self.player.enqueue(t, play_now=False)
                    await inter.followup.send(f"🎶 Добавлено: **{t.title}**", ephemeral=True)
                    await self.refresh_view_and_message()
                else:
                    await inter.followup.send(f"❌ Ничего не найдено по запросу: `{query}`", ephemeral=True)

            await interaction.response.send_modal(SearchModal(self.player, on_search=_on_search))

        # Mode Switching
        elif action == "cycle_mode":
            await interaction.response.defer()
            modes = ["compact", "full", "queue", "lyrics"]
            idx = modes.index(self.current_mode) if self.current_mode in modes else 0
            self.current_mode = modes[(idx + 1) % len(modes)]
            await self.refresh_view_and_message()

        elif action == "switch_player":
            await interaction.response.defer()
            self.current_mode = "full"
            await self.refresh_view_and_message()

        # Queue pagination
        elif action == "queue_prev":
            await interaction.response.defer()
            self.queue_page = max(1, self.queue_page - 1)
            await self.refresh_view_and_message()

        elif action == "queue_next":
            await interaction.response.defer()
            self.queue_page += 1
            await self.refresh_view_and_message()

        elif action == "queue_clear":
            await interaction.response.defer()
            self.player.clear_queue()
            self.queue_page = 1
            await self.refresh_view_and_message()

        # Lyrics refresh
        elif action == "lyrics_refresh":
            await interaction.response.defer()
            await self.refresh_view_and_message()

        # Launch Activity
        elif action == "launch_app":
            try:
                await interaction.response.launch_activity()
            except Exception:
                try:
                    await interaction.response.send_message("🌐 Запуск Mini App поддерживается через голосовой канал.", ephemeral=True)
                except Exception:
                    pass

    async def render_current_card(self) -> Optional[discord.File]:
        """Renders the appropriate visionOS card file based on self.current_mode."""
        guild_id = self.player.guild.id if (self.player and self.player.guild) else None
        theme_name = get_guild_theme_name(guild_id)

        # 1. Queue Card
        if self.current_mode == "queue":
            qr = get_queue_renderer()
            return await qr.render_queue_card(
                current_track=self.player.current_track,
                queue_tracks=self.player.queue,
                theme_name=theme_name,
                page=self.queue_page,
            )

        # 2. Lyrics Card
        elif self.current_mode == "lyrics":
            lr = get_lyrics_renderer()
            track = self.player.current_track
            if not track:
                lyrics_data = {"found": False, "synced": False, "lyrics": "Сейчас ничего не играет."}
            else:
                lyrics_data = await self.player.music_service.fetch_lyrics(
                    track.title, track.artist, track.duration
                )

            return await lr.render_lyrics_card(
                title=track.title if track else "Нет трека",
                artist=track.artist if track else "—",
                thumbnail_url=track.thumbnail if track else None,
                lyrics_text=lyrics_data.get("lyrics", ""),
                is_synced=lyrics_data.get("synced", False),
                elapsed_sec=self.player.get_elapsed_seconds() if self.player else 0,
                theme_name=theme_name,
            )

        # 3. Now Playing Card (Compact & Full)
        else:
            anim = get_animation_engine()
            track = self.player.current_track
            if not track:
                # Idle or empty card
                return await anim.render_now_playing_card(
                    title="Очередь воспроизведения пуста",
                    artist="Добавьте музыку с помощью /play",
                    thumbnail_url=None,
                    elapsed_sec=0,
                    duration_sec=0,
                    is_playing=False,
                    theme_name=theme_name,
                    animated=False,
                )

            return await anim.render_now_playing_card(
                title=track.title,
                artist=track.artist,
                thumbnail_url=track.thumbnail,
                elapsed_sec=self.player.get_elapsed_seconds(),
                duration_sec=track.duration or 0,
                is_playing=self.player.is_playing,
                loop_mode=getattr(self.player, "loop_mode", "off"),
                requester=getattr(track, "requester_name", "Пользователь"),
                theme_name=theme_name,
                animated=self.player.is_playing,  # Generate animated WebP when playing
            )

    async def refresh_view_and_message(self):
        """Re-renders the visual card and edits the Discord message in place with debouncing."""
        async with self._edit_lock:
            now = time.time()
            if now - self._last_edit_time < 1.2:
                # Prevent spamming Discord API
                await asyncio.sleep(1.2 - (now - self._last_edit_time))

            self.rebuild_components()

            if self.message:
                try:
                    card_file = await self.render_current_card()
                    attachments = [card_file] if card_file else []
                    await self.message.edit(attachments=attachments, view=self)
                    self._last_edit_time = time.time()
                except Exception as e:
                    logger.debug(f"Failed to edit glass player message: {e}")
