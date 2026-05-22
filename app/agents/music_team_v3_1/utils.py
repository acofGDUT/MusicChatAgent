import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from .config import HISTORY_PATH, MEMORY_DIR, SOUL_PATH, USER_PROFILE_PATH
from .state import MusicGraphStateV31


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
        USER_PROFILE_PATH.write_text("# 用户画像（User Profile）\n\n## 基础偏好\n- 常听歌手：\n- 常见风格：\n- 常用语言：\n- 使用场景：\n\n## 操作习惯\n- 偏好歌单命名：\n- 添加歌曲策略偏好：\n- 是否偏好自动创建歌单：\n\n## 约束与禁忌\n- 不希望添加的类型：\n- 明确拒绝项：\n\n## 长期记忆实体\n- 常用歌单（name -> dirid）：\n- 高频关键词：\n\n## 更新时间\n- last_updated: \n- update_reason: init\n", encoding="utf-8")
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
    if role != "intent_parser":
        if memory.get("summary", ""):
            runtime.append(SystemMessage(content=f"MEMORY_SUMMARY:\n{memory.get('summary', '')}"))
        if memory.get("user_profile", ""):
            runtime.append(SystemMessage(content=f"USER_PROFILE:\n{memory.get('user_profile', '')[:2200]}"))
        if memory.get("soul", ""):
            runtime.append(SystemMessage(content=f"AGENT_SOUL:\n{memory.get('soul', '')[:2200]}"))
    if role == "executor":
        runtime.append(SystemMessage(content="EXECUTION_PACKET_RULE: 仅依据当前执行包上下文工作。若缺 dirid 先查再建，不要同条件盲重试。"))
    runtime.extend(extract_messages(state))
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
