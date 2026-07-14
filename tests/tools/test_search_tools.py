import asyncio

import pytest

from app.tools import search_tools
from app.tools.tool_result import ToolResult, ToolResultCode


def run_search(**kwargs: object) -> ToolResult:
    raw = asyncio.run(search_tools.search_music_tool.ainvoke(kwargs))
    return ToolResult.model_validate_json(raw)


def test_search_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_by_type(**kwargs: object) -> dict:
        return {"status": "success", "data": [{"id": 1, "mid": "mid-1", "title": "晴天"}]}

    monkeypatch.setattr(search_tools.search_service, "search_by_type", fake_search_by_type)

    result = run_search(keyword=" 周杰伦 ", search_type="song", num=5)

    assert result.ok is True
    assert result.data["keyword"] == "周杰伦"
    assert result.data["search_type"] == "SONG"
    assert result.data["items"][0]["index"] == 1


def test_search_rejects_empty_keyword() -> None:
    result = run_search(keyword="  ", search_type="SONG", num=5)

    assert result.code == ToolResultCode.INVALID_ARGUMENT


def test_search_rejects_invalid_type() -> None:
    result = run_search(keyword="周杰伦", search_type="VIDEO", num=5)

    assert result.code == ToolResultCode.INVALID_ARGUMENT


def test_search_empty_result_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_by_type(**kwargs: object) -> dict:
        return {"status": "success", "data": []}

    monkeypatch.setattr(search_tools.search_service, "search_by_type", fake_search_by_type)

    result = run_search(keyword="不存在的歌", search_type="SONG", num=5)

    assert result.code == ToolResultCode.NOT_FOUND
    assert result.data["items"] == []


def test_search_service_error_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_by_type(**kwargs: object) -> dict:
        return {"status": "error", "message": "network"}

    monkeypatch.setattr(search_tools.search_service, "search_by_type", fake_search_by_type)

    result = run_search(keyword="周杰伦", search_type="SONG", num=5)

    assert result.code == ToolResultCode.UPSTREAM_ERROR
    assert result.retryable is True


def test_search_unexpected_exception_is_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search_by_type(**kwargs: object) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(search_tools.search_service, "search_by_type", fake_search_by_type)

    result = run_search(keyword="周杰伦", search_type="SONG", num=5)

    assert result.code == ToolResultCode.INTERNAL_ERROR
