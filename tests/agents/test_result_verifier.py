import asyncio
import json
import os
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest


# Agent modules construct ChatOpenAI clients at import time. Keep their configuration
# deterministic and local even though these tests never invoke a model.
os.environ.setdefault("OPENAI_API_BASE", "http://localhost:9999/v1")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("MUSIC_AGENT_BASE_URL", "http://localhost:9999/v1")
os.environ.setdefault("MUSIC_AGENT_API_KEY", "test-key")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.music_team_v3_1 import nodes
from app.agents.music_team_v3_1.agents import music_retry_tools
from app.agents.music_team_v3_1.nodes import (
    init_memory_node,
    result_verifier_node,
    route_after_verifier,
)
from app.agents.music_team_v3_1.utils import (
    WRITE_TOOL_NAMES,
    build_runtime_messages,
    current_run_has_write_tool,
    current_tool_names,
    extract_current_tool_run,
    update_last_search_results,
)
from app.tools.tool_result import ToolResult, ToolResultCode


def tool_message(
    name: str,
    content: str,
    call_id: str = "call-1",
) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name=name)


def run_entry(
    name: str,
    result: ToolResult | None,
    call_id: str = "call-1",
) -> dict:
    return {
        "tool_name": name,
        "tool_call_id": call_id,
        "protocol_valid": result is not None,
        "result": result.model_dump(mode="json") if result is not None else None,
    }


def search_payload(*, item_count: int = 2, search_type: str = "SONG") -> dict:
    return {
        "keyword": " 周杰伦 ",
        "search_type": search_type,
        "count": item_count,
        "items": [
            {
                "index": index,
                "id": str(1000 + index),
                "mid": f" mid-{index} ",
                "name": f" 第{index}首 ",
                "singer": [{"name": "周杰伦"}],
                "album": {"name": f"专辑{index}"},
                "url": "https://should-not-be-saved.example/song.mp3",
                "raw_response": {"large": "payload"},
            }
            for index in range(1, item_count + 1)
        ],
    }


def play_artifact(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "type": "play_music",
        "song_mid": "mid-1",
        "title": "晴天",
        "artist": "周杰伦",
        "url": "https://example.com/song.mp3",
        "cover": "",
        "description": "已获取播放链接",
    }
    payload.update(overrides)
    return payload


def verifier_state(
    *,
    intent: str = "music_ops",
    result: ToolResult | None = None,
    tool_name: str = "search_music_tool",
    ai_content: str = "执行完成",
    ai_id: str | None = None,
    current_run: list[dict] | None = None,
    control: dict | None = None,
) -> dict:
    extensions: dict = {
        "current_tool_run": (
            current_run
            if current_run is not None
            else ([run_entry(tool_name, result)] if result is not None else [])
        )
    }
    if result is not None:
        extensions["last_tool_result"] = result.model_dump(mode="json")
    return {
        "messages": [
            HumanMessage(content="处理这个请求"),
            AIMessage(content=ai_content, id=ai_id),
        ],
        "task": {"intent": intent, "status": "running", "goal": "处理这个请求"},
        "control": dict(control or {}),
        "extensions": extensions,
    }


def test_extract_current_tool_run_only_uses_latest_human_round() -> None:
    old_result = ToolResult.failure(
        code=ToolResultCode.NOT_FOUND,
        message="旧请求没有结果",
    )
    new_result = ToolResult.success("搜索成功", search_payload())
    messages = [
        HumanMessage(content="旧请求"),
        tool_message("search_music_tool", old_result.to_json(), "old-call"),
        HumanMessage(content="新请求"),
        tool_message("get_created_songlist_tool", "legacy plain text", "legacy-call"),
        tool_message("search_music_tool", new_result.to_json(), "new-call"),
        AIMessage(content="完成"),
    ]

    current_run = extract_current_tool_run(messages)

    assert [item["tool_name"] for item in current_run] == [
        "get_created_songlist_tool",
        "search_music_tool",
    ]
    assert [item["tool_call_id"] for item in current_run] == [
        "legacy-call",
        "new-call",
    ]
    assert current_run[0] == {
        "tool_name": "get_created_songlist_tool",
        "tool_call_id": "legacy-call",
        "protocol_valid": False,
        "result": None,
    }
    assert current_run[1]["protocol_valid"] is True
    assert current_run[1]["result"]["code"] == "SUCCESS"
    assert "legacy plain text" not in json.dumps(current_run, ensure_ascii=False)


