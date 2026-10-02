import os
import json
import asyncio
import logging
from typing import Optional
from aiohttp import web, WSMsgType
import aiohttp

from music_service import MusicService, Track
from player_manager import PlayerManager

logger = logging.getLogger("web_server")

class WebServer:
    def __init__(self, bot, player_manager: PlayerManager, music_service: MusicService):
        self.bot = bot
        self.player_manager = player_manager
        self.music_service = music_service
        self.app = web.Application()
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

        # WebSocket
        self.app.router.add_get("/ws", self.handle_websocket)

        # Static files and SPA index
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        os.makedirs(static_dir, exist_ok=True)
        self.app.router.add_static("/static/", path=static_dir, name="static")
        self.app.router.add_get("/", self.handle_index)

    async def handle_index(self, request: web.Request) -> web.Response:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return web.FileResponse(index_file)
        return web.Response(text="<h1>Discord Music Mini App</h1><p>Frontend loading...</p>", content_type="text/html")

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
            "yandex_configured": bool(self.music_service.yandex_client is not None),
        })

    async def handle_voice_users(self, request: web.Request) -> web.Response:
        """Returns users currently connected to voice channels in bot guilds."""
        voice_members = []
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if not member.bot:
                        voice_members.append({
                            "id": str(member.id),
                            "name": member.name,
                            "display_name": member.display_name,
                            "avatar": member.display_avatar.url,
                            "guild_id": str(guild.id),
                            "guild_name": guild.name,
                            "channel_id": str(vc.id),
                            "channel_name": vc.name,
                        })

        return web.json_response({"voice_users": voice_members})

    async def handle_user_voice(self, request: web.Request) -> web.Response:
        user_id_str = request.query.get("user_id")
        if not user_id_str:
            return web.json_response({"in_voice": False, "error": "Missing user_id parameter"}, status=400)

        try:
            user_id = int(user_id_str)
        except ValueError:
            return web.json_response({"in_voice": False, "error": "Invalid user_id"}, status=400)

        found = self.player_manager.find_user_voice(user_id)
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
            "player_active": player.is_playing if player else False,
        })

    async def handle_search(self, request: web.Request) -> web.Response:
        q = request.query.get("q", "").strip()
        source = request.query.get("source", "all").strip().lower()

        if not q:
            return web.json_response({"tracks": []})

        tracks = await self.music_service.search(query=q, source=source, limit=12)
        notice = None
        if source == "yandex" and not tracks:
            notice = "Яндекс.Музыка недоступна на зарубежном хостинге (территориальные ограничения API 451). Используйте YouTube Music!"

        return web.json_response({
            "query": q,
            "source": source,
            "tracks": [t.to_dict() for t in tracks],
            "notice": notice,
            "yandex_configured": bool(self.music_service.yandex_client is not None),
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
        track_data = data.get("track")
        play_now = bool(data.get("play_now", False))

        if not user_id_str or not track_data:
            return web.json_response({"success": False, "error": "user_id and track are required"}, status=400)

        try:
            user_id = int(user_id_str)
        except ValueError:
            return web.json_response({"success": False, "error": "Invalid user_id"}, status=400)

        # Find user's voice channel
        found = self.player_manager.find_user_voice(user_id)
        if not found:
            return web.json_response({
                "success": False,
                "error": "Вы не находитесь в голосовом канале! Зайдите в любой голосовой канал на сервере, чтобы бот мог включить трек.",
            }, status=400)

        guild, channel, member = found
        player = self.player_manager.get_or_create_player(guild)

        try:
            # Connect or move to channel
            await player.connect_to_channel(channel)

            # Build Track object
            track_data["requester_id"] = user_id
            track_data["requester_name"] = member.display_name
            track = Track.from_dict(track_data)

            # Enqueue or play
            res = await player.enqueue(track, play_now=play_now)

            return web.json_response({
                "success": True,
                "action": res.get("action"),
                "channel_name": channel.name,
                "guild_name": guild.name,
                "track": track.to_dict(),
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

        try:
            if action == "play_pause":
                paused = await player.toggle_play_pause()
                return web.json_response({"success": True, "is_paused": paused})

            elif action == "pause":
                await player.pause()
                return web.json_response({"success": True, "is_paused": True})

            elif action == "resume":
                await player.resume()
                return web.json_response({"success": True, "is_paused": False})

            elif action in ("skip", "vote_skip"):
                forced = bool(data.get("forced", False))
                result = await player.skip(forced=forced, user_id=user_id)
                return web.json_response({"success": True, **result})

            elif action == "stop":
                await player.stop()
                return web.json_response({"success": True, "message": "Остановлено"})

            elif action == "volume":
                vol_val = float(data.get("value", 100)) / 100.0
                new_vol = player.set_volume(vol_val)
                return web.json_response({"success": True, "volume": int(new_vol * 100)})

            elif action == "loop":
                mode = data.get("mode", "")
                new_mode = player.set_loop_mode(mode)
                return web.json_response({"success": True, "loop_mode": new_mode})

            elif action == "shuffle":
                count = player.shuffle_queue()
                return web.json_response({"success": True, "queue_size": count})

            elif action == "remove":
                idx = int(data.get("index", -1))
                removed = player.remove_from_queue(idx)
                return web.json_response({"success": bool(removed), "removed": removed.to_dict() if removed else None})

            elif action == "clear":
                player.clear_queue()
                return web.json_response({"success": True, "message": "Очередь очищена"})

            else:
                return web.json_response({"success": False, "error": f"Unknown action '{action}'"}, status=400)

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
                        elif action == "get_state":
                            guild_id = payload.get("guild_id")
                            user_id = payload.get("user_id")
                            player = None
                            if guild_id:
                                player = self.player_manager.get_player_by_guild_id(int(guild_id))
                            elif user_id:
                                player = self.player_manager.find_active_player_for_user(int(user_id))

                            if player:
                                await ws.send_json({"event": "player_update", "data": player.get_state()})
                    except Exception as e:
                        logger.error(f"Error processing WS message: {e}")
                elif msg.type == WSMsgType.ERROR:
                    logger.warning(f"WebSocket connection closed with error {ws.exception()}")
        finally:
            self.player_manager.ws_clients.discard(ws)
            logger.info("WebSocket client disconnected.")

        return ws

    async def start(self):
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
