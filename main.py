import os
import sys
import glob

# Ensure user-installed packages are on sys.path in isolated hosting containers
for p in glob.glob(os.path.expanduser("~/.local/lib/python*/site-packages")):
    if p not in sys.path:
        sys.path.insert(0, p)
deps_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deps")
if os.path.exists(deps_dir) and deps_dir not in sys.path:
    sys.path.insert(0, deps_dir)

import asyncio
import logging
from typing import Optional
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("bot")

# Add static ffmpeg binary paths
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
    logger.info("static-ffmpeg paths loaded successfully.")
except Exception as e:
    logger.warning(f"Could not load static-ffmpeg: {e}")

# Load Opus library for Discord voice mic streaming
try:
    import discord
    if not discord.opus.is_loaded():
        if sys.platform == "win32":
            opus_candidates = [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "opus.dll"),
                os.path.join(os.path.dirname(discord.__file__), "bin", "libopus-0.x64.dll"),
                "opus.dll",
            ]
            for c in opus_candidates:
                if os.path.exists(c):
                    try:
                        discord.opus.load_opus(c)
                        logger.info(f"Loaded Discord Voice Opus library from: {c}")
                        break
                    except Exception as e:
                        logger.warning(f"Could not load opus from {c}: {e}")
        else:
            linux_candidates = [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "libopus.so.0"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "libopus.so"),
                "libopus.so.0",
                "libopus.so",
                "/usr/lib/libopus.so.0",
                "/usr/lib/libopus.so",
                "/usr/lib/x86_64-linux-gnu/libopus.so.0",
            ]
            for c in linux_candidates:
                if os.path.exists(c):
                    try:
                        discord.opus.load_opus(c)
                        logger.info(f"Loaded Discord Voice Opus library from: {c}")
                        break
                    except Exception as e:
                        logger.warning(f"Could not load opus from {c}: {e}")

            if not discord.opus.is_loaded():
                import ctypes.util
                opus_lib = ctypes.util.find_library("opus")
                if opus_lib:
                    try:
                        discord.opus.load_opus(opus_lib)
                        logger.info(f"Loaded Discord Voice Opus library via find_library: {opus_lib}")
                    except Exception as e:
                        logger.warning(f"Could not load opus from find_library ({opus_lib}): {e}")
    logger.info(f"Discord Voice Opus status: {discord.opus.is_loaded()}")
except Exception as e:
    logger.warning(f"Failed to load opus in main.py: {e}")

import discord
from discord import app_commands
from discord.ext import commands

from music_service import MusicService
from player_manager import PlayerManager
from dm_controller import DMController
from web_server import WebServer

# Intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Initialize Services
music_service = MusicService()
player_manager = PlayerManager(bot, music_service)
dm_controller = DMController(bot, player_manager)
player_manager.set_dm_controller(dm_controller)

# Initialize Web Server
web_server = WebServer(bot, player_manager, music_service)

PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:3000")

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"Bot connected to {len(bot.guilds)} guilds.")

    # Start Web Server
    try:
        await web_server.start()
    except Exception as e:
        logger.error(f"Error starting web server: {e}")

    # Sync Slash Commands preserving Activity Entry Point
    try:
        app_id = bot.application_id or bot.user.id
        existing = await bot.http.get_global_commands(app_id)
        entry_points = [cmd for cmd in existing if cmd.get("type") == 4]

        tree_cmds = [cmd.to_dict(bot.tree) for cmd in bot.tree.get_commands()]
        all_payload = entry_points + tree_cmds

        await bot.http.bulk_upsert_global_commands(app_id, all_payload)
        logger.info(f"Successfully synced {len(tree_cmds)} slash commands and preserved {len(entry_points)} Activity entry point command(s).")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")

    # Auto-update bot avatar from static/activity_icon.jpg if available
    try:
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "activity_icon.jpg")
        if os.path.exists(icon_path):
            with open(icon_path, "rb") as f:
                avatar_bytes = f.read()
            await bot.user.edit(avatar=avatar_bytes)
            logger.info("Bot avatar synced from static/activity_icon.jpg")
    except Exception as e:
        logger.debug(f"Bot avatar auto-sync: {e}")

    # Re-attach any active voice connections across all guilds
    for g in bot.guilds:
        if getattr(g, "voice_client", None) and g.voice_client.is_connected():
            p = player_manager.get_or_create_player(g)
            p.voice_client = g.voice_client
            ch_name = g.voice_client.channel.name if g.voice_client.channel else "unknown"
            logger.info(f"Attached existing voice connection in guild '{g.name}' (room: '{ch_name}')")

    # Register persistent views for native Activity launching
    try:
        bot.add_view(PersistentActivityView())
        logger.info("Persistent Activity launch view registered successfully.")
    except Exception as e:
        logger.warning(f"Could not register PersistentActivityView: {e}")

    # Set Activity
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name=f"музыку • {PUBLIC_URL}"
    )
    await bot.change_presence(status=discord.Status.online, activity=activity)
    logger.info(f"Discord Music Mini App ready at: {PUBLIC_URL}")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # 1. If the bot itself was moved, connected or disconnected
    if member.id == bot.user.id:
        player = player_manager.get_player_by_guild_id(member.guild.id)
        if after.channel is None:
            logger.info(f"Bot was disconnected from voice channel in guild '{member.guild.name}'")
            if player:
                player._explicit_stop = True
                player._cancel_idle_watchdog()
                player.voice_client = None
                player.current_track = None
                player.is_paused = False
                player._play_generation += 1
                await player._notify_change()
            return
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            # Bot was moved to another channel on the server: smoothly update voice client and notify UI
            logger.info(f"Bot moved from '{before.channel.name}' to '{after.channel.name}' in guild '{member.guild.name}'.")
            if not player:
                player = player_manager.get_or_create_player(member.guild)
            player.voice_client = member.guild.voice_client
            await player._notify_change()
            return
        elif before.channel is None and after.channel is not None:
            logger.info(f"Bot connected to room '{after.channel.name}' in guild '{member.guild.name}'")
            if not player:
                player = player_manager.get_or_create_player(member.guild)
            player.voice_client = member.guild.voice_client
            # If idle watchdog was running or needs to start if empty
            if not player.current_track and len(player.queue) == 0:
                player._start_idle_watchdog("Очередь воспроизведения пуста")
            await player._notify_change()
            return
        return

    # 2. If users joined or left the bot's room, notify WebSocket listeners and check listeners
    guild_vc = getattr(member.guild, "voice_client", None)
    if guild_vc and guild_vc.channel:
        if before.channel == guild_vc.channel or after.channel == guild_vc.channel:
            player = player_manager.get_player_by_guild_id(member.guild.id)
            if player:
                await player._notify_change()
                human_listeners = [m for m in guild_vc.channel.members if not m.bot]
                if len(human_listeners) == 0:
                    logger.info(f"All listeners left room '{guild_vc.channel.name}' in guild '{member.guild.name}'. Starting 3-minute idle watchdog.")
                    player._start_idle_watchdog("Все пользователи вышли из голосового канала")
                elif player.is_playing:
                    player._cancel_idle_watchdog()

