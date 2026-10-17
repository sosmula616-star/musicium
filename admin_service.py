import os
import asyncio
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

PRIMARY_ADMIN_ID = (
    os.getenv("PRIMARY_ADMIN_ID")
    or (os.getenv("ADMIN_IDS", "410432175373156352").replace(";", ",").split(",")[0].strip())
    or "410432175373156352"
)
_extra_admin_ids: Set[str] = set()

def get_admin_ids() -> Set[str]:
    raw = os.getenv("ADMIN_IDS", PRIMARY_ADMIN_ID)
    ids = {x.strip() for x in raw.replace(";", ",").split(",") if x.strip()}
    ids.add(PRIMARY_ADMIN_ID)
    ids.update(_extra_admin_ids)
    return ids

def add_admin_id(uid: Any) -> None:
    if uid:
        u_str = str(uid).strip()
        if u_str.isdigit():
            _extra_admin_ids.add(u_str)

_SECRET_SALT = os.getenv("DISCORD_CLIENT_SECRET") or "musicium_super_secure_admin_salt_2026"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()

def verify_admin_password(password: Optional[str]) -> bool:
    if not password:
        return False
    pwd = password.strip()
    valid_passwords = set()
    if ADMIN_PASSWORD:
        valid_passwords.add(ADMIN_PASSWORD)
    discord_token = os.getenv("DISCORD_TOKEN", "").strip()
    if discord_token:
        valid_passwords.add(discord_token)
    client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
    if client_secret:
        valid_passwords.add(client_secret)
    if not valid_passwords:
        return False
    return pwd in valid_passwords

def is_admin_id(user_id: Any) -> bool:
    if not user_id:
        return False
    return str(user_id).strip() in get_admin_ids()

# In-memory storage for 6-digit one-time login PIN codes
_admin_login_codes: Dict[str, Dict[str, Any]] = {}

def create_admin_login_code(user_id: str, ttl_seconds: int = 900) -> Optional[str]:
    """Generates a secure 6-digit PIN code for an authorized admin user."""
    import secrets
    uid = user_id.strip()
    if not is_admin_id(uid):
        return None
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    _admin_login_codes[uid] = {
        "code": code,
        "expires_at": time.time() + ttl_seconds,
        "attempts": 0,
    }
    logger.info(f"[ADMIN AUTH] Generated one-time login PIN code for admin user {uid} (expires in {ttl_seconds}s)")
    return code

def verify_admin_login_code(user_id: str, input_code: str) -> bool:
    """Verifies a 6-digit PIN code with anti-brute force and expiration checks."""
    uid = user_id.strip()
    if not is_admin_id(uid):
        return False
    entry = _admin_login_codes.get(uid)
    if not entry:
        return False
    if time.time() > entry.get("expires_at", 0):
        _admin_login_codes.pop(uid, None)
        logger.info(f"[ADMIN AUTH] Code for {uid} expired")
        return False
    entry["attempts"] = entry.get("attempts", 0) + 1
    if entry["attempts"] > 5:
        _admin_login_codes.pop(uid, None)
        logger.warning(f"[ADMIN AUTH] Too many invalid attempts for {uid}, PIN invalidated")
        return False
    if hmac.compare_digest(str(entry.get("code", "")), input_code.strip()):
        _admin_login_codes.pop(uid, None)
        logger.info(f"[ADMIN AUTH] Login PIN verified successfully for admin {uid}")
        return True
    return False

