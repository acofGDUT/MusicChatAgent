import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.music_team_v3_1 import build_graph, nodes
from app.agents.music_team_v3_1.nodes import memory_sync_node, result_verifier_node
from app.agents.music_team_v3_1.utils import (
    build_runtime_messages,
    is_user_visible_ai_message,
    sanitize_ai_message_metadata,
)
from app.tools.tool_result import ToolResult, ToolResultCode


def test_all_terminal_paths_have_one_post_reply_memory_sync() -> None:
    edges = build_graph().get_graph().edges
    pairs = {(edge.source, edge.target) for edge in edges}
    assert ("chat_replier", "memory_sync") in pairs
    assert ("memory_sync", "finalizer") in pairs
    assert ("result_verifier", "memory_sync") in pairs
    assert ("result_verifier", "chat_replier") in pairs
    assert not any(edge.source == "memory_sync" and edge.conditional for edge in edges)
    assert sum(edge.source == "memory_sync" for edge in edges) == 1


def test_incremental_summary_never_deletes_checkpoint_messages(monkeypatch) -> None:
    class FakeLLM:
        def invoke(self, prompt):
            assert "旧摘要" in prompt
            return AIMessage(content="新摘要")

    monkeypatch.setattr(nodes, "llm0", FakeLLM())
    monkeypatch.setattr(nodes, "SUMMARY_TRIGGER_TOKENS", 1)
    messages = [HumanMessage(content="新增内容"), AIMessage(content="回复")]
    state = {
        "messages": messages,
        "memory": {"summary": "旧摘要", "summary_version": 2, "summary_message_count": 0},
    }
    output = memory_sync_node(state)
    assert output["messages"] is messages
    assert [message.content for message in output["messages"]] == ["新增内容", "回复"]
    assert output["memory"]["summary"] == "新摘要"
    assert output["memory"]["summary_version"] == 3
    assert output["memory"]["summary_message_count"] == 2


def test_runtime_keeps_all_unsummarized_delta() -> None:
    messages = [HumanMessage(content=f"message-{index}") for index in range(20)]
    state = {
        "messages": messages,
        "memory": {"summary": "旧摘要", "summary_message_count": 2},
    }
    runtime = build_runtime_messages(state, role="intent_parser")
    assert [message.content for message in runtime] == [
        f"message-{index}" for index in range(2, 20)
    ]


def test_model_cannot_spoof_visibility_metadata() -> None:
    message = AIMessage(
        content="内部",
        name="MusicExecutor",
        additional_kwargs={"user_visible": True, "created_at_ms": 123},
    )
    clean = sanitize_ai_message_metadata(message, name="MusicExecutor")
    assert clean.additional_kwargs == {}
    assert not is_user_visible_ai_message(clean)


def test_terminal_playback_failure_is_the_only_visible_attempt() -> None:
    original = ToolResult.failure(
        code=ToolResultCode.UPSTREAM_ERROR,
        message="播放上游暂时不可用",
        retryable=False,
    )
    first_attempt = AIMessage(content="第一次临时输出", name="PlayAgent", id="first")
    final_attempt = AIMessage(content="无关模型文本", name="PlayAgent", id="final")
    state = {
        "messages": [HumanMessage(content="播放晴天"), first_attempt, final_attempt],
        "task": {"intent": "playback", "status": "failed"},
        "control": {"retry_count": 1, "verifier_route": "retry_playback"},
        "extensions": {
            "last_tool_result": original.model_dump(mode="json"),
            "retry_original_result": original.model_dump(mode="json"),
            "current_tool_run": [],
        },
    }
    output = asyncio.run(result_verifier_node(state))
    visible = [message for message in output["messages"] if is_user_visible_ai_message(message)]
    assert len(visible) == 1
    assert visible[0].id == "final"
    assert visible[0].content == "播放上游暂时不可用"
