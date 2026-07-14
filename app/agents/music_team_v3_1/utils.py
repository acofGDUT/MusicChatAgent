import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.tools.tool_result import ToolResult, parse_tool_result

from .config import HISTORY_PATH, MEMORY_DIR, SOUL_PATH, USER_PROFILE_PATH
from .state import MusicGraphStateV31


TOOL_RESULT_REQUIRED_TOOLS = frozenset(
    {
        "search_music_tool",
        "play_music_tool",
        "create_playlist_tool",
        "add_songs_to_playlist_tool",
        "add_by_keyword_to_playlist_tool",
        "get_playlist_detail_tool",
    }
)

WRITE_TOOL_NAMES = frozenset(
    {
        "create_playlist_tool",
        "add_songs_to_playlist_tool",
        "add_by_keyword_to_playlist_tool",
        "delete_playlist_tool",
        "remove_songs_from_playlist_tool",
    }
)


def safe_kwargs(func: Any, candidate_kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        sig = inspect.signature(func)
        valid = set(sig.parameters.keys())
        return {k: v for k, v in candidate_kwargs.items() if k in valid and v is not None}
    except Exception:
        return {}


def extract_messages(state: MusicGraphStateV31) -> list[Any]:
    msgs = state.get("messages", [])
    return msgs if isinstance(msgs, list) else []


def msg_content(msg: Any) -> str:
    content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            elif isinstance(item, str) and item.strip():
                parts.append(item)
        if parts:
            return "\n".join(parts)
    return str(content)


def last_user_text(messages: list[Any]) -> str:
    return next((msg_content(m) for m in reversed(messages) if isinstance(m, HumanMessage)), "")


def estimate_tokens(messages: list[Any]) -> int:
    return sum(len(msg_content(m)) for m in messages)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_memory_files() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not USER_PROFILE_PATH.exists():
        USER_PROFILE_PATH.write_text("# 用户画像（User Profile）\n\n## 用户偏好（带置信度）\n- 喜欢歌手（high）：\n- 喜欢歌手（medium）：\n- 常见风格：\n- 常用语言：\n\n## 使用与任务偏好\n- 常见请求：\n- 播放策略偏好：\n- 歌单操作偏好：\n\n## 约束与禁忌\n- 不希望添加的类型：unknown\n- 明确拒绝项：unknown\n- 冲突处理：当用户偏好与平台/安全规则冲突时，优先遵守平台与安全规则\n\n## 长期记忆实体（结构化）\n- 常用歌单（name -> dirid）：\n- 关键歌曲消歧：\n\n## 画像维护元信息\n- last_updated: \n- update_reason: init\n- profile_version: 2\n", encoding="utf-8")
    if not SOUL_PATH.exists():
        SOUL_PATH.write_text("# Music Agent Soul\n\n## Identity\n- 我是谁：QQ音乐多代理音乐助理\n- 服务边界：仅执行音乐与播放相关能力\n\n## Non-Negotiables\n- 不编造工具结果\n- 不在失败后盲重试\n- 未授权不执行高风险操作\n\n## Style\n- 语气：友好、简洁\n- 简洁度：中\n- 解释深度：按需\n\n## Decision Policy\n- 成功优先级：高\n- 安全优先级：最高\n- 澄清触发条件：必要槽位缺失\n\n## Evolution Log\n- version: 1\n- last_updated: init\n- change_summary: init\n- approved_by: system\n", encoding="utf-8")
    if not HISTORY_PATH.exists():
        HISTORY_PATH.write_text("", encoding="utf-8")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def safe_message_preview(msg: Any, limit: int = 200) -> str:
    text = msg_content(msg).replace("\n", " ").strip()
    return text[:limit]


def collect_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for m in messages:
        name = m.get("name", "") if isinstance(m, dict) else getattr(m, "name", "")
        if name not in {"MusicExecutor", "PlayAgent"}:
            continue
        calls = m.get("tool_calls", None) if isinstance(m, dict) else getattr(m, "tool_calls", None)
        if not isinstance(calls, list):
            continue
        for c in calls:
            if isinstance(c, dict):
                tool_calls.append({"agent": name, "tool_name": c.get("name", ""), "args": c.get("args", {}), "call_id": c.get("id", "")})
    return tool_calls


def _current_round_messages(messages: list[Any]) -> list[Any]:
    last_human_index = -1
    for index, message in enumerate(messages):
        message_type = message.get("type", "") if isinstance(message, dict) else getattr(message, "type", "")
        if isinstance(message, HumanMessage) or message_type == "human":
            last_human_index = index
    return messages[last_human_index + 1 :]


def _required_tool_messages(messages: list[Any]) -> list[Any]:
    required_messages: list[Any] = []
    for message in _current_round_messages(messages):
        message_type = message.get("type", "") if isinstance(message, dict) else getattr(message, "type", "")
        if not isinstance(message, ToolMessage) and message_type != "tool":
            continue
        name = message.get("name", "") if isinstance(message, dict) else getattr(message, "name", "")
        if name in TOOL_RESULT_REQUIRED_TOOLS:
            required_messages.append(message)
    return required_messages


def has_required_tool_messages(messages: list[Any]) -> bool:
    return bool(_required_tool_messages(messages))


def extract_tool_results(messages: list[Any]) -> list[ToolResult]:
    results: list[ToolResult] = []
    for message in _required_tool_messages(messages):
        result = parse_tool_result(msg_content(message))
        if result is not None:
            results.append(result)
    return results


def extract_last_tool_result(messages: list[Any]) -> ToolResult | None:
    required_messages = _required_tool_messages(messages)
    if not required_messages:
        return None
    return parse_tool_result(msg_content(required_messages[-1]))


def extract_current_tool_run(messages: list[Any]) -> list[dict[str, Any]]:
    """Return a checkpoint-safe summary of tools used in the current attempt."""
    current_run: list[dict[str, Any]] = []
    for message in _current_round_messages(messages):
        message_type = message.get("type", "") if isinstance(message, dict) else getattr(message, "type", "")
        if not isinstance(message, ToolMessage) and message_type != "tool":
            continue

        name = message.get("name", "") if isinstance(message, dict) else getattr(message, "name", "")
        call_id = (
            message.get("tool_call_id", "")
            if isinstance(message, dict)
            else getattr(message, "tool_call_id", "")
        )
        parsed = parse_tool_result(msg_content(message))
        current_run.append(
            {
                "tool_name": str(name or ""),
                "tool_call_id": str(call_id or ""),
                "protocol_valid": parsed is not None,
                "result": parsed.model_dump(mode="json") if parsed is not None else None,
            }
        )
    return current_run


def current_tool_names(state: MusicGraphStateV31) -> set[str]:
    extensions = state.get("extensions", {})
    current_run = extensions.get("current_tool_run", []) if isinstance(extensions, dict) else []
    if not isinstance(current_run, list):
        return set()
    return {
        str(item.get("tool_name", ""))
        for item in current_run
        if isinstance(item, dict) and str(item.get("tool_name", ""))
    }


def current_run_has_write_tool(state: MusicGraphStateV31) -> bool:
    return bool(current_tool_names(state) & WRITE_TOOL_NAMES)


def _plain_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "title"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""
    if isinstance(value, list):
        parts = [_plain_text(item) for item in value]
        return " & ".join(part for part in parts if part)
    return str(value).strip() if value is not None else ""


def normalize_song_search_results(data: Any, *, max_items: int = 20) -> dict[str, Any] | None:
    if not isinstance(data, dict) or str(data.get("search_type", "")).upper() != "SONG":
        return None
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        return None

    items: list[dict[str, Any]] = []
    used_indexes: set[int] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        try:
            index = int(raw_item.get("index"))
        except (TypeError, ValueError):
            continue
        song_mid = _plain_text(raw_item.get("song_mid") or raw_item.get("mid"))
        title = _plain_text(raw_item.get("title") or raw_item.get("name"))
        if index < 1 or index in used_indexes or not song_mid or not title:
            continue

        song_id: int | None
        try:
            raw_song_id = raw_item.get("song_id", raw_item.get("id"))
            song_id = int(raw_song_id) if raw_song_id is not None else None
        except (TypeError, ValueError):
            song_id = None

        items.append(
            {
                "index": index,
                "song_id": song_id,
                "song_mid": song_mid,
                "title": title,
                "artist": _plain_text(raw_item.get("artist") or raw_item.get("singer")),
                "album": _plain_text(raw_item.get("album")),
            }
        )
        used_indexes.add(index)
        if len(items) >= max_items:
            break

    if not items:
        return None
    return {
        "keyword": _plain_text(data.get("keyword")),
        "search_type": "SONG",
        "count": len(items),
        "items": items,
    }


def update_last_search_results(extensions: dict[str, Any]) -> bool:
    """Update search context from the latest search call; return whether search ran."""
    current_run = extensions.get("current_tool_run", [])
    if not isinstance(current_run, list):
        return False
    search_entries = [
        item
        for item in current_run
        if isinstance(item, dict) and item.get("tool_name") == "search_music_tool"
    ]
    if not search_entries:
        return False

    latest = search_entries[-1]
    parsed = latest.get("result")
    normalized: dict[str, Any] | None = None
    if latest.get("protocol_valid") is True and isinstance(parsed, dict) and parsed.get("ok") is True:
        normalized = normalize_song_search_results(parsed.get("data"))

    if normalized is None:
        extensions.pop("last_search_results", None)
    else:
        extensions["last_search_results"] = normalized
    return True


def extract_last_ai_message(result: Any, fallback_name: str) -> AIMessage:
    if isinstance(result, dict):
        msgs = result.get("messages", [])
        if isinstance(msgs, list):
            for m in reversed(msgs):
                if isinstance(m, AIMessage):
                    if not getattr(m, "name", None):
                        m.name = fallback_name
                    return m
                if isinstance(m, BaseMessage) and getattr(m, "type", "") == "ai":
                    return AIMessage(content=str(m.content), name=fallback_name)
    if isinstance(result, AIMessage):
        if not getattr(result, "name", None):
            result.name = fallback_name
        return result
    return AIMessage(content=str(result), name=fallback_name)


def build_runtime_messages(state: MusicGraphStateV31, role: str) -> list[BaseMessage]:
    memory = state.get("memory", {})
    runtime: list[BaseMessage] = []
    retry_context: SystemMessage | None = None
    if role != "intent_parser":
        if memory.get("summary", ""):
            runtime.append(SystemMessage(content=f"MEMORY_SUMMARY:\n{memory.get('summary', '')}"))
        if memory.get("user_profile", ""):
            runtime.append(SystemMessage(content=f"USER_PROFILE:\n{memory.get('user_profile', '')[:2200]}"))
        if memory.get("soul", ""):
            runtime.append(SystemMessage(content=f"AGENT_SOUL:\n{memory.get('soul', '')[:2200]}"))
    if role in {"executor", "playback"}:
        extensions = state.get("extensions", {})
        last_search_results = (
            extensions.get("last_search_results") if isinstance(extensions, dict) else None
        )
        if isinstance(last_search_results, dict) and last_search_results.get("items"):
            compact_results = json.dumps(
                last_search_results,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            runtime.append(
                SystemMessage(
                    content=(
                        f"LAST_SEARCH_RESULTS_JSON:\n{compact_results}\n\n"
                        "规则：用户说‘第N首/刚才第N首’时，只能使用该列表中 index=N 的歌曲；"
                        "index 超出范围时必须说明，禁止猜测；已有 song_mid 时无需重新搜索。"
                    )
                )
            )

        control = state.get("control", {})
        retry_count = int(control.get("retry_count", 0) or 0) if isinstance(control, dict) else 0
        retry_reason = str(control.get("retry_reason", "") or "").strip() if isinstance(control, dict) else ""
        verifier_route = str(control.get("verifier_route", "") or "") if isinstance(control, dict) else ""
        if retry_count > 0 and retry_reason and verifier_route.startswith("retry_"):
            retry_context = SystemMessage(
                content=(
                    "RETRY_CONTEXT:\n"
                    "- 这是本轮唯一一次重试。\n"
                    f"- 原因：{retry_reason}\n"
                    "- 只重试失败的读取/播放步骤。\n"
                    "- 不得调用任何写工具。\n"
                    "- 不得扩大用户原始任务。"
                )
            )

    if role == "executor":
        runtime.append(SystemMessage(content="EXECUTION_PACKET_RULE: 仅依据当前执行包上下文工作。若缺 dirid 先查再建，不要同条件盲重试。"))
    runtime.extend(extract_messages(state))
    if retry_context is not None:
        # Keep retry instructions as the final input message so an earlier executor
        # failure response cannot make the model treat this attempt as completed.
        runtime.append(retry_context)
    return runtime


def is_json_like_text(text: str) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json|markdown)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]"))


def looks_like_valid_soul_markdown(text: str) -> bool:
    if not text or is_json_like_text(text):
        return False
    required_sections = ["# Music Agent Soul", "## Identity", "## Non-Negotiables", "## Style", "## Decision Policy", "## Evolution Log"]
    return all(section in text for section in required_sections)
