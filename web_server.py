import os
import json
import asyncio
import logging
from typing import Optional
from aiohttp import web, WSMsgType
import aiohttp

from music_service import MusicService, Track
from player_manager import PlayerManager

import db

logger = logging.getLogger("web_server")

@web.middleware
async def cache_control_middleware(request: web.Request, handler):
    response = await handler(request)
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

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
        self.app.router.add_get("/api/user-voice", self.handle_user_voice)
        self.app.router.add_get("/api/voice-users", self.handle_voice_users)
        self.app.router.add_get("/api/search", self.handle_search)
        self.app.router.add_get("/api/player", self.handle_get_player)
        self.app.router.add_post("/api/play", self.handle_play)
        self.app.router.add_post("/api/action", self.handle_action)
        self.app.router.add_post("/api/token", self.handle_discord_token)
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

    async def handle_voice_users(self, request: web.Request) -> web.Response:
        """Returns users currently connected to voice channels in bot guilds."""
        guild_id_str = request.query.get("guild_id")
        target_guild_id = None
        if guild_id_str:
            try:
                target_guild_id = int(guild_id_str)
            except ValueError:
                pass

        voice_members = []
        guilds_to_check = [self.bot.get_guild(target_guild_id)] if target_guild_id and self.bot.get_guild(target_guild_id) else self.bot.guilds

        for guild in guilds_to_check:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if not member.bot:
                        voice_members.append({
                            "id": str(member.id),
                            "name": member.name,
                            "display_name": member.display_name,
                            "avatar": member.display_avatar.url,
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

        if not user_id_str:
            return web.json_response({"in_voice": False, "error": "Missing user_id parameter"}, status=400)

        try:
            user_id = int(user_id_str)
        except ValueError:
            return web.json_response({"in_voice": False, "error": "Invalid user_id"}, status=400)

        guild_id = None
        if guild_id_str:
            try:
                guild_id = int(guild_id_str)
            except ValueError:
                pass

        # If channel_id was provided (e.g. from Discord Activity SDK), check it directly
        if channel_id_str:
            try:
                channel = self.bot.get_channel(int(channel_id_str))
                if channel and isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
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
                    })
            except Exception as e:
                logger.debug(f"Error checking channel_id {channel_id_str}: {e}")

        found = self.player_manager.find_user_voice(user_id, guild_id=guild_id)
        if not found:
            return web.json_response({
                "in_voice": False,
                "user_id": str(user_id),
                "message": "Пользователь не находится в голосовом канале",
            })

        guild, channel, member = found
        player = self.player_manager.get_player_by_guild_id(guild.id)
        return web.json_response({
            "in_voice": True,
            "user_id": str(user_id),
            "user_name": member.display_name,
            "avatar": member.display_avatar.url,
            "guild_id": str(guild.id),
            "guild_name": guild.name,
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "channel_members": self._serialize_channel_members(channel),
            "player_active": player.is_playing if player else False,
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

        player = None
        if guild_id_str:
            try:
                player = self.player_manager.get_player_by_guild_id(int(guild_id_str))
            except ValueError:
                pass
        elif user_id_str:
            try:
                player = self.player_manager.find_active_player_for_user(int(user_id_str))
            except ValueError:
                pass

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

        try:
            user_id = int(user_id_str)
        except ValueError:
            return web.json_response({"success": False, "error": "Invalid user_id"}, status=400)

        guild_id = None
        if guild_id_str:
            try:
                guild_id = int(guild_id_str)
            except ValueError:
                pass

        # 1. Find user's voice channel, scoped to requested guild_id if provided
        found = self.player_manager.find_user_voice(user_id, guild_id=guild_id)
        target_channel = None
        target_guild = None
        member_name = "Пользователь Discord"

        if found:
            target_guild, target_channel, member = found
            member_name = member.display_name
        elif channel_id_str:
            # 2. Fallback: if user launched via Discord Activity and channel_id is known
            try:
                ch = self.bot.get_channel(int(channel_id_str))
                if ch and isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                    target_channel = ch
                    target_guild = ch.guild
                    mem = ch.guild.get_member(user_id)
                    if mem:
                        member_name = mem.display_name
            except Exception as e:
                logger.warning(f"Failed to resolve channel_id {channel_id_str}: {e}")

        if not target_channel or not target_guild:
            return web.json_response({
                "success": False,
                "error": "Вы не находитесь в голосовом канале! Зайдите в любой голосовой канал на сервере, чтобы бот мог включить трек.",
            }, status=400)

        player = self.player_manager.get_or_create_player(target_guild)

        try:
            # Connect or move to channel
            await player.connect_to_channel(target_channel)

            # Build Track object
            track_data["requester_id"] = user_id
            track_data["requester_name"] = member_name
            track = Track.from_dict(track_data)

            track_url = track_data.get("url", "")
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

        user_id = int(user_id_str) if user_id_str else None

        player = None
        if guild_id_str:
            try:
                player = self.player_manager.get_player_by_guild_id(int(guild_id_str))
            except ValueError:
                pass
        elif user_id:
            player = self.player_manager.find_active_player_for_user(user_id)

        if not player:
            return web.json_response({"success": False, "error": "Плеер не найден или не активен"}, status=404)

        # Enforce that only members in the bot's voice channel can control the player
        if player.voice_client and player.voice_client.channel:
            bot_channel = player.voice_client.channel
            member_ids = {m.id for m in bot_channel.members}
            if user_id and user_id not in member_ids:
                return web.json_response({
                    "success": False,
                    "error": "Управлять плеером могут только участники голосового канала!",
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
                res_data["volume"] = int(new_vol * 100)

            elif action == "loop":
                mode = data.get("mode", "")
                new_mode = player.set_loop_mode(mode)
                res_data["loop_mode"] = new_mode

            elif action == "shuffle":
                count = player.shuffle_queue()
                res_data["queue_size"] = count

            elif action == "remove":
                idx = int(data.get("index", -1))
                removed = player.remove_from_queue(idx)
                res_data["success"] = bool(removed)
                res_data["removed"] = removed.to_dict() if removed else None

            elif action == "clear":
                player.clear_queue()
                res_data["message"] = "Очередь очищена"

            elif action == "seek":
                target_sec = int(data.get("seconds", 0))
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
        """Returns verified recommendation sections with valid YouTube thumbnails and URLs."""
        curated = [
            {"id": "pgPpgquGemg", "title": "Passengers & Pilots", "artist": "Big Baby Tape", "duration_str": "2:15", "thumbnail": "https://i.ytimg.com/vi/pgPpgquGemg/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=pgPpgquGemg"},
            {"id": "P8EYqmmeae8", "title": "Ova", "artist": "Lyov и Xudo", "duration_str": "3:04", "thumbnail": "https://i.ytimg.com/vi/P8EYqmmeae8/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=P8EYqmmeae8"},
            {"id": "TQSHNV3mCfU", "title": "Slimed Out", "artist": "Mamba Cinco & Zahsosaa", "duration_str": "2:40", "thumbnail": "https://i.ytimg.com/vi/TQSHNV3mCfU/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=TQSHNV3mCfU"},
            {"id": "tP3h0iP8OY8", "title": "Malo 2.0", "artist": "Егор Крид, OG Buda, Toxi$", "duration_str": "2:38", "thumbnail": "https://i.ytimg.com/vi/tP3h0iP8OY8/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=tP3h0iP8OY8"},
            {"id": "8CdcCD5V-d8", "title": "Venom (Music From The Motion Picture)", "artist": "Eminem", "duration_str": "4:29", "thumbnail": "https://i.ytimg.com/vi/8CdcCD5V-d8/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=8CdcCD5V-d8"},
            {"id": "EsmFmcpdybU", "title": "Spasi L", "artist": "Dav", "duration_str": "2:52", "thumbnail": "https://i.ytimg.com/vi/EsmFmcpdybU/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=EsmFmcpdybU"},
            {"id": "VHoT4N43jK8", "title": "Alors on danse (Radio Edit)", "artist": "Stromae", "duration_str": "3:28", "thumbnail": "https://i.ytimg.com/vi/VHoT4N43jK8/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=VHoT4N43jK8"},
            {"id": "I4Ra4z2Arqg", "title": "Overseas", "artist": "D-Block Europe & Central Cee", "duration_str": "3:42", "thumbnail": "https://i.ytimg.com/vi/I4Ra4z2Arqg/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=I4Ra4z2Arqg"},
            {"id": "UYSciD1u7sE", "title": "Държавен Кючек", "artist": "Leo Band", "duration_str": "3:15", "thumbnail": "https://i.ytimg.com/vi/UYSciD1u7sE/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=UYSciD1u7sE"},
            {"id": "xqkGMZCYbrY", "title": "Party Funk", "artist": "Young Madz & MC Zudo Bo", "duration_str": "2:12", "thumbnail": "https://i.ytimg.com/vi/xqkGMZCYbrY/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=xqkGMZCYbrY"},
            {"id": "ehcVomMexkY", "title": "Pour It Up", "artist": "Rihanna", "duration_str": "2:41", "thumbnail": "https://i.ytimg.com/vi/ehcVomMexkY/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=ehcVomMexkY"},
            {"id": "K0CEBXmehSg", "title": "Layli", "artist": "Jamshid Ximmatov", "duration_str": "3:30", "thumbnail": "https://i.ytimg.com/vi/K0CEBXmehSg/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=K0CEBXmehSg"}
        ]
        quick_picks = [
            {"title": "ДИНАСТИЯ", "artist": "VILLIAN & madk1d", "thumbnail": "https://i.ytimg.com/vi/J7NFL-eOxiQ/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=J7NFL-eOxiQ"},
            {"title": "Caramelldansen (Speedy Mixes)", "artist": "Caramella Girls", "thumbnail": "https://i.ytimg.com/vi/PDJLvF1dUek/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=PDJLvF1dUek"},
            {"title": "все хотят меня", "artist": "gotlib", "thumbnail": "https://i.ytimg.com/vi/DXoOqDf8o3k/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=DXoOqDf8o3k"},
            {"title": "Там ревели горы", "artist": "Miyagi & Эндшпиль", "thumbnail": "https://i.ytimg.com/vi/MzI_CIYSsfQ/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=MzI_CIYSsfQ"},
            {"title": "Sweater Weather", "artist": "The Neighbourhood", "thumbnail": "https://i.ytimg.com/vi/GCdwKhTtNNw/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=GCdwKhTtNNw"},
            {"title": "Где прошла ты", "artist": "Кравц & Гио Пика", "thumbnail": "https://i.ytimg.com/vi/I6dXiJ8r5jM/hqdefault.jpg", "source": "youtube", "url": "https://music.youtube.com/watch?v=I6dXiJ8r5jM"}
        ]
        albums = [
            {"title": "Viva La Vida", "artist": "SODA LUV", "subtitle": "Альбом • SODA LUV", "thumbnail": "https://i.ytimg.com/vi/9_wwDPM1OFE/hqdefault.jpg", "source": "yt_albums", "url": "https://music.youtube.com/watch?v=9_wwDPM1OFE"},
            {"title": "АРТЁМ", "artist": "SLAVA MARLOW", "subtitle": "EP • SLAVA MARLOW", "thumbnail": "https://i.ytimg.com/vi/ABow8gM1UI4/hqdefault.jpg", "source": "yt_albums", "url": "https://music.youtube.com/watch?v=ABow8gM1UI4"},
            {"title": "SODA LUV", "artist": "SODA LUV", "subtitle": "Альбом • SODA LUV", "thumbnail": "https://i.ytimg.com/vi/a39YBPPpmI4/hqdefault.jpg", "source": "yt_albums", "url": "https://music.youtube.com/watch?v=a39YBPPpmI4"},
            {"title": "BOYS DON'T CRY", "artist": "GONE.Fludd", "subtitle": "Альбом • GONE.Fludd", "thumbnail": "https://i.ytimg.com/vi/pomoFf4PUXE/hqdefault.jpg", "source": "yt_albums", "url": "https://music.youtube.com/watch?v=pomoFf4PUXE"},
            {"title": "DUMMY BOY", "artist": "6ix9ine", "subtitle": "Альбом • 6ix9ine", "thumbnail": "https://i.ytimg.com/vi/6cRTU8lpSMA/hqdefault.jpg", "source": "yt_albums", "url": "https://music.youtube.com/watch?v=6cRTU8lpSMA"},
            {"title": "Whenever You Need Somebody", "artist": "Rick Astley", "subtitle": "Альбом • Rick Astley", "thumbnail": "https://i.ytimg.com/vi/BeyEGebJ1l4/hqdefault.jpg", "source": "yt_albums", "url": "https://music.youtube.com/watch?v=BeyEGebJ1l4"}
        ]
        return web.json_response({
            "curated": curated,
            "quick_picks": quick_picks,
            "albums": albums
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
        playlist_id = request.match_info.get("id")
        try:
            data = await request.json()
        except Exception:
            data = {}
        user_id = data.get("user_id") or request.query.get("user_id")
        if not playlist_id or not user_id:
            return web.json_response({"success": False, "error": "playlist id and user_id required"}, status=400)
        res = await db.toggle_playlist_like(str(user_id), int(playlist_id))
        return web.json_response({"success": True, **res})

    async def handle_delete_playlist(self, request: web.Request) -> web.Response:
        playlist_id = request.match_info.get("id")
        user_id = request.query.get("user_id")
        if not playlist_id or not user_id:
            return web.json_response({"success": False, "error": "playlist id and user_id required"}, status=400)
        try:
            ok = await db.delete_user_playlist(str(user_id), int(playlist_id))
            return web.json_response({"success": ok})
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def handle_add_playlist_track(self, request: web.Request) -> web.Response:
        playlist_id = request.match_info.get("id")
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
        track = data.get("track")
        if not playlist_id or not track:
            return web.json_response({"success": False, "error": "playlist id and track required"}, status=400)
        try:
            ok = await db.add_track_to_playlist(int(playlist_id), track)
            return web.json_response({"success": ok})
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def handle_remove_playlist_track(self, request: web.Request) -> web.Response:
        playlist_id = request.match_info.get("id")
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)
        track_url = data.get("track_url")
        if not playlist_id or not track_url:
            return web.json_response({"success": False, "error": "playlist id and track_url required"}, status=400)
        try:
            ok = await db.remove_track_from_playlist(int(playlist_id), track_url)
            return web.json_response({"success": ok})
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def handle_get_history(self, request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"history": []})
        limit = int(request.query.get("limit", 50))
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
                            guild_id_raw = payload.get("guild_id")
                            user_id_raw = payload.get("user_id")
                            guild_id = int(guild_id_raw) if guild_id_raw else None
                            user_id = int(user_id_raw) if user_id_raw else None

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
