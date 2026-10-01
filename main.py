"""
main.py — Discord Music Bot (Pure Application)
High-performance, pure Discord audio player with rich interactive UI components.
"""

import os
import sys
import asyncio
from typing import Optional, Literal
from dotenv import load_dotenv

load_dotenv()

import discord
from discord.ext import commands
from discord import app_commands

# ── Auto-load Opus library on Linux / Alpine ────────────────
if not discord.opus.is_loaded():
    for opus_name in ("libopus.so.0", "libopus.so", "opus", "libopus-0.x86_64.so", "libopus.so.0.8.0"):
        try:
            discord.opus.load_opus(opus_name)
            if discord.opus.is_loaded():
                print(f"[Opus] Successfully loaded {opus_name}")
                break
        except Exception:
            pass

# ── Check Davey Protocol (DAVE E2EE) ────────────────────────
try:
    import davey
    print("[Voice] Davey (DAVE E2EE protocol) is active.")
except ImportError:
    print("[Voice] Notice: davey not loaded, standard voice active.")

from music_search import MusicSearchEngine, format_duration
from player_manager import PlayerManager, GuildPlayer
from chain_manager import ChainManager

# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════
TOKEN = os.getenv("DISCORD_TOKEN")
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", 3000))
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://gostingmusicium.bothost.tech")

HARDCODED_ADMINS = {410432175373156352}
env_admins = set()
for raw in os.getenv("ADMIN_IDS", "").split(","):
    raw = raw.strip()
    if raw.isdigit():
        env_admins.add(int(raw))
ADMIN_IDS = HARDCODED_ADMINS | env_admins


# ── BUILT-IN WEB SERVER (ELIMINATES 502 BAD GATEWAY) ────────
from aiohttp import web

