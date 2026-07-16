"""User-scoped preference persistence with explicit transaction ownership."""

from __future__ import annotations

import asyncio
import json
from typing import Protocol

import aiosqlite
from pydantic import ValidationError

from app.schemas.preferences import (
    PreferenceMergeResult,
    PreferencePatch,
    UserPreferences,
    merge_preferences,
)


class PreferenceDataError(RuntimeError):
    """Persisted preference data failed JSON or schema validation."""


class PreferenceRepository(Protocol):
    storage_backend: str

    async def get(self, user_id: str) -> UserPreferences: ...

    async def merge(self, user_id: str, patch: PreferencePatch) -> PreferenceMergeResult: ...


class DisabledPreferenceRepository:
    storage_backend = "disabled"

    async def get(self, user_id: str) -> UserPreferences:
        del user_id
        return UserPreferences()

    async def merge(self, user_id: str, patch: PreferencePatch) -> PreferenceMergeResult:
        del user_id, patch
        return PreferenceMergeResult(preferences=UserPreferences(), status="unchanged")


DISABLED_PREFERENCES = DisabledPreferenceRepository()


class SQLitePreferenceRepository:
    storage_backend = "sqlite"

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection
        self._lock = asyncio.Lock()

    async def setup(self) -> None:
        async with self._lock:
            await self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY,
                    preferences_json TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )

    async def _get_unlocked(self, user_id: str) -> UserPreferences:
        cursor = await self._connection.execute(
            "SELECT preferences_json, version, updated_at FROM user_preferences WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return UserPreferences()

        preferences_json, version, updated_at = row
        try:
            buckets = json.loads(preferences_json)
            if not isinstance(buckets, dict):
                raise ValueError("preferences_json must be an object")
            return UserPreferences.model_validate(
                {**buckets, "version": version, "updated_at": updated_at}
            )
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise PreferenceDataError("存储的用户偏好数据无效") from exc

    async def get(self, user_id: str) -> UserPreferences:
        async with self._lock:
            return await self._get_unlocked(user_id)

    async def merge(self, user_id: str, patch: PreferencePatch) -> PreferenceMergeResult:
        async with self._lock:
            await self._connection.execute("BEGIN IMMEDIATE")
            try:
                current = await self._get_unlocked(user_id)
                result = merge_preferences(current, patch)
                if result.status == "updated":
                    preferences = result.preferences
                    payload = json.dumps(
                        preferences.model_dump(
                            mode="json",
                            exclude={"version", "updated_at"},
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    assert preferences.updated_at is not None
                    await self._connection.execute(
                        """
                        INSERT INTO user_preferences(user_id, preferences_json, version, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET
                            preferences_json=excluded.preferences_json,
                            version=excluded.version,
                            updated_at=excluded.updated_at
                        """,
                        (
                            user_id,
                            payload,
                            preferences.version,
                            preferences.updated_at.isoformat(),
                        ),
                    )
                await self._connection.commit()
                return result
            except BaseException:
                await self._connection.rollback()
                raise
