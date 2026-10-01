"""
app.py — Discord Music Bot & Web Player Backend
Serves Discord slash commands, voice playback, and Flask REST API / WebApp.
"""

import sys
import os
import asyncio
import threading
import json
import urllib.request as _urlreq
import urllib.error as _urlerr
from functools import wraps

# Ensure local lib directory is on path if present
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

# ── Load Environment Variables ─────────────────────────────
def _load_env_fallback():
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _load_env_fallback()

# ── Flask Imports ──────────────────────────────────────────
from flask import Flask, jsonify, request, send_from_directory, render_template, abort, Response
from flask_cors import CORS

# ── Discord Voice & Davey protocol ─────────────────────────
try:
    import davey
    print("[Voice] Davey (DAVE E2EE protocol) initialized.")
except ImportError:
    print("[Voice] Notice: 'davey' is not installed; standard Discord voice used.")

import discord
from discord.ext import commands
from discord import app_commands

# ── Internal Modules ───────────────────────────────────────
from music_search import MusicSearchEngine
from player_manager import PlayerManager
from chain_manager import ChainManager

# ═══════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════
TOKEN = os.getenv("DISCORD_TOKEN")
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://gostingmusicium.bothost.tech").rstrip('/')
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", 3000))

HARDCODED_ADMINS = {410432175373156352}
env_admins = set()
for raw_id in os.getenv("ADMIN_IDS", "").split(","):
    raw_id = raw_id.strip()
    if raw_id.isdigit():
        env_admins.add(int(raw_id))

ADMIN_IDS = HARDCODED_ADMINS | env_admins

# ═══════════════════════════════════════════════════════════
#  DISCORD CLIENT SETUP
# ═══════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

search_engine = MusicSearchEngine()
player_manager = PlayerManager(bot)
chain_manager = ChainManager(bot)


# ── BOT EVENTS ────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user} (ID: {bot.user.id})")
    try:
        # Sync slash commands with Discord API
        existing = await bot.http.get_global_commands(bot.application_id)
        entry_points = [cmd for cmd in existing if cmd.get('type') == 4]

        payload = [cmd.to_dict(tree) for cmd in tree.get_commands()]
        for ep in entry_points:
            ep_dict = {
                "name": ep["name"],
                "description": ep["description"],
                "type": ep["type"],
            }
            if "handler" in ep:
                ep_dict["handler"] = ep["handler"]
            if "contexts" in ep:
                ep_dict["contexts"] = ep["contexts"]
            if "integration_types" in ep:
                ep_dict["integration_types"] = ep["integration_types"]
            payload.append(ep_dict)

        synced = await bot.http.bulk_upsert_global_commands(bot.application_id, payload)
        print(f"✅ Synced {len(synced)} slash commands globally.")
    except Exception as e:
        print(f"⚠️ Slash command sync notice: {e}")


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member == bot.user:
        return

    # Handle voice chaining if leader switched channels
    if before.channel != after.channel:
        await chain_manager.handle_voice_move(member, before.channel, after.channel)

    # Inactivity disconnect: If alone in voice channel for 45s, stop and leave
    gp = player_manager.get_player(member.guild.id)
    if gp and gp.voice_client:
        vc = gp.voice_client
        if vc.channel and len([m for m in vc.channel.members if not m.bot]) == 0:
            await asyncio.sleep(45)
            if vc.channel and len([m for m in vc.channel.members if not m.bot]) == 0:
                print(f"[Player] Channel '{vc.channel.name}' empty. Auto-disconnecting bot.")
                await gp.stop()
                await vc.disconnect()
                player_manager.remove_player(member.guild.id)


# ── HELPER VIEW ───────────────────────────────────────────
class PlayerButtonView(discord.ui.View):
    def __init__(self, client_id: str, invite_url: str = None):
        super().__init__(timeout=None)
        url = invite_url or (f"https://discord.com/activities/{client_id}" if client_id else PUBLIC_URL)
        self.add_item(discord.ui.Button(
            label="🎧 Открыть Web Player",
            style=discord.ButtonStyle.link,
            url=url
        ))


