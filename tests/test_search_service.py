import httpx
import pytest

from app.core.client import global_storage
from app.services.music.search_service import SearchService


@pytest.mark.asyncio
async def test_search_success():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        return httpx.Response(200, json={"result": 0, "data": {"list": []}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:3300") as client:
        global_storage.client = client
        service = SearchService()
        result = await service.search("test-key")

    assert result["result"] == 0
    assert result["data"]["list"] == []