@pytest.mark.parametrize("write_tool", sorted(WRITE_TOOL_NAMES))
def test_every_write_tool_is_detected_anywhere_in_current_run(write_tool: str) -> None:
    retryable_failure = ToolResult.failure(
        code=ToolResultCode.UPSTREAM_ERROR,
        message="读取暂时失败",
        retryable=True,
    )
    state = {
        "extensions": {
            "current_tool_run": [
                run_entry(write_tool, None, "write-call"),
                run_entry("search_music_tool", retryable_failure, "read-call"),
            ]
        }
    }

    assert write_tool in current_tool_names(state)
    assert current_run_has_write_tool(state) is True


def test_read_only_current_run_is_not_misclassified_as_write() -> None:
    state = {
        "extensions": {
            "current_tool_run": [
                run_entry("search_music_tool", ToolResult.success("ok")),
                run_entry("play_music_tool", ToolResult.success("ok")),
            ]
        }
    }

    assert current_tool_names(state) == {"search_music_tool", "play_music_tool"}
    assert current_run_has_write_tool(state) is False


def test_music_retry_executor_exposes_no_write_tools() -> None:
    retry_tool_names = {tool.name for tool in music_retry_tools}

    assert retry_tool_names
    assert retry_tool_names.isdisjoint(WRITE_TOOL_NAMES)


def test_song_search_results_are_normalized_truncated_and_sanitized() -> None:
    successful_search = ToolResult.success("搜索成功", search_payload(item_count=22))
    extensions = {
        "current_tool_run": [run_entry("search_music_tool", successful_search)],
        "last_search_results": {"keyword": "旧搜索", "items": [{"index": 1}]},
    }

    changed = update_last_search_results(extensions)

    assert changed is True
    saved = extensions["last_search_results"]
    assert saved["keyword"] == "周杰伦"
    assert saved["search_type"] == "SONG"
    assert saved["count"] == 20
    assert len(saved["items"]) == 20
    assert saved["items"][0] == {
        "index": 1,
        "song_id": 1001,
        "song_mid": "mid-1",
        "title": "第1首",
        "artist": "周杰伦",
        "album": "专辑1",
    }
    serialized = json.dumps(saved, ensure_ascii=False)
    assert "url" not in serialized
    assert "raw_response" not in serialized


def test_song_search_discards_invalid_items() -> None:
    payload = search_payload(item_count=2)
    payload["items"] = [
        {"index": 1, "mid": "", "name": "没有 mid"},
        {"index": 2, "mid": "mid-2", "name": "合法歌曲"},
        {"index": 2, "mid": "mid-duplicate", "name": "重复 index"},
        {"index": 0, "mid": "mid-zero", "name": "非法 index"},
    ]
    result = ToolResult.success("搜索成功", payload)
    extensions = {"current_tool_run": [run_entry("search_music_tool", result)]}

    update_last_search_results(extensions)

    assert extensions["last_search_results"]["items"] == [
        {
            "index": 2,
            "song_id": None,
            "song_mid": "mid-2",
            "title": "合法歌曲",
            "artist": "",
            "album": "",
        }
    ]


@pytest.mark.parametrize(
    "search_entry",
    [
        run_entry(
            "search_music_tool",
            ToolResult.failure(
                code=ToolResultCode.UPSTREAM_ERROR,
                message="搜索失败",
                retryable=True,
            ),
        ),
        run_entry(
            "search_music_tool",
            ToolResult.success("搜索成功", search_payload(search_type="ALBUM")),
        ),
        run_entry(
            "search_music_tool",
            ToolResult.success(
                "搜索成功",
                {"keyword": "x", "search_type": "SONG", "items": []},
            ),
        ),
        run_entry("search_music_tool", None),
    ],
    ids=["failed", "non-song", "empty", "invalid-protocol"],
)
def test_search_failure_or_unusable_result_clears_old_context(search_entry: dict) -> None:
    extensions = {
        "current_tool_run": [search_entry],
        "last_search_results": {"keyword": "旧结果", "items": [{"index": 1}]},
    }

    changed = update_last_search_results(extensions)

    assert changed is True
    assert "last_search_results" not in extensions


def test_no_search_call_preserves_old_search_context() -> None:
    old_results = {"keyword": "旧结果", "items": [{"index": 1}]}
    extensions = {
        "current_tool_run": [run_entry("get_hotkeys_tool", ToolResult.success("ok"))],
        "last_search_results": deepcopy(old_results),
    }

    changed = update_last_search_results(extensions)

    assert changed is False
    assert extensions["last_search_results"] == old_results