# ----------------- Native Discord Activity Views -----------------

class ActivityLaunchButton(discord.ui.Button):
    def __init__(self, label: str = "🚀 Открыть Mini App в Discord", custom_id: str = "musicium_launch_activity_btn", row: int = 0):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            custom_id=custom_id,
            emoji="🚀",
            row=row,
        )

    async def callback(self, interaction: discord.Interaction):
        # 1. Primary mechanism: launch the Discord Activity directly in Discord client
        try:
            await interaction.response.launch_activity()
            return
        except Exception as e:
            logger.warning(f"interaction.response.launch_activity() failed ({e}), attempting fallback invite...")

        # 2. Fallback: create an embedded application invite link for the user's/bot's voice channel
        invite_url = None
        vc = None
        if interaction.user and getattr(interaction.user, "voice", None) and interaction.user.voice.channel:
            vc = interaction.user.voice.channel
        elif interaction.guild and getattr(interaction.guild, "voice_client", None) and interaction.guild.voice_client.channel:
            vc = interaction.guild.voice_client.channel

        if vc:
            try:
                app_id = interaction.client.application_id or (interaction.client.user.id if interaction.client.user else 1555020109507199066)
                invite = await vc.create_invite(
                    target_type=discord.InviteTarget.embedded_application,
                    target_application_id=app_id,
                    max_age=3600,
                )
                invite_url = invite.url
            except Exception as inv_err:
                logger.debug(f"Could not generate activity invite: {inv_err}")

        guild_param = f"?guild_id={interaction.guild_id}" if interaction.guild_id else ""
        msg = "⚠️ Нажмите кнопку ниже для запуска Mini App в канале или откройте браузер:\n"
        if invite_url:
            msg += f"👉 **[Запустить Mini App в канале]({invite_url})**\n"
        msg += f"🌐 Веб-версия в браузере: {PUBLIC_URL}{guild_param}"

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        except Exception as send_err:
            logger.debug(f"Could not send activity launch response: {send_err}")


class PersistentActivityView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ActivityLaunchButton())

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        logger.error(f"Error in PersistentActivityView ({item}): {error}", exc_info=error)
        try:
            msg = "⚠️ Не удалось открыть активность напрямую. Попробуйте воспользоваться веб-версией."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


async def get_activity_view(guild: Optional[discord.Guild] = None, voice_channel: Optional[discord.VoiceChannel] = None) -> discord.ui.View:
    view = discord.ui.View(timeout=None)

    # 1. Native Activity launch button
    view.add_item(ActivityLaunchButton())

    # 2. Activity Voice Channel Invite Link
    target_vc = voice_channel
    if not target_vc and guild and getattr(guild, "voice_client", None) and guild.voice_client.channel:
        target_vc = guild.voice_client.channel

    if target_vc:
        try:
            app_id = bot.application_id or (bot.user.id if bot.user else 1555020109507199066)
            invite = await target_vc.create_invite(
                target_type=discord.InviteTarget.embedded_application,
                target_application_id=app_id,
                max_age=86400,
            )
            view.add_item(discord.ui.Button(
                label=f"🎮 Войти в {target_vc.name}",
                style=discord.ButtonStyle.link,
                url=invite.url,
            ))
        except Exception as e:
            logger.debug(f"Could not create activity invite for {target_vc.name}: {e}")

    # 3. External browser fallback link
    guild_param = f"?guild_id={guild.id}" if guild else ""
    view.add_item(discord.ui.Button(
        label="🌐 Браузер",
        style=discord.ButtonStyle.link,
        url=f"{PUBLIC_URL}{guild_param}",
    ))

    return view

