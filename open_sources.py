"""Дополнительные источники треков из открытого доступа — без API-ключей и регистрации.

* Audius        — децентрализованная платформа независимых артистов (публичный API, полные треки)
* Internet Archive — открытая библиотека аудио: лайв-записи, нетлейбы, классика, public domain
* Mixcloud      — DJ-сеты и радиошоу (публичный поиск; поток извлекает yt-dlp)

Модуль не импортирует music_service (во избежание циклического импорта):
класс Track передаётся параметром.
"""
import logging
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Type

import aiohttp

logger = logging.getLogger("open_sources")

APP_NAME = "Musicium"
HEADERS = {"User-Agent": "Musicium/2.0 (+https://github.com/sosmula616-star/musicium)"}
TIMEOUT = aiohttp.ClientTimeout(total=7.0, connect=3.0)

# Человекочитаемые названия для интерфейса и логов
SOURCE_LABELS = {
    "audius": "Audius",
    "archive": "Internet Archive",
    "mixcloud": "Mixcloud",
}

_audius_hosts: List[str] = []
_audius_hosts_at: float = 0.0


async def _get_json(session: aiohttp.ClientSession, url: str, **kwargs) -> Any:
    async with session.get(url, headers=HEADERS, **kwargs) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        return await resp.json(content_type=None)


# ---------------------------------------------------------------- Audius ---

async def _audius_host(session: aiohttp.ClientSession) -> str:
    """Выбирает рабочий узел Audius (список узлов кешируется на час)."""
    global _audius_hosts, _audius_hosts_at
    now = time.time()
    if not _audius_hosts or now - _audius_hosts_at > 3600:
        try:
            data = await _get_json(session, "https://api.audius.co")
            hosts = [h for h in (data.get("data") or []) if isinstance(h, str) and h.startswith("https://")]
            if hosts:
                _audius_hosts, _audius_hosts_at = hosts, now
        except Exception as e:
            logger.debug(f"Audius host discovery failed: {e}")
    return _audius_hosts[0] if _audius_hosts else "https://api.audius.co"


def _audius_track(Track: Type, item: Dict[str, Any]) -> Optional[Any]:
    if not item or item.get("is_streamable") is False or not item.get("id"):
        return None
    art = item.get("artwork") or {}
    thumb = art.get("480x480") or art.get("1000x1000") or art.get("150x150") or ""
    user = item.get("user") or {}
    permalink = item.get("permalink") or ""
    return Track(
        id=f"audius_{item['id']}",
        title=item.get("title") or "Без названия",
        artist=user.get("name") or user.get("handle") or "Audius",
        duration=int(item.get("duration") or 0),
        thumbnail=thumb,
        url=f"https://audius.co{permalink}" if permalink else "https://audius.co",
        source="audius",
    )


async def search_audius(Track: Type, query: str, limit: int = 8) -> List[Any]:
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        host = await _audius_host(session)
        params = urllib.parse.urlencode({"query": query, "limit": limit, "app_name": APP_NAME})
        data = await _get_json(session, f"{host}/v1/tracks/search?{params}")
    tracks = [_audius_track(Track, it) for it in (data.get("data") or [])]
    return [t for t in tracks if t]


async def resolve_audius_url(Track: Type, url: str) -> List[Any]:
    """Прямая ссылка audius.co/... → список из одного трека."""
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        host = await _audius_host(session)
        params = urllib.parse.urlencode({"url": url, "app_name": APP_NAME})
        data = await _get_json(session, f"{host}/v1/resolve?{params}")
    item = data.get("data")
    if isinstance(item, dict) and item.get("id") and item.get("title"):
        t = _audius_track(Track, item)
        return [t] if t else []
    return []


