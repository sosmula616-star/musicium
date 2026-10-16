"""Автоподбор по вкусу пользователя: ищет новое в стиле и на языке его лайкнутых треков.

Без внешних ключей: «радио» YouTube Music (RD-микс по лайкнутому треку) + обычный поиск как запасной путь.
Фильтры: язык (кириллица / латиница по доле в лайках), длительность, уже знакомые треки и артисты-повторы.
"""
import asyncio
import logging
import random
import re
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger("taste")

_CYR = re.compile(r"[Ѐ-ӿ]")
_LAT = re.compile(r"[A-Za-z]")
_YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")
_JUNK = re.compile(r"\(.*?\)|\[.*?\]|official|video|audio|lyrics|клип|премьера|feat\.?|ft\.?", re.I)


def _norm(text: Optional[str]) -> str:
    t = _JUNK.sub(" ", (text or "").lower())
    return re.sub(r"[^\w]+", " ", t).strip()


def _script_counts(text: str) -> tuple:
    return len(_CYR.findall(text)), len(_LAT.findall(text))


def _first_artist(artist: Optional[str]) -> str:
    return _norm(re.split(r"[,&]|\sfeat|\sft|\sx\s", artist or "", maxsplit=1, flags=re.I)[0])


def _yt_id(url: Optional[str]) -> Optional[str]:
    m = _YT_ID.search(url or "")
    return m.group(1) if m else None


def taste_profile(liked: List[Dict[str, Any]]) -> Dict[str, Any]:
    cyr = lat = 0
    artists: Counter = Counter()
    for t in liked:
        c, l = _script_counts(f"{t.get('title') or ''} {t.get('artist') or ''}")
        cyr += c
        lat += l
        a = _first_artist(t.get("artist"))
        if a:
            artists[a] += 1
    total = cyr + lat
    return {"cyr_share": (cyr / total) if total else 0.5, "artists": artists}


def _language_ok(track: Dict[str, Any], cyr_share: float) -> bool:
    c, l = _script_counts(f"{track.get('title') or ''} {track.get('artist') or ''}")
    if c + l == 0:
        return True
    share = c / (c + l)
    if cyr_share >= 0.65:
        return share >= 0.4          # любимое — русскоязычное: оставляем кириллицу
    if cyr_share <= 0.15:
        return share < 0.4           # любимое — зарубежное: без русскоязычного
    return True                      # смешанный вкус — язык не ограничиваем


async def discover(music_service: Any, liked: List[Dict[str, Any]], history: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    if not liked:
        return []

    profile = taste_profile(liked)
    known_titles = {_norm(t.get("title")) for t in (liked + history) if t.get("title")}
    liked_artists = set(profile["artists"].keys())

    # Семена: свежие лайки важнее, но берём разных артистов, чтобы подборка не была однообразной
    seeds: List[Dict[str, Any]] = []
    seen_artists = set()
    pool = list(liked[:25])
    random.shuffle(pool)
    pool.sort(key=lambda t: 0 if t in liked[:6] else 1)
    for t in pool:
        a = _first_artist(t.get("artist"))
        if a in seen_artists:
            continue
        seen_artists.add(a)
        seeds.append(t)
        if len(seeds) >= 3:
            break

    async def from_seed(seed: Dict[str, Any]) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        vid = _yt_id(seed.get("track_url") or seed.get("url"))
        try:
            if vid and hasattr(music_service, "get_youtube_radio"):
                found = await asyncio.wait_for(music_service.get_youtube_radio(vid, limit=18), timeout=12.0)
            if len(found) < 5:
                q = f"{seed.get('artist') or ''} {seed.get('title') or ''}".strip()
                res = await asyncio.wait_for(music_service.search(f"{q} похожие песни" if profile["cyr_share"] > 0.5 else f"{q} similar songs", source="youtube", limit=12), timeout=12.0)
                found += [t.to_dict() for t in res]
        except Exception as e:
            logger.info(f"Taste seed lookup failed: {e}")
        return found

    batches = await asyncio.gather(*(from_seed(s) for s in seeds), return_exceptions=True)

    candidates: List[Dict[str, Any]] = []
    seen_norm = set(known_titles)
    for batch in batches:
        if not isinstance(batch, list):
            continue
        for td in batch:
            n = _norm(td.get("title"))
            dur = int(td.get("duration") or 0)
            if not n or n in seen_norm:
                continue
            if dur and not (90 <= dur <= 480):
                continue
            if not _language_ok(td, profile["cyr_share"]):
                continue
            seen_norm.add(n)
            candidates.append(td)

    # Новые артисты вперёд, не больше двух треков одного исполнителя
    random.shuffle(candidates)
    candidates.sort(key=lambda t: 1 if _first_artist(t.get("artist")) in liked_artists else 0)
    out: List[Dict[str, Any]] = []
    per_artist: Counter = Counter()
    for td in candidates:
        a = _first_artist(td.get("artist"))
        if per_artist[a] >= 2:
            continue
        per_artist[a] += 1
        td["isAutoplay"] = True
        out.append(td)
        if len(out) >= limit:
            break
    return out