# ----------------- Helper: Control Permissions -----------------

def check_user_can_control(interaction: discord.Interaction, player) -> Optional[str]:
    """Ensures that user is not restricted and only participants in the bot's current room or admins/requester can control playback."""
    import anticrash_service
    if anticrash_service.anticrash.is_restricted(interaction.user.id):
        info = anticrash_service.anticrash.get_restriction(interaction.user.id)
        r_reason = info.get("reason", "Превышение лимита запросов (спам)") if info else "Ограничение доступа"
        return f"⛔ Доступ к боту ограничен администратором. Причина: **{r_reason}**"

    if not player or not player.voice_client or not player.voice_client.channel:
        return None
    bot_channel = player.voice_client.channel
    human_members = [m for m in bot_channel.members if not m.bot]
    if not human_members:
        return None
    if interaction.user.id in [m.id for m in human_members]:
        return None
    if player.current_track and player.current_track.requester_id == interaction.user.id:
        return None
    if getattr(interaction.user, "guild_permissions", None) and interaction.user.guild_permissions.administrator:
        return None
    return f"⚠️ Управлять плеером могут только участники голосовой комнаты `🔊 {bot_channel.name}`!"

# ----------------- Global Slash Command Error Handler -----------------

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f"App command error in '{interaction.command.name if interaction.command else 'unknown'}': {error}", exc_info=error)
    msg = "❌ Произошла ошибка при выполнении взаимодействия."
    if isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Команда на перезарядке. Подождите {error.retry_after:.1f} сек."
    elif isinstance(error, app_commands.MissingPermissions):
        msg = "⛔ У вас недостаточно прав для этой команды."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "⛔ У бота недостаточно прав для выполнения этой команды."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

# ----------------- Slash Commands -----------------

