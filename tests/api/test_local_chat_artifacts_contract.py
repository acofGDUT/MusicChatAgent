"""Task 03 failure tests: artifacts & run status in /chat/local response.

All tests monkeypatch the graph — no real LLM or QQ Music calls.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

import app.api.v1.endpoints as endpoints
import main
from app.tools.tool_result import ToolResult


@pytest.fixture()
def client(tmp_path, monkeypatch):
    async def authenticated_user_id() -> str:
        return "artifact-test-user"

    monkeypatch.setattr(main, "STATE_DB_PATH", tmp_path / "artifacts.sqlite3")
    monkeypatch.setattr(endpoints, "get_authenticated_user_id", authenticated_user_id)
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def _make_fake_astream(messages_to_yield: list[dict]):
    """Build a fake graph.astream that yields given update dicts then stops."""

    async def _fake(*args, **kwargs):
        for update in messages_to_yield:
            yield update

    return _fake


def _install_graph(client: TestClient, updates: list[dict]) -> None:
    client.app.state.music_graph = SimpleNamespace(
        astream=_make_fake_astream(updates)
    )


# ---------------------------------------------------------------------------
# 1. Graph produces play_music artifact → API returns it
# ---------------------------------------------------------------------------


class TestArtifactsInSuccess:
    def test_play_music_artifact_returned(self, client, monkeypatch):
        play_payload = {
            "type": "play_music",
            "song_mid": "abc123",
            "title": "Test Song",
            "artist": "Singer",
            "url": "https://example.com/s.mp3",
            "cover": "",
            "description": "已获取播放链接",
        }

        fake_update = {
            "chat_replier": {
                "messages": [
                    AIMessage(
                        content=f"好的，为你播放 Test Song\n\n```json\n{json.dumps(play_payload, ensure_ascii=False)}\n```",
                        name="ChatReplier",
                        additional_kwargs={"user_visible": True},
                    )
                ]
            }
        }

        _install_graph(client, [fake_update])

        resp = client.post("/api/v1/chat/local", json={"message": "播放 Test Song"})
        body = resp.json()

        assert resp.status_code == 200
        assert body["status"] == "success"
        assert body["data"]["run"]["status"] == "succeeded"
        assert isinstance(body["data"]["artifacts"], list)
        assert len(body["data"]["artifacts"]) >= 1
        assert body["data"]["artifacts"][0]["type"] == "play_music"
        assert body["data"]["artifacts"][0]["song_mid"] == "abc123"

    def test_no_artifact_returns_empty_list(self, client, monkeypatch):
        fake_update = {
            "chat_replier": {
                "messages": [
                    AIMessage(
                        content="今天天气不错！",
                        name="ChatReplier",
                        additional_kwargs={"user_visible": True},
                    )
                ]
            }
        }

        _install_graph(client, [fake_update])

        resp = client.post("/api/v1/chat/local", json={"message": "你好"})
        body = resp.json()

        assert resp.status_code == 200
        assert body["data"]["artifacts"] == []
        assert body["data"]["run"]["status"] == "succeeded"

    def test_reply_empty_but_artifact_valid_is_success(self, client, monkeypatch):
        """Even when reply text is empty, a valid artifact makes it success."""
        play_payload = {
            "type": "play_music",
            "song_mid": "xyz",
            "title": "Song",
            "url": "https://x.com/s.mp3",
        }

        fake_update = {
            "music_ops_subgraph": {
                "messages": [
                    AIMessage(
                        content=json.dumps(play_payload, ensure_ascii=False),
                        name="MusicExecutor",
                    )
                ]
            }
        }

        _install_graph(client, [fake_update])

        resp = client.post("/api/v1/chat/local", json={"message": "播放"})
        body = resp.json()

        assert resp.status_code == 200
        assert body["data"]["run"]["status"] == "succeeded"
        assert len(body["data"]["artifacts"]) == 1

    def test_tool_message_artifact_survives_chat_replier_delta(self, client, monkeypatch):
        play_payload = {
            "type": "play_music",
            "song_mid": "tool-abc",
            "title": "Tool Song",
            "artist": "Singer",
            "url": "https://example.com/tool.mp3",
        }

        fake_updates = [
            {
                "music_ops_subgraph": {
                    "messages": [
                        ToolMessage(
                            content=ToolResult.success(
                                message="playback link ready",
                                data=play_payload,
                            ).to_json(),
                            tool_call_id="call-play-music",
                            name="play_music_tool",
                        ),
                        AIMessage(content="工具已返回播放链接", name="MusicExecutor"),
                    ]
                }
            },
            {
                "chat_replier": {
                    "messages": [
                        AIMessage(
                            content="好的，已为你准备播放。",
                            name="ChatReplier",
                            additional_kwargs={"user_visible": True},
                        ),
                    ]
                }
            },
        ]

        _install_graph(client, fake_updates)

        resp = client.post("/api/v1/chat/local", json={"message": "播放 Tool Song"})
        body = resp.json()

        assert resp.status_code == 200
        assert body["data"]["reply"] == "好的，已为你准备播放。"
        assert body["data"]["artifacts"] == [
            {
                "type": "play_music",
                "song_mid": "tool-abc",
                "title": "Tool Song",
                "artist": "Singer",
                "url": "https://example.com/tool.mp3",
                "cover": "",
                "description": "已获取播放链接",
            }
        ]


# ---------------------------------------------------------------------------
# 2. Error path also has artifacts=[] and run.status=failed
# ---------------------------------------------------------------------------


class TestArtifactsInError:
    def test_error_has_empty_artifacts_and_failed_run(self, client, monkeypatch):
        async def _boom(*args, **kwargs):
            yield {"init_memory": {}}
            raise RuntimeError("LLM exploded")

        client.app.state.music_graph = SimpleNamespace(astream=_boom)

        resp = client.post("/api/v1/chat/local", json={"message": "hi"})
        body = resp.json()

        assert resp.status_code == 502
        assert body["data"]["artifacts"] == []
        assert body["data"]["run"]["status"] == "failed"


# ---------------------------------------------------------------------------
# 3. Old reply and trace fields preserved
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_reply_and_trace_still_present(self, client, monkeypatch):
        fake_update = {
            "chat_replier": {
                "messages": [
                    AIMessage(
                        content="你好呀！",
                        name="ChatReplier",
                        additional_kwargs={"user_visible": True},
                    )
                ]
            }
        }

        _install_graph(client, [fake_update])

        resp = client.post("/api/v1/chat/local", json={"message": "你好"})
        body = resp.json()

        assert "reply" in body["data"]
        assert "trace" in body["data"]
        assert isinstance(body["data"]["trace"], list)
        assert body["data"]["reply"] == "你好呀！"
