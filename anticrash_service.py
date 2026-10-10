import os
import json
import time
import asyncio
import logging
from collections import deque
from typing import Dict, Any, List, Optional, Tuple, Set

import db

logger = logging.getLogger("anticrash")

ANTICRASH_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anticrash_settings.json")

class AntiCrashService:
    def __init__(self):
        # Rolling request timestamps: user_id -> deque of float timestamps
        self._user_requests: Dict[str, deque] = {}

        # In-memory fast cache of restricted user IDs: user_id -> dict
        self._restricted_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_loaded: bool = False

        # Configurable protection settings
        self.settings: Dict[str, Any] = {
            "enabled": True,
            "max_requests_10s": 6,       # Max requests within 10 seconds
            "max_requests_60s": 18,      # Max requests within 60 seconds
            "auto_block": True,          # Automatically block on spam threshold
            "auto_restrict": True,       # Alias for admin UI compatibility
            "notify_admins": True,
        }
        self._load_settings_from_disk()

    def _load_settings_from_disk(self):
        try:
            if os.path.exists(ANTICRASH_SETTINGS_FILE):
                with open(ANTICRASH_SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.settings.update(data)
                        if "auto_block" in data and "auto_restrict" not in data:
                            self.settings["auto_restrict"] = data["auto_block"]
                        elif "auto_restrict" in data and "auto_block" not in data:
                            self.settings["auto_block"] = data["auto_restrict"]
                        logger.info(f"Loaded AntiCrash settings from disk: {self.settings}")
        except Exception as e:
            logger.warning(f"Could not load anticrash settings from disk: {e}")

    def _save_settings_to_disk(self):
        try:
            with open(ANTICRASH_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            logger.info("Saved AntiCrash settings to disk.")
        except Exception as e:
            logger.warning(f"Could not save anticrash settings to disk: {e}")

    async def ensure_loaded(self):
        if self._cache_loaded:
            return
        try:
            # 1. Load settings from database if available
            db_settings_str = await db.get_bot_setting("anticrash_settings")
            if db_settings_str:
                try:
                    db_settings = json.loads(db_settings_str)
                    if isinstance(db_settings, dict):
                        self.settings.update(db_settings)
                        self._save_settings_to_disk()
                except Exception:
                    pass
            else:
                try:
                    await db.set_bot_setting("anticrash_settings", json.dumps(self.settings))
                except Exception:
                    pass

            # 2. Load restricted users
            users = await db.get_restricted_users()
            for u in users:
                self._restricted_cache[str(u["user_id"])] = u
            self._cache_loaded = True
            logger.info(f"AntiCrash cache initialized with {len(self._restricted_cache)} restricted users.")
        except Exception as e:
            logger.debug(f"AntiCrash init db load: {e}")

    def is_restricted(self, user_id: Any) -> bool:
        if not user_id:
            return False
        uid = str(user_id).strip()
        return uid in self._restricted_cache

    def get_restriction(self, user_id: Any) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        return self._restricted_cache.get(str(user_id).strip())

    async def get_all_restricted_users(self) -> List[Dict[str, Any]]:
        await self.ensure_loaded()
        try:
            db_users = await db.get_restricted_users()
            self._restricted_cache = {str(u["user_id"]): u for u in db_users}
            return db_users
        except Exception as e:
            logger.error(f"Error fetching restricted users list: {e}")
            return list(self._restricted_cache.values())

    async def check_and_record_request(
        self,
        user_id: Any,
        user_name: str = "Пользователь",
        user_avatar: Optional[str] = None,
        guild_id: Optional[Any] = None,
        guild_name: Optional[str] = None,
        action: str = "play"
    ) -> Tuple[bool, Optional[str]]:
        """
        Records an interaction/music request.
        Returns: (is_blocked: bool, reason_message: Optional[str])
        """
        if not user_id:
            return False, None

        uid = str(user_id).strip()
        await self.ensure_loaded()

        # If already restricted
        if uid in self._restricted_cache:
            info = self._restricted_cache[uid]
            reason = info.get("reason", "Превышение лимита запросов (спам)")
            return True, f"⛔ Доступ к боту ограничен администратором. Причина: {reason}"

        if not self.settings.get("enabled", True):
            return False, None

        # Exclude bot administrators from spam limit
        import admin_service
        if admin_service.is_admin_id(uid):
            return False, None

        now = time.time()
        if uid not in self._user_requests:
            self._user_requests[uid] = deque(maxlen=40)

        dq = self._user_requests[uid]
        dq.append(now)

        # Count requests in last 10 seconds and 60 seconds
        cutoff_10s = now - 10.0
        cutoff_60s = now - 60.0

        count_10s = sum(1 for t in dq if t >= cutoff_10s)
        count_60s = sum(1 for t in dq if t >= cutoff_60s)

        max_10s = int(self.settings.get("max_requests_10s", 6))
        max_60s = int(self.settings.get("max_requests_60s", 18))

        is_spam = False
        spam_reason = ""

        if count_10s > max_10s:
            is_spam = True
            spam_reason = f"Спам запросами музыки ({count_10s} запросов за 10 сек)"
        elif count_60s > max_60s:
            is_spam = True
            spam_reason = f"Превышен лимит запросов ({count_60s} запросов за минуту)"

        if is_spam and self.settings.get("auto_block", True):
            # Restrict the user
            g_id = str(guild_id) if guild_id else ""
            g_name = guild_name or "Сервер Discord"
            avatar = user_avatar or "/static/activity_icon.jpg"

            restriction_entry = {
                "user_id": uid,
                "user_name": user_name,
                "user_avatar": avatar,
                "guild_id": g_id,
                "guild_name": g_name,
                "reason": spam_reason,
                "requests_count": count_10s,
                "restricted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "is_active": True,
            }
            self._restricted_cache[uid] = restriction_entry

            logger.warning(
                f"[ANTI-CRASH TRIGGERED] User '{user_name}' (ID: {uid}) RESTRICTED on guild '{g_name}' ({g_id}). Reason: {spam_reason}"
            )

            # Persist to PostgreSQL in background
            asyncio.create_task(db.add_restricted_user(
                user_id=uid,
                user_name=user_name,
                user_avatar=avatar,
                guild_id=g_id,
                guild_name=g_name,
                reason=spam_reason,
                requests_count=count_10s,
            ))

            return True, f"⛔ Доступ к боту ограничен антикраш-системой из-за спама ({spam_reason}). Обратитесь к администратору."

        return False, None

    async def unrestrict_user(self, user_id: Any) -> bool:
        if not user_id:
            return False
        uid = str(user_id).strip()
        self._restricted_cache.pop(uid, None)
        ok = await db.remove_restricted_user(uid)
        logger.info(f"[ANTI-CRASH] Restriction removed for user ID {uid}")
        return ok

    async def restrict_user_manually(
        self,
        user_id: Any,
        user_name: str = "Пользователь",
        user_avatar: Optional[str] = None,
        guild_id: Optional[Any] = None,
        guild_name: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        if not user_id:
            return False
        uid = str(user_id).strip()
        g_id = str(guild_id) if guild_id else ""
        g_name = guild_name or "Ручная блокировка"
        r_reason = reason or "Ограничен администратором"
        avatar = user_avatar or "/static/activity_icon.jpg"

        entry = {
            "user_id": uid,
            "user_name": user_name,
            "user_avatar": avatar,
            "guild_id": g_id,
            "guild_name": g_name,
            "reason": r_reason,
            "requests_count": 1,
            "restricted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "is_active": True,
        }
        self._restricted_cache[uid] = entry
        ok = await db.add_restricted_user(
            user_id=uid,
            user_name=user_name,
            user_avatar=avatar,
            guild_id=g_id,
            guild_name=g_name,
            reason=r_reason,
            requests_count=1,
        )
        logger.info(f"[ANTI-CRASH] User {user_name} ({uid}) manually restricted by admin on {g_name}. Reason: {r_reason}")
        return ok

    async def update_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        for k in ["enabled", "notify_admins"]:
            if k in new_settings:
                self.settings[k] = bool(new_settings[k])
        if "auto_block" in new_settings:
            self.settings["auto_block"] = bool(new_settings["auto_block"])
            self.settings["auto_restrict"] = self.settings["auto_block"]
        elif "auto_restrict" in new_settings:
            self.settings["auto_block"] = bool(new_settings["auto_restrict"])
            self.settings["auto_restrict"] = self.settings["auto_block"]
        for k in ["max_requests_10s", "max_requests_60s"]:
            if k in new_settings:
                try:
                    val = int(new_settings[k])
                    if 2 <= val <= 100:
                        self.settings[k] = val
                except (ValueError, TypeError):
                    pass
        logger.info(f"[ANTI-CRASH] Settings updated: {self.settings}")
        self._save_settings_to_disk()
        try:
            await db.set_bot_setting("anticrash_settings", json.dumps(self.settings))
        except Exception as e:
            logger.warning(f"[ANTI-CRASH] Could not persist settings to db: {e}")
        return dict(self.settings)

    def update_settings_sync(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        for k in ["enabled", "notify_admins"]:
            if k in new_settings:
                self.settings[k] = bool(new_settings[k])
        if "auto_block" in new_settings:
            self.settings["auto_block"] = bool(new_settings["auto_block"])
            self.settings["auto_restrict"] = self.settings["auto_block"]
        elif "auto_restrict" in new_settings:
            self.settings["auto_block"] = bool(new_settings["auto_restrict"])
            self.settings["auto_restrict"] = self.settings["auto_block"]
        for k in ["max_requests_10s", "max_requests_60s"]:
            if k in new_settings:
                try:
                    val = int(new_settings[k])
                    if 2 <= val <= 100:
                        self.settings[k] = val
                except (ValueError, TypeError):
                    pass
        self._save_settings_to_disk()
        try:
            asyncio.create_task(db.set_bot_setting("anticrash_settings", json.dumps(self.settings)))
        except Exception:
            pass
        return dict(self.settings)


# Global singleton instance
anticrash = AntiCrashService()