@bot.tree.command(name="player", description="Открыть мини-приложение музыкального плеера")
async def slash_player(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        embed = discord.Embed(
            title="🎵 Музыкальный плеер Discord Mini App",
            description=(
                "Нажмите кнопку **🚀 Открыть Mini App в Discord**, чтобы открыть интерактивное мини-приложение плеера прямо внутри Discord!\n\n"
                "✨ **Возможности:**\n"
                "• Поиск в YouTube Music, SoundCloud и Яндекс Музыке\n"
                "• Воспроизведение через микрофон бота в голосовом канале\n"
                "• Управление воспроизведением и громкостью\n"
                "• Голосование за скип трека\n"
                "• Очередь и история воспроизведения\n"
                "• Автоматическое подключение к вашему голосовому каналу"
            ),
            color=0x5865F2,
        )
        embed.set_thumbnail(url=f"{PUBLIC_URL}/static/activity_icon.jpg")
        embed.set_image(url=f"{PUBLIC_URL}/static/activity_banner.jpg")
        embed.set_footer(text=f"Вызвал: {interaction.user.display_name}")

        vc = interaction.user.voice.channel if (interaction.user and interaction.user.voice) else None
        view = await get_activity_view(guild=interaction.guild, voice_channel=vc)

        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"Error in slash_player: {e}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)


@bot.tree.command(name="miniapp", description="Запустить интерактивное мини-приложение прямо в Discord")
async def slash_miniapp(interaction: discord.Interaction):
    try:
        await interaction.response.launch_activity()
    except Exception as e:
        logger.info(f"Direct launch_activity in /miniapp fallback ({e})")
        if not interaction.response.is_done():
            await slash_player.callback(interaction)


@bot.tree.command(name="play", description="Включить музыку по названию или ссылке")
@app_commands.describe(query="Название трека, артист или прямая ссылка (YouTube, SoundCloud, Яндекс)")
async def slash_play(interaction: discord.Interaction, query: str):
    import anticrash_service
    anticrash = anticrash_service.anticrash
    if anticrash.is_restricted(interaction.user.id):
        info = anticrash.get_restriction(interaction.user.id)
        r_reason = info.get("reason", "Превышение лимита запросов (спам)") if info else "Ограничение доступа"
        await interaction.response.send_message(
            f"⛔ Доступ к боту ограничен администратором.\nПричина: **{r_reason}**",
            ephemeral=True
        )
        return

    is_spam, spam_msg = await anticrash.check_and_record_request(
        user_id=interaction.user.id,
        user_name=interaction.user.display_name,
        user_avatar=interaction.user.display_avatar.url if hasattr(interaction.user, "display_avatar") else None,
        guild_id=interaction.guild_id,
        guild_name=interaction.guild.name if interaction.guild else None,
        action="slash_play"
    )
    if is_spam:
        await interaction.response.send_message(
            spam_msg or "⛔ Превышен лимит запросов к боту. Доступ временно ограничен.",
            ephemeral=True
        )
        return

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message(
            "⚠️ Вы должны находиться в голосовом канале, чтобы включить музыку!",
            ephemeral=True
        )
        return

    await interaction.response.defer()
    voice_channel = interaction.user.voice.channel
    guild = interaction.guild

    # Rule: do not move bot across channels on the server
    guild_vc = getattr(guild, "voice_client", None)
    if guild_vc and guild_vc.is_connected() and guild_vc.channel:
        if guild_vc.channel.id != voice_channel.id:
            await interaction.followup.send(
                f"⚠️ Бот уже находится в канале `🔊 {guild_vc.channel.name}`. Перемещение бота по серверу запрещено! Перейдите в комнату к боту, чтобы включить музыку.",
                ephemeral=True
            )
            return

    try:
        tracks = await music_service.search(query, source="all", limit=5)
        if not tracks:
            await interaction.followup.send(f"❌ Ничего не найдено по запросу: `{query}`", ephemeral=True)
            return

        track = tracks[0]
        track.requester_id = interaction.user.id
        track.requester_name = interaction.user.display_name

        player = player_manager.get_or_create_player(guild)
        connect_task = asyncio.create_task(player.connect_to_channel(voice_channel))
        # If search() already pre-warmed the stream cache, reuse it. Otherwise resolve in parallel.
        if not track.stream_url:
            stream_task = asyncio.create_task(music_service.get_stream_url(track))
            await asyncio.gather(connect_task, stream_task, return_exceptions=True)
            if stream_task.done() and not stream_task.cancelled():
                try:
                    resolved = stream_task.result()
                    if resolved and not isinstance(resolved, Exception):
                        track.stream_url = resolved
                except Exception:
                    pass
        else:
            await connect_task
        res = await player.enqueue(track, play_now=False)

        embed = discord.Embed(
            title="🎶 Трек добавлен!" if res.get("action") == "queued" else "▶️ Начинаем воспроизведение через микрофон!",
            description=f"**[{track.title}]({track.url})**\n👤 {track.artist} • ⏱ {track.duration_str}",
            color=0x5865F2,
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        embed.set_footer(text=f"Голосовой канал: {voice_channel.name} • Discord Mini App")

        view = await get_activity_view(guild=guild, voice_channel=voice_channel)
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"Error in slash_play: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Ошибка воспроизведения: {e}", ephemeral=True)


@bot.tree.command(name="skip", description="Пропустить текущий трек или проголосовать за скип")
async def slash_skip(interaction: discord.Interaction):
    await interaction.response.defer()
    player = player_manager.get_player_by_guild_id(interaction.guild_id)
    if not player or not player.current_track:
        await interaction.followup.send("❌ Сейчас ничего не играет!", ephemeral=True)
        return

    err = check_user_can_control(interaction, player)
    if err:
        await interaction.followup.send(err, ephemeral=True)
        return

    try:
        result = await player.skip(user_id=interaction.user.id)
        if result.get("skipped"):
            await interaction.followup.send(f"⏭️ {result.get('message', 'Трек успешно пропущен!')}")
        else:
            await interaction.followup.send(f"🗳️ {result.get('message')}")
    except Exception as e:
        logger.error(f"Error in slash_skip: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Ошибка скипа: {e}", ephemeral=True)


@bot.tree.command(name="pause", description="Поставить воспроизведение на паузу")
async def slash_pause(interaction: discord.Interaction):
    await interaction.response.defer()
    player = player_manager.get_player_by_guild_id(interaction.guild_id)
    if not player or not player.is_playing:
        await interaction.followup.send("❌ Сейчас музыка не играет.", ephemeral=True)
        return

    err = check_user_can_control(interaction, player)
    if err:
        await interaction.followup.send(err, ephemeral=True)
        return

    try:
        await player.pause()
        await interaction.followup.send("⏸️ Воспроизведение приостановлено.")
    except Exception as e:
        logger.error(f"Error in slash_pause: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Ошибка паузы: {e}", ephemeral=True)


@bot.tree.command(name="resume", description="Возобновить воспроизведение")
async def slash_resume(interaction: discord.Interaction):
    await interaction.response.defer()
    player = player_manager.get_player_by_guild_id(interaction.guild_id)
    if not player or not player.is_paused:
        await interaction.followup.send("❌ Музыка не стоит на паузе.", ephemeral=True)
        return

    err = check_user_can_control(interaction, player)
    if err:
        await interaction.followup.send(err, ephemeral=True)
        return

    try:
        await player.resume()
        await interaction.followup.send("▶️ Воспроизведение возобновлено.")
    except Exception as e:
        logger.error(f"Error in slash_resume: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Ошибка возобновления: {e}", ephemeral=True)


@bot.tree.command(name="volume", description="Установить громкость воспроизведения (0-200%)")
@app_commands.describe(percent="Уровень громкости в процентах (от 0 до 200)")
async def slash_volume(interaction: discord.Interaction, percent: int):
    await interaction.response.defer()
    player = player_manager.get_player_by_guild_id(interaction.guild_id)
    if not player or not player.is_connected:
        await interaction.followup.send("❌ Бот не подключен к голосовому каналу.", ephemeral=True)
        return

    err = check_user_can_control(interaction, player)
    if err:
        await interaction.followup.send(err, ephemeral=True)
        return

    clamped = max(0, min(200, percent))
    player.set_volume(clamped / 100.0)
    await interaction.followup.send(f"🔊 Громкость установлена на **{clamped}%**.")


@bot.tree.command(name="queue", description="Показать очередь треков")
async def slash_queue(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        player = player_manager.get_player_by_guild_id(interaction.guild_id)
        if not player or (not player.current_track and not player.queue):
            await interaction.followup.send("📜 Очередь пуста!", ephemeral=True)
            return

        lines = []
        if player.current_track:
            lines.append(f"**Сейчас играет:** [{player.current_track.title}]({player.current_track.url}) (`{player.current_track.duration_str}`)")

        if player.queue:
            lines.append("\n**Следующие треки:**")
            for i, t in enumerate(player.queue[:10], 1):
                lines.append(f"`{i}.` [{t.title}]({t.url}) - `{t.duration_str}` (от {t.requester_name})")

            if len(player.queue) > 10:
                lines.append(f"\n*...и ещё {len(player.queue) - 10} треков*")

        embed = discord.Embed(
            title=f"📜 Очередь воспроизведения ({len(player.queue)} в очереди)",
            description="\n".join(lines),
            color=0x5865F2,
        )
        vc = interaction.user.voice.channel if (interaction.user and interaction.user.voice) else None
        view = await get_activity_view(guild=interaction.guild, voice_channel=vc)
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"Error in slash_queue: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Ошибка отображения очереди: {e}", ephemeral=True)


@bot.tree.command(name="stop", description="Остановить плеер и отключить бота от голосового канала")
async def slash_stop(interaction: discord.Interaction):
    await interaction.response.defer()
    player = player_manager.get_player_by_guild_id(interaction.guild_id)
    if not player and interaction.guild and getattr(interaction.guild, "voice_client", None):
        player = player_manager.get_or_create_player(interaction.guild)

    if not player or (not player.voice_client and not getattr(interaction.guild, "voice_client", None)):
        await interaction.followup.send("❌ Бот не подключен к голосовому каналу.", ephemeral=True)
        return

    err = check_user_can_control(interaction, player)
    if err:
        await interaction.followup.send(err, ephemeral=True)
        return

    try:
        await player.stop()
        await interaction.followup.send("⏹️ Плеер остановлен, бот отключился от канала.")
    except Exception as e:
        logger.error(f"Error in slash_stop: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Ошибка остановки плеера: {e}", ephemeral=True)


@bot.tree.command(name="room", description="Показать, в какой комнате на сервере сейчас находится бот")
async def slash_room(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        guild = interaction.guild
        guild_vc = getattr(guild, "voice_client", None) if guild else None

        lines = []
        if guild_vc and guild_vc.is_connected() and guild_vc.channel:
            bot_channel = guild_vc.channel
            human_listeners = [m.display_name for m in bot_channel.members if not m.bot]
            player = player_manager.get_player_by_guild_id(guild.id) if guild else None
            track_info = f"\n🎶 Сейчас играет: **{player.current_track.title}**" if (player and player.current_track and player.is_playing) else ""
            lines.append(f"🤖 **Бот находится в комнате:** `🔊 {bot_channel.name}`{track_info}")
            if human_listeners:
                lines.append(f"👥 **Слушатели в комнате:** {', '.join(human_listeners)}")
            else:
                lines.append("👥 **Слушатели:** В комнате никого нет (бот один)")
        else:
            lines.append("🤖 **Бот не подключен** ни к одной комнате на этом сервере.")

        user_vc = interaction.user.voice.channel if (interaction.user and interaction.user.voice) else None
        if user_vc:
            lines.append(f"👤 **Вы находитесь в комнате:** `🔊 {user_vc.name}`")
        else:
            lines.append("👤 **Вы:** Не находитесь в голосовом канале")

        embed = discord.Embed(
            title=f"🔊 Голосовой статус • {guild.name if guild else 'Discord'}",
            description="\n\n".join(lines),
            color=0x5865F2 if (guild_vc and guild_vc.is_connected()) else 0x99AAB5,
        )
        vc = guild_vc.channel if (guild_vc and guild_vc.channel) else None
        view = await get_activity_view(guild=guild, voice_channel=vc)
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"Error in slash_room: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Ошибка статуса комнаты: {e}", ephemeral=True)


@bot.tree.command(name="channels", description="Список голосовых комнат на сервере и где сейчас бот")
async def slash_channels(interaction: discord.Interaction):
    await interaction.response.defer()
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ Команда доступна только на сервере.", ephemeral=True)
        return

    try:
        guild_vc = getattr(guild, "voice_client", None)
        bot_chan_id = guild_vc.channel.id if (guild_vc and guild_vc.is_connected() and guild_vc.channel) else None

        all_vcs = list(getattr(guild, "voice_channels", [])) + list(getattr(guild, "stage_channels", []))
        if not all_vcs:
            await interaction.followup.send("⚠️ На этом сервере нет голосовых каналов!", ephemeral=True)
            return

        lines = []
        for vc in all_vcs[:20]:
            is_bot = (vc.id == bot_chan_id)
            user_cnt = len([m for m in vc.members if not m.bot])
            badge = " 🟢 **[БОТ ЗДЕСЬ]**" if is_bot else ""
            lines.append(f"• `🔊 {vc.name}` — {user_cnt} участн.{badge}")

        embed = discord.Embed(
            title=f"📋 Голосовые комнаты сервера {guild.name}",
            description="\n".join(lines),
            color=0x5865F2,
        )
        embed.set_footer(text=f"Всего голосовых комнат: {len(all_vcs)}")
        vc = guild_vc.channel if (guild_vc and guild_vc.channel) else None
        view = await get_activity_view(guild=guild, voice_channel=vc)
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"Error in slash_channels: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Ошибка списка каналов: {e}", ephemeral=True)