async def audius_stream(track: Any) -> Optional[str]:
    track_id = str(track.id).split("_", 1)[-1]
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        host = await _audius_host(session)
        base = f"{host}/v1/tracks/{track_id}/stream?app_name={APP_NAME}"
        try:
            # узел отвечает редиректом на CDN — берём конечную ссылку, чтобы ffmpeg не зависел от редиректов
            async with session.get(base, headers=HEADERS, allow_redirects=False) as resp:
                loc = resp.headers.get("Location")
                if resp.status in (301, 302, 303, 307, 308) and loc:
                    return loc
                if resp.status == 200:
                    return base
        except Exception as e:
            logger.debug(f"Audius stream redirect lookup failed: {e}")
    return base


# ------------------------------------------------------ Internet Archive ---

_AUDIO_FORMATS = ("VBR MP3", "MP3", "128Kbps MP3", "64Kbps MP3", "Ogg Vorbis", "Flac")


def _parse_length(value: Any) -> int:
    """Длительность файла в архиве бывает секундами ('215.3') или 'мм:сс'."""
    if value is None:
        return 0
    s = str(value).strip()
    try:
        if ":" in s:
            secs = 0
            for part in s.split(":"):
                secs = secs * 60 + int(float(part))
            return secs
        return int(float(s))
    except ValueError:
        return 0


