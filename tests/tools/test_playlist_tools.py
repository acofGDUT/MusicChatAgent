import asyncio

import pytest

from app.tools import playlist_tools
from app.tools.tool_result import ToolResult, ToolResultCode


def run_tool(tool: object, **kwargs: object) -> ToolResult:
    raw = asyncio.run(tool.ainvoke(kwargs))
    return ToolResult.model_validate_json(raw)


def test_create_playlist_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create(name: str) -> dict:
        return {"id": 99, "dirid": 201, "name": name}

    monkeypatch.setattr(playlist_tools.playlist_service, "create_playlist", fake_create)

    result = run_tool(playlist_tools.create_playlist_tool, name=" 夜跑 ")

    assert result.ok is True
    assert result.data["playlist"] == {"id": 99, "dirid": 201, "name": "夜跑"}


def test_create_playlist_rejects_empty_name() -> None:
    result = run_tool(playlist_tools.create_playlist_tool, name=" ")

    assert result.code == ToolResultCode.INVALID_ARGUMENT


@pytest.mark.parametrize("service_result", [None, {}, {"error": "failed"}, {"dirid": "bad"}])
def test_create_playlist_uncertain_result(monkeypatch: pytest.MonkeyPatch, service_result: object) -> None:
    async def fake_create(name: str) -> object:
        return service_result

    monkeypatch.setattr(playlist_tools.playlist_service, "create_playlist", fake_create)

    result = run_tool(playlist_tools.create_playlist_tool, name="夜跑")

    assert result.code == ToolResultCode.WRITE_UNCERTAIN
    assert result.retryable is False


def test_create_playlist_exception_is_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create(name: str) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(playlist_tools.playlist_service, "create_playlist", fake_create)

    result = run_tool(playlist_tools.create_playlist_tool, name="夜跑")

    assert result.code == ToolResultCode.WRITE_UNCERTAIN


def test_add_songs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_add(song_ids: list[int], dirid: int) -> bool:
        return True

    monkeypatch.setattr(playlist_tools.playlist_service, "add_songs_to_playlist", fake_add)

    result = run_tool(playlist_tools.add_songs_to_playlist_tool, song_ids=[1, 2], dirid=201)

    assert result.ok is True
    assert result.data["requested_count"] == 2


def test_add_songs_false_is_never_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_add(song_ids: list[int], dirid: int) -> bool:
        return False

    monkeypatch.setattr(playlist_tools.playlist_service, "add_songs_to_playlist", fake_add)

    result = run_tool(playlist_tools.add_songs_to_playlist_tool, song_ids=[1], dirid=201)

    assert result.ok is False
    assert result.code == ToolResultCode.WRITE_UNCERTAIN


def test_add_songs_exception_is_never_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_add(song_ids: list[int], dirid: int) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(playlist_tools.playlist_service, "add_songs_to_playlist", fake_add)

    result = run_tool(playlist_tools.add_songs_to_playlist_tool, song_ids=[1], dirid=201)

    assert result.ok is False
    assert result.code == ToolResultCode.WRITE_UNCERTAIN
    assert result.retryable is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"song_ids": [], "dirid": 201},
        {"song_ids": [1], "dirid": 0},
    ],
)
def test_add_songs_rejects_invalid_arguments(kwargs: dict[str, object]) -> None:
    result = run_tool(playlist_tools.add_songs_to_playlist_tool, **kwargs)

    assert result.code == ToolResultCode.INVALID_ARGUMENT


@pytest.mark.parametrize(
    ("service_result", "expected_code"),
    [
        ({"status": "success", "added_count": 2, "added_song_ids": [1, 2]}, ToolResultCode.SUCCESS),
        ({"status": "success", "added_count": 0}, ToolResultCode.NOT_FOUND),
        ({"status": "partial", "added_count": 1, "added_song_ids": [1]}, ToolResultCode.PARTIAL_SUCCESS),
        ({"status": "partial", "added_count": 0, "candidate_song_ids": [1]}, ToolResultCode.WRITE_UNCERTAIN),
        ({"status": "error", "message": "failed"}, ToolResultCode.UPSTREAM_ERROR),
    ],
)
def test_add_by_keyword_status_mapping(
    monkeypatch: pytest.MonkeyPatch,
    service_result: dict,
    expected_code: ToolResultCode,
) -> None:
    async def fake_add_by_keyword(**kwargs: object) -> dict:
        return service_result

    monkeypatch.setattr(
        playlist_tools.playlist_service,
        "add_songs_by_keyword_to_playlist",
        fake_add_by_keyword,
    )

    result = run_tool(
        playlist_tools.add_by_keyword_to_playlist_tool,
        playlist_name="夜跑",
        keyword="周杰伦",
        target_count=2,
        search_page_size=20,
        max_expand_rounds=5,
    )

    assert result.code == expected_code


def test_add_by_keyword_exception_is_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_add_by_keyword(**kwargs: object) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        playlist_tools.playlist_service,
        "add_songs_by_keyword_to_playlist",
        fake_add_by_keyword,
    )

    result = run_tool(
        playlist_tools.add_by_keyword_to_playlist_tool,
        playlist_name="夜跑",
        keyword="周杰伦",
        target_count=2,
        search_page_size=20,
        max_expand_rounds=5,
    )

    assert result.code == ToolResultCode.WRITE_UNCERTAIN
    assert result.retryable is False