@bot.tree.command(name="join", description="Подключить бота к голосовому каналу")
@app_commands.describe(channel="Голосовой канал, в который нужно зайти боту (необязательно)")
async def slash_join(interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None):
    await interaction.response.defer()
    target = channel
    if not target:
        if interaction.user.voice and interaction.user.voice.channel:
            target = interaction.user.voice.channel
        else:
            await interaction.followup.send("⚠️ Вы не в голосовом канале! Укажите канал или зайдите в голосовой канал.", ephemeral=True)
            return

    # Rule: do not move bot across channels on the server
    guild_vc = getattr(interaction.guild, 'voice_client', None)
    if guild_vc and guild_vc.is_connected() and guild_vc.channel:
        if guild_vc.channel.id != target.id:
            await interaction.followup.send(
                f"⚠️ Бот уже находится в канале `🔊 {guild_vc.channel.name}`. Перемещение бота по серверу запрещено!",
                ephemeral=True
            )
            return
        else:
            await interaction.followup.send(
                f"ℹ️ Бот уже находится в канале `🔊 {guild_vc.channel.name}`.",
                ephemeral=True
            )
            return

    player = player_manager.get_or_create_player(interaction.guild)
    try:
        await player.connect_to_channel(target)
        embed = discord.Embed(
            title="✅ Бот подключился к комнате!",
            description=f"Бот успешно вошел в комнату **`🔊 {target.name}`** на сервере **{interaction.guild.name}**.",
            color=0x57F287,
        )
        view = await get_activity_view(guild=interaction.guild, voice_channel=target)
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        await interaction.followup.send(f"❌ Не удалось подключиться к каналу `{target.name}`: {e}", ephemeral=True)