@pytest.mark.parametrize("role", ["executor", "playback"])
def test_runtime_prompt_injects_compact_search_results_for_execution_roles(role: str) -> None:
    results = {
        "keyword": "周杰伦",
        "search_type": "SONG",
        "count": 1,
        "items": [
            {
                "index": 1,
                "song_id": 1001,
                "song_mid": "mid-1",
                "title": "晴天",
                "artist": "周杰伦",
                "album": "叶惠美",
            }
        ],
    }
    messages = build_runtime_messages(
        {
            "messages": [HumanMessage(content="播放刚才第 1 首")],
            "extensions": {"last_search_results": results},
        },
        role=role,
    )

    context = next(
        message.content
        for message in messages
        if isinstance(message, SystemMessage)
        and message.content.startswith("LAST_SEARCH_RESULTS_JSON:")
    )
    assert json.dumps(results, ensure_ascii=False, separators=(",", ":")) in context
    assert "index=N" in context
    assert "禁止猜测" in context
    assert "无需重新搜索" in context


def test_runtime_prompt_only_adds_retry_context_during_scheduled_retry() -> None:
    base_state = {"messages": [HumanMessage(content="搜索歌曲")], "control": {}}
    normal_messages = build_runtime_messages(base_state, role="executor")
    assert not any(
        isinstance(message, SystemMessage)
        and message.content.startswith("RETRY_CONTEXT:")
        for message in normal_messages
    )

    retry_state = {
        **base_state,
        "control": {
            "retry_count": 1,
            "retry_reason": "上游暂时失败",
            "verifier_route": "retry_music_ops",
        },
    }
    retry_messages = build_runtime_messages(retry_state, role="executor")

    assert isinstance(retry_messages[-1], SystemMessage)
    assert retry_messages[-1].content.startswith("RETRY_CONTEXT:")
    assert "唯一一次重试" in retry_messages[-1].content
    assert "不得调用任何写工具" in retry_messages[-1].content
    assert "上游暂时失败" in retry_messages[-1].content