# ── DISCORD SLASH COMMANDS ────────────────────────────────
@tree.command(name="play", description="Включить музыку (поиск YouTube / SoundCloud или прямая ссылка)")
@app_commands.describe(query="Название трека, имя автора или ссылка")
async def play_command(interaction: discord.Interaction, query: str):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ Зайдите в голосовой канал!", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    voice_channel = interaction.user.voice.channel
    guild_id = interaction.guild_id

    results = await search_engine.search(query, limit=5)
    if not results:
        await interaction.followup.send("❌ Ничего не найдено по вашему запросу!")
        return

    track = results[0]
    guild_player = player_manager.get_or_create(guild_id, interaction.channel)
    await guild_player.connect(voice_channel)
    await guild_player.add_to_queue(track, interaction.user)

    embed = discord.Embed(
        title="🎵 Добавлено в очередь",
        description=f"**{track['title']}**\n*{track['artist']}*",
        color=0x8b5cf6
    )
    if track.get("thumbnail"):
        embed.set_thumbnail(url=track["thumbnail"])
    embed.add_field(name="Платформа", value=f"{track.get('platform_emoji', '🎵')} {track.get('platform', 'Web')}", inline=True)
    embed.add_field(name="Длительность", value=track.get("duration_str", "N/A"), inline=True)
    embed.set_footer(text=f"Запросил: {interaction.user.display_name}")

    view = PlayerButtonView(CLIENT_ID)
    await interaction.followup.send(embed=embed, view=view)


