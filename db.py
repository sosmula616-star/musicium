import os
import asyncio
import logging
from typing import List, Optional, Dict, Any
import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("db")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://bothost_db_4ab6bf62ff61:VVp8rQpEA7e8VEEIUUi0amEDwlH3uu4KZVAIR-tgcns@node1.pghost.ru:16183/bothost_db_4ab6bf62ff61"
)

_pool: Optional[asyncpg.Pool] = None

async def init_db() -> Optional[asyncpg.Pool]:
    global _pool
    if _pool is not None:
        return _pool
    try:
        logger.info("Connecting to PostgreSQL database...")
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=15.0
        )
        # Ensure tables exist
        async with _pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_liked_tracks (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    track_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    artist TEXT,
                    thumbnail TEXT,
                    duration_str VARCHAR(32),
                    source VARCHAR(32) DEFAULT 'youtube',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, track_url)
                );
                CREATE INDEX IF NOT EXISTS idx_liked_user ON user_liked_tracks(user_id);

                CREATE TABLE IF NOT EXISTS user_playlists (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    title TEXT NOT NULL,
                    cover TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_playlists_user ON user_playlists(user_id);

                CREATE TABLE IF NOT EXISTS user_playlist_tracks (
                    id SERIAL PRIMARY KEY,
                    playlist_id INTEGER REFERENCES user_playlists(id) ON DELETE CASCADE,
                    track_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    artist TEXT,
                    thumbnail TEXT,
                    duration_str VARCHAR(32),
                    source VARCHAR(32) DEFAULT 'youtube',
                    position INTEGER DEFAULT 0,
                    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_playlist_tracks_pl ON user_playlist_tracks(playlist_id);

                CREATE TABLE IF NOT EXISTS user_history (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    track_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    artist TEXT,
                    thumbnail TEXT,
                    duration_str VARCHAR(32),
                    source VARCHAR(32) DEFAULT 'youtube',
                    played_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_history_user ON user_history(user_id);

                CREATE TABLE IF NOT EXISTS bot_restricted_users (
                    user_id VARCHAR(64) PRIMARY KEY,
                    user_name TEXT NOT NULL,
                    user_avatar TEXT,
                    guild_id VARCHAR(64),
                    guild_name TEXT,
                    reason TEXT,
                    requests_count INTEGER DEFAULT 1,
                    restricted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                );
                CREATE INDEX IF NOT EXISTS idx_restricted_active ON bot_restricted_users(is_active);
            """)
        logger.info("PostgreSQL database initialized successfully.")
        return _pool
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        return None

async def close_db():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed.")

# --- Liked Tracks ---

async def get_user_liked_tracks(user_id: str) -> List[Dict[str, Any]]:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT track_url, title, artist, thumbnail, duration_str, source, created_at
                FROM user_liked_tracks
                WHERE user_id = $1
                ORDER BY created_at DESC
                """,
                str(user_id)
            )
            return [
                {
                    "url": r["track_url"],
                    "title": r["title"],
                    "artist": r["artist"] or "Неизвестный исполнитель",
                    "thumbnail": r["thumbnail"] or "/static/activity_icon.jpg",
                    "duration_str": r["duration_str"] or "00:00",
                    "source": r["source"] or "youtube",
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"Error fetching liked tracks for user {user_id}: {e}")
        return []

async def add_user_liked_track(user_id: str, track: Dict[str, Any]) -> bool:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id or not track:
        return False
    try:
        url = track.get("url") or f"https://music.youtube.com/search?q={track.get('title', '')}"
        title = track.get("title", "Без названия")
        artist = track.get("artist", "")
        thumbnail = track.get("thumbnail", "/static/activity_icon.jpg")
        duration_str = track.get("duration_str", "00:00")
        source = track.get("source", "youtube")

        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_liked_tracks (user_id, track_url, title, artist, thumbnail, duration_str, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (user_id, track_url) DO UPDATE
                SET title = EXCLUDED.title,
                    artist = EXCLUDED.artist,
                    thumbnail = EXCLUDED.thumbnail,
                    duration_str = EXCLUDED.duration_str,
                    source = EXCLUDED.source,
                    created_at = CURRENT_TIMESTAMP
                """,
                str(user_id), url, title, artist, thumbnail, duration_str, source
            )
            return True
    except Exception as e:
        logger.error(f"Error adding liked track for user {user_id}: {e}")
        return False

async def remove_user_liked_track(user_id: str, track_url: str) -> bool:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id or not track_url:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM user_liked_tracks
                WHERE user_id = $1 AND track_url = $2
                """,
                str(user_id), track_url
            )
            return True
    except Exception as e:
        logger.error(f"Error removing liked track for user {user_id}: {e}")
        return False

# --- User Playlists ---

async def get_user_playlists(user_id: str) -> List[Dict[str, Any]]:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id:
        return []
    try:
        async with _pool.acquire() as conn:
            playlists = await conn.fetch(
                """
                SELECT p.id, p.title, p.cover, p.author_name, p.author_avatar, p.likes_count, p.created_at,
                       COUNT(t.id) as track_count,
                       (SELECT t2.thumbnail FROM user_playlist_tracks t2 WHERE t2.playlist_id = p.id ORDER BY t2.position ASC, t2.id ASC LIMIT 1) as first_track_thumb
                FROM user_playlists p
                LEFT JOIN user_playlist_tracks t ON t.playlist_id = p.id
                WHERE p.user_id = $1
                GROUP BY p.id
                ORDER BY p.created_at DESC
                """,
                str(user_id)
            )

            result = []
            for p in playlists:
                pl_id = p["id"]
                tracks_rows = await conn.fetch(
                    """
                    SELECT id, track_url, title, artist, thumbnail, duration_str, source, position, added_at
                    FROM user_playlist_tracks
                    WHERE playlist_id = $1
                    ORDER BY position ASC, id ASC
                    """,
                    pl_id
                )
                tracks = [
                    {
                        "id": tr["id"],
                        "url": tr["track_url"],
                        "title": tr["title"],
                        "artist": tr["artist"] or "Неизвестный исполнитель",
                        "thumbnail": tr["thumbnail"] or "/static/activity_icon.jpg",
                        "duration_str": tr["duration_str"] or "00:00",
                        "source": tr["source"] or "youtube",
                    }
                    for tr in tracks_rows
                ]
                cover = p["cover"] or p["first_track_thumb"] or "/static/activity_icon.jpg"
                result.append({
                    "id": p["id"],
                    "title": p["title"],
                    "cover": cover,
                    "author_name": p["author_name"] or "Пользователь",
                    "author_avatar": p["author_avatar"] or "/static/activity_icon.jpg",
                    "likes_count": p["likes_count"] or 0,
                    "created_at": p["created_at"].isoformat() if p["created_at"] else None,
                    "tracks": tracks
                })
            return result
    except Exception as e:
        logger.error(f"Error fetching playlists for user {user_id}: {e}")
        return []

async def create_user_playlist(user_id: str, title: str, cover: Optional[str] = None, author_name: str = "Пользователь", author_avatar: str = "/static/activity_icon.jpg") -> Optional[Dict[str, Any]]:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id or not title:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO user_playlists (user_id, title, cover, author_name, author_avatar)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, title, cover, author_name, author_avatar, likes_count, created_at
                """,
                str(user_id), title.strip(), cover, author_name, author_avatar
            )
            if row:
                return {
                    "id": row["id"],
                    "title": row["title"],
                    "cover": row["cover"] or "/static/activity_icon.jpg",
                    "author_name": row["author_name"] or "Пользователь",
                    "author_avatar": row["author_avatar"] or "/static/activity_icon.jpg",
                    "likes_count": row["likes_count"] or 0,
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "tracks": []
                }
            return None
    except Exception as e:
        logger.error(f"Error creating playlist for user {user_id}: {e}")
        return None

async def get_community_playlists(current_user_id: Optional[str] = None, sort_by: str = "top", limit: int = 20) -> List[Dict[str, Any]]:
    global _pool
    if not _pool:
        await init_db()
    if not _pool:
        return []
    try:
        order_clause = "ORDER BY p.likes_count DESC, track_count DESC, p.created_at DESC" if sort_by == "top" else "ORDER BY p.created_at DESC"
        async with _pool.acquire() as conn:
            playlists = await conn.fetch(
                f"""
                SELECT p.id, p.user_id, p.title, p.cover, p.author_name, p.author_avatar, p.likes_count, p.created_at,
                       COUNT(t.id) as track_count,
                       (SELECT t2.thumbnail FROM user_playlist_tracks t2 WHERE t2.playlist_id = p.id ORDER BY t2.position ASC, t2.id ASC LIMIT 1) as first_track_thumb,
                       CASE WHEN $1::text IS NOT NULL AND EXISTS(SELECT 1 FROM playlist_likes plk WHERE plk.playlist_id = p.id AND plk.user_id = $1::text) THEN TRUE ELSE FALSE END as is_liked
                FROM user_playlists p
                LEFT JOIN user_playlist_tracks t ON t.playlist_id = p.id
                WHERE p.is_public = TRUE
                GROUP BY p.id
                {order_clause}
                LIMIT $2
                """,
                str(current_user_id) if current_user_id else None,
                limit
            )

            result = []
            for p in playlists:
                pl_id = p["id"]
                tracks_rows = await conn.fetch(
                    """
                    SELECT id, track_url, title, artist, thumbnail, duration_str, source, position, added_at
                    FROM user_playlist_tracks
                    WHERE playlist_id = $1
                    ORDER BY position ASC, id ASC
                    """,
                    pl_id
                )
                tracks = [
                    {
                        "id": tr["id"],
                        "url": tr["track_url"],
                        "title": tr["title"],
                        "artist": tr["artist"] or "Неизвестный исполнитель",
                        "thumbnail": tr["thumbnail"] or "/static/activity_icon.jpg",
                        "duration_str": tr["duration_str"] or "00:00",
                        "source": tr["source"] or "youtube",
                    }
                    for tr in tracks_rows
                ]
                cover = p["cover"] or p["first_track_thumb"] or "/static/activity_icon.jpg"
                result.append({
                    "id": p["id"],
                    "user_id": p["user_id"],
                    "title": p["title"],
                    "author_name": p["author_name"] or "Пользователь",
                    "author_avatar": p["author_avatar"] or "/static/activity_icon.jpg",
                    "likes_count": p["likes_count"] or 0,
                    "is_liked": bool(p["is_liked"]),
                    "cover": cover,
                    "created_at": p["created_at"].isoformat() if p["created_at"] else None,
                    "tracks": tracks
                })
            return result
    except Exception as e:
        logger.error(f"Error fetching community playlists: {e}")
        return []

async def toggle_playlist_like(user_id: str, playlist_id: int) -> Dict[str, Any]:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id or not playlist_id:
        return {"liked": False, "likes_count": 0}
    try:
        async with _pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM playlist_likes WHERE playlist_id = $1 AND user_id = $2",
                int(playlist_id), str(user_id)
            )
            if existing:
                await conn.execute("DELETE FROM playlist_likes WHERE id = $1", existing)
                await conn.execute("UPDATE user_playlists SET likes_count = GREATEST(0, likes_count - 1) WHERE id = $1", int(playlist_id))
                liked = False
            else:
                await conn.execute(
                    "INSERT INTO playlist_likes (playlist_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    int(playlist_id), str(user_id)
                )
                await conn.execute("UPDATE user_playlists SET likes_count = likes_count + 1 WHERE id = $1", int(playlist_id))
                liked = True

            current_count = await conn.fetchval("SELECT likes_count FROM user_playlists WHERE id = $1", int(playlist_id))
            return {"liked": liked, "likes_count": current_count or 0}
    except Exception as e:
        logger.error(f"Error toggling like for playlist {playlist_id} by user {user_id}: {e}")
        return {"liked": False, "likes_count": 0}

async def delete_user_playlist(user_id: str, playlist_id: int) -> bool:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM user_playlists
                WHERE id = $1 AND user_id = $2
                """,
                int(playlist_id), str(user_id)
            )
            return True
    except Exception as e:
        logger.error(f"Error deleting playlist {playlist_id} for user {user_id}: {e}")
        return False

async def add_track_to_playlist(playlist_id: int, track: Dict[str, Any]) -> bool:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not playlist_id or not track:
        return False
    try:
        url = track.get("url") or f"https://music.youtube.com/search?q={track.get('title', '')}"
        title = track.get("title", "Без названия")
        artist = track.get("artist", "")
        thumbnail = track.get("thumbnail", "/static/activity_icon.jpg")
        duration_str = track.get("duration_str", "00:00")
        source = track.get("source", "youtube")

        async with _pool.acquire() as conn:
            # Check if track already in playlist
            existing = await conn.fetchval(
                "SELECT id FROM user_playlist_tracks WHERE playlist_id = $1 AND track_url = $2",
                int(playlist_id), url
            )
            if existing:
                return False

            max_pos = await conn.fetchval(
                "SELECT COALESCE(MAX(position), 0) FROM user_playlist_tracks WHERE playlist_id = $1",
                int(playlist_id)
            )
            next_pos = (max_pos or 0) + 1

            await conn.execute(
                """
                INSERT INTO user_playlist_tracks (playlist_id, track_url, title, artist, thumbnail, duration_str, source, position)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                int(playlist_id), url, title, artist, thumbnail, duration_str, source, next_pos
            )
            return True
    except Exception as e:
        logger.error(f"Error adding track to playlist {playlist_id}: {e}")
        return False

async def remove_track_from_playlist(playlist_id: int, track_url: str) -> bool:
    global _pool
    if not _pool:
        await init_db()
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM user_playlist_tracks
                WHERE playlist_id = $1 AND track_url = $2
                """,
                int(playlist_id), track_url
            )
            return True
    except Exception as e:
        logger.error(f"Error removing track from playlist {playlist_id}: {e}")
        return False

# --- User History ---

async def get_user_history(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT track_url, title, artist, thumbnail, duration_str, source, played_at
                FROM user_history
                WHERE user_id = $1
                ORDER BY played_at DESC
                LIMIT $2
                """,
                str(user_id), limit
            )
            return [
                {
                    "url": r["track_url"],
                    "title": r["title"],
                    "artist": r["artist"] or "Неизвестный исполнитель",
                    "thumbnail": r["thumbnail"] or "/static/activity_icon.jpg",
                    "duration_str": r["duration_str"] or "00:00",
                    "source": r["source"] or "youtube",
                    "played_at": r["played_at"].isoformat() if r["played_at"] else None
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"Error fetching history for user {user_id}: {e}")
        return []

async def add_user_history(user_id: str, track: Dict[str, Any]) -> bool:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id or not track:
        return False
    try:
        url = track.get("url") or f"https://music.youtube.com/search?q={track.get('title', '')}"
        title = track.get("title", "Без названия")
        artist = track.get("artist", "")
        thumbnail = track.get("thumbnail", "/static/activity_icon.jpg")
        duration_str = track.get("duration_str", "00:00")
        source = track.get("source", "youtube")

        async with _pool.acquire() as conn:
            # Delete previous identical entry to bring to top
            await conn.execute(
                """
                DELETE FROM user_history
                WHERE user_id = $1 AND track_url = $2
                """,
                str(user_id), url
            )
            # Insert fresh
            await conn.execute(
                """
                INSERT INTO user_history (user_id, track_url, title, artist, thumbnail, duration_str, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                str(user_id), url, title, artist, thumbnail, duration_str, source
            )
            # Keep max 100 history items per user
            await conn.execute(
                """
                DELETE FROM user_history
                WHERE id IN (
                    SELECT id FROM user_history
                    WHERE user_id = $1
                    ORDER BY played_at DESC
                    OFFSET 100
                )
                """,
                str(user_id)
            )
            return True
    except Exception as e:
        logger.error(f"Error adding to history for user {user_id}: {e}")
        return False

async def clear_user_history(user_id: str) -> bool:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM user_history
                WHERE user_id = $1
                """,
                str(user_id)
            )
            return True
    except Exception as e:
        logger.error(f"Error clearing history for user {user_id}: {e}")
        return False

async def get_global_recent_history(limit: int = 20) -> List[Dict[str, Any]]:
    global _pool
    if not _pool:
        await init_db()
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT track_url, title, artist, thumbnail, duration_str, source, played_at
                FROM user_history
                ORDER BY played_at DESC
                LIMIT $1
                """,
                limit
            )
            # Deduplicate by title & artist keeping newest
            seen = set()
            result = []
            for r in rows:
                key = (r["title"].strip().lower(), (r["artist"] or "").strip().lower())
                if key in seen:
                    continue
                seen.add(key)
                result.append({
                    "url": r["track_url"],
                    "title": r["title"],
                    "artist": r["artist"] or "Неизвестный исполнитель",
                    "thumbnail": r["thumbnail"] or "/static/activity_icon.jpg",
                    "duration_str": r["duration_str"] or "00:00",
                    "source": r["source"] or "youtube",
                    "played_at": r["played_at"].isoformat() if r["played_at"] else None
                })
            return result
    except Exception as e:
        logger.error(f"Error fetching global recent history: {e}")
        return []

# --- Anti-Crash & Restricted Users ---

async def get_restricted_users() -> List[Dict[str, Any]]:
    global _pool
    if not _pool:
        await init_db()
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, user_name, user_avatar, guild_id, guild_name, reason, requests_count, restricted_at, is_active
                FROM bot_restricted_users
                WHERE is_active = TRUE
                ORDER BY restricted_at DESC;
                """
            )
            return [
                {
                    "user_id": r["user_id"],
                    "user_name": r["user_name"],
                    "user_avatar": r["user_avatar"] or "/static/activity_icon.jpg",
                    "guild_id": r["guild_id"] or "",
                    "guild_name": r["guild_name"] or "Неизвестный сервер",
                    "reason": r["reason"] or "Спам запросами",
                    "requests_count": r["requests_count"] or 1,
                    "restricted_at": r["restricted_at"].strftime("%Y-%m-%d %H:%M:%S") if r["restricted_at"] else "",
                    "is_active": r["is_active"]
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"Error fetching restricted users: {e}")
        return []

async def add_restricted_user(
    user_id: str,
    user_name: str,
    user_avatar: Optional[str] = None,
    guild_id: Optional[str] = None,
    guild_name: Optional[str] = None,
    reason: Optional[str] = None,
    requests_count: int = 1
) -> bool:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_restricted_users (user_id, user_name, user_avatar, guild_id, guild_name, reason, requests_count, restricted_at, is_active)
                VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_TIMESTAMP, TRUE)
                ON CONFLICT (user_id) DO UPDATE SET
                    user_name = EXCLUDED.user_name,
                    user_avatar = COALESCE(EXCLUDED.user_avatar, bot_restricted_users.user_avatar),
                    guild_id = COALESCE(EXCLUDED.guild_id, bot_restricted_users.guild_id),
                    guild_name = COALESCE(EXCLUDED.guild_name, bot_restricted_users.guild_name),
                    reason = EXCLUDED.reason,
                    requests_count = bot_restricted_users.requests_count + EXCLUDED.requests_count,
                    restricted_at = CURRENT_TIMESTAMP,
                    is_active = TRUE;
                """,
                str(user_id),
                user_name or "Пользователь",
                user_avatar or "/static/activity_icon.jpg",
                str(guild_id) if guild_id else "",
                guild_name or "Сервер Discord",
                reason or "Спам запросами музыки",
                requests_count
            )
            return True
    except Exception as e:
        logger.error(f"Error adding restricted user {user_id}: {e}")
        return False

async def remove_restricted_user(user_id: str) -> bool:
    global _pool
    if not _pool:
        await init_db()
    if not _pool or not user_id:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM bot_restricted_users
                WHERE user_id = $1;
                """,
                str(user_id)
            )
            return True
    except Exception as e:
        logger.error(f"Error removing restricted user {user_id}: {e}")
        return False

async def is_user_restricted(user_id: str) -> bool:
    global _pool
    if not _pool or not user_id:
        return False
    try:
        async with _pool.acquire() as conn:
            val = await conn.fetchval(
                """
                SELECT is_active FROM bot_restricted_users
                WHERE user_id = $1 AND is_active = TRUE;
                """,
                str(user_id)
            )
            return bool(val)
    except Exception as e:
        logger.debug(f"is_user_restricted check: {e}")
        return False

