"""Task 01 failure tests: stable model config & error response contract.

All tests monkeypatch the graph — no real LLM or QQ Music calls.
"""

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

import app.api.v1.endpoints as endpoints
import main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    async def authenticated_user_id() -> str:
        return "error-test-user"

    monkeypatch.setattr(main, "STATE_DB_PATH", tmp_path / "errors.sqlite3")
    monkeypatch.setattr(endpoints, "get_authenticated_user_id", authenticated_user_id)
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# 1. Empty message → stable error
# ---------------------------------------------------------------------------


class TestEmptyMessage:
    def test_empty_string_returns_error(self, client):
        resp = client.post("/api/v1/chat/local", json={"message": ""})
        body = resp.json()
        assert resp.status_code in (400, 422)
        assert body["status"] == "error"
        assert "data" in body
        assert body["data"]["run"]["status"] == "failed"
        assert body["data"]["artifacts"] == []

    def test_whitespace_only_returns_error(self, client):
        resp = client.post("/api/v1/chat/local", json={"message": "   "})
        body = resp.json()
        assert resp.status_code in (400, 422)
        assert body["status"] == "error"
        assert "data" in body
        assert body["data"]["run"]["status"] == "failed"

    def test_missing_message_field_returns_error(self, client):
        resp = client.post("/api/v1/chat/local", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 2. Graph exception → 502 stable JSON, no traceback/secrets
# ---------------------------------------------------------------------------


class TestGraphException:
    def test_graph_raises_returns_502(self, client, monkeypatch):
        """monkeypatch graph.astream to raise — verify stable error response."""
        async def _boom(*args, **kwargs):
            yield {"init_memory": {}}
            raise RuntimeError("simulated LLM failure")

        client.app.state.music_graph = SimpleNamespace(astream=_boom)

        resp = client.post("/api/v1/chat/local", json={"message": "hello"})
        body = resp.json()

        assert resp.status_code == 502
        assert body["status"] == "error"
        assert body["data"]["run"]["status"] == "failed"
        assert body["data"]["artifacts"] == []
        assert "message" in body

    def test_graph_error_from_browser_origin_has_json_and_cors(self, client, monkeypatch):
        async def _boom(*args, **kwargs):
            yield {"init_memory": {}}
            raise RuntimeError("browser-visible failure")

        client.app.state.music_graph = SimpleNamespace(astream=_boom)

        resp = client.post(
            "/api/v1/chat/local",
            json={"message": "hello", "thread_id": "cors-thread"},
            headers={"Origin": "http://localhost:3000"},
        )
        body = resp.json()

        assert resp.status_code == 502
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert body["status"] == "error"
        assert body["data"]["thread_id"] == "cors-thread"
        assert body["data"]["run"]["status"] == "failed"
        assert body["data"]["run"]["error"]["code"] == "agent_upstream_error"
        assert body["data"]["artifacts"] == []

    def test_error_response_has_no_traceback(self, client, monkeypatch):
        """Error body must not contain Python traceback text."""
        async def _boom(*args, **kwargs):
            yield {"init_memory": {}}
            raise RuntimeError("SECRET_API_KEY=sk-12345 should not leak")

        client.app.state.music_graph = SimpleNamespace(astream=_boom)

        resp = client.post("/api/v1/chat/local", json={"message": "hi"})
        body = resp.json()
        body_str = str(body)

        assert "SECRET_API_KEY" not in body_str
        assert "sk-12345" not in body_str
        assert "Traceback" not in body_str
        assert "raise RuntimeError" not in body_str

    def test_error_response_preserves_thread_id(self, client, monkeypatch):
        async def _boom(*args, **kwargs):
            yield {"init_memory": {}}
            raise ValueError("boom")

        client.app.state.music_graph = SimpleNamespace(astream=_boom)

        resp = client.post(
            "/api/v1/chat/local",
            json={"message": "hi", "thread_id": "my-thread"},
        )
        body = resp.json()
        assert body["data"]["run"]["status"] == "failed"
        assert body["data"]["thread_id"] == "my-thread"


# ---------------------------------------------------------------------------
# 3. OPENAI_MODEL env var → llm0 model name
# ---------------------------------------------------------------------------


class TestModelConfig:
    def test_openai_model_env_used(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "custom-gpt-model")

        import importlib
        import app.agents.music_team_v3_1.config as cfg

        importlib.reload(cfg)

        assert cfg.SECONDARY_MODEL_NAME == "custom-gpt-model"
        assert cfg.llm0.model_name == "custom-gpt-model"

    def test_default_model_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("OPENAI_MODEL", raising=False)

        import importlib
        import app.agents.music_team_v3_1.config as cfg

        importlib.reload(cfg)

        assert cfg.SECONDARY_MODEL_NAME == "gpt-4o-mini"
