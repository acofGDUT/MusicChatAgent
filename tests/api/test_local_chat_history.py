import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import app.api.v1.endpoints as endpoints
from app.core.auth import AuthenticationRequiredError, AuthenticationUnavailableError
import main


class FakeGraph:
    def __init__(self, *, snapshot=None, events=None, error=None) -> None:
        self.snapshot = snapshot or SimpleNamespace(values={}, created_at=None)
        self.events = events or []
        self.error = error
        self.configs = []

    async def aget_state(self, config):
        self.configs.append(config)
        if self.error:
            raise self.error
        return self.snapshot

    async def astream(self, input_state, *, config, stream_mode):
        self.configs.append(config)
        if self.error:
            raise self.error
        for event in self.events:
            yield event


def _authenticate(monkeypatch, user_id: str = "10001") -> None:
    async def fake_user_id() -> str:
        return user_id

    monkeypatch.setattr(endpoints, "get_authenticated_user_id", fake_user_id)


def test_history_reads_complete_visible_checkpoint_messages(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "STATE_DB_PATH", tmp_path / "history.sqlite3")
    _authenticate(monkeypatch)
    long_content = "长内容" * 150
    visible = AIMessage(
        content=long_content,
        name="ChatReplier",
        additional_kwargs={"user_visible": True, "created_at_ms": 200},
    )
    fake = FakeGraph(
        snapshot=SimpleNamespace(
            values={
                "messages": [
                    HumanMessage(content="再来一首", additional_kwargs={"created_at_ms": 100}),
                    HumanMessage(content="再来一首", additional_kwargs={"created_at_ms": True}),
                    AIMessage(content="内部", name="MusicExecutor"),
                    ToolMessage(content="工具", tool_call_id="call-1"),
                    visible,
                ]
            },
            created_at="2026-07-15T00:00:00+00:00",
        )
    )
    with TestClient(main.app) as client:
        main.app.state.music_graph = fake
        first = client.get("/api/v1/chat/local/history?thread_id=thread-1&limit=3")
        second = client.get("/api/v1/chat/local/history?thread_id=thread-1&limit=2")

    assert first.status_code == 200
    messages = first.json()["data"]["messages"]
    assert [item["content"] for item in messages] == ["再来一首", "再来一首", long_content]
    assert messages[0]["ts"] < messages[1]["ts"] < messages[2]["ts"]
    assert second.json()["data"]["messages"] == messages[-2:]
    assert fake.configs[0]["configurable"]["thread_id"].startswith("music:")
    assert "10001" not in fake.configs[0]["configurable"]["thread_id"]


def test_history_storage_failure_is_503(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "STATE_DB_PATH", tmp_path / "history-error.sqlite3")
    _authenticate(monkeypatch)
    with TestClient(main.app) as client:
        main.app.state.music_graph = FakeGraph(error=sqlite3.OperationalError("private path"))
        response = client.get("/api/v1/chat/local/history")
    assert response.status_code == 503
    assert "private path" not in response.text


def test_post_rejects_client_user_id_and_invalid_thread(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "STATE_DB_PATH", tmp_path / "validation.sqlite3")
    _authenticate(monkeypatch)
    with TestClient(main.app) as client:
        assert client.post(
            "/api/v1/chat/local",
            json={"message": "你好", "thread_id": "ok", "user_id": "attacker"},
        ).status_code == 422
        assert client.post(
            "/api/v1/chat/local", json={"message": "你好", "thread_id": " bad"}
        ).status_code == 400


def test_post_only_returns_trusted_visible_reply(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "STATE_DB_PATH", tmp_path / "post.sqlite3")
    _authenticate(monkeypatch)
    messages = [
        HumanMessage(content="搜索歌"),
        AIMessage(content="内部执行", name="MusicExecutor"),
        AIMessage(
            content="最终回复",
            name="ChatReplier",
            additional_kwargs={"user_visible": True, "created_at_ms": 300},
        ),
    ]
    fake = FakeGraph(events=[{"chat_replier": {"messages": messages}}])
    with TestClient(main.app) as client:
        main.app.state.music_graph = fake
        response = client.post("/api/v1/chat/local", json={"message": "搜索歌"})
    assert response.status_code == 200
    assert response.json()["data"]["reply"] == "最终回复"


def test_post_without_visible_reply_is_safe_500(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "STATE_DB_PATH", tmp_path / "no-reply.sqlite3")
    _authenticate(monkeypatch)
    fake = FakeGraph(
        events=[{"music_ops_subgraph": {"messages": [AIMessage(content="内部", name="MusicExecutor")]}}]
    )
    with TestClient(main.app) as client:
        main.app.state.music_graph = fake
        response = client.post("/api/v1/chat/local", json={"message": "搜索歌"})
    assert response.status_code == 500
    assert "内部" not in response.text


def test_authentication_errors_map_to_safe_status_codes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "STATE_DB_PATH", tmp_path / "auth-errors.sqlite3")

    async def missing() -> str:
        raise AuthenticationRequiredError("private")

    monkeypatch.setattr(endpoints, "get_authenticated_user_id", missing)
    with TestClient(main.app) as client:
        response = client.get("/api/v1/chat/local/history")
    assert response.status_code == 401
    assert response.json()["detail"] == "请先登录 QQ 音乐"

    async def unavailable() -> str:
        raise AuthenticationUnavailableError("private credential path")

    monkeypatch.setattr(endpoints, "get_authenticated_user_id", unavailable)
    with TestClient(main.app) as client:
        response = client.get("/api/v1/chat/local/history")
    assert response.status_code == 503
    assert response.json()["detail"] == "认证状态暂时不可用"
    assert "private credential path" not in response.text