async def search_archive(Track: Type, query: str, limit: int = 6) -> List[Any]:
    safe = re.sub(r'[\\"():\[\]{}^~*?!]', " ", query).strip()
    if not safe:
        return []
    lucene = f'(title:({safe}) OR creator:({safe})) AND mediatype:audio'
    params = [
        ("q", lucene), ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "creator"),
        ("sort[]", "downloads desc"), ("rows", str(limit)), ("output", "json"),
    ]
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        data = await _get_json(session, "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params))
    tracks = []
    for doc in (data.get("response", {}).get("docs") or []):
        ident = doc.get("identifier")
        if not ident:
            continue
        creator = doc.get("creator")
        if isinstance(creator, list):
            creator = ", ".join(str(c) for c in creator[:2])
        title = doc.get("title")
        if isinstance(title, list):
            title = title[0] if title else None
        tracks.append(Track(
            id=f"archive_{ident}",
            title=title or ident,
            artist=creator or "Internet Archive",
            duration=0,
            thumbnail=f"https://archive.org/services/img/{ident}",
            url=f"https://archive.org/details/{ident}",
            source="archive",
        ))
    return tracks


async def _archive_best_file(session: aiohttp.ClientSession, ident: str) -> Optional[Dict[str, Any]]:
    meta = await _get_json(session, f"https://archive.org/metadata/{urllib.parse.quote(ident)}")
    files = [f for f in (meta.get("files") or []) if f.get("format") in _AUDIO_FORMATS and f.get("name")]
    if not files:
        return None
    files.sort(key=lambda f: (_AUDIO_FORMATS.index(f["format"]), f["name"]))
    return files[0]


async def resolve_archive_url(Track: Type, url: str) -> List[Any]:
    m = re.search(r"archive\.org/(?:details|download)/([^/?#]+)", url)
    if not m:
        return []
    ident = urllib.parse.unquote(m.group(1))
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        meta = await _get_json(session, f"https://archive.org/metadata/{urllib.parse.quote(ident)}")
    md = meta.get("metadata") or {}
    creator = md.get("creator")
    if isinstance(creator, list):
        creator = ", ".join(str(c) for c in creator[:2])
    title = md.get("title")
    if isinstance(title, list):
        title = title[0] if title else None
    return [Track(
        id=f"archive_{ident}", title=title or ident, artist=creator or "Internet Archive", duration=0,
        thumbnail=f"https://archive.org/services/img/{ident}", url=f"https://archive.org/details/{ident}", source="archive",
    )]


async def archive_stream(track: Any) -> Optional[str]:
    ident = str(track.id).split("_", 1)[-1]
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        best = await _archive_best_file(session, ident)
    if not best:
        return None
    dur = _parse_length(best.get("length"))
    if dur and not track.duration:
        track.duration = dur
    return f"https://archive.org/download/{urllib.parse.quote(ident)}/{urllib.parse.quote(best['name'])}"


# -------------------------------------------------------------- Mixcloud ---

async def search_mixcloud(Track: Type, query: str, limit: int = 6) -> List[Any]:
    params = urllib.parse.urlencode({"q": query, "type": "cloudcast", "limit": limit})
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        data = await _get_json(session, f"https://api.mixcloud.com/search/?{params}")
    tracks = []
    for it in (data.get("data") or []):
        key = it.get("key") or ""
        if not key:
            continue
        pics = it.get("pictures") or {}
        thumb = pics.get("640wx640h") or pics.get("large") or pics.get("medium") or ""
        tracks.append(Track(
            id=f"mixcloud_{key.strip('/').replace('/', '_')}",
            title=it.get("name") or "Без названия",
            artist=(it.get("user") or {}).get("name") or "Mixcloud",
            duration=int(it.get("audio_length") or 0),
            thumbnail=thumb,
            url=it.get("url") or f"https://www.mixcloud.com{key}",
            source="mixcloud",
        ))
    return tracks


# ------------------------------------------------------------- Диспетчер ---

async def search_source(Track: Type, source: str, query: str, limit: int) -> List[Any]:
    if source == "audius":
        return await search_audius(Track, query, limit)
    if source == "archive":
        return await search_archive(Track, query, limit)
    if source == "mixcloud":
        return await search_mixcloud(Track, query, limit)
    return []


async def resolve_url(Track: Type, url: str) -> Optional[List[Any]]:
    """Возвращает треки, если ссылка относится к нашим источникам; иначе None."""
    host = urllib.parse.urlparse(url).netloc.lower()
    try:
        if host.endswith("audius.co"):
            return await resolve_audius_url(Track, url)
        if host.endswith("archive.org"):
            return await resolve_archive_url(Track, url)
    except Exception as e:
        logger.warning(f"Open-source URL resolve failed ({url}): {e}")
        return []
    return None


async def stream_url(track: Any) -> Optional[str]:
    """Прямая ссылка на аудио для audius/archive. Mixcloud и прочие разбирает yt-dlp."""
    try:
        if track.source == "audius":
            return await audius_stream(track)
        if track.source == "archive":
            return await archive_stream(track)
    except Exception as e:
        logger.warning(f"Open-source stream resolve failed for {track.id}: {e}")
    return None


# ------------------------------------------------- Piped (запасной путь для YouTube) ---
# Публичные зеркала без ключей. Используются, когда yt-dlp не смог получить поток напрямую
# (YouTube часто блокирует IP хостинга) — это тот же ролик, а не подмена на другой трек.

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.private.coffee",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.leptons.xyz",
]


def piped_audio_sync(video_id: str, timeout: float = 4.0) -> Optional[str]:
    """Прямая ссылка на лучший аудиопоток ролика через публичные Piped-API (синхронно, для потоков yt-dlp)."""
    import concurrent.futures
    import json as _json
    import urllib.request

    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return None

    def fetch(base: str) -> Optional[str]:
        req = urllib.request.Request(f"{base}/streams/{video_id}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace"))
        streams = [s for s in (data.get("audioStreams") or []) if s.get("url") and not s.get("videoOnly")]
        if not streams:
            return None
        # AAC (mp4) надёжнее в ffmpeg; среди равных берём максимальный битрейт
        streams.sort(key=lambda s: (("mp4" in str(s.get("mimeType", ""))), int(s.get("bitrate") or 0)), reverse=True)
        return streams[0]["url"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PIPED_INSTANCES)) as ex:
        futures = [ex.submit(fetch, b) for b in PIPED_INSTANCES]
        try:
            for fut in concurrent.futures.as_completed(futures, timeout=timeout + 1.5):
                try:
                    url = fut.result()
                except Exception:
                    continue
                if url:
                    return url
        except concurrent.futures.TimeoutError:
            pass
    return None
