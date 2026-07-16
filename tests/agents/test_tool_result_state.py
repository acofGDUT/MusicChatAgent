import asyncio
import os

os.environ.setdefault("OPENAI_API_BASE", "http://localhost:9999/v1")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("MUSIC_AGENT_BASE_URL", "http://localhost:9999/v1")
os.environ.setdefault("MUSIC_AGENT_API_KEY", "test-key")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.music_team_v3_1 import nodes
from app.agents.music_team_v3_1.nodes import _apply_tool_result_status
from app.tools.tool_result import ToolResult, ToolResultCode


def tool_message(name: str, content: str, call_id: str = "call-1") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name=name)


def apply(messages: list) -> tuple[dict, dict]:
    task: dict = {"status": "running", "error_code": "OLD", "error_reason": "old"}
    extensions: dict = {"last_tool_result": {"code": "OLD"}}
    _apply_tool_result_status(task=task, extensions=extensions, result_messages=messages)
    return task, extensions


def test_success_result_wins_over_failure_word_in_ai_text() -> None:
    result = ToolResult.success("执行成功")
    messages = [
        HumanMessage(content="搜索歌曲"),
        tool_message("search_music_tool", result.to_json()),
        AIMessage(content="这里出现了失败这个词，但工具成功"),
    ]

    task, extensions = apply(messages)

    assert task == {"status": "done"}
    assert extensions["last_tool_result"]["code"] == "SUCCESS"


def test_failure_result_fails_without_failure_word_in_ai_text() -> None:
    result = ToolResult.failure(code=ToolResultCode.NOT_FOUND, message="没有结果")
    messages = [
        HumanMessage(content="搜索歌曲"),
        tool_message("search_music_tool", result.to_json()),
        AIMessage(content="我已经处理了你的请求"),
    ]

    task, _ = apply(messages)

    assert task["status"] == "failed"
    assert task["error_code"] == "NOT_FOUND"


def test_last_migrated_tool_result_wins() -> None:
    failed = ToolResult.failure(code=ToolResultCode.UPSTREAM_ERROR, message="temporary", retryable=True)
    succeeded = ToolResult.success("recovered")
    messages = [
        HumanMessage(content="搜索歌曲"),
        tool_message("search_music_tool", failed.to_json(), "call-1"),
        tool_message("search_music_tool", succeeded.to_json(), "call-2"),
    ]

    task, _ = apply(messages)

    assert task["status"] == "done"


def test_previous_round_result_does_not_leak() -> None:
    failed = ToolResult.failure(code=ToolResultCode.NOT_FOUND, message="old failure")
    messages = [
        HumanMessage(content="旧请求"),
        tool_message("search_music_tool", failed.to_json()),
        HumanMessage(content="谢谢"),
        AIMessage(content="不客气"),
    ]

    task, extensions = apply(messages)

    assert task == {"status": "done"}
    assert "last_tool_result" not in extensions


def test_invalid_result_from_migrated_tool_is_failure() -> None:
    messages = [
        HumanMessage(content="搜索歌曲"),
        tool_message("search_music_tool", "legacy plain text"),
    ]

    task, extensions = apply(messages)

    assert task["status"] == "failed"
    assert task["error_code"] == "INVALID_TOOL_RESULT"
    assert extensions["last_tool_result"]["code"] == "INVALID_TOOL_RESULT"


def test_legacy_tool_plain_text_remains_compatible() -> None:
    messages = [
        HumanMessage(content="查询我的歌单"),
        tool_message("get_created_songlist_tool", "legacy plain text"),
        AIMessage(content="你有两个歌单"),
    ]

    task, extensions = apply(messages)

    assert task == {"status": "done"}
    assert "last_tool_result" not in extensions


class FailingAgent:
    async def ainvoke(self, payload: dict) -> dict:
        raise RuntimeError("boom")


class SuccessfulPlaybackAgent:
    async def ainvoke(self, payload: dict) -> dict:
        artifact = {
            "type": "play_music",
            "song_mid": "mid-1",
            "title": "晴天",
            "artist": "周杰伦",
            "url": "https://example.com/song.mp3",
            "cover": "",
        }
        result = ToolResult.success("已获取歌曲播放信息", artifact)
        return {
            "messages": [
                *payload["messages"],
                tool_message("play_music_tool", result.to_json()),
                AIMessage(content=result.model_dump_json(include={"data"})),
            ]
        }


def test_music_agent_exception_becomes_internal_error(monkeypatch) -> None:
    monkeypatch.setattr(nodes, "music_executor", FailingAgent())

    output = asyncio.run(
        nodes.music_ops_subgraph_node(
            {
                "messages": [HumanMessage(content="搜索歌曲")],
                "task": {"status": "running"},
                "control": {"executor_reentry": 0},
            }
        )
    )

    assert output["task"]["status"] == "failed"
    assert output["task"]["error_code"] == "INTERNAL_ERROR"
    assert output["extensions"]["last_tool_result"]["code"] == "INTERNAL_ERROR"


def test_playback_agent_exception_becomes_internal_error(monkeypatch) -> None:
    monkeypatch.setattr(nodes, "playback_executor", FailingAgent())

    output = asyncio.run(
        nodes.playback_subgraph_node(
            {
                "messages": [HumanMessage(content="播放歌曲")],
                "task": {"status": "running"},
            }
        )
    )

    assert output["task"]["status"] == "failed"
    assert output["task"]["error_code"] == "INTERNAL_ERROR"


def test_playback_node_keeps_final_artifact_message(monkeypatch) -> None:
    import json

    class ArtifactPlaybackAgent(SuccessfulPlaybackAgent):
        async def ainvoke(self, payload: dict) -> dict:
            result = await super().ainvoke(payload)
            artifact = {
                "type": "play_music",
                "song_mid": "mid-1",
                "title": "晴天",
                "artist": "周杰伦",
                "url": "https://example.com/song.mp3",
                "cover": "",
            }
            result["messages"][-1] = AIMessage(content=json.dumps(artifact, ensure_ascii=False))
            return result

    monkeypatch.setattr(nodes, "playback_executor", ArtifactPlaybackAgent())

    output = asyncio.run(
        nodes.playback_subgraph_node(
            {
                "messages": [HumanMessage(content="播放晴天")],
                "task": {"status": "running"},
            }
        )
    )

    final_payload = json.loads(output["messages"][-1].content)
    assert output["task"]["status"] == "done"
    assert final_payload["type"] == "play_music"
    assert "ok" not in final_payload