async def handle_web_index(request):
    """Serve a sleek dark status page for Bothost / Web visitors."""
    bot = request.app["bot"]
    latency = int(bot.latency * 1000) if bot.latency else 0
    guild_count = len(bot.guilds)
    playing_count = sum(1 for p in player_manager._players.values() if p.is_playing())
    invite_url = (
        f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&scope=bot%20applications.commands"
        if CLIENT_ID
        else "#"
    )

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GostingMusic • Discord Bot</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #090a10;
      color: #f8fafc;
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      overflow-x: hidden;
      position: relative;
    }}
    .glow {{
      position: fixed;
      width: 500px;
      height: 500px;
      border-radius: 50%;
      filter: blur(140px);
      pointer-events: none;
      opacity: 0.35;
    }}
    .glow-1 {{ top: -100px; left: -100px; background: #8b5cf6; }}
    .glow-2 {{ bottom: -100px; right: -100px; background: #06b6d4; }}
    .card {{
      position: relative;
      z-index: 1;
      background: rgba(18, 21, 35, 0.75);
      border: 1px solid rgba(255, 255, 255, 0.1);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border-radius: 28px;
      max-width: 520px;
      width: 100%;
      padding: 38px 30px;
      text-align: center;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
    }}
    .logo {{
      width: 64px;
      height: 64px;
      border-radius: 20px;
      background: linear-gradient(135deg, #8b5cf6, #06b6d4);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 30px;
      margin-bottom: 18px;
      box-shadow: 0 8px 24px rgba(139, 92, 246, 0.5);
    }}
    h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.02em;
      margin-bottom: 8px;
    }}
    h1 span {{ color: #8b5cf6; }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 16px;
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
      border-radius: 99px;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 22px;
    }}
    .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #10b981; box-shadow: 0 0 10px #10b981; }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin-bottom: 24px;
    }}
    .stat-box {{
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 16px;
      padding: 12px 8px;
    }}
    .stat-val {{
      font-family: 'Outfit', sans-serif;
      font-size: 20px;
      font-weight: 700;
      color: #fff;
    }}
    .stat-label {{
      font-size: 11px;
      color: #94a3b8;
      margin-top: 2px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .btn-invite {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      width: 100%;
      background: linear-gradient(135deg, #8b5cf6, #7c3aed);
      color: #fff;
      text-decoration: none;
      padding: 14px 24px;
      border-radius: 14px;
      font-size: 15px;
      font-weight: 700;
      box-shadow: 0 8px 24px rgba(139, 92, 246, 0.4);
      transition: all 0.2s ease;
      margin-bottom: 18px;
    }}
    .btn-invite:hover {{
      transform: translateY(-2px);
      box-shadow: 0 12px 30px rgba(139, 92, 246, 0.6);
    }}
    .commands-list {{
      background: rgba(0, 0, 0, 0.25);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 16px;
      padding: 14px;
      text-align: left;
      font-size: 12px;
      color: #94a3b8;
      line-height: 1.8;
    }}
    .cmd {{ color: #a78bfa; font-family: monospace; font-weight: 600; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="glow glow-1"></div>
  <div class="glow glow-2"></div>
  <div class="card">
    <div class="logo">🎵</div>
    <h1>Gosting<span>Music</span></h1>
    <div class="status-badge"><span class="dot"></span>Бот в сети и готов к воспроизведению</div>

    <div class="stats-grid">
      <div class="stat-box">
        <div class="stat-val">{guild_count}</div>
        <div class="stat-label">Серверов</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">{latency} ms</div>
        <div class="stat-label">Пинг</div>
      </div>
      <div class="stat-box">
        <div class="stat-val">{playing_count}</div>
        <div class="stat-label">Играет</div>
      </div>
    </div>

    <a href="{invite_url}" target="_blank" class="btn-invite">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.894.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
      Пригласить бота в Discord
    </a>

    <div class="commands-list">
      <div><span class="cmd">/play &lt;песня&gt;</span> — Воспроизвести с интерактивными кнопками</div>
      <div><span class="cmd">/nowplaying</span> — Информация о треке и полоса прогресса</div>
      <div><span class="cmd">/queue</span> — Список очереди воспроизведения</div>
      <div><span class="cmd">/volume &lt;1-100&gt;</span> — Регулировка громкости</div>
      <div><span class="cmd">/loop &lt;off|track|queue&gt;</span> — Режимы повтора</div>
      <div><span class="cmd">/chain &lt;target&gt;</span> — Голосовые связки участников</div>
    </div>
  </div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html", status=200)

async def handle_web_health(request):
    bot = request.app["bot"]
    data = {
        "status": "ok",
        "bot": str(bot.user) if bot.user else "connecting",
        "guilds": len(bot.guilds),
        "latency_ms": int(bot.latency * 1000) if bot.latency else 0,
    }
    return web.json_response(data)


# ═══════════════════════════════════════════════════════════
#  BOT CLASS SETUP
# ═══════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True

class MusicBot(commands.Bot):
    async def setup_hook(self):
        # 1. Sync global slash commands
        try:
            synced = await self.tree.sync()
            print(f"✅ Synced {len(synced)} global slash commands.")
        except Exception as e:
            print(f"⚠️ Slash command sync note: {e}")

        # 2. Start HTTP server on port 3000 to eliminate Bad Gateway
        try:
            app = web.Application()
            app["bot"] = self
            app.router.add_get("/", handle_web_index)
            app.router.add_get("/player", handle_web_index)
            app.router.add_get("/health", handle_web_health)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host=WEB_HOST, port=WEB_PORT)
            await site.start()
            print(f"🌐 HTTP Status Server running on {WEB_HOST}:{WEB_PORT}")
        except Exception as e:
            print(f"⚠️ Could not start HTTP server on port {WEB_PORT}: {e}")

bot = MusicBot(command_prefix="!", intents=intents)
tree = bot.tree

search_engine = MusicSearchEngine()
player_manager = PlayerManager(bot)
chain_manager = ChainManager(bot)


# ── EMBED BUILDERS ─────────────────────────────────────────
def build_progress_bar(elapsed: int, total: int, length: int = 14) -> str:
    """Generate a visual progress bar string."""
    if total <= 0:
        return "▬" * length
    pct = max(0.0, min(1.0, elapsed / total))
    pos = int(pct * length)
    bar = ""
    for i in range(length):
        if i == pos:
            bar += "🔘"
        else:
            bar += "▬"
    return bar


def create_now_playing_embed(player: GuildPlayer) -> discord.Embed:
    """Build a rich embed for currently playing track."""
    track = player.current_track
    if not track:
        embed = discord.Embed(
            title="🎵 Плеер свободен",
            description="Сейчас ничего не играет. Используйте `/play <название или ссылка>`, чтобы включить музыку!",
            color=0x2b2d31
        )
        return embed

    elapsed = player.elapsed_seconds
    total = track.get("duration", 0)
    elapsed_str = format_duration(elapsed)
    total_str = track.get("duration_str", "Live")
    bar = build_progress_bar(elapsed, total, length=14)

    status_icon = "⏸️ Пауза" if player.is_paused else "▶️ Играет"
    embed_color = 0xef4444 if track.get("platform") == "YouTube" else 0xf97316 if track.get("platform") == "SoundCloud" else 0x8b5cf6

    embed = discord.Embed(
        title=f"{status_icon}: {track.get('title')}",
        url=track.get("url") if track.get("url", "").startswith("http") else None,
        description=f"**Исполнитель:** {track.get('artist')}\n\n`{elapsed_str}` {bar} `{total_str}`",
        color=embed_color
    )

    if track.get("thumbnail"):
        embed.set_thumbnail(url=track["thumbnail"])

    vol_pct = int(player.volume * 100)
    loop_str = "Выкл" if player.loop_mode == "none" else "Трек 🔂" if player.loop_mode == "track" else "Очередь 🔁"

    embed.add_field(name="Платформа", value=f"{track.get('platform_emoji', '🎵')} {track.get('platform', 'Web')}", inline=True)
    embed.add_field(name="Громкость", value=f"🔊 {vol_pct}%", inline=True)
    embed.add_field(name="Режим повтора", value=loop_str, inline=True)

    if player.queue:
        next_track = player.queue[0]
        embed.add_field(name="Следующий трек", value=f"🎶 **{next_track.get('title')}**", inline=False)

    embed.set_footer(text=f"Запросил: {track.get('requester', 'Пользователь')} • Всего в очереди: {len(player.queue)}")
    return embed


# ── INTERACTIVE CONTROLS VIEW ─────────────────────────────
class MusicControlView(discord.ui.View):
    def __init__(self, player: GuildPlayer):
        super().__init__(timeout=None)
        self.player = player
        self._update_button_states()

    def _update_button_states(self):
        # Update Play/Pause label
        if self.player.is_paused:
            self.btn_play_pause.emoji = "▶️"
            self.btn_play_pause.style = discord.ButtonStyle.success
        else:
            self.btn_play_pause.emoji = "⏸️"
            self.btn_play_pause.style = discord.ButtonStyle.secondary

        # Update Loop button style
        if self.player.loop_mode == "track":
            self.btn_loop.style = discord.ButtonStyle.primary
            self.btn_loop.emoji = "🔂"
        elif self.player.loop_mode == "queue":
            self.btn_loop.style = discord.ButtonStyle.primary
            self.btn_loop.emoji = "🔁"
        else:
            self.btn_loop.style = discord.ButtonStyle.secondary
            self.btn_loop.emoji = "🔁"

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary, row=0, custom_id="btn_play_pause")
    async def btn_play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Зайдите в голосовой канал!", ephemeral=True)
            return

        if self.player.is_paused:
            await self.player.resume()
        else:
            await self.player.pause()

        self._update_button_states()
        embed = create_now_playing_embed(self.player)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0, custom_id="btn_skip")
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice:
            await interaction.response.send_message("❌ Зайдите в голосовой канал!", ephemeral=True)
            return

        await self.player.skip()
        await interaction.response.send_message("⏭️ Трек пропущен!", ephemeral=True)
        await asyncio.sleep(0.5)
        self._update_button_states()
        embed = create_now_playing_embed(self.player)
        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0, custom_id="btn_stop")
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice:
            await interaction.response.send_message("❌ Зайдите в голосовой канал!", ephemeral=True)
            return

        await self.player.stop()
        if self.player.voice_client:
            await self.player.voice_client.disconnect()
        player_manager.remove_player(interaction.guild_id)

        embed = discord.Embed(
            title="⏹️ Музыка остановлена",
            description=f"Воспроизведение остановлено пользователем **{interaction.user.display_name}**.",
            color=0xef4444
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=0, custom_id="btn_loop")
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        next_mode = "track" if self.player.loop_mode == "none" else "queue" if self.player.loop_mode == "track" else "none"
        self.player.loop_mode = next_mode
        self._update_button_states()

        labels = {"none": "Повтор выключен", "track": "Повтор одного трека 🔂", "queue": "Повтор очереди 🔁"}
        embed = create_now_playing_embed(self.player)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=0, custom_id="btn_shuffle")
    async def btn_shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.player.queue:
            await interaction.response.send_message("📭 Очередь пуста!", ephemeral=True)
            return

        self.player.shuffle()
        embed = create_now_playing_embed(self.player)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=1, custom_id="btn_voldown")
    async def btn_voldown(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_vol = max(0.0, self.player.volume - 0.1)
        self.player.set_volume(new_vol)
        embed = create_now_playing_embed(self.player)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=1, custom_id="btn_volup")
    async def btn_volup(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_vol = min(1.5, self.player.volume + 0.1)
        self.player.set_volume(new_vol)
        embed = create_now_playing_embed(self.player)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Очередь", emoji="📜", style=discord.ButtonStyle.secondary, row=1, custom_id="btn_queue")
    async def btn_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.player.queue and not self.player.current_track:
            await interaction.response.send_message("📭 Очередь треков пуста!", ephemeral=True)
            return

        lines = []
        if self.player.current_track:
            lines.append(f"▶️ **Сейчас:** {self.player.current_track.get('title')} — *{self.player.current_track.get('artist')}*")

        if self.player.queue:
            lines.append("\n**В очереди:**")
            for i, t in enumerate(list(self.player.queue)[:12], start=1):
                lines.append(f"`{i}.` {t.get('platform_emoji', '🎵')} **{t.get('title')}** — *{t.get('artist')}* (`{t.get('duration_str')}`)")
            if len(self.player.queue) > 12:
                lines.append(f"\n*...и ещё {len(self.player.queue) - 12} треков*")

        q_embed = discord.Embed(
            title=f"📜 Очередь треков ({len(self.player.queue)} в очереди)",
            description="\n".join(lines),
            color=0x8b5cf6
        )
        await interaction.response.send_message(embed=q_embed, ephemeral=True)


# ── DISCORD BOT EVENTS ────────────────────────────────────
@bot.event
async def on_ready():
    print(f"========================================")
    print(f"🤖 Bot online: {bot.user} (ID: {bot.user.id})")
    print(f"🌐 Connected Guilds: {len(bot.guilds)}")
    print(f"========================================")

    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} global slash commands.")
    except Exception as e:
        print(f"⚠️ Command sync error: {e}")


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member == bot.user:
        return

    # Handle voice chaining
    if before.channel != after.channel:
        await chain_manager.handle_voice_move(member, before.channel, after.channel)

    # Inactivity disconnect: If bot is alone in channel for 60s, leave
    gp = player_manager.get_player(member.guild.id)
    if gp and gp.voice_client and gp.voice_client.channel:
        vc = gp.voice_client.channel
        human_members = [m for m in vc.members if not m.bot]
        if len(human_members) == 0:
            await asyncio.sleep(60)
            if gp.voice_client and gp.voice_client.channel:
                human_members = [m for m in gp.voice_client.channel.members if not m.bot]
                if len(human_members) == 0:
                    print(f"[Player] Channel '{vc.name}' empty. Auto-disconnecting bot.")
                    await gp.stop()
                    await gp.voice_client.disconnect()
                    player_manager.remove_player(member.guild.id)


