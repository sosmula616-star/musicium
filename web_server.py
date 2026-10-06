import os
import json
import asyncio
import logging
from typing import Optional, Tuple, Dict, Any, List
import urllib.parse
from aiohttp import web, WSMsgType
import aiohttp
import discord

from music_service import MusicService, Track
from player_manager import PlayerManager

import db
import admin_service

logger = logging.getLogger("web_server")

@web.middleware
async def cache_control_middleware(request: web.Request, handler):
    response = await handler(request)
    if request.path.startswith("/static/") or request.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

def safe_int(val, default=None):
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

class WebServer:
    def __init__(self, bot, player_manager: PlayerManager, music_service: MusicService):
        self.bot = bot
        self.player_manager = player_manager
        self.music_service = music_service
        self.app = web.Application(middlewares=[cache_control_middleware])
        self.runner = None
        self.site = None

        self.host = os.getenv("WEB_HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT") or os.getenv("SERVER_PORT") or os.getenv("WEB_PORT", 3000))
        self.client_id = os.getenv("DISCORD_CLIENT_ID", "")
        self.client_secret = os.getenv("DISCORD_CLIENT_SECRET", "")

        self._setup_routes()

    def _setup_routes(self):
        # API routes
        self.app.router.add_get("/api/status", self.handle_status)
        self.app.router.add_get("/api/guilds", self.handle_guilds)
        self.app.router.add_post("/api/join-channel", self.handle_join_channel)
        self.app.router.add_get("/api/user-voice", self.handle_user_voice)
        self.app.router.add_get("/api/voice-users", self.handle_voice_users)
        self.app.router.add_get("/api/search", self.handle_search)
        self.app.router.add_get("/api/player", self.handle_get_player)
        self.app.router.add_post("/api/play", self.handle_play)
        self.app.router.add_post("/api/action", self.handle_action)
        self.app.router.add_post("/api/token", self.handle_discord_token)
        self.app.router.add_get("/api/auth/discord", self.handle_auth_discord)
        self.app.router.add_get("/api/auth/callback", self.handle_auth_callback)
        self.app.router.add_get("/api/proxy-image", self.handle_proxy_image)
        self.app.router.add_get("/api/recommendations", self.handle_recommendations)

        # User Database routes (PostgreSQL)
        self.app.router.add_get("/api/user/liked", self.handle_get_liked)
        self.app.router.add_post("/api/user/liked", self.handle_post_liked)
        self.app.router.add_get("/api/user/playlists", self.handle_get_playlists)
        self.app.router.add_post("/api/user/playlists", self.handle_post_playlists)
        self.app.router.add_delete("/api/user/playlists/{id}", self.handle_delete_playlist)
        self.app.router.add_post("/api/user/playlists/{id}/tracks", self.handle_add_playlist_track)
        self.app.router.add_delete("/api/user/playlists/{id}/tracks", self.handle_remove_playlist_track)
        self.app.router.add_get("/api/user/history", self.handle_get_history)
        self.app.router.add_post("/api/user/history", self.handle_post_history)
        self.app.router.add_delete("/api/user/history", self.handle_clear_history)

        # Community / Shared Playlists & Leaderboard (PostgreSQL)
        self.app.router.add_get("/api/community/playlists", self.handle_get_community_playlists)
        self.app.router.add_post("/api/community/playlists/{id}/like", self.handle_post_playlist_like)

        # Live Streams & Recent Plays Feed
        self.app.router.add_get("/api/feed/discovery", self.handle_feed_discovery)

        # Admin / Diagnostics
        self.app.router.add_get("/admin", self.handle_admin)
        self.app.router.add_get("/api/admin/auth/status", self.handle_admin_auth_status)
        self.app.router.add_post("/api/admin/auth/login", self.handle_admin_auth_login)
        self.app.router.add_post("/api/admin/auth/logout", self.handle_admin_auth_logout)
        self.app.router.add_get("/api/admin/stats", self.handle_admin_stats)
        self.app.router.add_get("/api/admin/guilds", self.handle_admin_guilds)
        self.app.router.add_post("/api/admin/bot/switch-channel", self.handle_admin_switch_channel)
        self.app.router.add_post("/api/admin/bot/disconnect", self.handle_admin_disconnect)
        self.app.router.add_post("/api/admin/bot/player-action", self.handle_admin_player_action)
        self.app.router.add_post("/api/admin/bot/leave-guild", self.handle_admin_leave_guild)
        self.app.router.add_get("/api/admin/logs", self.handle_admin_logs)
        self.app.router.add_post("/api/admin/logs/clear", self.handle_admin_logs_clear)
        self.app.router.add_get("/api/admin/logs/download", self.handle_admin_logs_download)
        self.app.router.add_post("/api/admin/broadcast", self.handle_admin_broadcast)
        self.app.router.add_get("/api/admin/cookies", self.handle_admin_cookies)
        self.app.router.add_post("/api/admin/cookies", self.handle_admin_cookies)

        # WebSocket
        self.app.router.add_get("/ws", self.handle_websocket)

        # Static files and SPA index
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        os.makedirs(static_dir, exist_ok=True)
        self.app.router.add_static("/static/", path=static_dir, name="static")
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/terms", self.handle_terms)
        self.app.router.add_get("/privacy", self.handle_privacy)

    async def handle_index(self, request: web.Request) -> web.Response:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return web.FileResponse(index_file, headers={"Cache-Control": "no-cache, must-revalidate"})
        return web.Response(text="<h1>Discord Music Mini App</h1><p>Frontend loading...</p>", content_type="text/html")

    async def handle_terms(self, request: web.Request) -> web.Response:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        terms_file = os.path.join(static_dir, "terms.html")
        if os.path.exists(terms_file):
            return web.FileResponse(terms_file, headers={"Cache-Control": "no-cache, must-revalidate"})
        return web.Response(text="<h1>Terms of Service</h1><p>Musicium Terms of Service</p>", content_type="text/html")

    async def handle_privacy(self, request: web.Request) -> web.Response:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        privacy_file = os.path.join(static_dir, "privacy.html")
        if os.path.exists(privacy_file):
            return web.FileResponse(privacy_file, headers={"Cache-Control": "no-cache, must-revalidate"})
        return web.Response(text="<h1>Privacy Policy</h1><p>Musicium Privacy Policy</p>", content_type="text/html")

    async def handle_status(self, request: web.Request) -> web.Response:
        bot_user = None
        if self.bot.user:
            bot_user = {
                "id": str(self.bot.user.id),
                "name": self.bot.user.name,
                "avatar": self.bot.user.display_avatar.url if hasattr(self.bot.user, "display_avatar") else None,
            }

        return web.json_response({
            "online": self.bot.is_ready(),
            "bot": bot_user,
            "guilds_count": len(self.bot.guilds),
        })

    async def handle_guilds(self, request: web.Request) -> web.Response:
        user_id_str = request.query.get("user_id")
        guild_id_str = request.query.get("guild_id")
        current_user_id = safe_int(user_id_str)
        target_guild_id = safe_int(guild_id_str)
        guilds = self.player_manager.get_all_guilds_info(current_user_id=current_user_id)
        if target_guild_id:
            guilds = [g for g in guilds if g["id"] == str(target_guild_id)]
        return web.json_response({"guilds": guilds})

    async def handle_join_channel(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON body"}, status=400)

        channel_id_str = data.get("channel_id")
        guild_id_str = data.get("guild_id")
        user_id_str = data.get("user_id")
        action = data.get("action", "join")

        guild_id = safe_int(guild_id_str)
        user_id = safe_int(user_id_str)

        if action == "leave":
            player = self.player_manager.get_player_by_guild_id(guild_id) if guild_id else None
            if player and player.voice_client and player.voice_client.channel:
                bot_channel = player.voice_client.channel
                human_members = [m for m in bot_channel.members if not m.bot]
                if human_members and user_id and user_id not in [m.id for m in human_members]:
                    member = player.guild.get_member(user_id)
                    if not (member and member.guild_permissions.administrator):
                        return web.json_response({
                            "success": False,
                            "error": "Отключить бота могут только участники голосовой комнаты, в которой он находится!"
                        }, status=403)
                await player.stop()
            elif guild_id:
                g = self.bot.get_guild(guild_id)
                if g and getattr(g, "voice_client", None):
                    await g.voice_client.disconnect(force=True)
            return web.json_response({"success": True, "action": "left"})

        channel_id = safe_int(channel_id_str)
        if not channel_id:
            return web.json_response({"success": False, "error": "channel_id is required or invalid"}, status=400)

        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                pass

        if not channel or not isinstance(channel, (discord.VoiceChannel, getattr(discord, "StageChannel", ()))):
            return web.json_response({"success": False, "error": "Голосовой канал не найден или недоступен"}, status=404)

        guild = channel.guild

        # Check: User must belong to this guild
        if user_id:
            member = guild.get_member(user_id)
            if not member:
                return web.json_response({
                    "success": False,
                    "error": "Вы не являетесь участником этого сервера!"
                }, status=403)

        # Check: If bot is already connected in a channel on this guild, prevent moving across channels
        guild_vc = getattr(guild, "voice_client", None)
        if guild_vc and guild_vc.is_connected() and guild_vc.channel:
            if guild_vc.channel.id != channel.id:
                return web.json_response({
                    "success": False,
                    "error": f"Бот уже находится в комнате «{guild_vc.channel.name}». Перемещение бота по серверу запрещено!"
                }, status=403)

        player = self.player_manager.get_or_create_player(guild)
        try:
            await player.connect_to_channel(channel)
            return web.json_response({
                "success": True,
                "action": "joined",
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "channel_id": str(channel.id),
                "channel_name": channel.name,
                "player": player.get_state(),
            })
        except Exception as e:
            logger.error(f"Error connecting to channel {channel_id}: {e}")
            return web.json_response({"success": False, "error": f"Не удалось подключиться: {str(e)}"}, status=500)

    async def handle_voice_users(self, request: web.Request) -> web.Response:
        """Returns users currently connected to voice channels across bot guilds."""
        guild_id_str = request.query.get("guild_id")
        target_guild_id = safe_int(guild_id_str)

        voice_members = []
        guilds_to_check = [self.bot.get_guild(target_guild_id)] if target_guild_id and self.bot.get_guild(target_guild_id) else self.bot.guilds

        for guild in guilds_to_check:
            all_vcs = list(getattr(guild, "voice_channels", [])) + list(getattr(guild, "stage_channels", []))
            for vc in all_vcs:
                for member in vc.members:
                    if not member.bot:
                        voice_members.append({
                            "id": str(member.id),
                            "name": member.name,
                            "display_name": member.display_name,
                            "avatar": member.display_avatar.url if hasattr(member, "display_avatar") else None,
                            "channel_id": str(vc.id),
                            "channel_name": vc.name,
                            "guild_id": str(guild.id),
                            "guild_name": guild.name,
                        })

        return web.json_response({"voice_users": voice_members})

    def _serialize_channel_members(self, channel):
        if not channel or not hasattr(channel, "members"):
            return []
        members_data = []
        for m in channel.members:
            members_data.append({
                "id": str(m.id),
                "name": m.name,
                "display_name": m.display_name,
                "avatar": m.display_avatar.url if hasattr(m, "display_avatar") else None,
                "bot": m.bot,
            })
        return members_data

    async def handle_user_voice(self, request: web.Request) -> web.Response:
        user_id_str = request.query.get("user_id")
        guild_id_str = request.query.get("guild_id")
        channel_id_str = request.query.get("channel_id")

        guild_id = safe_int(guild_id_str)
        user_id = safe_int(user_id_str)
        channel_id = safe_int(channel_id_str)

        # Helper to find where bot is currently connected
        bot_voice = None
        if guild_id:
            g = self.bot.get_guild(guild_id)
            if g and getattr(g, "voice_client", None) and g.voice_client.is_connected() and g.voice_client.channel:
                bot_voice = {
                    "guild_id": str(g.id),
                    "guild_name": g.name,
                    "channel_id": str(g.voice_client.channel.id),
                    "channel_name": g.voice_client.channel.name,
                    "channel_members": self._serialize_channel_members(g.voice_client.channel),
                }
        if not bot_voice:
            for g in self.bot.guilds:
                if getattr(g, "voice_client", None) and g.voice_client.is_connected() and g.voice_client.channel:
                    bot_voice = {
                        "guild_id": str(g.id),
                        "guild_name": g.name,
                        "channel_id": str(g.voice_client.channel.id),
                        "channel_name": g.voice_client.channel.name,
                        "channel_members": self._serialize_channel_members(g.voice_client.channel),
                    }
                    break

        if not user_id:
            return web.json_response({
                "in_voice": False,
                "is_guest": True,
                "bot_voice": bot_voice,
                "message": "Гостевой сеанс или не указан ID",
            })

        # If channel_id was provided (e.g. from Discord Activity SDK), check it directly
        if channel_id:
            try:
                channel = self.bot.get_channel(channel_id)
                if channel and isinstance(channel, (discord.VoiceChannel, getattr(discord, "StageChannel", ()))):
                    guild = channel.guild
                    user_member = None
                    for m in channel.members:
                        if m.id == user_id:
                            user_member = m
                            break
                    if not user_member:
                        user_member = guild.get_member(user_id)

                    player = self.player_manager.get_player_by_guild_id(guild.id)
                    return web.json_response({
                        "in_voice": True,
                        "user_id": str(user_id),
                        "user_name": user_member.display_name if user_member else "Пользователь Discord",
                        "avatar": user_member.display_avatar.url if (user_member and hasattr(user_member, 'display_avatar')) else None,
                        "guild_id": str(guild.id),
                        "guild_name": guild.name,
                        "channel_id": str(channel.id),
                        "channel_name": channel.name,
                        "channel_members": self._serialize_channel_members(channel),
                        "player_active": player.is_playing if player else False,
                        "bot_voice": bot_voice,
                    })
            except Exception as e:
                logger.debug(f"Error checking channel_id {channel_id_str}: {e}")

        found = self.player_manager.find_user_voice(user_id, guild_id=guild_id)
        if not found:
            return web.json_response({
                "in_voice": False,
                "user_id": str(user_id),
                "bot_voice": bot_voice,
                "message": "Пользователь не находится в голосовом канале",
            })

        guild, channel, member = found
        player = self.player_manager.get_player_by_guild_id(guild.id)
        return web.json_response({
            "in_voice": True,
            "user_id": str(user_id),
            "user_name": member.display_name if member else "Пользователь Discord",
            "avatar": member.display_avatar.url if (member and hasattr(member, 'display_avatar')) else None,
            "guild_id": str(guild.id),
            "guild_name": guild.name,
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "channel_members": self._serialize_channel_members(channel),
            "player_active": player.is_playing if player else False,
            "bot_voice": bot_voice,
        })

    async def handle_search(self, request: web.Request) -> web.Response:
        q = request.query.get("q", "").strip()
        source = request.query.get("source", "all").strip().lower()

        if not q:
            return web.json_response({"tracks": []})

        limit_arg = int(request.query.get("limit", 35))
        tracks = await self.music_service.search(query=q, source=source, limit=min(limit_arg, 50))

        return web.json_response({
            "query": q,
            "source": source,
            "tracks": [t.to_dict() for t in tracks],
        })

    async def handle_get_player(self, request: web.Request) -> web.Response:
        guild_id_str = request.query.get("guild_id")
        user_id_str = request.query.get("user_id")

        guild_id = safe_int(guild_id_str)
        user_id = safe_int(user_id_str)

        player = None
        if guild_id:
            player = self.player_manager.get_player_by_guild_id(guild_id)
        elif user_id:
            player = self.player_manager.find_active_player_for_user(user_id)

        if not player:
            return web.json_response({"player": None})

        return web.json_response({"player": player.get_state()})

    async def handle_play(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON body"}, status=400)

        user_id_str = data.get("user_id")
        guild_id_str = data.get("guild_id")
        channel_id_str = data.get("channel_id")
        track_data = data.get("track")
        play_now = bool(data.get("play_now", False))

        if not user_id_str or not track_data:
            return web.json_response({"success": False, "error": "user_id and track are required"}, status=400)

        user_id = safe_int(user_id_str, default=0)
        guild_id = safe_int(guild_id_str)
        channel_id = safe_int(channel_id_str)

        # 1. Resolve user's voice channel
        target_channel = None
        target_guild = None
        member_name = "Пользователь Discord" if user_id else "Гость"

        if user_id:
            found = self.player_manager.find_user_voice(user_id, guild_id=guild_id)
            if found:
                target_guild, target_channel, member = found
                if member:
                    member_name = member.display_name

        # If user explicitly provided channel_id from UI, verify user membership
        if not target_channel and channel_id:
            try:
                ch = self.bot.get_channel(channel_id)
                if not ch:
                    try:
                        ch = await self.bot.fetch_channel(channel_id)
                    except Exception:
                        pass
                if ch and isinstance(ch, (discord.VoiceChannel, getattr(discord, "StageChannel", ()))):
                    if not guild_id or guild_id == ch.guild.id:
                        is_member = False
                        if user_id:
                            is_member = bool(ch.guild.get_member(user_id))
                        if is_member:
                            target_channel = ch
                            target_guild = ch.guild
            except Exception as e:
                logger.warning(f"Could not resolve explicit channel_id {channel_id}: {e}")

        # Strictly reject if user has not joined any voice room! Never fall back to arbitrary rooms/servers!
        if not target_channel or not target_guild:
            return web.json_response({
                "success": False,
                "error": "Вы должны находиться в голосовом канале на сервере, чтобы включить музыку!",
            }, status=400)

        # Rule: Bot cannot be moved across channels on the server
        guild_vc = getattr(target_guild, "voice_client", None)
        if guild_vc and guild_vc.is_connected() and guild_vc.channel:
            if guild_vc.channel.id != target_channel.id:
                return web.json_response({
                    "success": False,
                    "error": f"Бот уже находится в комнате «{guild_vc.channel.name}». Перемещение бота по серверу запрещено! Перейдите в комнату к боту, чтобы слушать музыку.",
                }, status=403)

        player = self.player_manager.get_or_create_player(target_guild)

        # Rule: If bot is in room with human listeners, only participants (or requester / admin) can add music
        if player.voice_client and player.voice_client.channel:
            bot_channel = player.voice_client.channel
            human_members = [m for m in bot_channel.members if not m.bot]
            if human_members and user_id and user_id not in [m.id for m in human_members]:
                member = target_guild.get_member(user_id) if target_guild else None
                if not (member and member.guild_permissions.administrator):
                    return web.json_response({
                        "success": False,
                        "error": f"Бот сейчас играет в комнате «{bot_channel.name}». Добавлять музыку могут только слушатели в этой комнате!",
                    }, status=403)

        try:
            # If client supplied explicit volume preference, apply it
            vol_arg = data.get("volume")
            if vol_arg is not None:
                try:
                    vol_float = float(vol_arg) / 100.0
                    player.set_volume(vol_float)
                    self.player_manager.guild_volumes[target_guild.id] = vol_float
                except Exception:
                    pass

            # Build Track object
            track_data["requester_id"] = user_id
            track_data["requester_name"] = member_name
            track = Track.from_dict(track_data)

            track_url = track_data.get("url", "")
            is_playlist = ("playlist" in track_url or "/sets/" in track_url)

            # Parallelize voice channel connection and stream URL resolution for instant start
            connect_task = asyncio.create_task(player.connect_to_channel(target_channel))
            if not is_playlist and not track.stream_url:
                stream_task = asyncio.create_task(self.music_service.get_stream_url(track))
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
            if ("playlist" in track_url or "/sets/" in track_url) and not track_data.get("stream_url"):
                try:
                    album_tracks = await self.music_service._resolve_direct_url(track_url)
                    if album_tracks and len(album_tracks) > 1:
                        first_t = album_tracks[0]
                        first_t.requester_id = user_id
                        first_t.requester_name = member_name
                        res = await player.enqueue(first_t, play_now=play_now)
                        for sub_t in album_tracks[1:]:
                            sub_t.requester_id = user_id
                            sub_t.requester_name = member_name
                            await player.enqueue(sub_t, play_now=False)
                        return web.json_response({
                            "success": True,
                            "action": "album_enqueued",
                            "tracks_count": len(album_tracks),
                            "channel_name": target_channel.name,
                            "guild_name": target_guild.name,
                            "track": first_t.to_dict(),
                            "player": player.get_state(),
                        })
                except Exception as ex:
                    logger.warning(f"Could not batch-resolve playlist {track_url}: {ex}")

            # Enqueue or play single track
            logger.info(f"handle_play: user {user_id} ({member_name}) requested '{track.title}' (play_now={play_now}) in {target_guild.name} / {target_channel.name}")
            res = await player.enqueue(track, play_now=play_now)

            # Record track in user history in PostgreSQL
            asyncio.create_task(db.add_user_history(str(user_id), track.to_dict()))

            return web.json_response({
                "success": True,
                "action": res.get("action"),
                "channel_name": target_channel.name,
                "guild_name": target_guild.name,
                "track": track.to_dict(),
                "player": player.get_state(),
            })

        except Exception as e:
            logger.error(f"Error handling play request: {e}", exc_info=True)
            return web.json_response({"success": False, "error": f"Ошибка воспроизведения: {str(e)}"}, status=500)

    async def handle_action(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

        action = data.get("action")
        user_id_str = data.get("user_id")
        guild_id_str = data.get("guild_id")
        channel_id_str = data.get("channel_id")

        user_id = safe_int(user_id_str)
        guild_id = safe_int(guild_id_str)
        channel_id = safe_int(channel_id_str)

        player = None
        if guild_id:
            player = self.player_manager.get_player_by_guild_id(guild_id)
        elif user_id:
            player = self.player_manager.find_active_player_for_user(user_id)

        if action == "join":
            if channel_id:
                ch = self.bot.get_channel(channel_id)
                if not ch:
                    try:
                        ch = await self.bot.fetch_channel(channel_id)
                    except Exception:
                        pass
                if ch and isinstance(ch, (discord.VoiceChannel, getattr(discord, "StageChannel", ()))):
                    # Check if already connected to another channel on this server
                    guild_vc = getattr(ch.guild, "voice_client", None)
                    if guild_vc and guild_vc.is_connected() and guild_vc.channel and guild_vc.channel.id != ch.id:
                        return web.json_response({
                            "success": False,
                            "error": f"Бот уже находится в комнате «{guild_vc.channel.name}». Перемещение бота по серверу запрещено!"
                        }, status=403)
                    p = self.player_manager.get_or_create_player(ch.guild)
                    await p.connect_to_channel(ch)
                    return web.json_response({"success": True, "action": "joined", "player": p.get_state()})

        if action == "leave":
            if player and player.voice_client and player.voice_client.channel:
                bot_channel = player.voice_client.channel
                human_members = [m for m in bot_channel.members if not m.bot]
                if human_members and user_id and user_id not in [m.id for m in human_members]:
                    member = player.guild.get_member(user_id)
                    if not (member and member.guild_permissions.administrator):
                        return web.json_response({
                            "success": False,
                            "error": "Отключить бота могут только участники голосовой комнаты, в которой он находится!"
                        }, status=403)
                await player.stop()
            elif guild_id:
                g = self.bot.get_guild(guild_id)
                if g and getattr(g, "voice_client", None):
                    await g.voice_client.disconnect(force=True)
            return web.json_response({"success": True, "action": "left"})

        if not player:
            if action == "volume":
                if guild_id:
                    g = self.bot.get_guild(guild_id)
                    if g:
                        player = self.player_manager.get_or_create_player(g)
                if not player and len(self.bot.guilds) == 1:
                    player = self.player_manager.get_or_create_player(self.bot.guilds[0])
                if not player and user_id:
                    for g in self.bot.guilds:
                        if g.get_member(user_id):
                            player = self.player_manager.get_or_create_player(g)
                            break
            if not player:
                return web.json_response({"success": False, "error": "Плеер не найден или не активен"}, status=404)

        # Enforce that only members in the bot's voice channel can control the player if listeners present
        if action != "volume" and player.voice_client and player.voice_client.channel:
            bot_channel = player.voice_client.channel
            human_members = [m for m in bot_channel.members if not m.bot]
            if human_members and user_id and user_id not in [m.id for m in human_members]:
                is_admin = False
                member = player.guild.get_member(user_id) if player.guild else None
                if member and member.guild_permissions.administrator:
                    is_admin = True
                is_requester = bool(player.current_track and player.current_track.requester_id == user_id)
                if not is_admin and not is_requester:
                    return web.json_response({
                        "success": False,
                        "error": f"Управлять плеером могут только участники голосовой комнаты «{bot_channel.name}»!",
                    }, status=403)

        try:
            res_data = {"success": True}
            if action == "play_pause":
                paused = await player.toggle_play_pause()
                res_data["is_paused"] = paused

            elif action == "pause":
                await player.pause()
                res_data["is_paused"] = True

            elif action == "resume":
                await player.resume()
                res_data["is_paused"] = False

            elif action in ("skip", "vote_skip"):
                forced = bool(data.get("forced", False))
                result = await player.skip(forced=forced, user_id=user_id)
                res_data.update(result)

            elif action == "stop":
                await player.stop()
                res_data["message"] = "Остановлено"

            elif action == "volume":
                vol_val = float(data.get("value", 100)) / 100.0
                new_vol = player.set_volume(vol_val)
                self.player_manager.guild_volumes[player.guild.id] = new_vol
                res_data["volume"] = int(new_vol * 100)

            elif action == "loop":
                mode = data.get("mode", "")
                new_mode = player.set_loop_mode(mode)
                res_data["loop_mode"] = new_mode

            elif action == "shuffle":
                count = player.shuffle_queue()
                res_data["queue_size"] = count

            elif action == "remove":
                idx = safe_int(data.get("index"), -1)
                removed = player.remove_from_queue(idx)
                res_data["success"] = bool(removed)
                res_data["removed"] = removed.to_dict() if removed else None

            elif action == "clear":
                player.clear_queue()
                res_data["message"] = "Очередь очищена"

            elif action == "seek":
                target_sec = safe_int(data.get("seconds"), 0)
                ok = await player.seek(target_sec)
                res_data["seeked"] = ok
                res_data["seconds"] = target_sec

            else:
                return web.json_response({"success": False, "error": f"Unknown action '{action}'"}, status=400)

            res_data["player"] = player.get_state()
            return web.json_response(res_data)

        except Exception as e:
            logger.error(f"Error executing action {action}: {e}", exc_info=True)
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def handle_discord_token(self, request: web.Request) -> web.Response:
        """Exchanges authorization code for an access token (for Discord Activity)."""
        try:
            data = await request.json()
            code = data.get("code")
            if not code or not self.client_id or not self.client_secret:
                return web.json_response({"error": "Missing code or Discord credentials"}, status=400)

            async with aiohttp.ClientSession() as session:
                token_url = "https://discord.com/api/oauth2/token"
                payload = {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                }
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                async with session.post(token_url, data=payload, headers=headers) as resp:
                    resp_data = await resp.json()
                    return web.json_response(resp_data, status=resp.status)
        except Exception as e:
            logger.error(f"Error exchanging discord token: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_auth_discord(self, request: web.Request) -> web.Response:
        """Redirects browser to Discord OAuth2 login."""
        public_url = os.getenv("PUBLIC_URL", "").rstrip("/")
        if not public_url:
            host_header = request.headers.get("Host", "localhost:3000")
            proto = request.headers.get("X-Forwarded-Proto", "http")
            public_url = f"{proto}://{host_header}"
        redirect_uri = f"{public_url}/api/auth/callback"
        
        redirect_target = request.query.get("redirect") or request.query.get("state") or ""
        state_param = "admin" if ("admin" in redirect_target) else "web"
        
        oauth_url = (
            f"https://discord.com/oauth2/authorize?client_id={self.client_id}"
            f"&response_type=code&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
            f"&scope=identify%20guilds"
            f"&state={state_param}"
        )
        return web.HTTPFound(oauth_url)

    async def handle_auth_callback(self, request: web.Request) -> web.Response:
        """Handles Discord OAuth2 callback, fetches user info and redirects back to app."""
        code = request.query.get("code")
        state_param = request.query.get("state", "web")
        if not code or not self.client_id or not self.client_secret:
            err_dest = "/admin?auth_error=missing_code" if state_param == "admin" else "/?auth_error=missing_code"
            return web.HTTPFound(err_dest)

        public_url = os.getenv("PUBLIC_URL", "").rstrip("/")
        if not public_url:
            host_header = request.headers.get("Host", "localhost:3000")
            proto = request.headers.get("X-Forwarded-Proto", "http")
            public_url = f"{proto}://{host_header}"
        redirect_uri = f"{public_url}/api/auth/callback"

        try:
            async with aiohttp.ClientSession() as session:
                token_url = "https://discord.com/api/oauth2/token"
                payload = {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                }
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                async with session.post(token_url, data=payload, headers=headers) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        logger.error(f"Discord OAuth2 token error: {err_text}")
                        err_dest = "/admin?auth_error=token_failed" if state_param == "admin" else "/?auth_error=token_failed"
                        return web.HTTPFound(err_dest)
                    token_data = await resp.json()

                access_token = token_data.get("access_token")
                if not access_token:
                    err_dest = "/admin?auth_error=no_access_token" if state_param == "admin" else "/?auth_error=no_access_token"
                    return web.HTTPFound(err_dest)

                # Fetch user info
                user_headers = {"Authorization": f"Bearer {access_token}"}
                async with session.get("https://discord.com/api/users/@me", headers=user_headers) as u_resp:
                    if u_resp.status != 200:
                        err_dest = "/admin?auth_error=user_fetch_failed" if state_param == "admin" else "/?auth_error=user_fetch_failed"
                        return web.HTTPFound(err_dest)
                    user_data = await u_resp.json()

                u_id = str(user_data.get("id", ""))
                u_name = user_data.get("global_name") or user_data.get("username", "Пользователь Discord")
                u_avatar = user_data.get("avatar")
                avatar_url = f"https://cdn.discordapp.com/avatars/{u_id}/{u_avatar}.png" if u_avatar else "/static/activity_icon.jpg"

                is_adm = admin_service.is_admin_id(u_id)
                admin_token = None
                if is_adm:
                    admin_token = admin_service.generate_admin_token(u_id)

                if state_param == "admin":
                    if is_adm:
                        target = "/admin?auth=success"
                    else:
                        target = "/admin?auth_error=not_authorized"
                else:
                    target = (
                        f"/?user_id={urllib.parse.quote(u_id)}"
                        f"&user_name={urllib.parse.quote(u_name)}"
                        f"&user_avatar={urllib.parse.quote(avatar_url)}"
                        f"&auth=success"
                        f"{'&is_admin=1' if is_adm else ''}"
                    )

                response = web.HTTPFound(target)
                if is_adm and admin_token:
                    response.set_cookie("musicium_admin_token", admin_token, max_age=7*86400, path="/")
                return response

        except Exception as e:
            logger.error(f"Error in handle_auth_callback: {e}", exc_info=True)
            err_dest = "/admin?auth_error=exception" if state_param == "admin" else "/?auth_error=exception"
            return web.HTTPFound(err_dest)

    async def handle_proxy_image(self, request: web.Request) -> web.Response:
        """Proxies external image requests (YouTube, SoundCloud, Discord) to bypass iframe CSP & referer restrictions."""
        url = request.query.get("url")
        if not url:
            return web.Response(status=400)

        # Basic security check
        if not (url.startswith("https://") or url.startswith("http://")):
            return web.Response(status=400)

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=6.0)) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        content_type = resp.headers.get("Content-Type", "image/jpeg")
                        return web.Response(
                            body=content,
                            content_type=content_type,
                            headers={
                                "Cache-Control": "public, max-age=604800",
                                "Access-Control-Allow-Origin": "*",
                            }
                        )
        except Exception as e:
            logger.debug(f"Failed to proxy image {url}: {e}")

        # Fallback to local default activity icon
        static_icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "activity_icon.jpg")
        if os.path.exists(static_icon):
            return web.FileResponse(static_icon)
        return web.Response(status=404)

    async def handle_recommendations(self, request: web.Request) -> web.Response:
        """Returns verified recommendation sections with valid YouTube & SoundCloud tracks."""
        curated = [
            {"id": "4NRXx6U8ABQ", "title": "Blinding Lights", "artist": "The Weeknd", "duration_str": "3:20", "thumbnail": "https://i.ytimg.com/vi/4NRXx6U8ABQ/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=4NRXx6U8ABQ"},
            {"id": "5NV6Rdv1a3I", "title": "Get Lucky", "artist": "Daft Punk ft. Pharrell Williams", "duration_str": "4:08", "thumbnail": "https://i.ytimg.com/vi/5NV6Rdv1a3I/hqdefault.jpg", "source": "soundcloud", "url": "https://api.soundcloud.com/tracks/soundcloud%3Atracks%3A88335161"},
            {"id": "34Na4j8AVgA", "title": "Starboy", "artist": "The Weeknd ft. Daft Punk", "duration_str": "3:50", "thumbnail": "https://i.ytimg.com/vi/34Na4j8AVgA/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=34Na4j8AVgA"},
            {"id": "TUVcZfQe-Kw", "title": "Levitating", "artist": "Dua Lipa", "duration_str": "3:23", "thumbnail": "https://i.ytimg.com/vi/TUVcZfQe-Kw/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=TUVcZfQe-Kw"},
            {"id": "7wtfhZwyrcc", "title": "Believer", "artist": "Imagine Dragons", "duration_str": "3:24", "thumbnail": "https://i.ytimg.com/vi/7wtfhZwyrcc/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=7wtfhZwyrcc"},
            {"id": "ALZHF5UqnU4", "title": "Alone", "artist": "Marshmello", "duration_str": "3:19", "thumbnail": "https://i.ytimg.com/vi/ALZHF5UqnU4/hqdefault.jpg", "source": "soundcloud", "url": "https://soundcloud.com/marshmellomusic/marshmello-alone"},
            {"id": "60ItHLz5WEA", "title": "Faded", "artist": "Alan Walker", "duration_str": "3:32", "thumbnail": "https://i.ytimg.com/vi/60ItHLz5WEA/hqdefault.jpg", "source": "soundcloud", "url": "https://soundcloud.com/alanwalker/faded"},
            {"id": "DyDfgMOUjCI", "title": "Bad Guy", "artist": "Billie Eilish", "duration_str": "3:14", "thumbnail": "https://i.ytimg.com/vi/DyDfgMOUjCI/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=DyDfgMOUjCI"},
            {"id": "gCYcYZW45Uk", "title": "Animals", "artist": "Martin Garrix", "duration_str": "2:56", "thumbnail": "https://i.ytimg.com/vi/gCYcYZW45Uk/hqdefault.jpg", "source": "soundcloud", "url": "https://soundcloud.com/martingarrix/martin-garrix-animals"},
            {"id": "kTJczUoc268", "title": "Stay", "artist": "The Kid LAROI & Justin Bieber", "duration_str": "2:21", "thumbnail": "https://i.ytimg.com/vi/kTJczUoc268/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=kTJczUoc268"},
            {"id": "dX3k_QDnzHE", "title": "Midnight City", "artist": "M83", "duration_str": "4:03", "thumbnail": "https://i.ytimg.com/vi/dX3k_QDnzHE/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=dX3k_QDnzHE"},
            {"id": "UtF6Jej8yb4", "title": "The Nights", "artist": "Avicii", "duration_str": "2:56", "thumbnail": "https://i.ytimg.com/vi/UtF6Jej8yb4/hqdefault.jpg", "source": "soundcloud", "url": "https://soundcloud.com/aviciiofficial/the-nights"}
        ]
        quick_picks = [
            {"title": "Bangarang", "artist": "Skrillex", "thumbnail": "https://i.ytimg.com/vi/YJVmu6yttiw/hqdefault.jpg", "source": "soundcloud", "url": "https://soundcloud.com/skrillex/bangarang-feat-sirah"},
            {"title": "First of the Year (Equinox)", "artist": "Skrillex", "thumbnail": "https://i.ytimg.com/vi/2cXDgFwE13g/hqdefault.jpg", "source": "soundcloud", "url": "https://soundcloud.com/skrillex/first-of-the-year-equinox"},
            {"title": "Strobe", "artist": "deadmau5", "thumbnail": "https://i.ytimg.com/vi/tKi9Z-f6qX4/hqdefault.jpg", "source": "soundcloud", "url": "https://soundcloud.com/deadmau5/strobe"},
            {"title": "One More Time", "artist": "Daft Punk", "thumbnail": "https://i.ytimg.com/vi/FGBhQbmMxH8/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=FGBhQbmMxH8"},
            {"title": "Wake Me Up", "artist": "Avicii", "thumbnail": "https://i.ytimg.com/vi/IcrbM1l_BoI/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=IcrbM1l_BoI"},
            {"title": "Counting Stars", "artist": "OneRepublic", "thumbnail": "https://i.ytimg.com/vi/hT_nvWreIhg/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=hT_nvWreIhg"}
        ]
        return web.json_response({
            "curated": curated,
            "quick_picks": quick_picks
        })

    async def handle_feed_discovery(self, request: web.Request) -> web.Response:
        """Returns live streams currently playing across Discord servers, and global recent plays."""
        live_streams = self.player_manager.get_all_active_streams()
        recent_history = await db.get_global_recent_history(limit=25)
        return web.json_response({
            "live_now": live_streams,
            "recent_history": recent_history
        })

    # --- User PostgreSQL Endpoints ---

    async def handle_get_liked(self, request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"tracks": []})
        tracks = await db.get_user_liked_tracks(user_id)
        return web.json_response({"tracks": tracks})

    async def handle_post_liked(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
        user_id = data.get("user_id")
        track = data.get("track")
        action = data.get("action", "add")
        if not user_id or not track:
            return web.json_response({"success": False, "error": "user_id and track required"}, status=400)
        track_url = track.get("url") or f"https://music.youtube.com/search?q={track.get('title', '')}"
        if action == "remove":
            ok = await db.remove_user_liked_track(str(user_id), track_url)
        else:
            ok = await db.add_user_liked_track(str(user_id), track)
        updated = await db.get_user_liked_tracks(str(user_id))
        return web.json_response({"success": ok, "tracks": updated})

    async def handle_get_playlists(self, request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"playlists": []})
        playlists = await db.get_user_playlists(user_id)
        return web.json_response({"playlists": playlists})

    async def handle_post_playlists(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
        user_id = data.get("user_id")
        title = data.get("title")
        cover = data.get("cover")
        author_name = data.get("author_name") or "Пользователь"
        author_avatar = data.get("author_avatar") or "/static/activity_icon.jpg"
        if not user_id or not title:
            return web.json_response({"success": False, "error": "user_id and title required"}, status=400)
        pl = await db.create_user_playlist(str(user_id), title, cover, author_name=author_name, author_avatar=author_avatar)
        return web.json_response({"success": bool(pl), "playlist": pl})

    async def handle_get_community_playlists(self, request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        sort_by = request.query.get("sort", "top")
        playlists = await db.get_community_playlists(current_user_id=user_id, sort_by=sort_by)
        return web.json_response({"playlists": playlists})

    async def handle_post_playlist_like(self, request: web.Request) -> web.Response:
        playlist_id = safe_int(request.match_info.get("id"))
        try:
            data = await request.json()
        except Exception:
            data = {}
        user_id = data.get("user_id") or request.query.get("user_id")
        if not playlist_id or not user_id:
            return web.json_response({"success": False, "error": "playlist id and user_id required"}, status=400)
        res = await db.toggle_playlist_like(str(user_id), playlist_id)
        return web.json_response({"success": True, **res})

    async def handle_delete_playlist(self, request: web.Request) -> web.Response:
        playlist_id = safe_int(request.match_info.get("id"))
        user_id = request.query.get("user_id")
        if not playlist_id or not user_id:
            return web.json_response({"success": False, "error": "playlist id and user_id required"}, status=400)
        try:
            ok = await db.delete_user_playlist(str(user_id), playlist_id)
            return web.json_response({"success": ok})
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def handle_add_playlist_track(self, request: web.Request) -> web.Response:
        playlist_id = safe_int(request.match_info.get("id"))
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
        track = data.get("track")
        if not playlist_id or not track:
            return web.json_response({"success": False, "error": "playlist id and track required"}, status=400)
        try:
            ok = await db.add_track_to_playlist(playlist_id, track)
            return web.json_response({"success": ok})
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def handle_remove_playlist_track(self, request: web.Request) -> web.Response:
        playlist_id = safe_int(request.match_info.get("id"))
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
        track_url = data.get("track_url")
        if not playlist_id or not track_url:
            return web.json_response({"success": False, "error": "playlist id and track_url required"}, status=400)
        try:
            ok = await db.remove_track_from_playlist(playlist_id, track_url)
            return web.json_response({"success": ok})
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def handle_get_history(self, request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"history": []})
        limit = safe_int(request.query.get("limit"), 50)
        hist = await db.get_user_history(user_id, limit=limit)
        return web.json_response({"history": hist})

    async def handle_post_history(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
        user_id = data.get("user_id")
        track = data.get("track")
        if not user_id or not track:
            return web.json_response({"success": False, "error": "user_id and track required"}, status=400)
        ok = await db.add_user_history(str(user_id), track)
        return web.json_response({"success": ok})

    async def handle_clear_history(self, request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            try:
                data = await request.json()
                user_id = data.get("user_id")
            except Exception:
                pass
        if not user_id:
            return web.json_response({"success": False, "error": "user_id required"}, status=400)
        ok = await db.clear_user_history(str(user_id))
        return web.json_response({"success": ok})

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        self.player_manager.ws_clients.add(ws)
        logger.info(f"WebSocket client connected. Total clients: {len(self.player_manager.ws_clients)}")

        try:
            # Send initial status
            await ws.send_json({
                "event": "connected",
                "data": {"status": "ok", "bot_online": self.bot.is_ready()}
            })

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                        action = payload.get("action")
                        if action == "ping":
                            await ws.send_json({"event": "pong"})
                        elif action in ("subscribe", "get_state"):
                            guild_id = safe_int(payload.get("guild_id"))
                            user_id = safe_int(payload.get("user_id"))

                            if guild_id:
                                self.player_manager.ws_subscriptions[ws] = guild_id

                            player = None
                            if guild_id:
                                player = self.player_manager.get_player_by_guild_id(guild_id)
                            elif user_id:
                                player = self.player_manager.find_active_player_for_user(user_id)
                                if player:
                                    self.player_manager.ws_subscriptions[ws] = player.guild.id

                            if player:
                                await ws.send_json({"event": "player_update", "data": player.get_state()})
                    except Exception as e:
                        logger.error(f"Error processing WS message: {e}")
                elif msg.type == WSMsgType.ERROR:
                    logger.warning(f"WebSocket connection closed with error {ws.exception()}")
        finally:
            self.player_manager.ws_clients.discard(ws)
            self.player_manager.ws_subscriptions.pop(ws, None)
            logger.info("WebSocket client disconnected.")

        return ws

    def _verify_admin(self, request: web.Request) -> Tuple[bool, Optional[str]]:
        # 1. Cookie
        cookie_token = request.cookies.get("musicium_admin_token")
        if cookie_token:
            valid, user_id = admin_service.verify_admin_token(cookie_token)
            if valid:
                return True, user_id

        # 2. Authorization Header
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr.split(" ", 1)[1].strip()
            valid, user_id = admin_service.verify_admin_token(token)
            if valid:
                return True, user_id

        # 3. Custom Header X-Admin-User-Id
        hdr_user_id = request.headers.get("X-Admin-User-Id", "")
        if hdr_user_id and admin_service.is_admin_id(hdr_user_id):
            return True, hdr_user_id

        # 4. Query parameters
        q_user_id = request.query.get("user_id", "")
        if q_user_id and admin_service.is_admin_id(q_user_id):
            return True, q_user_id

        q_token = request.query.get("admin_token", "")
        if q_token:
            valid, user_id = admin_service.verify_admin_token(q_token)
            if valid:
                return True, user_id

        return False, None

    async def handle_admin(self, request: web.Request) -> web.Response:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        admin_file = os.path.join(static_dir, "admin.html")
        if os.path.exists(admin_file):
            return web.FileResponse(admin_file, headers={"Cache-Control": "no-cache, must-revalidate"})
        return web.Response(text="<h1>Musicium Admin</h1><p>Admin panel frontend loading...</p>", content_type="text/html")

    async def handle_admin_auth_status(self, request: web.Request) -> web.Response:
        is_adm, user_id = self._verify_admin(request)
        if is_adm:
            return web.json_response({
                "authenticated": True,
                "user_id": user_id,
                "primary_admin": admin_service.PRIMARY_ADMIN_ID,
            })
        return web.json_response({
            "authenticated": False,
            "oauth_url": "/api/auth/discord?redirect=/admin",
        })

    async def handle_admin_auth_login(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            user_id = str(data.get("user_id", "")).strip()
            if not user_id:
                return web.json_response({"ok": False, "error": "Не указан user_id"}, status=400)
            if not admin_service.is_admin_id(user_id):
                return web.json_response({"ok": False, "error": "Доступ запрещен. ID не в списке администраторов."}, status=403)
            token = admin_service.generate_admin_token(user_id)
            resp = web.json_response({"ok": True, "token": token, "user_id": user_id})
            resp.set_cookie("musicium_admin_token", token, max_age=7*86400, path="/")
            return resp
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_admin_auth_logout(self, request: web.Request) -> web.Response:
        resp = web.json_response({"ok": True})
        resp.del_cookie("musicium_admin_token", path="/")
        return resp

    async def handle_admin_stats(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.json_response({"error": "Unauthorized"}, status=401)
        stats = await admin_service.get_system_stats(self.bot, self.player_manager, self.music_service)
        return web.json_response(stats)

    async def handle_admin_guilds(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.json_response({"error": "Unauthorized"}, status=401)
        guilds = admin_service.get_guilds_admin_data(self.bot, self.player_manager)
        return web.json_response({"guilds": guilds})

    async def handle_admin_switch_channel(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
            guild_id = safe_int(data.get("guild_id"))
            channel_id = safe_int(data.get("channel_id"))
            if not guild_id or not channel_id:
                return web.json_response({"ok": False, "error": "Не указан guild_id или channel_id"}, status=400)
            ok, msg = await admin_service.switch_bot_channel(self.bot, self.player_manager, guild_id, channel_id)
            return web.json_response({"ok": ok, "message": msg}, status=200 if ok else 400)
        except Exception as e:
            logger.error(f"Error in handle_admin_switch_channel: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_admin_disconnect(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
            guild_id = safe_int(data.get("guild_id"))
            if not guild_id:
                return web.json_response({"ok": False, "error": "Не указан guild_id"}, status=400)
            ok, msg = await admin_service.disconnect_bot_voice(self.bot, self.player_manager, guild_id)
            return web.json_response({"ok": ok, "message": msg}, status=200 if ok else 400)
        except Exception as e:
            logger.error(f"Error in handle_admin_disconnect: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_admin_player_action(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
            guild_id = safe_int(data.get("guild_id"))
            action = data.get("action", "")
            val = data.get("value")
            if not guild_id or not action:
                return web.json_response({"ok": False, "error": "Не указан guild_id или action"}, status=400)
            ok, msg = await admin_service.perform_player_action(self.player_manager, guild_id, action, val)
            return web.json_response({"ok": ok, "message": msg}, status=200 if ok else 400)
        except Exception as e:
            logger.error(f"Error in handle_admin_player_action: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_admin_leave_guild(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
            guild_id = safe_int(data.get("guild_id"))
            guild = self.bot.get_guild(guild_id) if guild_id else None
            if not guild:
                return web.json_response({"ok": False, "error": "Сервер не найден"}, status=404)
            name = guild.name
            await guild.leave()
            return web.json_response({"ok": True, "message": f"Бот успешно покинул сервер {name}"})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_admin_logs(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.json_response({"error": "Unauthorized"}, status=401)
        lvl = request.query.get("level")
        search = request.query.get("search")
        limit = safe_int(request.query.get("limit"), 400)
        logs = admin_service.admin_log_handler.get_logs(level=lvl, search=search, limit=limit)
        return web.json_response({"logs": logs, "total": len(admin_service.admin_log_handler.buffer)})

    async def handle_admin_logs_clear(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.json_response({"error": "Unauthorized"}, status=401)
        admin_service.admin_log_handler.clear()
        return web.json_response({"ok": True, "message": "Буфер логов очищен"})

    async def handle_admin_logs_download(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.Response(text="Unauthorized", status=401)
        content = admin_service.admin_log_handler.export_text()
        return web.Response(
            text=content,
            content_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=\"musicium_logs.txt\""}
        )

    async def handle_admin_broadcast(self, request: web.Request) -> web.Response:
        is_adm, _ = self._verify_admin(request)
        if not is_adm:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
            guild_id = safe_int(data.get("guild_id"))
            channel_id = safe_int(data.get("channel_id"))
            msg = data.get("message", "").strip()
            if not channel_id or not msg:
                return web.json_response({"ok": False, "error": "Не указан channel_id или message"}, status=400)
            ch = self.bot.get_channel(channel_id)
            if not ch:
                return web.json_response({"ok": False, "error": "Текстовый канал не найден"}, status=404)
            embed = discord.Embed(
                title="📢 Оповещение от администрации Musicium",
                description=msg,
                color=0x00F2FE
            )
            embed.set_footer(text="Musicium Admin Broadcast", icon_url=self.bot.user.display_avatar.url if (self.bot and self.bot.user) else None)
            await ch.send(embed=embed)
            return web.json_response({"ok": True, "message": "Сообщение отправлено"})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_admin_cookies(self, request: web.Request) -> web.Response:
        if request.method == "GET":
            cookie_path = self.music_service.youtube_cookie_path
            configured = bool(cookie_path and os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 0)
            cookie_count = 0
            if configured:
                try:
                    with open(cookie_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    cookie_count = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
                except Exception:
                    pass
            return web.json_response({
                "configured": configured,
                "cookie_path": cookie_path,
                "cookie_count": cookie_count,
            })
        elif request.method == "POST":
            raw = ""
            try:
                data = await request.json()
                raw = data.get("cookies") or data.get("content") or data.get("base64") or ""
            except Exception:
                pass
            if not raw:
                try:
                    raw = await request.text()
                except Exception:
                    raw = ""
            if not raw.strip():
                return web.json_response({"ok": False, "error": "No cookie content provided"}, status=400)

            ok, path_or_err, count = self.music_service.update_cookies(raw)
            if ok:
                return web.json_response({"ok": True, "path": path_or_err, "cookie_count": count})
            else:
                return web.json_response({"ok": False, "error": path_or_err}, status=400)

    async def start(self):
        try:
            await db.init_db()
        except Exception as e:
            logger.error(f"Failed to initialize database on startup: {e}")
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"Web server running on http://{self.host}:{self.port}")

    async def stop(self):
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        try:
            await db.close_db()
        except Exception:
            pass
