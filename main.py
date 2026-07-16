"""FastAPI entrypoint with process-owned SQLite persistence."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv


# LangGraph caches serializer settings during import. This guard must stay
# above every import that can reach LangGraph/checkpointer modules.
load_dotenv()
if os.getenv("LANGGRAPH_STRICT_MSGPACK", "").lower() != "true":
    raise RuntimeError("LANGGRAPH_STRICT_MSGPACK=true is required before startup")

import aiosqlite
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.music_team_v3_1 import build_graph
from app.agents.music_team_v3_1.config import STATE_DB_PATH
from app.api.v1.endpoints import router as api_v1_router
from app.services.memory import SQLitePreferenceRepository


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
logger = logging.getLogger("app.main")


async def configure_sqlite_connection(connection: aiosqlite.Connection) -> None:
    cursor = await connection.execute("PRAGMA journal_mode=WAL")
    await cursor.fetchone()
    await cursor.close()
    await connection.execute("PRAGMA busy_timeout=5000")
    await connection.execute("PRAGMA foreign_keys=ON")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.music_graph = None
    app.state.preference_repository = None
    STATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(str(STATE_DB_PATH)) as saver:
        await configure_sqlite_connection(saver.conn)
        # Public, read-only access triggers the saver's lazy schema setup
        # without creating a fake business checkpoint.
        await saver.aget_tuple(
            {"configurable": {"thread_id": "__startup_healthcheck__"}}
        )

        async with aiosqlite.connect(
            str(STATE_DB_PATH),
            isolation_level=None,
        ) as preference_connection:
            await configure_sqlite_connection(preference_connection)
            repository = SQLitePreferenceRepository(preference_connection)
            await repository.setup()
            persistent_graph = build_graph(
                checkpointer=saver,
                preference_repository=repository,
            )
            app.state.music_graph = persistent_graph
            app.state.preference_repository = repository
            try:
                yield
            finally:
                # Clear callable references before either owned connection is
                # allowed to leave its context.
                app.state.music_graph = None
                app.state.preference_repository = None


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_v1_router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
