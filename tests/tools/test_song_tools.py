import asyncio

import pytest

from app.schemas import PlayMusicArtifact
from app.tools import song_tools
from app.tools.tool_result import ToolResult, ToolResultCode


def run_play(**kwargs: object) -> ToolResult:
    raw = asyncio.run(song_tools.play_music_tool.ainvoke(kwargs))
    return ToolResult.model_validate_json(raw)


def test_play_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_url(song_mid: str) -> str:
        return "https://example.com/song.mp3"

    async def fake_cover(song_mid: str, size: int) -> str:
        return "https://example.com/cover.jpg"

    monkeypatch.setattr(song_tools.song_service, "get_playable_url", fake_url)
    monkeypatch.setattr(song_tools.song_service, "get_song_cover", fake_cover)

    result = run_play(song_mid="mid-1", song_name="晴天", singer_name="周杰伦")

    assert result.ok is True
    assert result.data["type"] == "play_music"
    assert result.data["url"] == "https://example.com/song.mp3"
    assert PlayMusicArtifact.model_validate(result.data).title == "晴天"


def test_cover_failure_is_non_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_url(song_mid: str) -> str:
        return "https://example.com/song.mp3"

    async def fake_cover(song_mid: str, size: int) -> str:
        raise RuntimeError("cover failed")

    monkeypatch.setattr(song_tools.song_service, "get_playable_url", fake_url)
    monkeypatch.setattr(song_tools.song_service, "get_song_cover", fake_cover)

    result = run_play(song_mid="mid-1", song_name="晴天", singer_name="周杰伦")

    assert result.ok is True
    assert result.data["cover"] == ""


def test_playback_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_url(song_mid: str) -> None:
        return None

    monkeypatch.setattr(song_tools.song_service, "get_playable_url", fake_url)

    result = run_play(song_mid="mid-1", song_name="晴天", singer_name="周杰伦")

    assert result.code == ToolResultCode.PLAYBACK_UNAVAILABLE
    assert not result.data or result.data.get("type") != "play_music"


def test_play_rejects_empty_mid() -> None:
    result = run_play(song_mid="", song_name="晴天", singer_name="周杰伦")

    assert result.code == ToolResultCode.INVALID_ARGUMENT


def test_play_rejects_empty_name() -> None:
    result = run_play(song_mid="mid-1", song_name="", singer_name="周杰伦")

    assert result.code == ToolResultCode.INVALID_ARGUMENT


def test_play_service_exception_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_url(song_mid: str) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(song_tools.song_service, "get_playable_url", fake_url)

    result = run_play(song_mid="mid-1", song_name="晴天", singer_name="周杰伦")

    assert result.code == ToolResultCode.UPSTREAM_ERROR
    assert result.retryable is True
