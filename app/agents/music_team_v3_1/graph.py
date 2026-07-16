from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.services.memory import DISABLED_PREFERENCES, PreferenceRepository

from .nodes import (
    chat_replier_node,
    finalizer_node,
    init_memory_node,
    intent_parser_node,
    memory_sync_node,
    music_ops_subgraph_node,
    playback_subgraph_node,
    route_after_supervisor,
    route_after_verifier,
    result_verifier_node,
    supervisor_router_node,
)
from .state import MusicGraphStateV31


def build_graph(
    *,
    checkpointer: Any = None,
    preference_repository: PreferenceRepository = DISABLED_PREFERENCES,
):
    """Build one graph with explicitly owned persistence dependencies."""
    builder = StateGraph(MusicGraphStateV31)

    builder.add_node(
        "init_memory",
        partial(init_memory_node, preference_repository=preference_repository),
    )
    builder.add_node("intent_parser", intent_parser_node)
    builder.add_node("supervisor_router", supervisor_router_node)
    builder.add_node("music_ops_subgraph", music_ops_subgraph_node)
    builder.add_node("playback_subgraph", playback_subgraph_node)
    builder.add_node("result_verifier", result_verifier_node)
    builder.add_node("memory_sync", memory_sync_node)
    builder.add_node("chat_replier", chat_replier_node)
    builder.add_node("finalizer", finalizer_node)

    builder.add_edge(START, "init_memory")
    builder.add_edge("init_memory", "intent_parser")
    builder.add_edge("intent_parser", "supervisor_router")
    builder.add_conditional_edges(
        "supervisor_router",
        route_after_supervisor,
        {
            "music_ops_subgraph": "music_ops_subgraph",
            "playback_subgraph": "playback_subgraph",
            "chat_replier": "chat_replier",
        },
    )

    builder.add_edge("music_ops_subgraph", "result_verifier")
    builder.add_edge("playback_subgraph", "result_verifier")
    builder.add_conditional_edges(
        "result_verifier",
        route_after_verifier,
        {
            "retry_music_ops": "music_ops_subgraph",
            "retry_playback": "playback_subgraph",
            "music_done": "chat_replier",
            "playback_done": "memory_sync",
        },
    )
    builder.add_edge("chat_replier", "memory_sync")
    builder.add_edge("memory_sync", "finalizer")
    builder.add_edge("finalizer", END)

    return builder.compile(
        checkpointer=checkpointer,
        name="MusicTeamGraphV31",
    )


# LangGraph Studio imports this stateless graph. FastAPI builds its own graph
# inside lifespan and never uses this instance for local chat requests.
graph = build_graph()
