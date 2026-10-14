"""
ui/components.py - visionOS Interactive Modals & Select Menus
Provides input modals for Volume, Seeking, and Search, plus Theme Selection dropdowns.
"""

import logging
from typing import Optional, Callable

import discord

from theme import THEMES, set_guild_theme, get_guild_theme_name

logger = logging.getLogger("ui.components")


class VolumeModal(discord.ui.Modal, title="🔊 Уровень громкости"):
    volume_input = discord.ui.TextInput(
        label="Громкость (от 0 до 200%)",
        placeholder="Например: 100",
        default="100",
        min_length=1,
        max_length=4,
        required=True,
    )

    def __init__(self, player, on_complete: Optional[Callable] = None):
        super().__init__()
        self.player = player
        self.on_complete = on_complete
        if player:
            current_pct = int(getattr(player, "volume", 1.0) * 100)
            self.volume_input.default = str(current_pct)

    async def on_submit(self, interaction: discord.Interaction):
        val_str = self.volume_input.value.strip().replace("%", "")
        try:
            val = int(val_str)
            clamped = max(0, min(200, val))
            self.player.set_volume(clamped / 100.0)
            await interaction.response.send_message(f"🔊 Громкость установлена на **{clamped}%**", ephemeral=True)
            if self.on_complete:
                await self.on_complete()
        except ValueError:
            await interaction.response.send_message("❌ Введите целое число от 0 до 200.", ephemeral=True)


class SeekModal(discord.ui.Modal, title="⏩ Перемотка трека"):
    time_input = discord.ui.TextInput(
        label="Время (секунды или формат ММ:СС)",
        placeholder="Например: 1:30 или 90",
        min_length=1,
        max_length=8,
        required=True,
    )

    def __init__(self, player, on_complete: Optional[Callable] = None):
        super().__init__()
        self.player = player
        self.on_complete = on_complete

    async def on_submit(self, interaction: discord.Interaction):
        val = self.time_input.value.strip()
        seconds = 0
        try:
            if ":" in val:
                parts = val.split(":")
                if len(parts) == 2:
                    seconds = int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 3:
                    seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            else:
                seconds = int(val)

            if seconds < 0:
                seconds = 0

            await self.player.seek(seconds)
            m, s = divmod(seconds, 60)
            await interaction.response.send_message(f"⏩ Перемотано на **{m:02d}:{s:02d}**", ephemeral=True)
            if self.on_complete:
                await self.on_complete()
        except Exception as e:
            await interaction.response.send_message(f"❌ Неверный формат времени: {e}", ephemeral=True)


class SearchModal(discord.ui.Modal, title="🔍 Быстрый поиск трека"):
    query_input = discord.ui.TextInput(
        label="Название трека, автор или ссылка",
        placeholder="Например: Travis Scott - FE!N",
        min_length=2,
        max_length=200,
        required=True,
    )

    def __init__(self, player, on_search: Optional[Callable] = None):
        super().__init__()
        self.player = player
        self.on_search = on_search

    async def on_submit(self, interaction: discord.Interaction):
        q = self.query_input.value.strip()
        await interaction.response.defer(ephemeral=True)
        if self.on_search:
            await self.on_search(interaction, q)
        else:
            await interaction.followup.send(f"🔍 Ищем: `{q}`...", ephemeral=True)


class ThemeSelect(discord.ui.Select):
    """Dropdown for switching Liquid Glass / visionOS color themes."""

    def __init__(self, current_theme: str = "auto", on_theme_change: Optional[Callable] = None):
        options = []
        for key, th in THEMES.items():
            options.append(
                discord.SelectOption(
                    label=th.display_name,
                    value=key,
                    description=th.description[:95],
                    emoji=th.emoji,
                    default=(key == current_theme),
                )
            )

        super().__init__(
            placeholder="🎨 Выберите тему оформления...",
            min_values=1,
            max_values=1,
            options=options,
            row=2,
        )
        self.on_theme_change = on_theme_change

    async def callback(self, interaction: discord.Interaction):
        chosen = self.values[0]
        if interaction.guild_id:
            set_guild_theme(interaction.guild_id, chosen)

        th = THEMES.get(chosen, THEMES["auto"])
        await interaction.response.send_message(
            f"✨ Тема успешно переключена на **{th.emoji} {th.display_name}**!",
            ephemeral=True
        )

        if self.on_theme_change:
            await self.on_theme_change(chosen)
