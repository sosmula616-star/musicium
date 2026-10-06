import os
import sys
import time
import json
import base64
import hmac
import hashlib
import logging
import datetime
from collections import deque
from typing import Dict, Any, List, Optional, Tuple, Set

import discord

# --- Admin In-Memory Log Handler ---

class AdminLogHandler(logging.Handler):
    def __init__(self, maxlen: int = 3000):
        super().__init__()
        self.buffer = deque(maxlen=maxlen)
        self.formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    def emit(self, record: logging.LogRecord):
        try:
            formatted_msg = self.format(record)
            entry = {
                "id": int(time.time() * 1000) + len(self.buffer),
                "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "created": record.created,
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
                "formatted": formatted_msg,
            }
            self.buffer.append(entry)
        except Exception:
            pass

    def get_logs(self, level: Optional[str] = None, search: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        entries = list(self.buffer)
        if level and level.upper() != "ALL":
            target_level = level.upper()
            entries = [e for e in entries if e["level"] == target_level]
        if search:
            q = search.lower()
            entries = [e for e in entries if q in e["message"].lower() or q in e["name"].lower()]
        if limit and limit > 0:
            entries = entries[-limit:]
        return entries

    def clear(self):
        self.buffer.clear()

    def export_text(self) -> str:
        return "\n".join(e["formatted"] for e in self.buffer)


# Singleton log handler
admin_log_handler = AdminLogHandler(maxlen=3000)

def setup_admin_logging():
    root = logging.getLogger()
    if admin_log_handler not in root.handlers:
        root.addHandler(admin_log_handler)

setup_admin_logging()
logger = logging.getLogger("admin_service")


# --- Admin Authentication & Session Management ---

PRIMARY_ADMIN_ID = "410432175373156352"

def get_admin_ids() -> Set[str]:
    raw = os.getenv("ADMIN_IDS", PRIMARY_ADMIN_ID)
    ids = {x.strip() for x in raw.replace(";", ",").split(",") if x.strip()}
    ids.add(PRIMARY_ADMIN_ID)
    return ids

_SECRET_SALT = os.getenv("DISCORD_CLIENT_SECRET") or "musicium_super_secure_admin_salt_2026"

def is_admin_id(user_id: Any) -> bool:
    if not user_id:
        return False
    return str(user_id).strip() in get_admin_ids()

def generate_admin_token(user_id: str, max_age_days: int = 7) -> str:
    user_id = str(user_id).strip()
    exp = int(time.time()) + (max_age_days * 86400)
    msg = f"{user_id}:{exp}".encode("utf-8")
    sig = hmac.new(_SECRET_SALT.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{user_id}.{exp}.{sig}"

def verify_admin_token(token: Optional[str]) -> Tuple[bool, Optional[str]]:
    if not token or "." not in token:
        return False, None
    parts = token.split(".")
    if len(parts) != 3:
        return False, None
    user_id, exp_str, sig = parts
    try:
        exp = int(exp_str)
        if time.time() > exp:
            return False, None
    except ValueError:
        return False, None

    msg = f"{user_id}:{exp}".encode("utf-8")
    expected_sig = hmac.new(_SECRET_SALT.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False, None

    if not is_admin_id(user_id):
        return False, None

    return True, user_id


# --- System Statistics Helper ---

_START_TIME = time.time()

def get_memory_usage_mb() -> float:
    # 1. Windows via ctypes
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            class PMC(ctypes.Structure):
                _fields_ = [
                    ('cb', wintypes.DWORD),
                    ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t),
                    ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t),
                ]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            fn = ctypes.windll.psapi.GetProcessMemoryInfo
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            fn.restype = wintypes.BOOL
            if fn(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return round(pmc.WorkingSetSize / (1024 * 1024), 2)
        except Exception:
            pass

    # 2. Linux /proc/self/status
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return round(float(parts[1]) / 1024, 2)
    except Exception:
        pass

    # 3. Fallback resource
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != "darwin":
            return round(usage / 1024, 2)
        else:
            return round(usage / (1024 * 1024), 2)
    except Exception:
        pass

    return 0.0

def format_uptime(seconds: float) -> str:
    secs = int(seconds)
    days, secs = divmod(secs, 86400)
    hours, secs = divmod(secs, 3600)
    mins, secs = divmod(secs, 60)
    parts = []
    if days > 0:
        parts.append(f"{days} д")
    if hours > 0 or days > 0:
        parts.append(f"{hours} ч")
    parts.append(f"{mins} мин")
    parts.append(f"{secs} сек")
    return " ".join(parts)


async def get_system_stats(bot: discord.Client, player_manager: Any, music_service: Any) -> Dict[str, Any]:
    now = time.time()
    uptime_sec = now - _START_TIME
    
    guilds_count = len(bot.guilds) if bot and hasattr(bot, "guilds") else 0
    total_users = sum(getattr(g, "member_count", 0) for g in bot.guilds) if bot and hasattr(bot, "guilds") else 0
    
    active_voice_count = 0
    playing_count = 0
    
    if player_manager and hasattr(player_manager, "players"):
        for p in player_manager.players.values():
            if p.is_connected:
                active_voice_count += 1
            if p.is_playing:
                playing_count += 1
                
    # Discord latency
    latency_ms = round((bot.latency * 1000), 1) if (bot and hasattr(bot, "latency") and bot.latency is not None) else 0.0

    # YouTube cookies info
    cookie_path = getattr(music_service, "youtube_cookie_path", None)
    cookies_valid = bool(cookie_path and os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0)
    cookie_count = 0
    cookie_size_kb = 0.0
    if cookies_valid:
        try:
            with open(cookie_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            cookie_count = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
            cookie_size_kb = round(os.path.getsize(cookie_path) / 1024, 2)
        except Exception:
            pass

    # Database stats
    db_stats = {"connected": False, "liked_count": 0, "playlists_count": 0, "history_count": 0}
    try:
        import db
        if db._pool is not None:
            db_stats["connected"] = True
            async with db._pool.acquire() as conn:
                liked = await conn.fetchval("SELECT COUNT(*) FROM user_liked_tracks;")
                pl = await conn.fetchval("SELECT COUNT(*) FROM user_playlists;")
                hist = await conn.fetchval("SELECT COUNT(*) FROM user_history_tracks;")
                db_stats["liked_count"] = liked or 0
                db_stats["playlists_count"] = pl or 0
                db_stats["history_count"] = hist or 0
    except Exception as e:
        logger.debug(f"DB stats check: {e}")

    ws_clients_count = len(player_manager.ws_clients) if (player_manager and hasattr(player_manager, "ws_clients")) else 0

    return {
        "bot_online": bot.is_ready() if bot else False,
        "bot_user": {
            "id": str(bot.user.id) if bot and bot.user else "",
            "name": bot.user.name if bot and bot.user else "Musicium",
            "avatar": bot.user.display_avatar.url if (bot and bot.user and hasattr(bot.user, "display_avatar")) else "/static/activity_icon.jpg",
        },
        "guilds_count": guilds_count,
        "total_users": total_users,
        "active_voice_count": active_voice_count,
        "playing_count": playing_count,
        "latency_ms": latency_ms,
        "uptime_seconds": int(uptime_sec),
        "uptime_str": format_uptime(uptime_sec),
        "memory_mb": get_memory_usage_mb(),
        "platform": {
            "os": sys.platform,
            "python_version": sys.version.split()[0],
            "discord_version": discord.__version__,
        },
        "cookies": {
            "configured": cookies_valid,
            "count": cookie_count,
            "size_kb": cookie_size_kb,
            "path": cookie_path,
        },
        "database": db_stats,
        "ws_clients": ws_clients_count,
        "log_buffer_size": len(admin_log_handler.buffer),
    }


# --- Guilds & Voice Channels Management ---

def get_guilds_admin_data(bot: discord.Client, player_manager: Any) -> List[Dict[str, Any]]:
    if not bot or not hasattr(bot, "guilds"):
        return []

    result = []
    for g in bot.guilds:
        # Check voice state
        guild_vc = getattr(g, "voice_client", None)
        is_connected = bool(guild_vc and guild_vc.is_connected() and guild_vc.channel)
        
        current_ch_data = None
        current_members = []
        if is_connected and guild_vc.channel:
            ch = guild_vc.channel
            for m in ch.members:
                current_members.append({
                    "id": str(m.id),
                    "name": m.display_name or m.name,
                    "avatar": m.display_avatar.url if hasattr(m, "display_avatar") else None,
                    "bot": m.bot,
                })
            current_ch_data = {
                "id": str(ch.id),
                "name": ch.name,
                "bitrate": getattr(ch, "bitrate", 64000) // 1000,
                "user_limit": getattr(ch, "user_limit", 0),
                "members": current_members,
                "member_count": len([m for m in ch.members if not m.bot]),
            }

        # Player state
        player_data = None
        player = player_manager.players.get(g.id) if (player_manager and hasattr(player_manager, "players")) else None
        if player:
            track_dict = player.current_track.to_dict() if player.current_track else None
            player_data = {
                "is_playing": player.is_playing,
                "is_paused": player.is_paused,
                "volume": int(player.volume * 100),
                "loop_mode": player.loop_mode,
                "elapsed": player.get_elapsed_seconds(),
                "duration": player.current_track.duration if player.current_track else 0,
                "current_track": track_dict,
                "queue_count": len(player.queue),
            }

        # Available Voice & Stage channels for switching
        all_vcs = []
        for vc in list(getattr(g, "voice_channels", [])) + list(getattr(g, "stage_channels", [])):
            non_bots = len([m for m in vc.members if not m.bot])
            all_vcs.append({
                "id": str(vc.id),
                "name": vc.name,
                "type": "stage" if isinstance(vc, discord.StageChannel) else "voice",
                "user_count": non_bots,
                "is_current": bool(is_connected and guild_vc.channel and guild_vc.channel.id == vc.id),
            })

        # Sort channels: current first, then by name
        all_vcs.sort(key=lambda x: (not x["is_current"], x["name"].lower()))

        result.append({
            "id": str(g.id),
            "name": g.name,
            "icon": g.icon.url if g.icon else None,
            "member_count": getattr(g, "member_count", 0),
            "is_connected": is_connected,
            "current_channel": current_ch_data,
            "player": player_data,
            "voice_channels": all_vcs,
        })

    # Sort: Connected servers first, then alphabetically
    result.sort(key=lambda x: (not x["is_connected"], x["name"].lower()))
    return result


async def switch_bot_channel(bot: discord.Client, player_manager: Any, guild_id: int, channel_id: int) -> Tuple[bool, str]:
    guild = bot.get_guild(guild_id)
    if not guild:
        return False, f"Сервер с ID {guild_id} не найден."

    channel = guild.get_channel(channel_id)
    if not channel or not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        return False, f"Голосовой канал с ID {channel_id} не найден."

    player = player_manager.get_or_create_player(guild)
    try:
        player._allow_move = True
        await player.connect_to_channel(channel, force=True)
        logger.info(f"[ADMIN ACTION] Bot channel switched to '{channel.name}' in guild '{guild.name}'.")
        return True, f"Бот успешно переключен в канал «{channel.name}»"
    except Exception as e:
        logger.error(f"[ADMIN ACTION] Failed to switch channel: {e}", exc_info=True)
        return False, f"Ошибка переключения канала: {str(e)}"


async def disconnect_bot_voice(bot: discord.Client, player_manager: Any, guild_id: int) -> Tuple[bool, str]:
    guild = bot.get_guild(guild_id)
    if not guild:
        return False, f"Сервер с ID {guild_id} не найден."

    player = player_manager.get_player_by_guild_id(guild_id)
    if player:
        player._explicit_stop = True
        try:
            await player.stop()
        except Exception:
            pass

    guild_vc = getattr(guild, "voice_client", None)
    if guild_vc and guild_vc.is_connected():
        try:
            await guild_vc.disconnect(force=True)
            if player:
                player.voice_client = None
                await player._notify_change()
            logger.info(f"[ADMIN ACTION] Bot disconnected from voice in guild '{guild.name}'.")
            return True, f"Бот успешно отключен от голосового канала на сервере «{guild.name}»."
        except Exception as e:
            logger.error(f"[ADMIN ACTION] Disconnect error: {e}")
            return False, f"Ошибка отключения: {str(e)}"

    return True, "Бот уже не был подключен к голосовому каналу."


async def perform_player_action(player_manager: Any, guild_id: int, action: str, value: Any = None) -> Tuple[bool, str]:
    player = player_manager.get_player_by_guild_id(guild_id)
    if not player:
        return False, "Плеер для этого сервера не найден."

    action = (action or "").lower().strip()
    try:
        if action == "play" or action == "resume":
            await player.resume()
            return True, "Воспроизведение возобновлено"
        elif action == "pause":
            await player.pause()
            return True, "Воспроизведение приостановлено"
        elif action == "skip":
            res = await player.skip(forced=True)
            return True, "Трек пропущен"
        elif action == "stop":
            await player.stop()
            return True, "Воспроизведение остановлено"
        elif action == "volume":
            vol = float(value) / 100.0 if value is not None else 1.0
            new_vol = player.set_volume(vol)
            player_manager.guild_volumes[guild_id] = new_vol
            return True, f"Громкость установлена на {int(new_vol * 100)}%"
        else:
            return False, f"Неизвестное действие '{action}'"
    except Exception as e:
        return False, f"Ошибка выполнения действия: {str(e)}"