# ----------------- Prefix Command Fallbacks -----------------

@bot.command(name="player")
async def cmd_player(ctx):
    try:
        embed = discord.Embed(
            title="🎵 Музыкальный плеер Discord Mini App",
            description=(
                "Нажмите кнопку **🚀 Открыть Mini App в Discord**, чтобы открыть интерактивное мини-приложение плеера прямо внутри Discord!\n\n"
                "✨ **Возможности:**\n"
                "• Поиск в YouTube Music, SoundCloud и Яндекс Музыке\n"
                "• Воспроизведение через микрофон бота в голосовом канале\n"
                "• Управление воспроизведением и громкостью\n"
                "• Голосование за скип трека\n"
                "• Очередь и история воспроизведения"
            ),
            color=0x5865F2,
        )
        embed.set_thumbnail(url=f"{PUBLIC_URL}/static/activity_icon.jpg")
        embed.set_image(url=f"{PUBLIC_URL}/static/activity_banner.jpg")
        embed.set_footer(text=f"Вызвал: {ctx.author.display_name}")

        vc = ctx.author.voice.channel if (ctx.author and ctx.author.voice) else None
        view = await get_activity_view(guild=ctx.guild, voice_channel=vc)
        await ctx.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"Error in cmd_player: {e}")
        await ctx.send(f"❌ Ошибка команды: {e}")

