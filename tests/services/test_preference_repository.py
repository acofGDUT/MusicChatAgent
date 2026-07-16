import asyncio
import sqlite3

import aiosqlite
import pytest

from app.schemas.preferences import PreferencePatch, PreferenceSignal
from app.services.memory.preference_repository import (
    PreferenceDataError,
    SQLitePreferenceRepository,
)


def test_repository_persists_and_isolates_users(tmp_path) -> None:
    async def scenario() -> None:
        db_path = tmp_path / "preferences.sqlite3"
        async with aiosqlite.connect(db_path, isolation_level=None) as connection:
            repository = SQLitePreferenceRepository(connection)
            await repository.setup()
            result = await repository.merge(
                "user-a",
                PreferencePatch(
                    signals=[PreferenceSignal(category="artist", action="like", value="周杰伦")]
                ),
            )
            assert result.status == "updated"
            assert (await repository.get("user-b")).version == 0

        async with aiosqlite.connect(db_path, isolation_level=None) as connection:
            repository = SQLitePreferenceRepository(connection)
            loaded = await repository.get("user-a")
            assert loaded.artists.liked == ["周杰伦"]
            assert loaded.version == 1

    asyncio.run(scenario())


def test_repository_serializes_concurrent_merges(tmp_path) -> None:
    async def scenario() -> None:
        async with aiosqlite.connect(tmp_path / "concurrent.sqlite3", isolation_level=None) as connection:
            repository = SQLitePreferenceRepository(connection)
            await repository.setup()
            await asyncio.gather(
                repository.merge(
                    "user-a",
                    PreferencePatch(
                        signals=[PreferenceSignal(category="artist", action="like", value="周杰伦")]
                    ),
                ),
                repository.merge(
                    "user-a",
                    PreferencePatch(
                        signals=[PreferenceSignal(category="genre", action="like", value="爵士")]
                    ),
                ),
            )
            loaded = await repository.get("user-a")
            assert loaded.version == 2
            assert loaded.artists.liked == ["周杰伦"]
            assert loaded.genres.liked == ["爵士"]

    asyncio.run(scenario())


def test_repository_does_not_overwrite_corrupt_data(tmp_path) -> None:
    async def scenario() -> None:
        async with aiosqlite.connect(tmp_path / "corrupt.sqlite3", isolation_level=None) as connection:
            repository = SQLitePreferenceRepository(connection)
            await repository.setup()
            await connection.execute(
                "INSERT INTO user_preferences(user_id, preferences_json, version, updated_at) VALUES (?, ?, ?, ?)",
                ("user-a", "{broken", 1, "2026-07-15T00:00:00+00:00"),
            )
            with pytest.raises(PreferenceDataError):
                await repository.get("user-a")
            cursor = await connection.execute(
                "SELECT preferences_json FROM user_preferences WHERE user_id = ?", ("user-a",)
            )
            row = await cursor.fetchone()
            assert row == ("{broken",)

    asyncio.run(scenario())


def test_unchanged_merge_does_not_advance_metadata(tmp_path) -> None:
    async def scenario() -> None:
        async with aiosqlite.connect(tmp_path / "unchanged.sqlite3", isolation_level=None) as connection:
            repository = SQLitePreferenceRepository(connection)
            await repository.setup()
            patch = PreferencePatch(
                signals=[PreferenceSignal(category="artist", action="like", value="周杰伦")]
            )
            first = await repository.merge("user-a", patch)
            second = await repository.merge("user-a", patch)
            assert second.status == "unchanged"
            assert second.preferences.version == first.preferences.version
            assert second.preferences.updated_at == first.preferences.updated_at

    asyncio.run(scenario())


def test_merge_rolls_back_on_write_error(tmp_path) -> None:
    async def scenario() -> None:
        async with aiosqlite.connect(tmp_path / "rollback.sqlite3", isolation_level=None) as connection:
            repository = SQLitePreferenceRepository(connection)
            await repository.setup()
            await connection.execute(
                """
                CREATE TRIGGER reject_preferences BEFORE INSERT ON user_preferences
                BEGIN SELECT RAISE(ABORT, 'blocked'); END
                """
            )
            with pytest.raises(sqlite3.IntegrityError):
                await repository.merge(
                    "user-a",
                    PreferencePatch(
                        signals=[PreferenceSignal(category="genre", action="like", value="爵士")]
                    ),
                )
            assert not connection.in_transaction
            assert (await repository.get("user-a")).version == 0

    asyncio.run(scenario())
