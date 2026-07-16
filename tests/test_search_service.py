import importlib
from types import SimpleNamespace

import pytest
from qqmusic_api.modules.search import SearchType

from app.services.music.search_service import SearchService


search_service_module = importlib.import_module("app.services.music.search_service")


@pytest.mark.asyncio
async def test_search_by_type_cleans_song_results(monkeypatch) -> None:
    response = SimpleNamespace(
        song=[
            SimpleNamespace(
                name="晴天",
                singer=[SimpleNamespace(name="周杰伦")],
                album=SimpleNamespace(name="叶惠美"),
                id=1,
                mid="song-mid-1",
            )
        ]
    )

    class FakeSearch:
        async def search_by_type(self, **kwargs):
            assert kwargs["keyword"] == "周杰伦"
            assert kwargs["search_type"] == SearchType.SONG
            return response

    async def fake_create_client():
        return SimpleNamespace(search=FakeSearch())

    monkeypatch.setattr(search_service_module, "create_client", fake_create_client)

    result = await SearchService().search_by_type(
        keyword="周杰伦",
        search_type=SearchType.SONG,
        num=5,
    )

    assert result == {
        "status": "success",
        "data": [
            {
                "type": "song",
                "title": "晴天",
                "singer": "周杰伦",
                "album": "叶惠美",
                "id": 1,
                "mid": "song-mid-1",
            }
        ],
    }
