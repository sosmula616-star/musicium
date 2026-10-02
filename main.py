import os
import sys
import asyncio
import logging
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
        opus_candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "opus.dll"),
            os.path.join(os.path.dirname(discord.__file__), "bin", "libopus-0.x64.dll"),
            "opus.dll",
        ]
        for c in opus_candidates:
            if os.path.exists(c):
                discord.opus.load_opus(c)
                logger.info(f"Loaded Discord Voice Opus library from: {c}")
                break
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

    # Set Activity
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name=f"музыку • {PUBLIC_URL}"
    )
    await bot.change_presence(status=discord.Status.online, activity=activity)
    logger.info(f"Discord Music Mini App ready at: {PUBLIC_URL}")

# ----------------- Slash Commands -----------------

@bot.tree.command(name="player", description="Открыть мини-приложение музыкального плеера")
async def slash_player(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
        title="🎵 Музыкальный плеер Discord Mini App",
        description=(
            "Нажмите кнопку ниже, чтобы открыть интерактивное мини-приложение плеера!\n\n"
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
    embed.set_thumbnail(url="https://assets-global.website-files.com/6257adef93867e50d84d30e2/636e0a6a49cf127bf92de1e2_icon_clyde_blurple_RGB.png")
    embed.set_footer(text=f"Вызвал: {interaction.user.display_name}")

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="✨ Открыть Mini App Плеер",
        style=discord.ButtonStyle.link,
        url=PUBLIC_URL,
    ))

    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="miniapp", description="Ссылка на запуск мини-приложения")
async def slash_miniapp(interaction: discord.Interaction):
    await slash_player.callback(interaction)


@bot.tree.command(name="play", description="Включить музыку по названию или ссылке")
@app_commands.describe(query="Название трека, артист или прямая ссылка (YouTube, SoundCloud, Яндекс)")
async def slash_play(interaction: discord.Interaction, query: str):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message(
            "⚠️ Вы должны находиться в голосовом канале, чтобы включить музыку!",
            ephemeral=True
        )
        return

    await interaction.response.defer()
    voice_channel = interaction.user.voice.channel
    guild = interaction.guild

    tracks = await music_service.search(query, source="all", limit=1)
    if not tracks:
        await interaction.followup.send(f"❌ Ничего не найдено по запросу: `{query}`", ephemeral=True)
        return

    track = tracks[0]
    track.requester_id = interaction.user.id
    track.requester_name = interaction.user.display_name

    player = player_manager.get_or_create_player(guild)
    await player.connect_to_channel(voice_channel)
    res = await player.enqueue(track, play_now=False)

    embed = discord.Embed(
        title="🎶 Трек добавлен!" if res.get("action") == "queued" else "▶️ Начинаем воспроизведение через микрофон!",
        description=f"**[{track.title}]({track.url})**\n👤 {track.artist} • ⏱ {track.duration_str}",
        color=0x5865F2,
    )
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    embed.set_footer(text=f"Голосовой канал: {voice_channel.name} • Мини-апп: {PUBLIC_URL}")

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="📱 Открыть Mini App", style=discord.ButtonStyle.link, url=PUBLIC_URL))

    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="skip", description="Пропустить текущий трек или проголосовать за скип")
async def slash_skip(interaction: discord.Interaction):
    await interaction.response.defer()
    player = player_manager.get_player_by_guild_id(interaction.guild_id)
    if not player or not player.current_track:
        await interaction.followup.send("❌ Сейчас ничего не играет!", ephemeral=True)
        return

    result = await player.skip(user_id=interaction.user.id)
    if result.get("skipped"):
        await interaction.followup.send(f"⏭️ {result.get('message', 'Трек успешно пропущен!')}")
    else:
        await interaction.followup.send(f"🗳️ {result.get('message')}")


@bot.tree.command(name="pause", description="Поставить воспроизведение на паузу")
async def slash_pause(interaction: discord.Interaction):
    await interaction.response.defer()
    player = player_manager.get_player_by_guild_id(interaction.guild_id)
    if not player or not player.is_playing:
        await interaction.followup.send("❌ Сейчас музыка не играет.", ephemeral=True)
        return

    await player.pause()
    await interaction.followup.send("⏸️ Воспроизведение приостановлено.")


@bot.tree.command(name="resume", description="Возобновить воспроизведение")
async def slash_resume(interaction: discord.Interaction):
    await interaction.response.defer()
    player = player_manager.get_player_by_guild_id(interaction.guild_id)
    if not player or not player.is_paused:
        await interaction.followup.send("❌ Музыка не стоит на паузе.", ephemeral=True)
        return

    await player.resume()
    await interaction.followup.send("▶️ Воспроизведение возобновлено.")


@bot.tree.command(name="queue", description="Показать очередь треков")
async def slash_queue(interaction: discord.Interaction):
    await interaction.response.defer()
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
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="📱 Управлять в Mini App", style=discord.ButtonStyle.link, url=PUBLIC_URL))
    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="stop", description="Остановить плеер и отключить бота от голосового канала")
async def slash_stop(interaction: discord.Interaction):
    await interaction.response.defer()
    player = player_manager.get_player_by_guild_id(interaction.guild_id)
    if not player:
        await interaction.followup.send("❌ Бот не подключен к голосовому каналу.", ephemeral=True)
        return

    await player.stop()
    await interaction.followup.send("⏹️ Плеер остановлен, бот отключился от канала.")

# ----------------- Prefix Command Fallbacks -----------------

@bot.command(name="player")
async def cmd_player(ctx):
    await slash_player.callback(ctx)

@bot.command(name="play")
async def cmd_play(ctx, *, query: str):
    class FakeInteraction:
        def __init__(self, ctx):
            self.user = ctx.author
            self.guild = ctx.guild
            self.guild_id = ctx.guild.id
            self.response = None
        async def defer(self): pass

    # Run play logic via context
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("⚠️ Вы должны находиться в голосовом канале!")
        return

    voice_channel = ctx.author.voice.channel
    tracks = await music_service.search(query, source="all", limit=1)
    if not tracks:
        await ctx.send(f"❌ Ничего не найдено по запросу: `{query}`")
        return

    track = tracks[0]
    track.requester_id = ctx.author.id
    track.requester_name = ctx.author.display_name

    player = player_manager.get_or_create_player(ctx.guild)
    await player.connect_to_channel(voice_channel)
    res = await player.enqueue(track, play_now=False)

    embed = discord.Embed(
        title="🎶 Трек добавлен!" if res.get("action") == "queued" else "▶️ Начинаем воспроизведение!",
        description=f"**[{track.title}]({track.url})**\n👤 {track.artist} • ⏱ {track.duration_str}",
        color=0x5865F2,
    )
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)
    await ctx.send(embed=embed)

@bot.command(name="skip")
async def cmd_skip(ctx):
    player = player_manager.get_player_by_guild_id(ctx.guild.id)
    if not player or not player.current_track:
        await ctx.send("❌ Сейчас ничего не играет!")
        return
    res = await player.skip(user_id=ctx.author.id)
    await ctx.send(f"⏭️ {res.get('message')}")

@bot.command(name="stop")
async def cmd_stop(ctx):
    player = player_manager.get_player_by_guild_id(ctx.guild.id)
    if player:
        await player.stop()
        await ctx.send("⏹️ Плеер остановлен.")


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
