import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Annotated, TypedDict

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


class MinimalState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    summary: str
    extensions: dict


def _minimal_graph(checkpointer):
    builder = StateGraph(MinimalState)
    builder.add_node("identity", lambda state: {})
    builder.add_edge(START, "identity")
    builder.add_edge("identity", END)
    return builder.compile(checkpointer=checkpointer)


def test_sqlite_checkpoint_survives_reopen(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "checkpoint.sqlite3"
        config = {"configurable": {"thread_id": "music:test"}}
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            graph = _minimal_graph(saver)
            assert isinstance(graph.checkpointer, AsyncSqliteSaver)
            assert graph.checkpointer.conn is saver.conn
            await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="你好")],
                    "summary": "摘要",
                    "extensions": {"last_search_results": {"items": [1]}},
                },
                config=config,
            )

        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            graph = _minimal_graph(saver)
            snapshot = await graph.aget_state(config)
            assert snapshot.values["messages"][0].content == "你好"
            assert snapshot.values["summary"] == "摘要"
            assert snapshot.values["extensions"]["last_search_results"] == {"items": [1]}
            missing = await graph.aget_state(
                {"configurable": {"thread_id": "music:other"}}
            )
            assert not missing.values

    asyncio.run(scenario())


def test_fastapi_lifespan_owns_two_connections(tmp_path, monkeypatch) -> None:
    import main

    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setattr(main, "STATE_DB_PATH", db_path)
    with TestClient(main.app):
        graph = main.app.state.music_graph
        repository = main.app.state.preference_repository
        assert graph is not None
        assert repository is not None

        async def verify_pragmas() -> None:
            for connection in (repository._connection, graph.checkpointer.conn):
                cursor = await connection.execute("PRAGMA journal_mode")
                assert (await cursor.fetchone())[0].lower() == "wal"
                cursor = await connection.execute("PRAGMA busy_timeout")
                assert (await cursor.fetchone())[0] == 5000
                cursor = await connection.execute("PRAGMA foreign_keys")
                assert (await cursor.fetchone())[0] == 1

        asyncio.run(verify_pragmas())
        preference_connection = repository._connection
        checkpoint_connection = graph.checkpointer.conn

    assert main.app.state.music_graph is None
    assert main.app.state.preference_repository is None
    async def assert_closed() -> None:
        for connection in (preference_connection, checkpoint_connection):
            with pytest.raises(ValueError):
                await connection.execute("SELECT 1")

    asyncio.run(assert_closed())
    with sqlite3.connect(db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?",
            ("__startup_healthcheck__",),
        ).fetchone()[0]
        assert count == 0


def test_main_import_requires_strict_msgpack() -> None:
    env = os.environ.copy()
    env.pop("LANGGRAPH_STRICT_MSGPACK", None)
    env["PYTHON_DOTENV_DISABLED"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "LANGGRAPH_STRICT_MSGPACK=true is required" in result.stderr


def test_relative_database_path_is_repository_relative(tmp_path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["LANGGRAPH_STRICT_MSGPACK"] = "true"
    env["MUSIC_AGENT_STATE_DB"] = "relative/state.sqlite3"
    env["PYTHONPATH"] = str(repository_root)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.agents.music_team_v3_1.config import STATE_DB_PATH; print(STATE_DB_PATH)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert Path(result.stdout.strip()) == repository_root / "relative" / "state.sqlite3"
