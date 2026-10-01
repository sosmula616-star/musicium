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
from flask import Flask, jsonify, request, send_from_directory, abort
from flask_cors import CORS

# ── Discord ───────────────────────────────────────────────
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

    view = PlayerView(guild_id, PUBLIC_URL)
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
    await interaction.response.send_message(embed=embed, view=PlayerView(interaction.guild_id, PUBLIC_URL))


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


@tree.command(name="player", description="Открыть плеер")
async def player_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🎵 Music Player", description="Нажми кнопку ниже.", color=0x9B59B6)
    await interaction.response.send_message(embed=embed, view=PlayerView(interaction.guild_id, PUBLIC_URL), ephemeral=True)


# ── VIEWS ─────────────────────────────────────────────────
class PlayerView(discord.ui.View):
    def __init__(self, guild_id, public_url):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="🎵 Открыть плеер",
            style=discord.ButtonStyle.link,
            url=f"{public_url}/player?guild={guild_id}"
        ))


# ═══════════════════════════════════════════════════════════
#  FLASK WEB APP
# ═══════════════════════════════════════════════════════════
_STATIC = os.path.join(os.path.dirname(__file__), "webapp", "static")
_TMPL   = os.path.join(os.path.dirname(__file__), "webapp")

app = Flask(__name__, static_folder=_STATIC, template_folder=_TMPL)
CORS(app, resources={r"/api/*": {"origins": "*"}})


def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    return future.result(timeout=15)


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


# ── Static ────────────────────────────────────────────────
@app.route("/")
@app.route("/player")
def serve_player():
    return send_from_directory(_TMPL, "index.html")

@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(_STATIC, filename)

# ── Public Guilds API ──────────────────────────────────────
@app.route("/api/guilds")
def get_public_guilds():
    guilds = []
    for g in bot.guilds:
        gp = player_manager.get_player(g.id)
        guilds.append({
            "id": str(g.id),
            "name": g.name,
            "icon": str(g.icon.url) if g.icon else None,
            "has_player": gp is not None,
            "playing": gp.is_playing() if gp else False,
        })
    return jsonify({"guilds": guilds})

# ── Player API ────────────────────────────────────────────
@app.route("/api/player/<int:guild_id>")
def get_state(guild_id):
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
    gp = player_manager.get_player(guild_id)
    if not gp: return jsonify({"error": "No player"}), 404
    vol = float((request.get_json(silent=True) or {}).get("volume", 0.5))
    gp.set_volume(vol)
    return jsonify({"ok": True, "volume": gp.volume})

@app.route("/api/player/<int:guild_id>/loop", methods=["POST"])
def loop_mode(guild_id):
    gp = player_manager.get_player(guild_id)
    if not gp: return jsonify({"error": "No player"}), 404
    mode = (request.get_json(silent=True) or {}).get("mode", "none")
    if mode not in ("none", "track", "queue"): return jsonify({"error": "Invalid"}), 400
    gp.loop_mode = mode
    return jsonify({"ok": True, "loop_mode": mode})

# ── Search API ────────────────────────────────────────────
@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if not q: return jsonify({"results": []})
    try:
        results = run_async(search_engine.search(q, limit=10))
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/play", methods=["POST"])
def play_api():
    data      = request.get_json(silent=True) or {}
    guild_id  = int(data.get("guild_id", 0))
    track     = data.get("track")
    user_id   = data.get("user_id")

    if not guild_id:
        if bot.guilds:
            guild_id = bot.guilds[0].id
        else:
            return jsonify({"error": "No Discord guilds available for bot"}), 400

    if not track:
        return jsonify({"error": "Missing track data"}), 400

    guild = bot.get_guild(guild_id)
    if not guild: return jsonify({"error": f"Guild {guild_id} not found"}), 404

    target_channel = None

    # 1. Try specified user
    if user_id:
        try:
            member = guild.get_member(int(user_id))
            if member and member.voice:
                target_channel = member.voice.channel
        except Exception:
            pass

    # 2. Try channel where bot is already connected
    gp_existing = player_manager.get_player(guild_id)
    if not target_channel and gp_existing and gp_existing.voice_client and gp_existing.voice_client.is_connected():
        target_channel = gp_existing.voice_client.channel

    # 3. Try any voice channel with active non-bot members
    if not target_channel:
        for vc in guild.voice_channels:
            if any(not m.bot for m in vc.members):
                target_channel = vc
                break

    # 4. Fallback to first available voice channel
    if not target_channel and guild.voice_channels:
        target_channel = guild.voice_channels[0]

    if not target_channel:
        return jsonify({"error": "No voice channels available on server. Join a voice channel!"}), 400

    async def _play():
        text_channel = guild.text_channels[0] if guild.text_channels else None
        gp = player_manager.get_or_create(guild_id, text_channel)
        await gp.connect(target_channel)
        track_data = dict(track)
        track_data["requester"] = "Web Player"
        await gp.add_to_queue(track_data)

    try:
        run_async(_play())
        return jsonify({"ok": True, "guild_id": str(guild_id), "channel": target_channel.name})
    except Exception as e:
        print(f"[API play] Error: {e}")
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
