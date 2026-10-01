"""
app.py — Единая точка входа для bothost.tech
Bothost запускает этот файл через uvicorn.
Бот стартует в фоновом потоке, Flask отдаёт API и статику.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

import asyncio
import threading
import json
from functools import wraps

def _load_env_fallback():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
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


# ── Flask ─────────────────────────────────────────────────
from flask import Flask, jsonify, request, send_from_directory, render_template, abort, Response
from flask_cors import CORS
import urllib.request as _urlreq
import urllib.error as _urlerr

# ── Discord ───────────────────────────────────────────────
try:
    import davey
    print("[Voice] Davey (DAVE E2EE protocol) library loaded successfully.")
except ImportError:
    print("[Voice] Warning: 'davey' library is not installed. Install it with 'pip install davey' for Discord voice support.")

import discord
from discord.ext import commands
from discord import app_commands

# ── Bot modules ───────────────────────────────────────────
from music_search import MusicSearchEngine
from player_manager import PlayerManager
from chain_manager import ChainManager

# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════
TOKEN      = os.getenv("DISCORD_TOKEN")
CLIENT_ID  = os.getenv("DISCORD_CLIENT_ID")
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://gostingmusicium.bothost.tech")
WEB_HOST   = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT   = int(os.getenv("WEB_PORT", 3000))

HARDCODED_ADMIN_IDS = {
    410432175373156352,   # Владелец бота
}

env_admins = set()
for _aid in os.getenv("ADMIN_IDS", "").split(","):
    _aid = _aid.strip()
    if _aid.isdigit():
        env_admins.add(int(_aid))

ADMIN_IDS = HARDCODED_ADMIN_IDS | env_admins

# ═══════════════════════════════════════════════════════════
#  DISCORD BOT SETUP
# ═══════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.voice_states = True   # нужен для /chain и автовыхода
intents.guilds       = True   # нужен для работы с серверами
# intents.members = True       # ПРИВИЛЕГИРОВАННЫЙ — включи в Dev Portal если нужен
# intents.message_content = True  # ПРИВИЛЕГИРОВАННЫЙ — не нужен (слэш-команды)

bot            = commands.Bot(command_prefix="!", intents=intents)
tree           = bot.tree
search_engine  = MusicSearchEngine()
player_manager = PlayerManager(bot)
chain_manager  = ChainManager(bot)

# ── BOT EVENTS ────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Sync error: {e}")


@bot.event
async def on_voice_state_update(member, before, after):
    if member == bot.user:
        return
    if before.channel != after.channel:
        await chain_manager.handle_voice_move(member, before.channel, after.channel)

    guild_player = player_manager.get_player(member.guild.id)
    if guild_player and guild_player.voice_client:
        vc = guild_player.voice_client
        if vc.channel and len([m for m in vc.channel.members if not m.bot]) == 0:
            await asyncio.sleep(30)
            if vc.channel and len([m for m in vc.channel.members if not m.bot]) == 0:
                await guild_player.stop()
                await vc.disconnect()

# ── SLASH COMMANDS ────────────────────────────────────────
@tree.command(name="play", description="Найти и включить музыку из YouTube/Spotify/SoundCloud")
@app_commands.describe(query="Название трека, исполнитель или ссылка")
async def play_cmd(interaction: discord.Interaction, query: str):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ Зайди в голосовой канал!", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    voice_channel = interaction.user.voice.channel
    guild_id      = interaction.guild_id

    results = await search_engine.search(query, limit=5)
    if not results:
        await interaction.followup.send("❌ Ничего не найдено!")
        return

    track        = results[0]
    guild_player = player_manager.get_or_create(guild_id, interaction.channel)
    await guild_player.connect(voice_channel)
    await guild_player.add_to_queue(track, interaction.user)

    embed = discord.Embed(
        title       = "🎵 Добавлено в очередь",
        description = f"**{track['title']}**\n{track['artist']}",
        color       = 0x9B59B6
    )
    embed.set_thumbnail(url=track.get('thumbnail', ''))
    embed.add_field(name="Платформа",   value=track['platform_emoji'] + " " + track['platform'], inline=True)
    embed.add_field(name="Длительность", value=track.get('duration_str', 'N/A'),                 inline=True)

    view = PlayerView(guild_id, CLIENT_ID)
    await interaction.followup.send(embed=embed, view=view)


@tree.command(name="skip", description="Пропустить текущий трек")
async def skip_cmd(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.is_playing():
        await interaction.response.send_message("❌ Сейчас ничего не играет!", ephemeral=True)
        return
    await gp.skip()
    await interaction.response.send_message("⏭️ Пропущено!")


@tree.command(name="stop", description="Остановить музыку и покинуть канал")
async def stop_cmd(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp:
        await interaction.response.send_message("❌ Бот не в канале!", ephemeral=True)
        return
    await gp.stop()
    if gp.voice_client:
        await gp.voice_client.disconnect()
    player_manager.remove_player(interaction.guild_id)
    await interaction.response.send_message("⏹️ Остановлено!")


@tree.command(name="queue", description="Показать текущую очередь треков")
async def queue_cmd(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.queue:
        await interaction.response.send_message("📭 Очередь пуста!", ephemeral=True)
        return

    lines = [
        f"`{i}.` {t['platform_emoji']} **{t['title']}** — {t['artist']}"
        for i, t in enumerate(list(gp.queue)[:10], 1)
    ]
    embed = discord.Embed(title="🎶 Очередь", description="\n".join(lines), color=0x9B59B6)
    if gp.current_track:
        embed.set_footer(text=f"▶️ Сейчас: {gp.current_track['title']}")
    await interaction.response.send_message(embed=embed, view=PlayerView(interaction.guild_id, CLIENT_ID))


@tree.command(name="chain", description="Привязать пользователя к другому (следовать за ним)")
@app_commands.describe(target="Кого привязать", follow="За кем следовать (пусто = отвязать)")
async def chain_cmd(interaction: discord.Interaction, target: discord.Member, follow: discord.Member = None):
    is_admin = interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.move_members
    if not is_admin:
        await interaction.response.send_message("❌ Нет прав!", ephemeral=True)
        return
    if follow is None:
        removed = chain_manager.remove_chain(interaction.guild_id, target.id)
        msg = f"🔓 **{target.display_name}** отвязан." if removed else f"ℹ️ Не был привязан."
        await interaction.response.send_message(msg)
        return
    if target.id == follow.id:
        await interaction.response.send_message("❌ Нельзя привязать к самому себе!", ephemeral=True)
        return
    chain_manager.add_chain(interaction.guild_id, target.id, follow.id)
    embed = discord.Embed(
        title       = "🔗 Цепочка создана",
        description = f"**{target.display_name}** следует за **{follow.display_name}**",
        color       = 0xE91E63
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="chains", description="Показать активные привязки")
async def chains_cmd(interaction: discord.Interaction):
    is_admin = interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.move_members
    if not is_admin:
        await interaction.response.send_message("❌ Нет прав!", ephemeral=True)
        return
    chains = chain_manager.get_guild_chains(interaction.guild_id)
    if not chains:
        await interaction.response.send_message("📭 Нет активных привязок.", ephemeral=True)
        return
    lines = []
    for tid, fid in chains.items():
        t = interaction.guild.get_member(tid)
        f = interaction.guild.get_member(fid)
        lines.append(f"🔗 **{t.display_name if t else tid}** → **{f.display_name if f else fid}**")
    embed = discord.Embed(title="⛓️ Активные цепочки", description="\n".join(lines), color=0xE91E63)
    await interaction.response.send_message(embed=embed)


@tree.command(name="unchain", description="Отвязать пользователя от цепочки слежения")
@app_commands.describe(target="Пользователь которого нужно отвязать")
async def unchain_cmd(interaction: discord.Interaction, target: discord.Member):
    is_admin = interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.move_members
    if not is_admin:
        await interaction.response.send_message("❌ Нет прав! Нужно право 'Перемещать участников'.", ephemeral=True)
        return

    removed = chain_manager.remove_chain(interaction.guild_id, target.id)

    if removed:
        embed = discord.Embed(
            title       = "🔓 Цепочка удалена",
            description = f"**{target.display_name}** больше не следует ни за кем.",
            color       = 0x2ECC71
        )
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(
            f"ℹ️ **{target.display_name}** не был привязан ни к кому.",
            ephemeral=True
        )


@tree.command(name="player", description="Открыть плеер (Discord Mini App)")
async def player_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎵 Music Player — Discord Mini App",
        description="Запустите плеер прямо внутри Discord!",
        color=0x9B59B6
    )
    embed.set_footer(text="Нажмите 🚀 чтобы открыть плеер")

    # Generate a real Activity invite link if the user is in a voice channel
    invite_url = None
    if CLIENT_ID:
        try:
            vc = interaction.user.voice.channel if interaction.user.voice else None
            if not vc:
                # Fall back to the first voice channel in the guild
                guild = interaction.guild
                if guild and guild.voice_channels:
                    vc = guild.voice_channels[0]

            if vc:
                invite = await vc.create_invite(
                    max_age=86400,
                    max_uses=50,
                    unique=True,
                    target_type=discord.InviteTarget.embedded_application,
                    target_application_id=int(CLIENT_ID),
                )
                invite_url = invite.url
        except Exception as e:
            print(f"[player_cmd] Could not create activity invite: {e}")

    view = PlayerView(interaction.guild_id, CLIENT_ID, invite_url)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ── VIEWS ─────────────────────────────────────────────────
class PlayerView(discord.ui.View):
    def __init__(self, guild_id, client_id, invite_url=None):
        super().__init__(timeout=None)
        # Use the real activity invite if available, otherwise fall back
        url = invite_url or f"https://discord.com/activities/{client_id}"
        self.add_item(discord.ui.Button(
            label="🚀 Открыть Music Player",
            style=discord.ButtonStyle.link,
            url=url
        ))


# ═══════════════════════════════════════════════════════════
#  FLASK WEB APP
# ═══════════════════════════════════════════════════════════
_STATIC = os.path.join(os.path.dirname(__file__), "webapp", "static")
_TMPL   = os.path.join(os.path.dirname(__file__), "webapp")

app = Flask(__name__, static_folder=_STATIC, template_folder=_TMPL)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)


def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    return future.result(timeout=20)


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


# ── Cache Control & Headers ───────────────────────────────
@app.after_request
def add_cache_control(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    # CSP: allow images from YouTube, SoundCloud, Discord CDN (critical for iframe)
    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: *; "
            "img-src * data: blob:; "
            "media-src * blob: data:; "
            "connect-src *; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net *; "
            "style-src 'self' 'unsafe-inline' fonts.googleapis.com *; "
            "font-src 'self' data: fonts.gstatic.com *;"
        )
    return response


# ── Static & Player ───────────────────────────────────────
@app.route("/")
@app.route("/player")
@app.route("/.proxy/")
@app.route("/.proxy/player")
def serve_player():
    return render_template("index.html", public_url=PUBLIC_URL, client_id=CLIENT_ID)

@app.route("/static/<path:filename>")
@app.route("/.proxy/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(_STATIC, filename)


# ── Thumbnail Image Proxy ──────────────────────────────
# Serves external images server-side so Discord's iframe CSP can't block them
@app.route("/api/thumb", methods=["GET"])
@app.route("/.proxy/api/thumb", methods=["GET"])
def thumb_proxy():
    url = request.args.get("url", "").strip()
    if not url or not url.startswith("http"):
        abort(400)
    try:
        req = _urlreq.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.youtube.com/",
        })
        with _urlreq.urlopen(req, timeout=8) as resp:
            data = resp.read()
            ct   = resp.headers.get_content_type() or "image/jpeg"
        return Response(data, content_type=ct, headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        })
    except Exception as e:
        print(f"[thumb_proxy] Error fetching {url[:80]}: {e}")
        abort(404)

# ── Public Guilds API ──────────────────────────────────────
@app.route("/api/guilds", methods=["GET", "OPTIONS"])
@app.route("/.proxy/api/guilds", methods=["GET", "OPTIONS"])
def get_public_guilds():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    guilds = []
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

        guilds.append({
            "id": str(g.id),
            "name": g.name,
            "icon": str(g.icon.url) if g.icon else None,
            "has_player": gp is not None,
            "playing": gp.is_playing() if gp else False,
            "voice_channels": vcs,
        })
    return jsonify({"guilds": guilds})

# ── Player API ────────────────────────────────────────────
@app.route("/api/player/<int:guild_id>", methods=["GET", "OPTIONS"])
@app.route("/.proxy/api/player/<int:guild_id>", methods=["GET", "OPTIONS"])
def get_state(guild_id):
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    gp = player_manager.get_player(guild_id)
    if not gp:
        return jsonify({"playing": False, "paused": False, "current": None, "queue": [], "queue_count": 0, "history_count": 0, "volume": 0.5, "loop_mode": "none"})
    return jsonify(gp.get_state())

@app.route("/api/player/<int:guild_id>/pause", methods=["POST"])
def pause(guild_id):
    gp = player_manager.get_player(guild_id)
    if not gp: return jsonify({"error": "No player"}), 404
    run_async(gp.pause())
    return jsonify({"ok": True, "state": gp.get_state()})

@app.route("/api/player/<int:guild_id>/resume", methods=["POST"])
def resume(guild_id):
    guild = bot.get_guild(guild_id)
    text_ch = guild.text_channels[0] if (guild and guild.text_channels) else None
    gp = player_manager.get_or_create(guild_id, text_ch)
    
    # Auto-connect if not connected to voice
    if not gp.voice_client or not gp.voice_client.is_connected():
        target_vc = None
        if guild:
            # Look for active human members in voice channels
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

@app.route("/api/player/<int:guild_id>/prev", methods=["POST"])
def prev_track(guild_id):
    gp = player_manager.get_player(guild_id)
    if not gp: return jsonify({"error": "No player"}), 404
    res = run_async(gp.prev())
    if not res:
        return jsonify({"error": "No history available"}), 400
    return jsonify({"ok": True, "state": gp.get_state()})

@app.route("/api/player/<int:guild_id>/skip", methods=["POST"])
def skip(guild_id):
    gp = player_manager.get_player(guild_id)
    if not gp: return jsonify({"error": "No player"}), 404
    run_async(gp.skip())
    return jsonify({"ok": True, "state": gp.get_state()})

@app.route("/api/player/<int:guild_id>/stop", methods=["POST"])
def stop(guild_id):
    gp = player_manager.get_player(guild_id)
    if not gp: return jsonify({"error": "No player"}), 404
    async def _stop():
        await gp.stop()
        if gp.voice_client: await gp.voice_client.disconnect()
        player_manager.remove_player(guild_id)
    run_async(_stop())
    return jsonify({"ok": True})

@app.route("/api/player/<int:guild_id>/volume", methods=["POST"])
def volume(guild_id):
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

@app.route("/api/player/<int:guild_id>/loop", methods=["POST"])
def loop_mode(guild_id):
    gp = player_manager.get_player(guild_id)
    if not gp: return jsonify({"error": "No player"}), 404
    mode = (request.get_json(silent=True) or {}).get("mode", "none")
    if mode not in ("none", "track", "queue"): return jsonify({"error": "Invalid"}), 400
    gp.loop_mode = mode
    return jsonify({"ok": True, "loop_mode": mode})

# ── Search API ────────────────────────────────────────────
@app.route("/api/search", methods=["GET", "OPTIONS"])
@app.route("/.proxy/api/search", methods=["GET", "OPTIONS"])
def search():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    q = request.args.get("q", "").strip()
    if not q: return jsonify({"results": []})
    try:
        results = run_async(search_engine.search(q, limit=10))
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/play", methods=["POST", "OPTIONS"])
@app.route("/.proxy/api/play", methods=["POST", "OPTIONS"])
def play_api():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})
    data       = request.get_json(silent=True) or {}
    guild_id   = int(data.get("guild_id", 0))
    channel_id = int(data.get("channel_id", 0))
    track      = data.get("track")
    user_id    = data.get("user_id")

    if not track:
        return jsonify({"error": "Отсутствуют данные трека"}), 400

    async def _async_play():
        target_channel = None
        guild = None
        current_guild_id = guild_id

        # 1. Resolution by channel_id (essential for Discord Mini App!)
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
                        current_guild_id = guild.id
                    elif hasattr(ch, "guild") and ch.guild:
                        guild = ch.guild
                        current_guild_id = guild.id
            except Exception as e:
                print(f"[API play] Error resolving channel_id {channel_id}: {e}")

        # 2. Resolution by guild_id
        if not guild and current_guild_id:
            guild = bot.get_guild(current_guild_id)
            if not guild:
                try:
                    guild = await bot.fetch_guild(current_guild_id)
                except Exception:
                    guild = None

        # 3. Fallback to first available bot guild
        if not guild:
            if bot.guilds:
                guild = bot.guilds[0]
                current_guild_id = guild.id
            else:
                return {"error": "Бот не подключен ни к одному серверу Discord", "status": 400}

        # 4. Try specified user_id
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

        # 5. Try channel where bot is currently connected
        gp_existing = player_manager.get_player(guild.id)
        if not target_channel and gp_existing and gp_existing.voice_client and gp_existing.voice_client.is_connected():
            target_channel = gp_existing.voice_client.channel

        # 6. Try any voice channel with active non-bot members
        if not target_channel:
            for vc in guild.voice_channels:
                if any(not m.bot for m in vc.members):
                    target_channel = vc
                    break

        # 7. Fallback to first voice channel on the server
        if not target_channel and guild.voice_channels:
            target_channel = guild.voice_channels[0]

        if not target_channel:
            return {"error": "Голосовой канал не найден. Войдите в голосовой канал!", "status": 400}

        text_channel = guild.text_channels[0] if guild.text_channels else None
        gp = player_manager.get_or_create(guild.id, text_channel)
        await gp.connect(target_channel)
        track_data = dict(track)
        track_data["requester"] = "Discord Mini App"
        await gp.add_to_queue(track_data)

        return {
            "ok": True,
            "guild_id": str(guild.id),
            "channel_id": str(target_channel.id),
            "channel": target_channel.name,
            "status": 200
        }

    try:
        res = run_async(_async_play())
        status = res.pop("status", 200)
        return jsonify(res), status
    except Exception as e:
        print(f"[API play] Error starting playback: {e}")
        return jsonify({"error": str(e)}), 500


# ── Admin API ─────────────────────────────────────────────
@app.route("/api/admin/check")
def admin_check():
    try:
        uid = int(request.headers.get("X-User-Id", ""))
        return jsonify({"is_admin": uid in ADMIN_IDS})
    except:
        return jsonify({"is_admin": False})

@app.route("/api/admin/guilds")
@require_admin
def admin_guilds():
    guilds = []
    for g in bot.guilds:
        gp = player_manager.get_player(g.id)
        guilds.append({
            "id": str(g.id), "name": g.name, "member_count": g.member_count,
            "icon": str(g.icon.url) if g.icon else None,
            "has_player": gp is not None,
            "player_state": gp.get_state() if gp else None,
        })
    return jsonify({"guilds": guilds})

@app.route("/api/admin/chains/<int:guild_id>")
@require_admin
def admin_chains(guild_id):
    chains = chain_manager.get_guild_chains(guild_id)
    guild  = bot.get_guild(guild_id)
    result = []
    for fid, lid in chains.items():
        f = guild.get_member(fid) if guild else None
        l = guild.get_member(lid) if guild else None
        result.append({
            "follower_id":   str(fid), "follower_name": f.display_name if f else str(fid),
            "leader_id":     str(lid), "leader_name":   l.display_name if l else str(lid),
        })
    return jsonify({"chains": result})

@app.route("/api/admin/chains/<int:guild_id>", methods=["DELETE"])
@require_admin
def admin_del_chain(guild_id):
    fid     = int((request.get_json(silent=True) or {}).get("follower_id", 0))
    removed = chain_manager.remove_chain(guild_id, fid)
    return jsonify({"ok": removed})

@app.route("/api/admin/stop/<int:guild_id>", methods=["POST"])
@require_admin
def admin_stop(guild_id):
    gp = player_manager.get_player(guild_id)
    if not gp: return jsonify({"error": "No player"}), 404
    async def _s():
        await gp.stop()
        if gp.voice_client: await gp.voice_client.disconnect()
        player_manager.remove_player(guild_id)
    run_async(_s())
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════
#  START BOT IN BACKGROUND THREAD
# ═══════════════════════════════════════════════════════════
def _run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if not TOKEN:
        print("DISCORD_TOKEN не задан!")
        return
    loop.run_until_complete(bot.start(TOKEN))

_bot_thread = threading.Thread(target=_run_bot, daemon=True, name="discord-bot")
_bot_thread.start()


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT (если запускать напрямую: python app.py)
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"Starting web server on {WEB_HOST}:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False, threaded=True)
