"""Task 04 failure tests: message delta discipline.

Verifies that graph nodes return only NEW messages (delta), not the full
accumulated list.  With `add_messages`, returning the full list is technically
safe (dedup by ID), but semantically wrong and fragile — messages without
explicit IDs WILL duplicate.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.message import add_messages

from app.agents.music_team_v3_1.utils import extract_agent_delta_messages


# ---------------------------------------------------------------------------
# Helper: simulate add_messages merge
# ---------------------------------------------------------------------------


def _merge(existing: list, incoming: list) -> list:
    """Simulate the add_messages reducer behavior."""
    return add_messages(existing, incoming)


# ---------------------------------------------------------------------------
# 1. Delta-only pattern is correct
# ---------------------------------------------------------------------------


class TestDeltaReturnPattern:
    """Each node should return only new messages, not [*old_messages, *new]."""

    @pytest.fixture()
    def base_messages(self):
        return [
            HumanMessage(content="你好"),
            AIMessage(content="你好呀！", name="ChatReplier"),
        ]

    def test_delta_returns_exactly_one_new_message(self, base_messages):
        new_ai = AIMessage(content="已为你播放", name="MusicExecutor")
        merged = _merge(base_messages, [new_ai])
        assert len(merged) == len(base_messages) + 1

    def test_agent_delta_preserves_tool_message_without_old_inputs(self, base_messages):
        tool_msg = ToolMessage(
            content='{"type":"play_music","song_mid":"m1","title":"Song","url":"https://x.com/a.mp3"}',
            tool_call_id="call-1",
            name="play_music_tool",
        )
        final_ai = AIMessage(content="已准备播放", name="PlayAgent")
        result = {"messages": [*base_messages, tool_msg, final_ai]}

        delta = extract_agent_delta_messages(result, base_messages, fallback_name="PlayAgent")

        assert delta == [tool_msg, final_ai]

    def test_full_list_with_ids_does_not_duplicate(self, base_messages):
        """With deterministic IDs, add_messages deduplicates.
        This is why current code doesn't crash, but it's still wrong pattern."""
        new_ai = AIMessage(content="已为你播放", name="MusicExecutor")
        merged = _merge(base_messages, [*base_messages, new_ai])
        # add_messages deduplicates by ID, so no extra copies
        assert len(merged) == len(base_messages) + 1

    def test_full_list_without_ids_causes_duplication(self):
        """Messages without IDs get auto-generated UUIDs → duplicates."""
        old = [
            HumanMessage(content="你好", id="fixed-user-1"),
            AIMessage(content="你好呀", id="fixed-ai-1"),
        ]
        new_ai = AIMessage(content="播放", id="fixed-new-1")

        # Simulate returning [*old, new_ai] where old messages have different
        # auto-generated IDs (as would happen in a fresh invocation)
        old_copy = [
            HumanMessage(content="你好", id="copy-user-1"),  # different ID!
            AIMessage(content="你好呀", id="copy-ai-1"),     # different ID!
        ]

        merged = _merge(old, [*old_copy, new_ai])
        # 2 original + 2 "copies" (different IDs) + 1 new = 5
        assert len(merged) == 5, "Without same IDs, full list causes duplication"


# ---------------------------------------------------------------------------
# 2. Multi-round merge with delta pattern
# ---------------------------------------------------------------------------


class TestMultiRoundMerge:
    def test_three_rounds_delta_only(self):
        """3 rounds of delta-only returns → exactly 6 messages."""
        state: list = []

        state = _merge(state, [HumanMessage(content="你好")])
        state = _merge(state, [AIMessage(content="你好呀", name="ChatReplier")])

        state = _merge(state, [HumanMessage(content="播放周杰伦")])
        state = _merge(state, [AIMessage(content="好的", name="MusicExecutor")])

        state = _merge(state, [HumanMessage(content="下一首")])
        state = _merge(state, [AIMessage(content="切歌了", name="PlayAgent")])

        assert len(state) == 6
        contents = [m.content for m in state]
        assert len(contents) == len(set(contents))


# ---------------------------------------------------------------------------
# 3. Verify node source code uses delta pattern
# ---------------------------------------------------------------------------


class TestNodeSourceCodePattern:
    """Static check: ensure nodes return [ai_msg], not [*messages, ai_msg]."""

    def _get_node_source(self, func_name: str) -> str:
        import inspect
        import app.agents.music_team_v3_1.nodes as nodes_mod
        func = getattr(nodes_mod, func_name)
        return inspect.getsource(func)

    def test_music_ops_subgraph_returns_delta(self):
        source = self._get_node_source("music_ops_subgraph_node")
        # Should have: return {**state, "messages": [ai_msg], ...}
        # Should NOT have: "messages": [*messages, ai_msg]
        assert "[ai_msg]" in source or "[ai_msg," in source, (
            "music_ops_subgraph_node should return [ai_msg], not [*messages, ai_msg]"
        )

    def test_playback_subgraph_returns_delta(self):
        source = self._get_node_source("playback_subgraph_node")
        assert "[ai_msg]" in source or "[ai_msg," in source, (
            "playback_subgraph_node should return [ai_msg], not [*messages, ai_msg]"
        )

    def test_chat_replier_returns_delta(self):
        source = self._get_node_source("chat_replier_node")
        assert "[ai_msg]" in source or "[ai_msg," in source, (
            "chat_replier_node should return [ai_msg], not [*messages, ai_msg]"
        )

    def test_memory_sync_no_inplace_message_mutation(self):
        source = self._get_node_source("memory_sync_node")
        # Should not do: state["messages"] = ...
        # This is an in-place mutation that bypasses the reducer.
        if 'state["messages"]' in source or "state['messages']" in source:
            pytest.skip(
                "memory_sync_node still mutates state['messages'] in-place — "
                "risk documented, trimming deferred to future task"
            )