@bot.command(name="play")
async def cmd_play(ctx, *, query: str):
    import anticrash_service
    anticrash = anticrash_service.anticrash
    if anticrash.is_restricted(ctx.author.id):
        info = anticrash.get_restriction(ctx.author.id)
        r_reason = info.get("reason", "Превышение лимита запросов (спам)") if info else "Ограничение доступа"
        await ctx.send(f"⛔ Доступ к боту ограничен администратором.\nПричина: **{r_reason}**")
        return

    is_spam, spam_msg = await anticrash.check_and_record_request(
        user_id=ctx.author.id,
        user_name=ctx.author.display_name,
        user_avatar=ctx.author.display_avatar.url if hasattr(ctx.author, "display_avatar") else None,
        guild_id=ctx.guild.id if ctx.guild else None,
        guild_name=ctx.guild.name if ctx.guild else None,
        action="cmd_play"
    )
    if is_spam:
        await ctx.send(spam_msg or "⛔ Превышен лимит запросов к боту. Доступ временно ограничен.")
        return

    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("⚠️ Вы должны находиться в голосовом канале!")
        return

    voice_channel = ctx.author.voice.channel
    guild_vc = getattr(ctx.guild, 'voice_client', None)
    if guild_vc and guild_vc.is_connected() and guild_vc.channel:
        if guild_vc.channel.id != voice_channel.id:
            await ctx.send(f"⚠️ Бот уже находится в комнате `🔊 {guild_vc.channel.name}`. Перемещение бота по серверу запрещено! Перейдите в комнату к боту.")
            return

    try:
        tracks = await music_service.search(query, source="all", limit=5)
        if not tracks:
            await ctx.send(f"❌ Ничего не найдено по запросу: `{query}`")
            return

        track = tracks[0]
        track.requester_id = ctx.author.id
        track.requester_name = ctx.author.display_name

        player = player_manager.get_or_create_player(ctx.guild)
        connect_task = asyncio.create_task(player.connect_to_channel(voice_channel))
        if not track.stream_url:
            stream_task = asyncio.create_task(music_service.get_stream_url(track))
            await asyncio.gather(connect_task, stream_task, return_exceptions=True)
            if stream_task.done() and not stream_task.cancelled():
                try:
                    resolved = stream_task.result()
                    if resolved and not isinstance(resolved, Exception):
                        track.stream_url = resolved
                except Exception:
                    pass
        else:
            await connect_task
        res = await player.enqueue(track, play_now=False)

        embed = discord.Embed(
            title="🎶 Трек добавлен!" if res.get("action") == "queued" else "▶️ Начинаем воспроизведение!",
            description=f"**[{track.title}]({track.url})**\n👤 {track.artist} • ⏱ {track.duration_str}",
            color=0x5865F2,
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        view = await get_activity_view(guild=ctx.guild, voice_channel=voice_channel)
        await ctx.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"Error in cmd_play: {e}")
        await ctx.send(f"❌ Ошибка воспроизведения: {e}")

@bot.command(name="volume")
async def cmd_volume(ctx, percent: int):
    import anticrash_service
    if anticrash_service.anticrash.is_restricted(ctx.author.id):
        await ctx.send("⛔ Доступ к боту ограничен администратором.")
        return
    player = player_manager.get_player_by_guild_id(ctx.guild.id)
    if not player or not player.is_connected:
        await ctx.send("❌ Бот не подключен к голосовому каналу.")
        return

    if player.voice_client and player.voice_client.channel:
        bot_channel = player.voice_client.channel
        human_members = [m for m in bot_channel.members if not m.bot]
        if human_members and ctx.author.id not in [m.id for m in human_members]:
            is_admin = getattr(ctx.author, "guild_permissions", None) and ctx.author.guild_permissions.administrator
            is_req = player.current_track and player.current_track.requester_id == ctx.author.id
            if not is_admin and not is_req:
                await ctx.send(f"⚠️ Управлять плеером могут только участники голосовой комнаты `🔊 {bot_channel.name}`!")
                return

    clamped = max(0, min(200, percent))
    player.set_volume(clamped / 100.0)
    await ctx.send(f"🔊 Громкость установлена на **{clamped}%**.")

@bot.command(name="skip")
async def cmd_skip(ctx):
    import anticrash_service
    if anticrash_service.anticrash.is_restricted(ctx.author.id):
        await ctx.send("⛔ Доступ к боту ограничен администратором.")
        return
    player = player_manager.get_player_by_guild_id(ctx.guild.id)
    if not player or not player.current_track:
        await ctx.send("❌ Сейчас ничего не играет!")
        return

    if player.voice_client and player.voice_client.channel:
        bot_channel = player.voice_client.channel
        human_members = [m for m in bot_channel.members if not m.bot]
        if human_members and ctx.author.id not in [m.id for m in human_members]:
            is_admin = getattr(ctx.author, "guild_permissions", None) and ctx.author.guild_permissions.administrator
            is_req = player.current_track and player.current_track.requester_id == ctx.author.id
            if not is_admin and not is_req:
                await ctx.send(f"⚠️ Управлять плеером могут только участники голосовой комнаты `🔊 {bot_channel.name}`!")
                return

    try:
        res = await player.skip(user_id=ctx.author.id)
        await ctx.send(f"⏭️ {res.get('message')}")
    except Exception as e:
        await ctx.send(f"❌ Ошибка скипа: {e}")

@bot.command(name="stop")
async def cmd_stop(ctx):
    import anticrash_service
    if anticrash_service.anticrash.is_restricted(ctx.author.id):
        await ctx.send("⛔ Доступ к боту ограничен администратором.")
        return
    player = player_manager.get_player_by_guild_id(ctx.guild.id)
    if not player and ctx.guild and getattr(ctx.guild, "voice_client", None):
        player = player_manager.get_or_create_player(ctx.guild)

    if player and player.voice_client and player.voice_client.channel:
        bot_channel = player.voice_client.channel
        human_members = [m for m in bot_channel.members if not m.bot]
        if human_members and ctx.author.id not in [m.id for m in human_members]:
            if not (getattr(ctx.author, "guild_permissions", None) and ctx.author.guild_permissions.administrator):
                await ctx.send(f"⚠️ Остановить бота могут только участники голосовой комнаты `🔊 {bot_channel.name}`!")
                return

    try:
        if player:
            await player.stop()
            await ctx.send("⏹️ Плеер остановлен, бот отключился от канала.")
        elif ctx.guild and getattr(ctx.guild, "voice_client", None):
            await ctx.guild.voice_client.disconnect(force=True)
            await ctx.send("⏹️ Бот отключился от голосового канала.")
        else:
            await ctx.send("❌ Бот не подключен к голосовому каналу.")
    except Exception as e:
        await ctx.send(f"❌ Ошибка остановки: {e}")

