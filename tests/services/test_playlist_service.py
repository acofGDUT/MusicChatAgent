import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.music.playlist_service import PlaylistService

playlist_service_module = importlib.import_module("app.services.music.playlist_service")


class FakePaginatedRequest:
    def __init__(self, *, detail: Any = None, pages: list[Any] | None = None) -> None:
        self.detail = detail
        self.pages = pages or []
        self.paginate_calls = 0

    def __await__(self):
        async def resolve() -> Any:
            return self.detail

        return resolve().__await__()

    def paginate(self):
        self.paginate_calls += 1

        async def iterate_pages():
            for page in self.pages:
                yield page

        return iterate_pages()


class FakeGetDetail:
    def __init__(self, *, detail: Any = None, pages: list[Any] | None = None) -> None:
        self.detail = detail
        self.pages = pages or []
        self.detail_calls: list[dict[str, Any]] = []
        self.requests: list[FakePaginatedRequest] = []

    def __call__(self, **kwargs: Any) -> FakePaginatedRequest:
        self.detail_calls.append(kwargs)
        request = FakePaginatedRequest(detail=self.detail, pages=self.pages)
        self.requests.append(request)
        return request


class FakeClient:
    def __init__(self, get_detail: FakeGetDetail) -> None:
        self.songlist = SimpleNamespace(get_detail=get_detail)

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


def make_song(*, song_id: int, mid: str, title: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=song_id,
        mid=mid,
        title=title,
        name=title,
        singer=[SimpleNamespace(name="周杰伦")],
        album=SimpleNamespace(title="叶惠美"),
        time_public="2003-07-31",
    )


def install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    get_detail: FakeGetDetail,
) -> None:
    async def fake_create_client() -> FakeClient:
        return FakeClient(get_detail)

    monkeypatch.setattr(playlist_service_module, "create_client", fake_create_client)


def test_get_all_songs_supports_dirid_without_songlist_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_detail = FakeGetDetail(
        pages=[
            SimpleNamespace(
                songs=[make_song(song_id=101, mid="mid-101", title="晴天")],
            ),
            SimpleNamespace(
                songs=[make_song(song_id=102, mid="mid-102", title="七里香")],
            ),
        ],
    )
    install_fake_client(monkeypatch, get_detail)

    result = asyncio.run(
        PlaylistService().get_all_songs_in_playlist(songlist_id=0, dirid=201)
    )

    assert result == [
        {"id": 101, "mid": "mid-101", "title": "晴天"},
        {"id": 102, "mid": "mid-102", "title": "七里香"},
    ]
    assert get_detail.detail_calls == [
        {
            "songlist_id": 0,
            "dirid": 201,
            "num": 100,
            "onlysong": True,
            "tag": False,
            "userinfo": False,
        }
    ]
    assert get_detail.requests[0].paginate_calls == 1


def test_get_all_songs_rejects_missing_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called() -> FakeClient:
        raise AssertionError("create_client should not be called")

    monkeypatch.setattr(playlist_service_module, "create_client", fail_if_called)

    result = asyncio.run(PlaylistService().get_all_songs_in_playlist())

    assert result == []


def test_get_playlist_detail_slim_song_includes_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    song = make_song(song_id=101, mid="mid-101", title="晴天")
    detail = SimpleNamespace(
        total=1,
        songs=[song],
        info=SimpleNamespace(
            title="夜跑",
            desc="适合夜跑",
            creator=SimpleNamespace(nick="tester"),
            dirid=201,
            id=301,
        ),
    )
    get_detail = FakeGetDetail(detail=detail)
    install_fake_client(monkeypatch, get_detail)

    result = asyncio.run(
        PlaylistService().get_playlist_detail(
            songlist_id=0,
            dirid=201,
            num=10,
            page=1,
        )
    )

    assert result["status"] == "success"
    assert result["songlist"][0]["id"] == 101
    assert result["songlist"][0]["mid"] == "mid-101"
    assert result["songlist"][0]["title"] == "晴天"