# ═══════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ═══════════════════════════════════════════════════════════

@tree.command(name="play", description="Включить музыку из YouTube / SoundCloud или по прямой ссылке")
@app_commands.describe(query="Название песни, исполнитель или прямая ссылка")
async def cmd_play(interaction: discord.Interaction, query: str):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ Зайдите в голосовой канал, чтобы слушать музыку!", ephemeral=True)
        return

    voice_channel = interaction.user.voice.channel
    bot_member = interaction.guild.me
    if bot_member:
        perms = voice_channel.permissions_for(bot_member)
        if not perms.connect:
            await interaction.response.send_message(f"❌ У бота нет прав на подключение к каналу **{voice_channel.name}**!", ephemeral=True)
            return
        if not perms.speak:
            await interaction.response.send_message(f"❌ У бота нет прав говорить в канале **{voice_channel.name}**!", ephemeral=True)
            return

    await interaction.response.defer(thinking=True)

    results = await search_engine.search(query, limit=5)
    if not results:
        await interaction.followup.send("❌ Ничего не найдено по вашему запросу!")
        return

    track = results[0]
    gp = player_manager.get_or_create(interaction.guild_id, interaction.channel)

    try:
        await gp.connect(voice_channel)
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка подключения к голосовому каналу: `{e}`")
        return

    await gp.add_to_queue(track, interaction.user)

    embed = create_now_playing_embed(gp)
    view = MusicControlView(gp)
    await interaction.followup.send(embed=embed, view=view)