@bot.command(name="room")
async def cmd_room(ctx):
    try:
        guild = ctx.guild
        guild_vc = getattr(guild, "voice_client", None) if guild else None

        lines = []
        if guild_vc and guild_vc.is_connected() and guild_vc.channel:
            bot_channel = guild_vc.channel
            human_listeners = [m.display_name for m in bot_channel.members if not m.bot]
            player = player_manager.get_player_by_guild_id(guild.id) if guild else None
            track_info = f"\n🎶 Сейчас играет: **{player.current_track.title}**" if (player and player.current_track and player.is_playing) else ""
            lines.append(f"🤖 **Бот находится в комнате:** `🔊 {bot_channel.name}`{track_info}")
            if human_listeners:
                lines.append(f"👥 **Слушатели в комнате:** {', '.join(human_listeners)}")
            else:
                lines.append("👥 **Слушатели:** В комнате никого нет (бот один)")
        else:
            lines.append("🤖 **Бот не подключен** ни к одной комнате на этом сервере.")

        user_vc = ctx.author.voice.channel if (ctx.author and ctx.author.voice) else None
        if user_vc:
            lines.append(f"👤 **Вы находитесь в комнате:** `🔊 {user_vc.name}`")
        else:
            lines.append("👤 **Вы:** Не находитесь в голосовом канале")

        embed = discord.Embed(
            title=f"🔊 Голосовой статус • {guild.name if guild else 'Discord'}",
            description="\n\n".join(lines),
            color=0x5865F2 if (guild_vc and guild_vc.is_connected()) else 0x99AAB5,
        )
        vc = guild_vc.channel if (guild_vc and guild_vc.channel) else None
        view = await get_activity_view(guild=guild, voice_channel=vc)
        await ctx.send(embed=embed, view=view)
    except Exception as e:
        await ctx.send(f"❌ Ошибка статуса комнаты: {e}")

@bot.command(name="channels")
async def cmd_channels(ctx):
    try:
        guild = ctx.guild
        if not guild:
            await ctx.send("❌ Команда доступна только на сервере.")
            return

        guild_vc = getattr(guild, "voice_client", None)
        bot_chan_id = guild_vc.channel.id if (guild_vc and guild_vc.is_connected() and guild_vc.channel) else None

        all_vcs = list(getattr(guild, "voice_channels", [])) + list(getattr(guild, "stage_channels", []))
        if not all_vcs:
            await ctx.send("⚠️ На этом сервере нет голосовых каналов!")
            return

        lines = []
        for vc in all_vcs[:20]:
            is_bot = (vc.id == bot_chan_id)
            user_cnt = len([m for m in vc.members if not m.bot])
            badge = " 🟢 **[БОТ ЗДЕСЬ]**" if is_bot else ""
            lines.append(f"• `🔊 {vc.name}` — {user_cnt} участн.{badge}")

        embed = discord.Embed(
            title=f"📋 Голосовые комнаты сервера {guild.name}",
            description="\n".join(lines),
            color=0x5865F2,
        )
        embed.set_footer(text=f"Всего голосовых комнат: {len(all_vcs)}")
        vc = guild_vc.channel if (guild_vc and guild_vc.channel) else None
        view = await get_activity_view(guild=guild, voice_channel=vc)
        await ctx.send(embed=embed, view=view)
    except Exception as e:
        await ctx.send(f"❌ Ошибка списка каналов: {e}")

@bot.command(name="join")
async def cmd_join(ctx):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("⚠️ Вы должны находиться в голосовом канале!")
        return

    guild_vc = getattr(ctx.guild, 'voice_client', None)
    if guild_vc and guild_vc.is_connected() and guild_vc.channel:
        if guild_vc.channel.id != ctx.author.voice.channel.id:
            await ctx.send(f"⚠️ Бот уже находится в комнате `🔊 {guild_vc.channel.name}`. Перемещение бота по серверу запрещено! Перейдите в комнату к боту.")
            return
        else:
            await ctx.send(f"ℹ️ Бот уже подключен к вашей комнате `🔊 {guild_vc.channel.name}`.")
            return

    player = player_manager.get_or_create_player(ctx.guild)
    try:
        await player.connect_to_channel(ctx.author.voice.channel)
        await ctx.send(f"✅ Бот подключился к комнате **`🔊 {ctx.author.voice.channel.name}`**.")
    except Exception as e:
        await ctx.send(f"❌ Ошибка подключения: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f"Command error in {ctx.command}: {error}")
    await ctx.send(f"❌ Ошибка выполнения команды: {error}")


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN is missing in .env!")
        return

    try:
        await bot.start(token)
    except KeyboardInterrupt:
        logger.info("Bot shutting down...")
    finally:
        await web_server.stop()
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
