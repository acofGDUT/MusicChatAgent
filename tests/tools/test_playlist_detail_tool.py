import asyncio

import pytest

from app.schemas import PlaylistBrowserArtifact
from app.tools import playlist_tools
from app.tools.tool_result import ToolResult, ToolResultCode


def run_tool(**kwargs: object) -> ToolResult:
    raw = asyncio.run(playlist_tools.get_playlist_detail_tool.ainvoke(kwargs))
    return ToolResult.model_validate_json(raw)


def test_playlist_detail_rejects_missing_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(**kwargs: object) -> dict:
        raise AssertionError("playlist service should not be called")

    monkeypatch.setattr(
        playlist_tools.playlist_service,
        "get_playlist_detail",
        fail_if_called,
    )

    result = run_tool(songlist_id=0, dirid=0)

    assert result.ok is False
    assert result.code == ToolResultCode.INVALID_ARGUMENT
    assert result.retryable is False
    assert result.data == {"songlist_id": 0, "dirid": 0}


def test_playlist_detail_returns_valid_paginated_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_get_playlist_detail(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {
            "status": "success",
            "total_song_num": 5,
            "playlist_info": {"title": "  通勤歌单  ", "dirid": "42"},
            "songlist": [
                {"mid": " mid-3 ", "title": " 晴天 ", "singer": "周杰伦"},
                {"mid": "mid-4", "title": "夜曲", "singer": "周杰伦"},
            ],
        }

    monkeypatch.setattr(
        playlist_tools.playlist_service,
        "get_playlist_detail",
        fake_get_playlist_detail,
    )

    result = run_tool(songlist_id=301, dirid=0, num=2, page=2, onlysong=False)
    artifact = PlaylistBrowserArtifact.model_validate(result.data)

    assert captured == {
        "songlist_id": 301,
        "dirid": 0,
        "num": 2,
        "page": 2,
        "onlysong": False,
    }
    assert result.ok is True
    assert result.code == ToolResultCode.SUCCESS
    assert artifact.type == "playlist_browser"
    assert artifact.playlist_name == "通勤歌单"
    assert artifact.dirid == 42
    assert artifact.page == 2
    assert artifact.page_size == 2
    assert artifact.total_song_num == 5
    assert artifact.has_more is True
    assert artifact.description == "已加载第 2 页，可点击歌曲播放"
    assert [track.model_dump() for track in artifact.tracks] == [
        {
            "index": 3,
            "song_mid": "mid-3",
            "title": "晴天",
            "artist": "周杰伦",
            "cover": "",
        },
        {
            "index": 4,
            "song_mid": "mid-4",
            "title": "夜曲",
            "artist": "周杰伦",
            "cover": "",
        },
    ]


@pytest.mark.parametrize("service_result", [None, {"status": "error", "message": "busy"}])
def test_playlist_detail_service_error_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
    service_result: object,
) -> None:
    async def fake_get_playlist_detail(**kwargs: object) -> object:
        return service_result

    monkeypatch.setattr(
        playlist_tools.playlist_service,
        "get_playlist_detail",
        fake_get_playlist_detail,
    )

    result = run_tool(songlist_id=301, page=3)

    assert result.ok is False
    assert result.code == ToolResultCode.UPSTREAM_ERROR
    assert result.retryable is True
    assert result.data == {"songlist_id": 301, "dirid": 0, "page": 3}


def test_playlist_detail_exception_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_playlist_detail(**kwargs: object) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        playlist_tools.playlist_service,
        "get_playlist_detail",
        fake_get_playlist_detail,
    )

    result = run_tool(dirid=42, page=2)

    assert result.ok is False
    assert result.code == ToolResultCode.UPSTREAM_ERROR
    assert result.retryable is True
    assert result.data == {"songlist_id": 0, "dirid": 42, "page": 2}


def test_playlist_detail_empty_page_is_successful_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_playlist_detail(**kwargs: object) -> dict:
        return {
            "status": "success",
            "total_song_num": 0,
            "playlist_info": {"title": "空歌单", "dirid": 42},
            "songlist": [],
        }

    monkeypatch.setattr(
        playlist_tools.playlist_service,
        "get_playlist_detail",
        fake_get_playlist_detail,
    )

    result = run_tool(dirid=42, num=20, page=1)
    artifact = PlaylistBrowserArtifact.model_validate(result.data)

    assert result.ok is True
    assert artifact.playlist_name == "空歌单"
    assert artifact.tracks == []
    assert artifact.page == 1
    assert artifact.page_size == 20
    assert artifact.total_song_num == 0
    assert artifact.has_more is False
