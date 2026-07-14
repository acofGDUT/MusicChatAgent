import asyncio
import json
import os

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute


# The endpoints module imports the compiled graph, which constructs model clients at
# import time. Keep that import deterministic and offline for this test module.
os.environ.setdefault("OPENAI_API_BASE", "http://localhost:9999/v1")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("MUSIC_AGENT_BASE_URL", "http://localhost:9998/v1")
os.environ.setdefault("MUSIC_AGENT_API_KEY", "test-key")

from app.api.v1 import endpoints
from app.schemas import PlayMusicArtifact, PlaylistBrowserArtifact


def run(coro):
    return asyncio.run(coro)


def test_play_url_success_uses_schema_and_title_fallback(monkeypatch) -> None:
    async def fake_get_playable_url(song_mid: str) -> str:
        assert song_mid == "mid-1"
        return "https://example.com/mid-1.mp3"

    async def fake_get_song_cover(song_mid: str, size: int) -> str:
        assert (song_mid, size) == ("mid-1", 300)
        return "https://example.com/mid-1.jpg"

    monkeypatch.setattr(
        endpoints.song_service, "get_playable_url", fake_get_playable_url
    )
    monkeypatch.setattr(endpoints.song_service, "get_song_cover", fake_get_song_cover)

    result = run(
        endpoints.get_play_url_by_song_mid(
            song_mid=" mid-1 ",
            title="",
            artist=" 周杰伦 ",
        )
    )

    assert isinstance(result, PlayMusicArtifact)
    assert PlayMusicArtifact.model_validate(result.model_dump()) == result
    assert result.model_dump(mode="json") == {
        "type": "play_music",
        "song_mid": "mid-1",
        "title": "未知歌曲",
        "artist": "周杰伦",
        "url": "https://example.com/mid-1.mp3",
        "cover": "https://example.com/mid-1.jpg",
        "description": "已获取播放链接",
    }


def test_play_url_without_playable_url_raises_404_and_skips_cover(monkeypatch) -> None:
    async def fake_get_playable_url(song_mid: str) -> None:
        assert song_mid == "blocked-mid"
        return None

    async def fail_if_cover_requested(*args, **kwargs):
        raise AssertionError("cover lookup must not run when no playable URL exists")

    monkeypatch.setattr(
        endpoints.song_service, "get_playable_url", fake_get_playable_url
    )
    monkeypatch.setattr(
        endpoints.song_service, "get_song_cover", fail_if_cover_requested
    )

    with pytest.raises(HTTPException) as exc_info:
        run(
            endpoints.get_play_url_by_song_mid(
                song_mid="blocked-mid",
                title="",
                artist="",
            )
        )

    assert exc_info.value.status_code == 404
    assert "无法获取播放链接" in str(exc_info.value.detail)


def test_playlist_page_success_is_schema_compatible(monkeypatch) -> None:
    async def fake_get_playlist_detail(**kwargs):
        assert kwargs == {
            "dirid": 42,
            "page": 2,
            "num": 2,
            "onlysong": False,
        }
        return {
            "status": "success",
            "total_song_num": 5,
            "playlist_info": {"title": "通勤歌单"},
            "songlist": [
                {
                    "mid": "mid-3",
                    "title": "晴天",
                    "singer": "周杰伦",
                },
                {
                    "mid": "mid-4",
                    "title": "夜曲",
                    "singer": "周杰伦",
                },
            ],
        }

    monkeypatch.setattr(
        endpoints.playlist_service,
        "get_playlist_detail",
        fake_get_playlist_detail,
    )

    result = run(
        endpoints.get_playlist_browser_page(
            dirid=42,
            page=2,
            page_size=2,
            playlist_name="",
        )
    )

    assert isinstance(result, PlaylistBrowserArtifact)
    assert PlaylistBrowserArtifact.model_validate(result.model_dump()) == result
    assert result.playlist_name == "通勤歌单"
    assert result.total_song_num == 5
    assert result.has_more is True
    assert [track.index for track in result.tracks] == [3, 4]
    assert [track.song_mid for track in result.tracks] == ["mid-3", "mid-4"]


def test_playlist_invalid_dirid_raises_http_exception_without_service_call(
    monkeypatch,
) -> None:
    async def fail_if_called(**kwargs):
        raise AssertionError("invalid dirid must be rejected before service lookup")

    monkeypatch.setattr(
        endpoints.playlist_service,
        "get_playlist_detail",
        fail_if_called,
    )

    with pytest.raises(HTTPException) as exc_info:
        run(
            endpoints.get_playlist_browser_page(
                dirid=0,
                page=1,
                page_size=10,
                playlist_name="",
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "dirid 必须大于 0"


def test_playlist_service_error_becomes_http_exception(monkeypatch) -> None:
    async def fake_get_playlist_detail(**kwargs):
        return {"status": "error", "message": "上游歌单服务不可用"}

    monkeypatch.setattr(
        endpoints.playlist_service,
        "get_playlist_detail",
        fake_get_playlist_detail,
    )

    with pytest.raises(HTTPException) as exc_info:
        run(
            endpoints.get_playlist_browser_page(
                dirid=42,
                page=1,
                page_size=10,
                playlist_name="",
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "上游歌单服务不可用"


def test_artifact_routes_publish_pydantic_response_models() -> None:
    routes = {
        route.path: route
        for route in endpoints.router.routes
        if isinstance(route, APIRoute)
    }

    assert routes["/song/play-url"].response_model is PlayMusicArtifact
    assert (
        routes["/playlist/{dirid}/tracks"].response_model
        is PlaylistBrowserArtifact
    )


def test_result_verifier_trace_summary_is_structured_and_complete() -> None:
    assert "result_verifier" in endpoints.TRACE_NODE_NAMES

    summary = endpoints._build_non_llm_trace_summary(
        "result_verifier",
        {
            "task": {"status": "running"},
            "control": {
                "retry_count": 1,
                "verifier_route": "retry_playback",
            },
            "extensions": {
                "verification": {
                    "status": "failed",
                    "code": "UPSTREAM_ERROR",
                    "retry_scheduled": True,
                    "retry_count": 1,
                }
            },
        },
    )

    assert json.loads(summary) == {
        "verification_status": "failed",
        "verification_code": "UPSTREAM_ERROR",
        "retry_scheduled": True,
        "retry_count": 1,
        "verifier_route": "retry_playback",
    }
    assert endpoints._extract_trace_content(
        "result_verifier",
        {
            "control": {"verifier_route": "playback_done"},
            "extensions": {
                "verification": {
                    "status": "success",
                    "code": "SUCCESS",
                    "retry_scheduled": False,
                    "retry_count": 0,
                }
            },
        },
    ) == json.dumps(
        {
            "verification_status": "success",
            "verification_code": "SUCCESS",
            "retry_scheduled": False,
            "retry_count": 0,
            "verifier_route": "playback_done",
        },
        ensure_ascii=False,
    )