@tree.command(name="skip", description="Пропустить текущий трек")
async def skip_command(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.is_playing():
        await interaction.response.send_message("❌ Сейчас ничего не играет!", ephemeral=True)
        return
    await gp.skip()
    await interaction.response.send_message("⏭️ Трек пропущен!")


@tree.command(name="pause", description="Поставить воспроизведение на паузу")
async def pause_command(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.is_playing() or gp.is_paused:
        await interaction.response.send_message("❌ Музыка не играет или уже на паузе!", ephemeral=True)
        return
    await gp.pause()
    await interaction.response.send_message("⏸️ Воспроизведение приостановлено!")


@tree.command(name="resume", description="Возобновить воспроизведение музыки")
async def resume_command(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.is_paused:
        await interaction.response.send_message("❌ Музыка не стоит на паузе!", ephemeral=True)
        return
    await gp.resume()
    await interaction.response.send_message("▶️ Воспроизведение возобновлено!")


@tree.command(name="stop", description="Остановить плеер и выйти из канала")
async def stop_command(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp:
        await interaction.response.send_message("❌ Бот не находится в голосовом канале!", ephemeral=True)
        return
    await gp.stop()
    if gp.voice_client:
        await gp.voice_client.disconnect()
    player_manager.remove_player(interaction.guild_id)
    await interaction.response.send_message("⏹️ Воспроизведение остановлено, бот покинул канал.")


@tree.command(name="nowplaying", description="Показать информацию о текущем треке")
async def nowplaying_command(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.current_track:
        await interaction.response.send_message("❌ Сейчас ничего не играет!", ephemeral=True)
        return

    track = gp.current_track
    elapsed = gp.elapsed_seconds
    total = track.get("duration", 0)

    from music_search import format_duration
    elapsed_str = format_duration(elapsed)
    total_str = track.get("duration_str", "N/A")

    # Simple text progress bar
    if total > 0:
        pct = min(1.0, elapsed / total)
        bar_len = 16
        filled = int(pct * bar_len)
        bar = "▬" * filled + "🔘" + "▬" * max(0, bar_len - filled - 1)
    else:
        bar = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

    status = "⏸️ Пауза" if gp.is_paused else "▶️ Играет"
    embed = discord.Embed(
        title=f"{status}: {track.get('title')}",
        description=f"**{track.get('artist')}**\n\n`{elapsed_str}` {bar} `{total_str}`",
        color=0x8b5cf6
    )
    if track.get("thumbnail"):
        embed.set_thumbnail(url=track["thumbnail"])
    embed.add_field(name="Источник", value=track.get("platform", "Unknown"), inline=True)
    embed.add_field(name="Громкость", value=f"{int(gp.volume * 100)}%", inline=True)
    embed.add_field(name="Режим повтора", value=gp.loop_mode.capitalize(), inline=True)

    await interaction.response.send_message(embed=embed, view=PlayerButtonView(CLIENT_ID))


@tree.command(name="queue", description="Показать текущую очередь треков")
async def queue_command(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or (not gp.queue and not gp.current_track):
        await interaction.response.send_message("📭 Очередь пуста!", ephemeral=True)
        return

    lines = []
    if gp.current_track:
        lines.append(f"▶️ **Сейчас:** {gp.current_track.get('title')} — *{gp.current_track.get('artist')}*")

    if gp.queue:
        lines.append("\n**В очереди:**")
        for i, item in enumerate(list(gp.queue)[:10], start=1):
            lines.append(f"`{i}.` {item.get('platform_emoji', '🎵')} **{item.get('title')}** — *{item.get('artist')}*")

        if len(gp.queue) > 10:
            lines.append(f"\n*...и ещё {len(gp.queue) - 10} треков*")

    embed = discord.Embed(
        title="🎶 Список треков",
        description="\n".join(lines),
        color=0x8b5cf6
    )
    await interaction.response.send_message(embed=embed, view=PlayerButtonView(CLIENT_ID))


@tree.command(name="chain", description="Привязать участника к ведущему (автоматически перемещаться за ним)")
@app_commands.describe(target="Кого привязать", follow="За кем следовать (оставьте пустым чтобы отвязать)")
async def chain_command(interaction: discord.Interaction, target: discord.Member, follow: discord.Member = None):
    is_admin = interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.move_members
    if not is_admin:
        await interaction.response.send_message("❌ У вас нет прав на перемещение участников!", ephemeral=True)
        return

    if follow is None:
        removed = chain_manager.remove_chain(interaction.guild_id, target.id)
        msg = f"🔓 **{target.display_name}** отвязан." if removed else "ℹ️ Участник не был привязан."
        await interaction.response.send_message(msg)
        return

    if target.id == follow.id:
        await interaction.response.send_message("❌ Нельзя привязать пользователя к самому себе!", ephemeral=True)
        return

    chain_manager.add_chain(interaction.guild_id, target.id, follow.id)
    embed = discord.Embed(
        title="🔗 Связка активна",
        description=f"**{target.display_name}** теперь следует за **{follow.display_name}**",
        color=0xec4899
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="chains", description="Показать активные голосовые связки")
async def chains_command(interaction: discord.Interaction):
    chains = chain_manager.get_guild_chains(interaction.guild_id)
    if not chains:
        await interaction.response.send_message("📭 Активных голосовых связок нет.", ephemeral=True)
        return

    items = []
    for follower_id, leader_id in chains.items():
        f = interaction.guild.get_member(follower_id)
        l = interaction.guild.get_member(leader_id)
        f_name = f.display_name if f else str(follower_id)
        l_name = l.display_name if l else str(leader_id)
        items.append(f"🔗 **{f_name}** ➜ **{l_name}**")

    embed = discord.Embed(title="⛓️ Активные связки сервера", description="\n".join(items), color=0xec4899)
    await interaction.response.send_message(embed=embed)


@tree.command(name="unchain", description="Отвязать участника от голосовой связки")
@app_commands.describe(target="Кого отвязать")
async def unchain_command(interaction: discord.Interaction, target: discord.Member):
    is_admin = interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.move_members
    if not is_admin:
        await interaction.response.send_message("❌ Нет прав!", ephemeral=True)
        return

    if chain_manager.remove_chain(interaction.guild_id, target.id):
        await interaction.response.send_message(f"🔓 **{target.display_name}** успешно отвязан.")
    else:
        await interaction.response.send_message(f"ℹ️ **{target.display_name}** не был привязан.", ephemeral=True)


@tree.command(name="player", description="Открыть интерактивный Web Player / Discord Activity")
async def player_command_call(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    invite_url = None
    vc = interaction.user.voice.channel if (interaction.user.voice and interaction.user.voice.channel) else None
    if not vc and interaction.guild and interaction.guild.voice_channels:
        vc = interaction.guild.voice_channels[0]

    if vc and CLIENT_ID:
        try:
            invite = await vc.create_invite(
                max_age=86400,
                max_uses=50,
                unique=True,
                target_type=discord.InviteTarget.embedded_application,
                target_application_id=int(CLIENT_ID),
            )
            invite_url = invite.url
        except Exception as e:
            print(f"[player_cmd] Activity invite generation notice: {e}")

    embed = discord.Embed(
        title="🎧 Discord Music Player",
        description="Нажмите кнопку ниже, чтобы запустить интерактивный аудиоплеер прямо внутри Discord или в браузере!",
        color=0x8b5cf6
    )
    if vc:
        embed.add_field(name="Голосовой канал", value=f"🔊 {vc.name}", inline=True)
    embed.set_footer(text="Pure Audio Stream • YouTube & SoundCloud • Ultra-Low Latency")

    view = PlayerButtonView(CLIENT_ID, invite_url)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


# ═══════════════════════════════════════════════════════════
#  FLASK WEB APP & REST API
# ═══════════════════════════════════════════════════════════
STATIC_DIR = os.path.join(os.path.dirname(__file__), "webapp", "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "webapp")

app = Flask(__name__, static_folder=STATIC_DIR, template_folder=TEMPLATES_DIR)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)


class DiscordAppMiddleware:
    """Handles Discord Activity proxy path prefix (/.proxy) and preflight requests."""
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path.startswith('/.proxy'):
            new_path = path[len('/.proxy'):]
            if not new_path.startswith('/'):
                new_path = '/' + new_path
            environ['PATH_INFO'] = new_path

        if environ.get('REQUEST_METHOD') == 'OPTIONS':
            headers = [
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS, PATCH'),
                ('Access-Control-Allow-Headers', '*'),
                ('Access-Control-Max-Age', '86400'),
            ]
            start_response('200 OK', headers)
            return [b'{"ok":true}']

        return self.wsgi_app(environ, start_response)


app.wsgi_app = DiscordAppMiddleware(app.wsgi_app)


def run_async(coro):
    """Execute coroutine safely on Discord bot loop from Flask WSGI thread."""
    fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    return fut.result(timeout=25)


def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        uid_str = request.headers.get("X-User-Id", "")
        try:
            uid = int(uid_str)
        except (ValueError, TypeError):
            abort(403)
        if uid not in ADMIN_IDS:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


@app.after_request
def apply_security_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "*"
    # Remove X-Frame-Options to allow Discord Activity iframe embedding
    response.headers.pop("X-Frame-Options", None)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: *; "
        "frame-ancestors https://discord.com https://*.discord.com https://*.discordsays.com *; "
        "img-src * data: blob:; "
        "media-src * blob: data:; "
        "connect-src *; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net *; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com *; "
        "font-src 'self' data: fonts.gstatic.com *;"
    )
    return response


# ── Frontend HTML and Static Routes ─────────────────────────
@app.route("/")
@app.route("/player")
@app.route("/.proxy/")
@app.route("/.proxy/player")
def serve_index():
    return render_template("index.html", public_url=PUBLIC_URL, client_id=CLIENT_ID)


@app.route("/static/<path:filename>")
@app.route("/.proxy/static/<path:filename>")
def serve_static_asset(filename):
    return send_from_directory(STATIC_DIR, filename)


# ── Thumbnail Image Proxy ──────────────────────────────────
@app.route("/api/thumb", methods=["GET"])
@app.route("/.proxy/api/thumb", methods=["GET"])
def proxy_thumbnail():
    url = request.args.get("url", "").strip()
    if not url or not url.startswith("http"):
        abort(400)
    try:
        req = _urlreq.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.youtube.com/",
        })
        with _urlreq.urlopen(req, timeout=6) as resp:
            data = resp.read()
            content_type = resp.headers.get_content_type() or "image/jpeg"
        return Response(data, content_type=content_type, headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        })
    except Exception:
        abort(404)


# ── Public Guilds & Voice Channels ─────────────────────────
@app.route("/api/guilds", methods=["GET", "OPTIONS"])
@app.route("/.proxy/api/guilds", methods=["GET", "OPTIONS"])
def api_guilds():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    guild_list = []
    for g in bot.guilds:
        gp = player_manager.get_player(g.id)
        vcs = []
        try:
            for vc in g.voice_channels:
                vcs.append({
                    "id": str(vc.id),
                    "name": vc.name,
                    "user_count": len([m for m in vc.members if not m.bot])
                })
        except Exception:
            pass

        guild_list.append({
            "id": str(g.id),
            "name": g.name,
            "icon": str(g.icon.url) if g.icon else None,
            "has_player": gp is not None,
            "playing": gp.is_playing() if gp else False,
            "voice_channels": vcs,
        })
    return jsonify({"guilds": guild_list})


# ── Player API Endpoints ───────────────────────────────────
@app.route("/api/player/<int:guild_id>", methods=["GET", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>", methods=["GET", "OPTIONS"])
def api_player_state(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    gp = player_manager.get_player(guild_id)
    if not gp:
        return jsonify({
            "playing": False,
            "paused": False,
            "volume": 0.5,
            "loop_mode": "none",
            "elapsed": 0,
            "current": None,
            "queue": [],
            "queue_count": 0,
            "history_count": 0,
        })
    return jsonify(gp.get_state())


@app.route("/api/player/<int:guild_id>/pause", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>/pause", methods=["POST", "OPTIONS"])
def api_player_pause(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    gp = player_manager.get_player(guild_id)
    if not gp:
        return jsonify({"error": "No active player for guild"}), 404
    run_async(gp.pause())
    return jsonify({"ok": True, "state": gp.get_state()})


@app.route("/api/player/<int:guild_id>/resume", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>/resume", methods=["POST", "OPTIONS"])
def api_player_resume(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    guild = bot.get_guild(guild_id)
    text_ch = guild.text_channels[0] if (guild and guild.text_channels) else None
    gp = player_manager.get_or_create(guild_id, text_ch)

    if not gp.voice_client or not gp.voice_client.is_connected():
        target_vc = None
        if guild:
            for vc in guild.voice_channels:
                if any(not m.bot for m in vc.members):
                    target_vc = vc
                    break
            if not target_vc and guild.voice_channels:
                target_vc = guild.voice_channels[0]
        if target_vc:
            run_async(gp.connect(target_vc))

    run_async(gp.resume())
    return jsonify({"ok": True, "state": gp.get_state()})


@app.route("/api/player/<int:guild_id>/skip", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>/skip", methods=["POST", "OPTIONS"])
def api_player_skip(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    gp = player_manager.get_player(guild_id)
    if not gp:
        return jsonify({"error": "No active player"}), 404
    run_async(gp.skip())
    return jsonify({"ok": True, "state": gp.get_state()})


@app.route("/api/player/<int:guild_id>/prev", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>/prev", methods=["POST", "OPTIONS"])
def api_player_prev(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    gp = player_manager.get_player(guild_id)
    if not gp:
        return jsonify({"error": "No active player"}), 404
    success = run_async(gp.prev())
    if not success:
        return jsonify({"error": "No previous track history"}), 400
    return jsonify({"ok": True, "state": gp.get_state()})


@app.route("/api/player/<int:guild_id>/stop", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>/stop", methods=["POST", "OPTIONS"])
def api_player_stop(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    gp = player_manager.get_player(guild_id)
    if not gp:
        return jsonify({"error": "No active player"}), 404

    async def _do_stop():
        await gp.stop()
        if gp.voice_client:
            await gp.voice_client.disconnect()
        player_manager.remove_player(guild_id)

    run_async(_do_stop())
    return jsonify({"ok": True})


@app.route("/api/player/<int:guild_id>/volume", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>/volume", methods=["POST", "OPTIONS"])
def api_player_volume(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    guild = bot.get_guild(guild_id)
    text_ch = guild.text_channels[0] if (guild and guild.text_channels) else None
    gp = player_manager.get_or_create(guild_id, text_ch)
    data = request.get_json(silent=True) or {}
    try:
        vol = float(data.get("volume", 0.5))
        gp.set_volume(vol)
        return jsonify({"ok": True, "volume": gp.volume})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/player/<int:guild_id>/loop", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>/loop", methods=["POST", "OPTIONS"])
def api_player_loop(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    gp = player_manager.get_player(guild_id)
    if not gp:
        return jsonify({"error": "No active player"}), 404
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "none")
    if mode not in ("none", "track", "queue"):
        return jsonify({"error": "Invalid loop mode"}), 400
    gp.loop_mode = mode
    return jsonify({"ok": True, "loop_mode": mode})


@app.route("/api/player/<int:guild_id>/seek", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>/seek", methods=["POST", "OPTIONS"])
def api_player_seek(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    gp = player_manager.get_player(guild_id)
    if not gp or not gp.current_track:
        return jsonify({"error": "No track playing"}), 404
    data = request.get_json(silent=True) or {}
    try:
        seconds = float(data.get("seconds", 0))
        run_async(gp.seek(seconds))
        return jsonify({"ok": True, "elapsed": gp.elapsed_seconds})
    except Exception as err:
        return jsonify({"error": str(err)}), 400


# ── Search & Play API ──────────────────────────────────────
@app.route("/api/search", methods=["GET", "OPTIONS"])
@app.route("/.proxy/api/search", methods=["GET", "OPTIONS"])
def api_search():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})
    try:
        results = run_async(search_engine.search(q, limit=12))
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/play", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/play", methods=["POST", "OPTIONS"])
def api_play_track():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    guild_id = int(data.get("guild_id", 0))
    channel_id = int(data.get("channel_id", 0))
    track = data.get("track")
    user_id = data.get("user_id")

    if not track:
        return jsonify({"error": "Track payload missing"}), 400

    async def _do_play():
        target_channel = None
        guild = None
        cur_guild_id = guild_id

        # 1. Resolve channel_id directly (vital for Discord Mini App Activities)
        if channel_id:
            try:
                ch = bot.get_channel(channel_id)
                if not ch:
                    try:
                        ch = await bot.fetch_channel(channel_id)
                    except Exception:
                        ch = None
                if ch:
                    if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                        target_channel = ch
                        guild = ch.guild
                        cur_guild_id = guild.id
                    elif hasattr(ch, "guild") and ch.guild:
                        guild = ch.guild
                        cur_guild_id = guild.id
            except Exception as e:
                print(f"[API play] Error resolving channel {channel_id}: {e}")

        # 2. Resolve guild by guild_id
        if not guild and cur_guild_id:
            guild = bot.get_guild(cur_guild_id)
            if not guild:
                try:
                    guild = await bot.fetch_guild(cur_guild_id)
                except Exception:
                    guild = None

        # 3. Fallback to first guild
        if not guild:
            if bot.guilds:
                guild = bot.guilds[0]
                cur_guild_id = guild.id
            else:
                return {"error": "Бот не подключен ни к одному серверу Discord", "status": 400}

        # 4. Try user voice channel
        if not target_channel and user_id:
            try:
                member = guild.get_member(int(user_id))
                if not member:
                    try:
                        member = await guild.fetch_member(int(user_id))
                    except Exception:
                        pass
                if member and member.voice and member.voice.channel:
                    target_channel = member.voice.channel
            except Exception:
                pass

        # 5. Try channel bot is currently in
        gp_existing = player_manager.get_player(guild.id)
        if not target_channel and gp_existing and gp_existing.voice_client and gp_existing.voice_client.is_connected():
            target_channel = gp_existing.voice_client.channel

        # 6. Try voice channel with human members
        if not target_channel:
            for vc in guild.voice_channels:
                if any(not m.bot for m in vc.members):
                    target_channel = vc
                    break

        # 7. Fallback to first voice channel
        if not target_channel and guild.voice_channels:
            target_channel = guild.voice_channels[0]

        if not target_channel:
            return {"error": "Голосовой канал не найден. Зайдите в голосовой канал!", "status": 400}

        text_channel = guild.text_channels[0] if guild.text_channels else None
        gp = player_manager.get_or_create(guild.id, text_channel)
        await gp.connect(target_channel)

        track_data = dict(track)
        track_data["requester"] = "Discord Web Player"
        await gp.add_to_queue(track_data)

        return {
            "ok": True,
            "guild_id": str(guild.id),
            "channel_id": str(target_channel.id),
            "channel": target_channel.name,
            "status": 200,
        }

    try:
        res = run_async(_do_play())
        status_code = res.pop("status", 200)
        return jsonify(res), status_code
    except Exception as e:
        print(f"[API play] Playback initiation error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Admin Panel API ────────────────────────────────────────
@app.route("/api/admin/check")
@app.route("/.proxy/api/admin/check")
def api_admin_check():
    try:
        uid = int(request.headers.get("X-User-Id", ""))
        return jsonify({"is_admin": uid in ADMIN_IDS})
    except Exception:
        return jsonify({"is_admin": False})


@app.route("/api/admin/guilds")
@app.route("/.proxy/api/admin/guilds")
@require_admin
def api_admin_guilds():
    guilds_data = []
    for g in bot.guilds:
        gp = player_manager.get_player(g.id)
        guilds_data.append({
            "id": str(g.id),
            "name": g.name,
            "member_count": g.member_count,
            "icon": str(g.icon.url) if g.icon else None,
            "has_player": gp is not None,
            "player_state": gp.get_state() if gp else None,
        })
    return jsonify({"guilds": guilds_data})


@app.route("/api/admin/chains/<int:guild_id>")
@app.route("/.proxy/api/admin/chains/<int:guild_id>")
@require_admin
def api_admin_chains(guild_id):
    chains = chain_manager.get_guild_chains(guild_id)
    guild = bot.get_guild(guild_id)
    out = []
    for fid, lid in chains.items():
        f = guild.get_member(fid) if guild else None
        l = guild.get_member(lid) if guild else None
        out.append({
            "follower_id": str(fid),
            "follower_name": f.display_name if f else str(fid),
            "leader_id": str(lid),
            "leader_name": l.display_name if l else str(lid),
        })
    return jsonify({"chains": out})


@app.route("/api/admin/chains/<int:guild_id>", methods=["DELETE", "OPTIONS"])
@app.route("/.proxy/api/admin/chains/<int:guild_id>", methods=["DELETE", "OPTIONS"])
@require_admin
def api_admin_delete_chain(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    fid = int((request.get_json(silent=True) or {}).get("follower_id", 0))
    removed = chain_manager.remove_chain(guild_id, fid)
    return jsonify({"ok": removed})


@app.route("/api/admin/stop/<int:guild_id>", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/admin/stop/<int:guild_id>", methods=["POST", "OPTIONS"])
@require_admin
def api_admin_stop_guild(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    gp = player_manager.get_player(guild_id)
    if not gp:
        return jsonify({"error": "No player"}), 404

    async def _admin_stop():
        await gp.stop()
        if gp.voice_client:
            await gp.voice_client.disconnect()
        player_manager.remove_player(guild_id)

    run_async(_admin_stop())
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════
#  BOT BACKGROUND THREAD
# ═══════════════════════════════════════════════════════════
def _start_bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if not TOKEN:
        print("❌ Ошибка: DISCORD_TOKEN отсутствует в конфигурации!")
        return
    loop.run_until_complete(bot.start(TOKEN))


_bot_worker = threading.Thread(target=_start_bot_thread, daemon=True, name="discord-bot-worker")
_bot_worker.start()

# ═══════════════════════════════════════════════════════════
#  SERVER LAUNCH
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"🚀 Запуск веб-сервера на {WEB_HOST}:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False, threaded=True)
