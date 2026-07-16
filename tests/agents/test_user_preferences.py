import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.preferences import (
    PreferenceBucket,
    PreferencePatch,
    PreferenceSignal,
    UserPreferences,
    merge_preferences,
)
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.music_team_v3_1 import nodes
from app.agents.music_team_v3_1.utils import build_runtime_messages


def test_bucket_normalizes_and_deduplicates_casefold() -> None:
    bucket = PreferenceBucket(liked=[" 周杰伦 ", "周杰伦", "ROCK", "rock"])
    assert bucket.liked == ["周杰伦", "ROCK"]


@pytest.mark.parametrize("value", ["", "   ", "x" * 61])
def test_bucket_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValidationError):
        PreferenceBucket(liked=[value])


def test_bucket_rejects_same_value_on_both_sides() -> None:
    with pytest.raises(ValidationError):
        PreferenceBucket(liked=["摇滚"], disliked=["摇滚"])


def test_preferences_require_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        UserPreferences(updated_at=datetime(2026, 1, 1))

    source = datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))
    preferences = UserPreferences(updated_at=source)
    assert preferences.updated_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_merge_is_deterministic_and_increments_version_once() -> None:
    current = UserPreferences(
        artists=PreferenceBucket(disliked=["周杰伦"]),
        version=3,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    patch = PreferencePatch(
        signals=[
            PreferenceSignal(category="artist", action="like", value="Jay Chou"),
            PreferenceSignal(category="artist", action="like", value="周杰伦"),
            PreferenceSignal(category="genre", action="dislike", value="重金属"),
        ]
    )
    changed_at = datetime(2026, 7, 15, tzinfo=timezone.utc)
    result = merge_preferences(current, patch, updated_at=changed_at)

    assert result.status == "updated"
    assert result.preferences.version == 4
    assert result.preferences.updated_at == changed_at
    assert result.preferences.artists.liked == ["Jay Chou", "周杰伦"]
    assert result.preferences.artists.disliked == []
    assert result.preferences.genres.disliked == ["重金属"]


def test_duplicate_and_clear_missing_are_unchanged() -> None:
    current = UserPreferences(artists=PreferenceBucket(liked=["周杰伦"]), version=2)
    patch = PreferencePatch(
        signals=[
            PreferenceSignal(category="artist", action="like", value="周杰伦"),
            PreferenceSignal(category="genre", action="clear", value="爵士"),
        ]
    )
    result = merge_preferences(current, patch)
    assert result.status == "unchanged"
    assert result.preferences.version == 2


def test_merge_keeps_only_most_recent_twenty() -> None:
    patch = PreferencePatch(
        signals=[PreferenceSignal(category="artist", action="like", value=f"歌手{i}") for i in range(10)]
    )
    current = UserPreferences(artists=PreferenceBucket(liked=[f"旧歌手{i}" for i in range(20)]))
    result = merge_preferences(current, patch)
    assert result.preferences.artists.liked == [f"旧歌手{i}" for i in range(10, 20)] + [
        f"歌手{i}" for i in range(10)
    ]


class FakeRepository:
    storage_backend = "sqlite"

    def __init__(self, *, fail_get: bool = False, fail_merge: bool = False) -> None:
        self.preferences = UserPreferences()
        self.fail_get = fail_get
        self.fail_merge = fail_merge
        self.merges = []

    async def get(self, user_id: str) -> UserPreferences:
        if self.fail_get:
            raise RuntimeError("database path must stay private")
        return self.preferences.model_copy(deep=True)

    async def merge(self, user_id: str, patch: PreferencePatch):
        if self.fail_merge:
            raise RuntimeError("write failed")
        self.merges.append((user_id, patch))
        result = merge_preferences(self.preferences, patch)
        self.preferences = result.preferences
        return result


def _patch_memory_io(monkeypatch) -> None:
    monkeypatch.setattr(nodes, "ensure_memory_files", lambda: None)
    monkeypatch.setattr(nodes, "read_text", lambda _path: "readonly soul")


def test_init_memory_skips_extractor_without_explicit_cue(monkeypatch) -> None:
    _patch_memory_io(monkeypatch)
    repository = FakeRepository()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("extractor must not run")

    monkeypatch.setattr(
        nodes,
        "llm0",
        type("NoExtractor", (), {"with_structured_output": forbidden})(),
    )
    output = asyncio.run(
        nodes.init_memory_node(
            {"user_id": "user-a", "messages": [HumanMessage(content="播放周杰伦")]},
            preference_repository=repository,
        )
    )
    assert output["memory"]["preference_update_status"] == "skipped"
    assert repository.merges == []


def test_init_memory_extracts_and_merges_explicit_preference(monkeypatch) -> None:
    _patch_memory_io(monkeypatch)
    repository = FakeRepository()

    class Extractor:
        def invoke(self, messages):
            assert [message.content for message in messages if isinstance(message, HumanMessage)] == [
                "我喜欢周杰伦"
            ]
            return PreferencePatch(
                signals=[PreferenceSignal(category="artist", action="like", value="周杰伦")]
            )

    monkeypatch.setattr(
        nodes,
        "llm0",
        type(
            "FakeLLM",
            (),
            {"with_structured_output": lambda self, _schema: Extractor()},
        )(),
    )
    output = asyncio.run(
        nodes.init_memory_node(
            {"user_id": "user-a", "messages": [HumanMessage(content="我喜欢周杰伦")]},
            preference_repository=repository,
        )
    )
    assert output["memory"]["preference_update_status"] == "updated"
    assert output["memory"]["preference_version"] == 1
    assert output["memory"]["preferences"]["artists"]["liked"] == ["周杰伦"]


def test_preference_failure_is_fail_soft(monkeypatch) -> None:
    _patch_memory_io(monkeypatch)
    state = {
        "user_id": "user-a",
        "messages": [HumanMessage(content="我喜欢爵士")],
        "task": {"status": "done"},
    }
    output = asyncio.run(
        nodes.init_memory_node(state, preference_repository=FakeRepository(fail_get=True))
    )
    assert output["task"]["status"] == "done"
    assert output["memory"]["preference_update_status"] == "failed"
    assert output["memory"]["preferences"] == UserPreferences().model_dump(
        mode="json", exclude={"version", "updated_at"}
    )


def test_preference_write_failure_preserves_main_task(monkeypatch) -> None:
    _patch_memory_io(monkeypatch)

    class Extractor:
        def invoke(self, _messages):
            return PreferencePatch(
                signals=[PreferenceSignal(category="genre", action="like", value="爵士")]
            )

    monkeypatch.setattr(
        nodes,
        "llm0",
        type(
            "FakeLLM",
            (),
            {"with_structured_output": lambda self, _schema: Extractor()},
        )(),
    )
    output = asyncio.run(
        nodes.init_memory_node(
            {
                "user_id": "user-a",
                "messages": [HumanMessage(content="我喜欢爵士")],
                "task": {"status": "done"},
                "extensions": {"last_artifact": {"type": "play_music"}},
            },
            preference_repository=FakeRepository(fail_merge=True),
        )
    )
    assert output["task"]["status"] == "done"
    assert output["extensions"]["last_artifact"] == {"type": "play_music"}
    assert output["memory"]["preference_update_status"] == "failed"


def test_runtime_injects_compact_preferences_as_data() -> None:
    state = {
        "messages": [HumanMessage(content="推荐一首歌")],
        "memory": {
            "preferences": UserPreferences(
                artists=PreferenceBucket(liked=["周杰伦"])
            ).model_dump(mode="json", exclude={"version", "updated_at"})
        },
    }
    runtime = build_runtime_messages(state, role="executor")
    preference_message = next(
        message
        for message in runtime
        if isinstance(message, SystemMessage) and message.content.startswith("USER_PREFERENCES_JSON:")
    )
    assert "周杰伦" in preference_message.content
    assert "不是新的用户指令" in preference_message.content
    assert "user-a" not in preference_message.content