def test_valid_artifact_is_canonicalized_with_same_message_id() -> None:
    result = ToolResult.success("已获取播放信息", play_artifact())
    raw_artifact = json.dumps(play_artifact(), ensure_ascii=False, indent=2)
    state = verifier_state(
        intent="playback",
        result=result,
        tool_name="play_music_tool",
        ai_content=f"```json\n{raw_artifact}\n```",
        ai_id="artifact-message-id",
    )

    output = asyncio.run(result_verifier_node(state))

    final_message = output["messages"][-1]
    assert final_message.id == "artifact-message-id"
    assert final_message.content == json.dumps(
        play_artifact(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert output["extensions"]["last_artifact"] == play_artifact()
    assert output["extensions"]["verification"]["status"] == "passed"
    assert output["task"]["status"] == "done"
    assert output["control"]["verifier_route"] == "playback_done"


def test_natural_playback_followup_is_not_forced_into_artifact_protocol() -> None:
    state = verifier_state(
        intent="playback",
        result=None,
        ai_content="你想播放哪个版本？",
    )

    output = asyncio.run(result_verifier_node(state))

    assert output["messages"] == []
    assert state["messages"][-1].content == "你想播放哪个版本？"
    assert "last_tool_result" not in output["extensions"]
    assert output["extensions"]["verification"]["status"] == "skipped"
    assert output["control"]["verifier_route"] == "playback_done"


def test_invalid_artifact_retries_once_then_returns_safe_error() -> None:
    play_result = ToolResult.success("已获取播放信息", play_artifact())
    initial = verifier_state(
        intent="playback",
        result=play_result,
        tool_name="play_music_tool",
        ai_content='{"type":"play_music","song_mid":"mid-1"}',
        ai_id="bad-artifact-id",
    )

    first = asyncio.run(result_verifier_node(initial))

    assert first["control"]["retry_count"] == 1
    assert first["control"]["verifier_route"] == "retry_playback"
    assert first["control"]["retry_artifact_type"] == "play_music"
    assert first["task"]["status"] == "running"
    assert first["extensions"]["last_tool_result"]["code"] == "ARTIFACT_INVALID"
    assert first["extensions"]["verification"]["retry_scheduled"] is True

    second_state = {
        **first,
        "messages": [
            *first["messages"],
            AIMessage(content="still not json", id="second-bad-artifact-id"),
        ],
        "extensions": {
            **first["extensions"],
            "current_tool_run": [run_entry("play_music_tool", play_result, "retry-call")],
            "last_tool_result": play_result.model_dump(mode="json"),
        },
    }
    second = asyncio.run(result_verifier_node(second_state))

    assert second["control"]["retry_count"] == 1
    assert second["control"]["verifier_route"] == "playback_done"
    assert second["task"]["status"] == "failed"
    assert second["task"]["error_code"] == "ARTIFACT_INVALID"
    assert second["extensions"]["verification"]["retry_scheduled"] is False
    assert second["messages"][-1].id == "second-bad-artifact-id"
    assert second["messages"][-1].content == "播放结果格式校验失败，暂时无法展示。"


def test_retryable_read_failure_is_retried_once_then_exhausted() -> None:
    first_failure = ToolResult.failure(
        code=ToolResultCode.UPSTREAM_ERROR,
        message="搜索接口暂时不可用",
        retryable=True,
    )
    initial = verifier_state(
        intent="music_ops",
        result=first_failure,
        tool_name="search_music_tool",
        ai_content="搜索暂时失败",
    )

    first = asyncio.run(result_verifier_node(initial))

    assert first["control"]["retry_count"] == 1
    assert first["control"]["retry_reason"] == "搜索接口暂时不可用"
    assert first["control"]["retry_tool_name"] == "search_music_tool"
    assert first["control"]["verifier_route"] == "retry_music_ops"
    assert first["task"]["status"] == "running"

    second_failure = ToolResult.failure(
        code=ToolResultCode.UPSTREAM_ERROR,
        message="第二次仍然失败",
        retryable=True,
    )
    second_state = {
        **first,
        "messages": [*first["messages"], AIMessage(content="第二次失败")],
        "extensions": {
            **first["extensions"],
            "current_tool_run": [run_entry("search_music_tool", second_failure, "retry-call")],
            "last_tool_result": second_failure.model_dump(mode="json"),
        },
    }
    second = asyncio.run(result_verifier_node(second_state))

    assert second["control"]["retry_count"] == 1
    assert second["control"]["verifier_route"] == "music_done"
    assert second["task"]["status"] == "failed"
    assert second["task"]["error_code"] == "UPSTREAM_ERROR"
    assert second["task"]["error_reason"] == "第二次仍然失败"
    assert second["extensions"]["verification"]["retry_scheduled"] is False


def test_retry_target_success_finishes_task() -> None:
    original_failure = ToolResult.failure(
        code=ToolResultCode.UPSTREAM_ERROR,
        message="搜索接口暂时不可用",
        retryable=True,
    )
    first = asyncio.run(
        result_verifier_node(
            verifier_state(
                intent="music_ops",
                result=original_failure,
                tool_name="search_music_tool",
                ai_content="第一次失败",
            )
        )
    )
    recovered = ToolResult.success("搜索成功", search_payload())
    retry_state = {
        **first,
        "messages": [*first["messages"], AIMessage(content="搜索成功")],
        "extensions": {
            **first["extensions"],
            "current_tool_run": [run_entry("search_music_tool", recovered, "retry-call")],
            "last_tool_result": recovered.model_dump(mode="json"),
        },
    }

    output = asyncio.run(result_verifier_node(retry_state))

    assert output["control"]["retry_count"] == 1
    assert output["control"]["verifier_route"] == "music_done"
    assert output["task"]["status"] == "done"
    assert output["extensions"]["verification"]["status"] == "passed"


def test_retry_omitting_original_tool_restores_original_failure() -> None:
    original_failure = ToolResult.failure(
        code=ToolResultCode.UPSTREAM_ERROR,
        message="原始搜索失败",
        retryable=True,
    )
    initial = verifier_state(
        intent="music_ops",
        result=original_failure,
        tool_name="search_music_tool",
        ai_content="第一次失败",
    )
    first = asyncio.run(result_verifier_node(initial))

    unrelated_success = ToolResult.success("查询热门词成功")
    retry_state = {
        **first,
        "messages": [*first["messages"], AIMessage(content="没有重试原工具")],
        "extensions": {
            **first["extensions"],
            "current_tool_run": [run_entry("get_hotkeys_tool", unrelated_success)],
            "last_tool_result": unrelated_success.model_dump(mode="json"),
        },
    }

    output = asyncio.run(result_verifier_node(retry_state))

    assert output["control"]["retry_count"] == 1
    assert output["control"]["verifier_route"] == "music_done"
    assert output["extensions"]["last_tool_result"]["code"] == "UPSTREAM_ERROR"
    assert output["extensions"]["last_tool_result"]["message"] == "原始搜索失败"
    assert output["task"]["status"] == "failed"
    assert output["task"]["error_reason"] == "原始搜索失败"


@pytest.mark.parametrize("write_tool", sorted(WRITE_TOOL_NAMES))
def test_any_write_tool_in_attempt_forbids_retry(write_tool: str) -> None:
    retryable_failure = ToolResult.failure(
        code=ToolResultCode.UPSTREAM_ERROR,
        message="读取暂时失败",
        retryable=True,
    )
    state = verifier_state(
        intent="music_ops",
        result=retryable_failure,
        current_run=[
            run_entry(write_tool, ToolResult.success("写入完成"), "write-call"),
            run_entry("search_music_tool", retryable_failure, "read-call"),
        ],
        ai_content="读取失败",
    )

    output = asyncio.run(result_verifier_node(state))

    assert output["control"]["retry_count"] == 0
    assert output["control"]["verifier_route"] == "music_done"
    assert output["task"]["status"] == "failed"
    assert output["extensions"]["verification"]["retry_scheduled"] is False


def uncertain_add_state() -> dict:
    uncertain = ToolResult.failure(
        code=ToolResultCode.WRITE_UNCERTAIN,
        message="请求已发送，但平台未确认",
        data={"dirid": 42, "song_ids": [101, 102]},
    )
    return verifier_state(
        intent="music_ops",
        result=uncertain,
        tool_name="add_songs_to_playlist_tool",
        ai_content="加歌结果暂时无法确认",
    )


def test_direct_add_postcondition_all_present_becomes_success(monkeypatch) -> None:
    read_playlist = AsyncMock(
        return_value=[
            {"id": 101, "mid": "mid-101", "title": "歌曲 101"},
            {"id": "102", "mid": "mid-102", "title": "歌曲 102"},
        ]
    )
    monkeypatch.setattr(
        nodes.playlist_service,
        "get_all_songs_in_playlist",
        read_playlist,
    )

    output = asyncio.run(result_verifier_node(uncertain_add_state()))

    read_playlist.assert_awaited_once_with(songlist_id=0, dirid=42)
    assert output["extensions"]["last_tool_result"]["code"] == "SUCCESS"
    assert output["extensions"]["last_tool_result"]["message"] == "加歌结果已通过查询确认"
    assert output["extensions"]["last_tool_result"]["data"]["verified_song_ids"] == [101, 102]
    assert output["extensions"]["last_tool_result"]["data"]["missing_song_ids"] == []
    assert output["extensions"]["verification"]["status"] == "passed"
    assert output["task"]["status"] == "done"
    assert output["control"]["retry_count"] == 0


def test_direct_add_postcondition_partial_becomes_partial_success(monkeypatch) -> None:
    read_playlist = AsyncMock(
        return_value=[{"id": 101, "mid": "mid-101", "title": "歌曲 101"}]
    )
    monkeypatch.setattr(
        nodes.playlist_service,
        "get_all_songs_in_playlist",
        read_playlist,
    )

    output = asyncio.run(result_verifier_node(uncertain_add_state()))

    read_playlist.assert_awaited_once_with(songlist_id=0, dirid=42)
    verified = output["extensions"]["last_tool_result"]
    assert verified["code"] == "PARTIAL_SUCCESS"
    assert verified["data"]["verified_song_ids"] == [101]
    assert verified["data"]["missing_song_ids"] == [102]
    assert output["extensions"]["verification"]["status"] == "failed"
    assert output["task"]["status"] == "failed"
    assert output["control"]["retry_count"] == 0


@pytest.mark.parametrize("read_result", [[], [{"id": 999}]])
def test_direct_add_postcondition_inconclusive_keeps_write_uncertain(
    monkeypatch,
    read_result: list[dict],
) -> None:
    read_playlist = AsyncMock(return_value=read_result)
    monkeypatch.setattr(
        nodes.playlist_service,
        "get_all_songs_in_playlist",
        read_playlist,
    )

    output = asyncio.run(result_verifier_node(uncertain_add_state()))

    read_playlist.assert_awaited_once_with(songlist_id=0, dirid=42)
    assert output["extensions"]["last_tool_result"]["code"] == "WRITE_UNCERTAIN"
    assert output["extensions"]["verification"]["status"] == "inconclusive"
    assert output["task"]["status"] == "failed"
    assert output["control"]["retry_count"] == 0
    assert output["control"]["verifier_route"] == "music_done"


def test_direct_add_postcondition_query_error_is_inconclusive(monkeypatch) -> None:
    read_playlist = AsyncMock(side_effect=RuntimeError("temporary read failure"))
    monkeypatch.setattr(
        nodes.playlist_service,
        "get_all_songs_in_playlist",
        read_playlist,
    )

    output = asyncio.run(result_verifier_node(uncertain_add_state()))

    read_playlist.assert_awaited_once_with(songlist_id=0, dirid=42)
    assert output["extensions"]["last_tool_result"]["code"] == "WRITE_UNCERTAIN"
    assert output["extensions"]["verification"]["status"] == "inconclusive"
    assert output["extensions"]["verification"]["retry_scheduled"] is False


@pytest.mark.parametrize(
    "tool_name",
    ["create_playlist_tool", "add_by_keyword_to_playlist_tool"],
)
def test_other_uncertain_writes_do_not_trigger_postcondition_query(
    monkeypatch,
    tool_name: str,
) -> None:
    read_playlist = AsyncMock()
    monkeypatch.setattr(
        nodes.playlist_service,
        "get_all_songs_in_playlist",
        read_playlist,
    )
    uncertain = ToolResult.failure(
        code=ToolResultCode.WRITE_UNCERTAIN,
        message="写入结果不确定",
        data={"dirid": 42, "song_ids": [101]},
    )
    state = verifier_state(
        intent="music_ops",
        result=uncertain,
        tool_name=tool_name,
        ai_content="无法确认",
    )

    output = asyncio.run(result_verifier_node(state))

    read_playlist.assert_not_awaited()
    assert output["extensions"]["last_tool_result"]["code"] == "WRITE_UNCERTAIN"
    assert output["extensions"]["verification"]["status"] == "failed"
    assert output["control"]["retry_count"] == 0


def test_init_memory_resets_retry_attempt_state_but_preserves_search_context(
    monkeypatch,
) -> None:
    monkeypatch.setattr(nodes, "ensure_memory_files", lambda: None)
    monkeypatch.setattr(nodes, "read_text", lambda _path: "memory text")
    search_context = {
        "keyword": "周杰伦",
        "search_type": "SONG",
        "count": 1,
        "items": [{"index": 1, "song_mid": "mid-1", "title": "晴天"}],
    }
    state = {
        "messages": [HumanMessage(content="播放第一首")],
        "task": {"status": "done", "retries": 2},
        "control": {
            "executor_reentry": 7,
            "max_reentry": 9,
            "retry_count": 1,
            "max_retries": 99,
            "retry_reason": "old",
            "retry_tool_name": "search_music_tool",
            "retry_artifact_type": "play_music",
            "verifier_route": "retry_playback",
        },
        "extensions": {
            "current_tool_run": [{"old": True}],
            "verification": {"status": "failed"},
            "retry_original_result": {"code": "UPSTREAM_ERROR"},
            "last_search_results": deepcopy(search_context),
            "last_artifact": play_artifact(),
        },
    }

    output = asyncio.run(init_memory_node(state))

    assert output["control"]["retry_count"] == 0
    assert output["control"]["max_retries"] == 1
    assert output["control"]["executor_reentry"] == 7
    assert output["control"]["max_reentry"] == 9
    for key in (
        "retry_reason",
        "retry_tool_name",
        "retry_artifact_type",
        "verifier_route",
    ):
        assert key not in output["control"]
    assert output["extensions"]["last_search_results"] == search_context
    assert output["extensions"]["last_artifact"] == play_artifact()
    for key in ("current_tool_run", "verification", "retry_original_result"):
        assert key not in output["extensions"]


@pytest.mark.parametrize(
    "route",
    ["retry_music_ops", "retry_playback", "music_done", "playback_done"],
)
def test_route_after_verifier_returns_each_explicit_route(route: str) -> None:
    assert route_after_verifier({"control": {"verifier_route": route}}) == route


@pytest.mark.parametrize(
    ("intent", "expected"),
    [("playback", "playback_done"), ("music_ops", "music_done"), (None, "music_done")],
)
def test_route_after_verifier_unknown_route_never_retries(
    intent: str | None,
    expected: str,
) -> None:
    state = {
        "task": {"intent": intent},
        "control": {"verifier_route": "unexpected-route"},
    }

    assert route_after_verifier(state) == expected