def generate_admin_token(user_id: str, name: Optional[str] = "", avatar: Optional[str] = "", max_age_days: int = 7) -> str:
    user_id = user_id.strip()
    exp = int(time.time()) + (max_age_days * 86400)
    payload_data = {
        "uid": user_id,
        "name": name or f"Admin ({user_id[-4:]})",
        "avatar": avatar or "/static/activity_icon.jpg",
        "exp": exp,
        "auth": "discord_oauth2",
        "created_at": int(time.time()),
    }
    raw = json.dumps(payload_data, separators=(',', ':')).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    sig = hmac.new(_SECRET_SALT.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"

def verify_admin_token(token: Optional[str]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    if not token or "." not in token:
        return False, None
    parts = token.split(".")
    if len(parts) != 2:
        return False, None
    payload_b64, sig = parts

    expected_sig = hmac.new(_SECRET_SALT.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False, None

    try:
        rem = len(payload_b64) % 4
        padded = payload_b64 + ("=" * ((4 - rem) % 4))
        raw = base64.urlsafe_b64decode(padded)
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return False, None

    # Check expiration
    if time.time() > data.get("exp", 0):
        return False, None

    # Verify ID is in admin IDs list
    uid = str(data.get("uid", ""))
    if not is_admin_id(uid):
        return False, None

    return True, data


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

    # WebSocket clients count
    ws_clients_count = len(getattr(player_manager, "ws_clients", ())) if player_manager else 0

    # YouTube cookies info
    cookie_path = getattr(music_service, "youtube_cookie_path", None)
    cookies_valid = bool(cookie_path and isinstance(cookie_path, str) and os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0)
    cookie_count = 0
    cookie_size_kb = 0.0
    if cookies_valid and isinstance(cookie_path, str):
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

    # AntiCrash stats
    restricted_count = 0
    try:
        import anticrash_service
        restricted_count = len(anticrash_service.anticrash._restricted_cache)
    except Exception:
        pass

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
        "streaming_settings": getattr(music_service, "streaming_settings", {}),
        "database": db_stats,
        "ws_clients": ws_clients_count,
        "log_buffer_size": len(admin_log_handler.buffer),
        "restricted_count": restricted_count,
    }


async def get_admin_stats(bot: discord.Client, player_manager_or_music: Any = None, music_service: Any = None) -> Dict[str, Any]:
    """Flexible compatibility alias for get_system_stats."""
    if music_service is None and hasattr(player_manager_or_music, "get_streaming_settings"):
        return await get_system_stats(bot, None, player_manager_or_music)
    return await get_system_stats(bot, player_manager_or_music, music_service)


# --- Guilds & Voice Channels Management ---

def get_guilds_admin_data(bot: discord.Client, player_manager: Any) -> List[Dict[str, Any]]:
    if not bot or not hasattr(bot, "guilds"):
        return []

    result = []
    for g in bot.guilds:
        # Check voice state
        guild_vc = getattr(g, "voice_client", None)
        active_channel = getattr(guild_vc, "channel", None) if guild_vc else None
        is_connected = bool(guild_vc and getattr(guild_vc, "is_connected", lambda: False)() and active_channel)
        
        current_ch_data = None
        current_members = []
        if is_connected and active_channel:
            ch_members = getattr(active_channel, "members", [])
            for m in ch_members:
                current_members.append({
                    "id": str(getattr(m, "id", "")),
                    "name": getattr(m, "display_name", None) or getattr(m, "name", "User"),
                    "avatar": m.display_avatar.url if hasattr(m, "display_avatar") else None,
                    "bot": getattr(m, "bot", False),
                })
            current_ch_data = {
                "id": str(getattr(active_channel, "id", "")),
                "name": getattr(active_channel, "name", "Voice"),
                "bitrate": getattr(active_channel, "bitrate", 64000) // 1000,
                "user_limit": getattr(active_channel, "user_limit", 0),
                "members": current_members,
                "member_count": len([m for m in ch_members if not getattr(m, "bot", False)]),
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
                "queue": [t.to_dict() for t in player.queue[:25]],
            }


        # Available Voice & Stage channels for switching
        all_vcs = []
        for vc in list(getattr(g, "voice_channels", [])) + list(getattr(g, "stage_channels", [])):
            vc_members = getattr(vc, "members", [])
            non_bots = len([m for m in vc_members if not getattr(m, "bot", False)])
            all_vcs.append({
                "id": str(getattr(vc, "id", "")),
                "name": getattr(vc, "name", "Voice"),
                "type": "stage" if isinstance(vc, discord.StageChannel) else "voice",
                "user_count": non_bots,
                "is_current": bool(is_connected and active_channel and getattr(active_channel, "id", None) == getattr(vc, "id", None)),
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
        logger.info(f"[ADMIN ACTION] Connecting to '{channel.name}' in guild '{guild.name}'...")
        # Без таймаута зависшее голосовое подключение держит запрос открытым, и админка «молчит»
        await asyncio.wait_for(player.connect_to_channel(channel, force=True), timeout=25.0)
        logger.info(f"[ADMIN ACTION] Bot channel switched to '{channel.name}' in guild '{guild.name}'.")
        return True, f"Бот успешно переключен в канал «{channel.name}»"
    except asyncio.TimeoutError:
        logger.error(f"[ADMIN ACTION] Voice connect to '{channel.name}' timed out in guild '{guild.name}'")
        return False, "Голосовое подключение не установилось за 25 секунд. Проверьте права бота (Подключаться / Говорить) в канале и версию discord.py + davey на хостинге."
    except discord.Forbidden:
        return False, f"У бота нет прав на вход в канал «{channel.name}» (нужны «Подключаться» и «Говорить»)."
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
        elif action == "clear_queue":
            player.clear_queue()
            return True, "Очередь сервера очищена"
        elif action == "remove_queue_track":
            idx = int(value) if value is not None else -1
            removed = player.remove_from_queue(idx)
            if removed:
                return True, f"Трек «{removed.title}» удален из очереди"
            return False, "Некорректный индекс трека"
        else:
            return False, f"Неизвестное действие '{action}'"
    except Exception as e:
        return False, f"Ошибка выполнения действия: {str(e)}"


async def play_url_on_guild(bot: discord.Client, player_manager: Any, music_service: Any, guild_id: int, query: str) -> Tuple[bool, str]:
    guild = bot.get_guild(guild_id)
    if not guild:
        return False, f"Сервер с ID {guild_id} не найден."

    tracks = await music_service.search(query, source="all", limit=1)
    if not tracks:
        return False, f"Ничего не найдено по запросу: {query}"

    track = tracks[0]
    track.requester_name = "Администратор"

    player = player_manager.get_or_create_player(guild)
    if not player.is_connected:
        # Find first channel with members or any voice channel
        all_vcs = list(getattr(guild, "voice_channels", [])) + list(getattr(guild, "stage_channels", []))
        target_vc = None
        for vc in all_vcs:
            if any(not m.bot for m in vc.members):
                target_vc = vc
                break
        if not target_vc and all_vcs:
            target_vc = all_vcs[0]
        if target_vc:
            try:
                await asyncio.wait_for(player.connect_to_channel(target_vc, force=True), timeout=25.0)
            except asyncio.TimeoutError:
                return False, "Голосовое подключение не установилось за 25 секунд (права бота или версия discord.py/davey)."
            except discord.Forbidden:
                return False, f"У бота нет прав на вход в канал «{target_vc.name}»."
        else:
            return False, "На сервере нет доступных голосовых комнат."

    res = await player.enqueue(track, play_now=True)
    logger.info(f"[ADMIN ACTION] Admin enqueued '{track.title}' on guild '{guild.name}'.")
    return True, f"Трек «{track.title}» успешно включен!"



# --- Admin Audit Trail (журнал действий администраторов) ---

AUDIT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin_audit.jsonl")
AUDIT_MAXLEN = 2000
_SENSITIVE_KEYS = ("password", "pass", "code", "pin", "key", "token", "secret", "cookie", "content", "authorization")

audit_buffer: "deque[Dict[str, Any]]" = deque(maxlen=AUDIT_MAXLEN)
_audit_seq = 0


def _load_audit_tail() -> None:
    """Подгружает последние записи журнала с диска, чтобы он переживал перезапуск."""
    global _audit_seq
    try:
        if not os.path.exists(AUDIT_FILE):
            return
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-AUDIT_MAXLEN:]
        for line in lines:
            try:
                entry = json.loads(line)
                audit_buffer.append(entry)
                _audit_seq = max(_audit_seq, int(entry.get("id", 0)))
            except Exception:
                continue
    except Exception as e:
        logging.getLogger("admin_service").warning(f"Не удалось загрузить журнал аудита: {e}")


def sanitize_audit_details(data: Any, depth: int = 0) -> Any:
    """Убирает секреты из тела запроса и обрезает длинные значения."""
    if depth > 3:
        return "…"
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            kl = str(k).lower()
            if any(s in kl for s in _SENSITIVE_KEYS):
                out[k] = "***"
            else:
                out[k] = sanitize_audit_details(v, depth + 1)
        return out
    if isinstance(data, list):
        return [sanitize_audit_details(v, depth + 1) for v in data[:10]]
    if isinstance(data, str):
        return data if len(data) <= 200 else data[:200] + "…"
    return data


def record_audit(action: str, admin_id: str = "", admin_name: str = "", ip: str = "",
                 method: str = "", path: str = "", status: int = 200,
                 details: Optional[Dict[str, Any]] = None, message: str = "",
                 duration_ms: int = 0) -> Dict[str, Any]:
    """Добавляет запись в журнал действий (память + файл + общий лог)."""
    global _audit_seq
    _audit_seq += 1
    now = time.time()
    entry = {
        "id": _audit_seq,
        "ts": now,
        "time": datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "admin_id": str(admin_id or ""),
        "admin_name": admin_name or "",
        "ip": ip,
        "method": method,
        "path": path,
        "status": int(status),
        "ok": 200 <= int(status) < 400,
        "message": message or "",
        "details": sanitize_audit_details(details or {}),
        "duration_ms": duration_ms,
    }
    audit_buffer.append(entry)
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
    logging.getLogger("admin_audit").info(
        "%s | admin=%s | status=%s | %s", action, entry["admin_name"] or entry["admin_id"] or "anonymous",
        entry["status"], json.dumps(entry["details"], ensure_ascii=False)
    )
    return entry


def get_audit(search: Optional[str] = None, status: Optional[str] = None,
              action: Optional[str] = None, limit: int = 300) -> List[Dict[str, Any]]:
    entries = list(audit_buffer)
    if status == "ok":
        entries = [e for e in entries if e["ok"]]
    elif status == "error":
        entries = [e for e in entries if not e["ok"]]
    if action:
        entries = [e for e in entries if e["action"] == action]
    if search:
        q = search.lower()
        entries = [e for e in entries if q in json.dumps(e, ensure_ascii=False).lower()]
    if limit and limit > 0:
        entries = entries[-limit:]
    return entries


def export_audit_text() -> str:
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in audit_buffer)


_load_audit_tail()


# --- Bot management: maintenance mode, presence, diagnostics, bulk actions ---

BOT_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_settings.json")
_DEFAULT_BOT_SETTINGS: Dict[str, Any] = {
    "maintenance": {"enabled": False, "message": "Бот временно на техническом обслуживании. Попробуйте позже."},
    "presence": {"status": "online", "activity_type": "listening", "text": ""},
}
bot_settings: Dict[str, Any] = json.loads(json.dumps(_DEFAULT_BOT_SETTINGS))


def _load_bot_settings() -> None:
    try:
        if os.path.exists(BOT_SETTINGS_FILE):
            with open(BOT_SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for key in _DEFAULT_BOT_SETTINGS:
                if isinstance(saved.get(key), dict):
                    bot_settings[key].update(saved[key])
    except Exception as e:
        logging.getLogger("admin_service").warning(f"Не удалось загрузить bot_settings.json: {e}")


def _save_bot_settings() -> None:
    try:
        with open(BOT_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(bot_settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.getLogger("admin_service").warning(f"Не удалось сохранить bot_settings.json: {e}")


def get_maintenance() -> Dict[str, Any]:
    return dict(bot_settings["maintenance"])


def set_maintenance(enabled: bool, message: Optional[str] = None) -> Dict[str, Any]:
    bot_settings["maintenance"]["enabled"] = bool(enabled)
    if message is not None and message.strip():
        bot_settings["maintenance"]["message"] = message.strip()[:300]
    _save_bot_settings()
    return get_maintenance()


def is_maintenance_blocked(user_id: Any) -> Tuple[bool, str]:
    """True, если включён режим обслуживания и пользователь не администратор."""
    m = bot_settings["maintenance"]
    if not m.get("enabled"):
        return False, ""
    try:
        if user_id is not None and is_admin_id(user_id):
            return False, ""
    except Exception:
        pass
    return True, str(m.get("message") or "Бот на обслуживании.")


_STATUS_MAP = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}


async def apply_presence(bot: discord.Client, status: str, activity_type: str, text: str) -> Tuple[bool, str]:
    status = (status or "online").lower()
    activity_type = (activity_type or "listening").lower()
    text = (text or "").strip()[:128]
    if status not in _STATUS_MAP:
        return False, "Неизвестный статус"
    activity = None
    if text:
        if activity_type == "playing":
            activity = discord.Game(name=text)
        elif activity_type == "watching":
            activity = discord.Activity(type=discord.ActivityType.watching, name=text)
        elif activity_type == "competing":
            activity = discord.Activity(type=discord.ActivityType.competing, name=text)
        else:
            activity_type = "listening"
            activity = discord.Activity(type=discord.ActivityType.listening, name=text)
    try:
        await bot.change_presence(status=_STATUS_MAP[status], activity=activity)
    except Exception as e:
        return False, f"Не удалось изменить статус: {e}"
    bot_settings["presence"] = {"status": status, "activity_type": activity_type, "text": text}
    _save_bot_settings()
    return True, "Статус бота обновлён"


async def apply_saved_presence(bot: discord.Client) -> None:
    """Применяет сохранённый статус после готовности бота."""
    try:
        await bot.wait_until_ready()
        p = bot_settings["presence"]
        if p.get("text") or p.get("status") != "online":
            await apply_presence(bot, p.get("status"), p.get("activity_type"), p.get("text"))
    except Exception as e:
        logging.getLogger("admin_service").debug(f"apply_saved_presence: {e}")


async def stop_all_players(player_manager: Any) -> int:
    stopped = 0
    for player in list(getattr(player_manager, "players", {}).values()):
        try:
            if player.current_track or player.queue:
                await player.stop()
                stopped += 1
        except Exception as e:
            logging.getLogger("admin_service").debug(f"stop_all_players: {e}")
    return stopped


async def disconnect_all_voice(bot: discord.Client, player_manager: Any) -> int:
    count = 0
    for guild in list(getattr(bot, "guilds", [])):
        vc = getattr(guild, "voice_client", None)
        if vc and vc.is_connected():
            ok, _ = await disconnect_bot_voice(bot, player_manager, guild.id)
            if ok:
                count += 1
    return count


def _which(cmd: str) -> Optional[str]:
    import shutil
    return shutil.which(cmd)


async def get_bot_overview(bot: discord.Client, player_manager: Any, music_service: Any) -> Dict[str, Any]:
    import platform
    diag: Dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.system() + " " + platform.release(),
        "discord_py": getattr(discord, "__version__", "?"),
    }
    try:
        import yt_dlp
        diag["yt_dlp"] = yt_dlp.version.__version__
    except Exception:
        diag["yt_dlp"] = None
    try:
        import player as _player
        ff = getattr(_player, "FFMPEG_EXECUTABLE", None)
        diag["ffmpeg"] = bool(ff and (os.path.isfile(ff) or _which(ff)))
    except Exception:
        diag["ffmpeg"] = False
    try:
        diag["opus"] = bool(discord.opus.is_loaded())
    except Exception:
        diag["opus"] = False
    try:
        import db as _db
        diag["database"] = getattr(_db, "_pool", None) is not None
    except Exception:
        diag["database"] = False

    players = getattr(player_manager, "players", {}) or {}
    playing = sum(1 for p in players.values() if getattr(p, "is_playing", False))
    queued = sum(len(getattr(p, "queue", []) or []) for p in players.values())
    voice_conns = 0
    for g in getattr(bot, "guilds", []):
        vc = getattr(g, "voice_client", None)
        if vc and vc.is_connected():
            voice_conns += 1
    latency = getattr(bot, "latency", 0) or 0
    if latency != latency:  # NaN, пока бот не подключён
        latency = 0
    return {
        "maintenance": get_maintenance(),
        "presence": dict(bot_settings["presence"]),
        "diagnostics": diag,
        "players": {"total": len(players), "playing": playing, "queued_tracks": queued, "voice_connections": voice_conns},
        "caches": {
            "streams": len(getattr(music_service, "_stream_cache", {}) or {}),
            "trending": len(getattr(music_service, "_sc_trending_cache", {}) or {}),
        },
        "latency_ms": int(latency * 1000),
    }


# --- Changelog (публичный журнал обновлений) ---

CHANGELOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "changelog.json")


def load_changelog() -> List[Dict[str, Any]]:
    try:
        with open(CHANGELOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def add_changelog_entry(version: str, title: str, items: List[str], author: str = "") -> Dict[str, Any]:
    version = (version or "").strip()[:20]
    title = (title or "").strip()[:120]
    clean_items = [str(i).strip()[:300] for i in (items or []) if str(i).strip()][:30]
    if not version or not title or not clean_items:
        raise ValueError("Нужны версия, заголовок и хотя бы один пункт")
    entries = load_changelog()
    entry = {
        "version": version,
        "title": title,
        "date": datetime.date.today().isoformat(),
        "items": clean_items,
        "author": author or "",
    }
    entries = [e for e in entries if e.get("version") != version]
    entries.insert(0, entry)
    with open(CHANGELOG_FILE, "w", encoding="utf-8") as f:
        json.dump(entries[:100], f, ensure_ascii=False, indent=2)
    return entry


_load_bot_settings()
