from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

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

graph_builder = StateGraph(MusicGraphStateV31)

graph_builder.add_node("init_memory", init_memory_node)
graph_builder.add_node("intent_parser", intent_parser_node)
graph_builder.add_node("supervisor_router", supervisor_router_node)
graph_builder.add_node("music_ops_subgraph", music_ops_subgraph_node)
graph_builder.add_node("playback_subgraph", playback_subgraph_node)
graph_builder.add_node("result_verifier", result_verifier_node)
graph_builder.add_node("memory_sync", memory_sync_node)
graph_builder.add_node("chat_replier", chat_replier_node)
graph_builder.add_node("finalizer", finalizer_node)

graph_builder.add_edge(START, "init_memory")
graph_builder.add_edge("init_memory", "intent_parser")
graph_builder.add_edge("intent_parser", "supervisor_router")

graph_builder.add_conditional_edges(
    "supervisor_router",
    route_after_supervisor,
    {
        "music_ops_subgraph": "music_ops_subgraph",
        "playback_subgraph": "playback_subgraph",
        "chat_replier": "chat_replier",
    },
)

graph_builder.add_edge("music_ops_subgraph", "result_verifier")
graph_builder.add_edge("playback_subgraph", "result_verifier")
graph_builder.add_conditional_edges(
    "result_verifier",
    route_after_verifier,
    {
        "retry_music_ops": "music_ops_subgraph",
        "retry_playback": "playback_subgraph",
        "music_done": "memory_sync",
        "playback_done": "finalizer",
    },
)
graph_builder.add_edge("memory_sync", "chat_replier")
graph_builder.add_edge("chat_replier", "finalizer")
graph_builder.add_edge("finalizer", END)

checkpointer = InMemorySaver()
graph = graph_builder.compile(checkpointer=checkpointer, name="MusicTeamGraphV31")