@tree.command(name="skip", description="Пропустить текущий трек")
async def cmd_skip(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.is_playing():
        await interaction.response.send_message("❌ Сейчас ничего не играет!", ephemeral=True)
        return
    await gp.skip()
    await interaction.response.send_message("⏭️ Трек пропущен!")


@tree.command(name="pause", description="Поставить воспроизведение на паузу")
async def cmd_pause(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.is_playing() or gp.is_paused:
        await interaction.response.send_message("❌ Музыка не играет или уже на паузе!", ephemeral=True)
        return
    await gp.pause()
    await interaction.response.send_message("⏸️ Воспроизведение приостановлено!")


@tree.command(name="resume", description="Возобновить воспроизведение")
async def cmd_resume(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.is_paused:
        await interaction.response.send_message("❌ Плеер не стоит на паузе!", ephemeral=True)
        return
    await gp.resume()
    await interaction.response.send_message("▶️ Воспроизведение возобновлено!")


@tree.command(name="stop", description="Остановить плеер, очистить очередь и выйти из канала")
async def cmd_stop(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp:
        await interaction.response.send_message("❌ Бот не находится в голосовом канале!", ephemeral=True)
        return
    await gp.stop()
    if gp.voice_client:
        await gp.voice_client.disconnect()
    player_manager.remove_player(interaction.guild_id)
    await interaction.response.send_message("⏹️ Музыка остановлена, бот покинул канал.")


@tree.command(name="nowplaying", description="Показать информацию о текущем треке с кнопками управления")
async def cmd_nowplaying(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.current_track:
        await interaction.response.send_message("📭 Сейчас ничего не играет!", ephemeral=True)
        return
    embed = create_now_playing_embed(gp)
    view = MusicControlView(gp)
    await interaction.response.send_message(embed=embed, view=view)


@tree.command(name="queue", description="Показать текущую очередь треков")
async def cmd_queue(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or (not gp.queue and not gp.current_track):
        await interaction.response.send_message("📭 Очередь пуста!", ephemeral=True)
        return

    lines = []
    if gp.current_track:
        lines.append(f"▶️ **Сейчас играет:** {gp.current_track.get('title')} — *{gp.current_track.get('artist')}*")

    if gp.queue:
        lines.append("\n**Список очереди:**")
        for i, t in enumerate(list(gp.queue)[:15], start=1):
            lines.append(f"`{i}.` {t.get('platform_emoji', '🎵')} **{t.get('title')}** — *{t.get('artist')}* (`{t.get('duration_str')}`)")
        if len(gp.queue) > 15:
            lines.append(f"\n*...и ещё {len(gp.queue) - 15} треков*")

    embed = discord.Embed(
        title=f"📜 Очередь сервера ({len(gp.queue)} треков)",
        description="\n".join(lines),
        color=0x8b5cf6
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="volume", description="Настроить громкость музыки (1-100%)")
@app_commands.describe(percent="Уровень громкости от 1 до 100")
async def cmd_volume(interaction: discord.Interaction, percent: int):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp:
        await interaction.response.send_message("❌ Плеер не активен!", ephemeral=True)
        return
    if percent < 1 or percent > 150:
        await interaction.response.send_message("❌ Укажите громкость от 1 до 100!", ephemeral=True)
        return

    vol = percent / 100.0
    gp.set_volume(vol)
    await interaction.response.send_message(f"🔊 Громкость установлена на **{percent}%**!")


@tree.command(name="loop", description="Переключить режим повтора музыки")
@app_commands.describe(mode="Режим: off (выкл), track (один трек), queue (вся очередь)")
async def cmd_loop(interaction: discord.Interaction, mode: Literal["off", "track", "queue"]):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp:
        await interaction.response.send_message("❌ Плеер не активен!", ephemeral=True)
        return

    mapping = {"off": "none", "track": "track", "queue": "queue"}
    gp.loop_mode = mapping[mode]
    labels = {"none": "Повтор отключен", "track": "Повтор текущего трека 🔂", "queue": "Повтор всей очереди 🔁"}
    await interaction.response.send_message(f"🔁 {labels[gp.loop_mode]}")


@tree.command(name="shuffle", description="Перемешать треки в очереди")
async def cmd_shuffle(interaction: discord.Interaction):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.queue:
        await interaction.response.send_message("📭 В очереди нет треков для перемешивания!", ephemeral=True)
        return
    gp.shuffle()
    await interaction.response.send_message(f"🔀 Очередь перемешана ({len(gp.queue)} треков)!")


@tree.command(name="seek", description="Перемотать текущий трек на указанное время")
@app_commands.describe(time="Время перемотки в формате ММ:СС или количество секунд")
async def cmd_seek(interaction: discord.Interaction, time: str):
    gp = player_manager.get_player(interaction.guild_id)
    if not gp or not gp.current_track:
        await interaction.response.send_message("❌ Сейчас ничего не играет!", ephemeral=True)
        return

    seconds = 0
    try:
        if ":" in time:
            parts = [int(p) for p in time.split(":")]
            if len(parts) == 2:
                seconds = parts[0] * 60 + parts[1]
            elif len(parts) == 3:
                seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
        else:
            seconds = int(time)
    except ValueError:
        await interaction.response.send_message("❌ Неверный формат времени! Используйте `01:30` или `90`.", ephemeral=True)
        return

    await interaction.response.defer()
    await gp.seek(seconds)
    await interaction.followup.send(f"⏩ Перемотано на `{format_duration(seconds)}`!")


@tree.command(name="chain", description="Привязать участника к ведущему (автоматически переходить за ним по голосовым каналам)")
@app_commands.describe(target="Кого привязать", follow="За кем следовать (пусто чтобы отвязать)")
async def cmd_chain(interaction: discord.Interaction, target: discord.Member, follow: Optional[discord.Member] = None):
    is_admin = interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.move_members
    if not is_admin:
        await interaction.response.send_message("❌ Недостаточно прав! Требуется право 'Перемещать участников'.", ephemeral=True)
        return

    if follow is None:
        if chain_manager.remove_chain(interaction.guild_id, target.id):
            await interaction.response.send_message(f"🔓 **{target.display_name}** отвязан.")
        else:
            await interaction.response.send_message(f"ℹ️ **{target.display_name}** не был привязан.", ephemeral=True)
        return

    if target.id == follow.id:
        await interaction.response.send_message("❌ Нельзя привязать пользователя к самому себе!", ephemeral=True)
        return

    chain_manager.add_chain(interaction.guild_id, target.id, follow.id)
    embed = discord.Embed(
        title="🔗 Голосовая связка активна",
        description=f"**{target.display_name}** теперь следует за **{follow.display_name}**",
        color=0xec4899
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="chains", description="Показать активные голосовые связки на сервере")
async def cmd_chains(interaction: discord.Interaction):
    chains = chain_manager.get_guild_chains(interaction.guild_id)
    if not chains:
        await interaction.response.send_message("📭 На этом сервере нет активных голосовых связок.", ephemeral=True)
        return

    items = []
    for fid, lid in chains.items():
        f = interaction.guild.get_member(fid)
        l = interaction.guild.get_member(lid)
        f_name = f.display_name if f else str(fid)
        l_name = l.display_name if l else str(lid)
        items.append(f"🔗 **{f_name}** ➜ **{l_name}**")

    embed = discord.Embed(
        title="⛓️ Активные связки",
        description="\n".join(items),
        color=0xec4899
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="unchain", description="Отвязать участника от голосовой связки")
@app_commands.describe(target="Кого отвязать")
async def cmd_unchain(interaction: discord.Interaction, target: discord.Member):
    is_admin = interaction.user.id in ADMIN_IDS or interaction.user.guild_permissions.move_members
    if not is_admin:
        await interaction.response.send_message("❌ Недостаточно прав!", ephemeral=True)
        return

    if chain_manager.remove_chain(interaction.guild_id, target.id):
        await interaction.response.send_message(f"🔓 **{target.display_name}** отвязан.")
    else:
        await interaction.response.send_message(f"ℹ️ **{target.display_name}** не был привязан.", ephemeral=True)


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Ошибка: DISCORD_TOKEN отсутствует в файле .env!")
        sys.exit(1)

    print("🚀 Запуск Discord Music Bot...")
    bot.run(TOKEN)
