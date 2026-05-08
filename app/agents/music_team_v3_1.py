import inspect
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from app.tools.playlist_tools import (
    add_by_keyword_to_playlist_tool,
    add_songs_to_playlist_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
    get_playlist_detail_tool,
)
from app.tools.search_tools import get_hotkeys_tool, search_music_tool
from app.tools.user_tools import get_created_songlist_tool, get_fav_song_tool
from app.tools.song_tools import play_music_tool


# ==========================================
# 1. 环境变量与模型初始化
# ==========================================
MODEL_NAME = os.getenv("MUSIC_AGENT_MODEL", "glm-5")
MUSIC_MODEL_BASE_URL = os.getenv("MUSIC_AGENT_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MUSIC_MODEL_API_KEY = os.getenv("MUSIC_AGENT_API_KEY", "")
MODEL_BASE_URL = os.getenv("OPENAI_API_BASE", "")
MODEL_API_KEY = os.getenv("OPENAI_API_KEY", "")

MAX_EXECUTOR_REENTRY_WITHOUT_USER = int(os.getenv("MUSIC_AGENT_MAX_EXECUTOR_REENTRY_WITHOUT_USER", "1"))
SUMMARY_TRIGGER_TOKENS = int(os.getenv("MUSIC_AGENT_SUMMARY_TRIGGER_TOKENS", "5000"))
SUMMARY_KEEP_MESSAGES = int(os.getenv("MUSIC_AGENT_SUMMARY_KEEP_MESSAGES", "12"))
ENABLE_SOUL_AUTOTUNE = os.getenv("MUSIC_AGENT_ENABLE_SOUL_AUTOTUNE", "false").lower() == "true"

BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory"
USER_PROFILE_PATH = MEMORY_DIR / "user_profile.md"
SOUL_PATH = MEMORY_DIR / "soul.md"
HISTORY_PATH = MEMORY_DIR / "history.jsonl"

llm0 = ChatOpenAI(
    temperature=0,
    model="gpt-4o-mini",
    openai_api_key=MODEL_API_KEY,
    openai_api_base=MODEL_BASE_URL,
)

llm1 = ChatOpenAI(
    temperature=0,
    model=MODEL_NAME,
    openai_api_key=MUSIC_MODEL_API_KEY,
    openai_api_base=MUSIC_MODEL_BASE_URL,
)


# ==========================================
# 2. Prompt
# ==========================================
summary_prompt = (
    "请将以下对话总结为【记忆摘要】，必须包含："
    "1) 用户偏好；2) 当前任务状态(进行中/已完成/已中断待用户补充)；3) 实体记忆(歌单名/dirid/关键词)；4) 最近失败原因。"
    "严格要求：不要写下一步建议、不要写行动号召、不要写应继续执行之类指令。"
    "输出简体中文，控制在400字内。\n\n{messages}"
)

profile_update_prompt = (
    "你是用户画像维护器。根据最新对话，生成对 user_profile.md 的增量更新建议。"
    "仅输出 markdown，保留原有结构，不要编造。若无可靠更新，输出原文。\n\n"
    "[当前画像]\n{profile}\n\n[最新消息]\n{messages}"
)

soul_tune_prompt = (
    "你是 SoulGuardian（保守模式）。你的任务是对 soul.md 做最小必要更新。"
    "只允许改动两个章节中的有限字段：\n"
    "1) ## Style：仅可微调『简洁度』『解释深度』两行；\n"
    "2) ## Decision Policy：仅可微调『信息策略』『失败策略』两行。\n"
    "绝对禁止改动：# 标题、## Identity、## Non-Negotiables、## Evolution Log，以及其他任意行。\n"
    "若上下文不足以支持可靠调整，必须返回原文，不做任何改写。\n"
    "若进行改动，必须满足：\n"
    "- 仅做措辞级微调，不新增新条目、不删除条目、不改章节顺序；\n"
    "- 不引入与执行层 prompt 重复的步骤化规则；\n"
    "- 保持 Soul 的稳定宪法属性，避免会话级短期偏好写入。\n"
    "输出要求：仅输出完整 markdown（不要解释、不要代码块）。\n\n"
    "[soul]\n{soul}\n\n[上下文]\n{messages}"
)


intent_parser_prompt = """
你是 IntentParser，负责做一级意图分流与基础信息抽取。

可选 intent：
- smalltalk: 闲聊、问候、感谢、寒暄
- playback: 播放相关（播放某首歌、播放歌单、点第N首）
- music_ops: 音乐操作（非播放类操作都可以进这个意图）（建歌单/加歌/删歌/搜歌/查歌单）

规则：
1) 仅提取你能从上下文可靠识别的槽位，写入 extracted_slots（如 song_name / artist / keyword / playlist_name / page）。
2) 对“播放”场景，若用户说“播放一首rap歌曲/来点摇滚”等，优先识别为 play_by_keyword 并提取 keyword。
3) 不允许输出 unknown。凡是不属于 smalltalk 且又不明确是 playback 的请求，一律归类为 music_ops。
4) 仅当 intent=smalltalk 时 is_ready_to_execute=false；其他 intent 均为 true。
""".strip()

executor_prompt = """
你是 **MusicExecutor**，只负责 QQ 音乐账户内的“查/增/删/建”操作。

【职责边界】
1) 你只能处理：搜索歌曲、查询歌单、创建歌单、添加歌曲、删除歌曲等账户操作。
2) 遇到“播放/听歌/生成播放器/返回HTML播放标签”相关请求，一律不执行，直接返回："该请求属于播放场景，应交由 PlayAgent 处理"。
3) 不要寒暄，不要解释内部流程，不要输出 Thought/Action。

【执行规则】
1) 任何需要 `dirid` 的操作：若未知 `dirid`，必须先调用 `get_created_songlist_tool` 查询并匹配目标歌单。
2) 目标歌单不存在时：先调用 `create_playlist_tool` 创建，再继续后续步骤。
3) 用户表达“加点某歌手/某风格的歌”时：优先用 `add_by_keyword_to_playlist_tool`。
4) 对 `add_songs_to_playlist_tool`：单次调用后不要在同一轮因同类错误反复换参重试。
5) 缺少关键参数（如歌单名、歌名）时，不要猜测；输出结构化缺参说明并结束本轮。

【输出要求】
- 只输出最终执行结果，简洁中文，禁止中间过程。
- 成功时尽量包含：操作类型、歌单名、dirid、成功数量。
- 失败时仅说明真实失败原因与缺失参数，不给超出职责的建议。
"""

replier_prompt = (
    "你是 ChatReplier。你不调用工具，只负责把执行结果清晰地回复给用户。\n\n"
    "要求：\n"
    "1) 忠实转述上游执行结果；\n"
    "2) 若上游返回 type=play_music 或 type=playlist_browser 的 JSON，优先原样输出 JSON；\n"
    "3) 禁止输出 <audio>/<div> 等 HTML 播放器代码；\n"
    "4) 若为 waiting_user，明确告知缺失参数；\n"
    "5) 若是寒暄/闲聊，直接自然回应。"
)

playback_prompt = """
你是一个专门负责提供音乐播放服务的 **PlayAgent**。
你要支持两类场景：A) 单曲播放；B) 歌单浏览后点播。

【场景A：单曲播放】
1. 提取用户想听的歌名/歌手；若没有 song_mid，先调用 `search_music_tool` 获取。
2. 调用 `play_music_tool` 获取可播放链接。
3. 最终输出 `type=play_music` 的 JSON（禁止输出 HTML）。

【场景B：歌单播放（先列表后点播）】
1. 当用户表达“播放某个歌单/听这个歌单”时，不要直接播单曲，先返回歌单歌曲列表。
2. 若用户给的是歌单名但无 dirid：先用 `get_created_songlist_tool` 匹配到 dirid。
3. 调用 `get_playlist_detail_tool(dirid=..., page=..., num=...)` 拉取歌曲页。
4. 输出 `type=playlist_browser` JSON，供前端渲染列表。
5. 当用户说“播放第N首/点某首”时，再基于该首歌的 song_mid 调用 `play_music_tool`，输出 `type=play_music` JSON。

【分页策略】
- 默认 `num=10`。
- 若歌单总数超过当前页容量，返回 `has_more=true`、`page`、`page_size`、`total_song_num`。
- 用户说“下一页/第N页”时，按页继续调用 `get_playlist_detail_tool`。

【输出协议（严格）】
1) 单曲播放成功：
{
  "type": "play_music",
  "title": "歌曲名",
  "artist": "歌手名",
  "song_mid": "歌曲mid",
  "url": "播放链接",
  "cover": "封面链接(可选)",
  "description": "给用户的简短说明(可选)"
}

2) 歌单浏览页成功：
{
  "type": "playlist_browser",
  "playlist_name": "歌单名",
  "dirid": 123,
  "page": 1,
  "page_size": 10,
  "total_song_num": 86,
  "has_more": true,
  "tracks": [
    {"index": 1, "song_mid": "xxx", "title": "晴天", "artist": "周杰伦", "cover": ""}
  ],
  "description": "已加载第1页，可点击歌曲播放"
}

【强约束】
- 禁止输出 HTML（如 <audio>/<div>）。
- 成功时只输出 JSON（纯 JSON 或 ```json 代码块），不要附加额外自然语言。
- 若工具结果缺少 song_mid，需给出简洁失败原因，不要伪造字段。
"""


# ==========================================
# 3. State 定义
# ==========================================
TaskStatus = Literal["pending", "running", "waiting_user", "done", "failed"]
IntentType = Literal["smalltalk", "music_ops", "playback"]
RouteType = Literal["chat_replier", "music_ops_subgraph", "playback_subgraph"]


class IntentParserDecision(BaseModel):
    intent: Literal["smalltalk", "music_ops", "playback"] = Field(
        description="判断用户的真实意图"
    )
    extracted_slots: Dict[str, str] = Field(
        default_factory=dict,
        description="从上下文中提取的参数，如 playlist_name, keyword 等",
    )
    missing_slots: List[str] = Field(
        default_factory=list,
        description="执行当前 intent 仍然缺失的【必填】参数名。如果全齐则为空列表",
    )
    is_ready_to_execute: bool = Field(
        description="intent 明确且 missing_slots 为空时为 True，否则为 False"
    )


class TaskMeta(TypedDict, total=False):
    id: str
    intent: IntentType
    status: TaskStatus
    goal: str
    required_slots: dict[str, Any]
    extracted_slots: dict[str, str]
    missing_slots: list[str]
    retries: int
    error_code: str | None
    error_reason: str | None


class MemoryMeta(TypedDict, total=False):
    summary: str
    summary_version: int
    user_profile_path: str
    soul_path: str
    history_path: str
    user_profile: str
    soul: str
    last_profile_update_at: str
    last_soul_update_at: str
    last_history_write_at: str


class RuntimeControl(TypedDict, total=False):
    route: RouteType
    executor_reentry: int
    max_reentry: int
    should_summarize: bool
    should_update_profile: bool
    should_update_soul: bool
    is_ready_to_execute: bool


class MusicGraphStateV31(TypedDict, total=False):
    thread_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    task: TaskMeta
    memory: MemoryMeta
    control: RuntimeControl
    extensions: dict[str, Any]


# ==========================================
# 4. 辅助函数
# ==========================================
def _safe_kwargs(func: Any, candidate_kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        sig = inspect.signature(func)
        valid = set(sig.parameters.keys())
        return {k: v for k, v in candidate_kwargs.items() if k in valid and v is not None}
    except Exception:
        return {}


def _extract_messages(state: MusicGraphStateV31) -> list[Any]:
    msgs = state.get("messages", [])
    return msgs if isinstance(msgs, list) else []


def _msg_content(msg: Any) -> str:
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


def _last_user_text(messages: list[Any]) -> str:
    return next((_msg_content(m) for m in reversed(messages) if isinstance(m, HumanMessage)), "")


def _estimate_tokens(messages: list[Any]) -> int:
    return sum(len(_msg_content(m)) for m in messages)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_memory_files() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not USER_PROFILE_PATH.exists():
        USER_PROFILE_PATH.write_text(
            "# 用户画像（User Profile）\n\n"
            "## 基础偏好\n- 常听歌手：\n- 常见风格：\n- 常用语言：\n- 使用场景：\n\n"
            "## 操作习惯\n- 偏好歌单命名：\n- 添加歌曲策略偏好：\n- 是否偏好自动创建歌单：\n\n"
            "## 约束与禁忌\n- 不希望添加的类型：\n- 明确拒绝项：\n\n"
            "## 长期记忆实体\n- 常用歌单（name -> dirid）：\n- 高频关键词：\n\n"
            "## 更新时间\n- last_updated: \n- update_reason: init\n",
            encoding="utf-8",
        )
    if not SOUL_PATH.exists():
        SOUL_PATH.write_text(
            "# Music Agent Soul\n\n"
            "## Identity\n- 我是谁：QQ音乐多代理音乐助理\n- 服务边界：仅执行音乐与播放相关能力\n\n"
            "## Non-Negotiables\n- 不编造工具结果\n- 不在失败后盲重试\n- 未授权不执行高风险操作\n\n"
            "## Style\n- 语气：友好、简洁\n- 简洁度：中\n- 解释深度：按需\n\n"
            "## Decision Policy\n- 成功优先级：高\n- 安全优先级：最高\n- 澄清触发条件：必要槽位缺失\n\n"
            "## Evolution Log\n- version: 1\n- last_updated: init\n- change_summary: init\n- approved_by: system\n",
            encoding="utf-8",
        )
    if not HISTORY_PATH.exists():
        HISTORY_PATH.write_text("", encoding="utf-8")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _safe_message_preview(msg: Any, limit: int = 200) -> str:
    text = _msg_content(msg)
    text = text.replace("\n", " ").strip()
    return text[:limit]


def _collect_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for m in messages:
        name = m.get("name", "") if isinstance(m, dict) else getattr(m, "name", "")
        if name not in {"MusicExecutor", "PlayAgent"}:
            continue
        calls = m.get("tool_calls", None) if isinstance(m, dict) else getattr(m, "tool_calls", None)
        if not isinstance(calls, list):
            continue
        for c in calls:
            if not isinstance(c, dict):
                continue
            tool_calls.append(
                {
                    "agent": name,
                    "tool_name": c.get("name", ""),
                    "args": c.get("args", {}),
                    "call_id": c.get("id", ""),
                }
            )
    return tool_calls


def _extract_last_ai_message(result: Any, fallback_name: str) -> AIMessage:
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


def _build_runtime_messages(state: MusicGraphStateV31, role: str) -> list[BaseMessage]:
    memory = state.get("memory", {})
    summary = memory.get("summary", "")
    profile = memory.get("user_profile", "")
    soul = memory.get("soul", "")

    runtime: list[BaseMessage] = []
    if role != "intent_parser":
        if summary:
            runtime.append(SystemMessage(content=f"MEMORY_SUMMARY:\n{summary}"))
        if profile:
            runtime.append(SystemMessage(content=f"USER_PROFILE:\n{profile[:2200]}"))
        if soul:
            runtime.append(SystemMessage(content=f"AGENT_SOUL:\n{soul[:2200]}"))

    if role == "executor":
        runtime.append(
            SystemMessage(
                content=(
                    "EXECUTION_PACKET_RULE: 仅依据当前执行包上下文工作。"
                    "若缺 dirid 先查再建，不要同条件盲重试。"
                )
            )
        )

    runtime.extend(_extract_messages(state))
    return runtime


def _is_json_like_text(text: str) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json|markdown)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )


def _looks_like_valid_soul_markdown(text: str) -> bool:
    if not text or _is_json_like_text(text):
        return False

    required_sections = [
        "# Music Agent Soul",
        "## Identity",
        "## Non-Negotiables",
        "## Style",
        "## Decision Policy",
        "## Evolution Log",
    ]
    return all(section in text for section in required_sections)


# ==========================================
# 5. Agents
# ==========================================
music_ops_tools = [
    search_music_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
    get_created_songlist_tool,
    get_fav_song_tool,
    add_songs_to_playlist_tool,
    get_hotkeys_tool,
    add_by_keyword_to_playlist_tool,
    get_playlist_detail_tool,
]

playback_tools = [search_music_tool, get_created_songlist_tool, get_playlist_detail_tool, play_music_tool]

music_executor = create_agent(
    **_safe_kwargs(
        create_agent,
        {
            "model": llm1,
            "tools": music_ops_tools,
            "system_prompt": executor_prompt,
            "name": "MusicExecutor",
        },
    )
    | {
        "model": llm1,
        "tools": music_ops_tools,
        "system_prompt": executor_prompt,
        "name": "MusicExecutor",
    }
)

playback_executor = create_agent(
    **_safe_kwargs(
        create_agent,
        {
            "model": llm1,
            "tools": playback_tools,
            "system_prompt": playback_prompt,
            "name": "PlayAgent",
        },
    )
    | {
        "model": llm1,
        "tools": playback_tools,
        "system_prompt": playback_prompt,
        "name": "PlayAgent",
    }
)

chat_replier = create_agent(
    **_safe_kwargs(
        create_agent,
        {
            "model": llm0,
            "tools": [],
            "system_prompt": replier_prompt,
            "name": "ChatReplier",
        },
    )
    | {
        "model": llm0,
        "tools": [],
        "system_prompt": replier_prompt,
        "name": "ChatReplier",
    }
)


# ==========================================
# 6. Nodes
# ==========================================
def init_memory_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    _ensure_memory_files()
    memory = dict(state.get("memory", {}))
    memory.setdefault("user_profile_path", str(USER_PROFILE_PATH))
    memory.setdefault("soul_path", str(SOUL_PATH))
    memory.setdefault("history_path", str(HISTORY_PATH))
    memory["user_profile"] = _read_text(USER_PROFILE_PATH)
    memory["soul"] = _read_text(SOUL_PATH)

    control = dict(state.get("control", {}))
    control.setdefault("max_reentry", MAX_EXECUTOR_REENTRY_WITHOUT_USER)
    control.setdefault("executor_reentry", 0)

    task = dict(state.get("task", {}))
    task.setdefault("status", "pending")
    task.setdefault("retries", 0)

    return {**state, "memory": memory, "control": control, "task": task}


def intent_parser_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    task = dict(state.get("task", {}))
    control = dict(state.get("control", {}))
    messages = _extract_messages(state)
    last_user_text = _last_user_text(messages)

    parser_messages: list[BaseMessage] = [SystemMessage(content=intent_parser_prompt)]
    parser_messages.extend(_build_runtime_messages(state, role="intent_parser"))

    parsed: dict[str, Any] = {}
    parser_failed = False
    parser_error_reason = ""
    try:
        structured_llm = llm0.with_structured_output(IntentParserDecision)
        structured_decision = structured_llm.invoke(parser_messages)
        parsed = structured_decision.model_dump() if hasattr(structured_decision, "model_dump") else dict(structured_decision)
    except Exception as structured_err:
        try:
            raw_decision = llm0.invoke(parser_messages)
            raw_text = _msg_content(raw_decision).strip()

            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                raw_text = re.sub(r"\s*```$", "", raw_text).strip()

            try:
                parsed = json.loads(raw_text)
            except Exception:
                parsed = {}
        except Exception as raw_err:
            parser_failed = True
            parser_error_reason = (
                f"intent_parser模型不可用: structured={type(structured_err).__name__}; raw={type(raw_err).__name__}"
            )
            parsed = {}

    intent = parsed.get("intent", "music_ops")
    if intent not in {"smalltalk", "music_ops", "playback"}:
        intent = "music_ops"

    extracted_slots = parsed.get("extracted_slots", {})
    if not isinstance(extracted_slots, dict):
        extracted_slots = {}

    # 取消全局槽位硬校验：由工具调用结果决定成功/失败与是否追问
    required_slots: dict[str, Any] = {}
    missing_slots: list[str] = []

    is_ready_to_execute = intent in {"music_ops", "playback"}
    if intent == "smalltalk":
        is_ready_to_execute = False

    task.update(
        {
            "intent": intent,
            "goal": last_user_text,
            "required_slots": required_slots,
            "missing_slots": missing_slots,
            "extracted_slots": extracted_slots,
            "status": "pending",
        }
    )

    if parser_failed:
        task["status"] = "failed"
        task["error_reason"] = parser_error_reason or "intent_parser模型不可用"
        control["is_ready_to_execute"] = False
    else:
        control["is_ready_to_execute"] = bool(is_ready_to_execute)

    return {**state, "task": task, "control": control}


def supervisor_router_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    task = dict(state.get("task", {}))
    control = dict(state.get("control", {}))

    intent = task.get("intent", "music_ops")
    is_ready_to_execute = bool(control.get("is_ready_to_execute", False))

    if not is_ready_to_execute:
        task["status"] = "done"
        control["route"] = "chat_replier"
        return {**state, "task": task, "control": control}

    reentry = int(control.get("executor_reentry", 0))
    max_reentry = int(control.get("max_reentry", MAX_EXECUTOR_REENTRY_WITHOUT_USER))
    if reentry >= max_reentry:
        task["status"] = "failed"
        task["error_reason"] = "达到最大重入次数，停止同条件重试"
        control["route"] = "chat_replier"
        return {**state, "task": task, "control": control}

    task["status"] = "running"
    task.pop("error_reason", None)
    if intent == "music_ops":
        control["route"] = "music_ops_subgraph"
    elif intent == "playback":
        control["route"] = "playback_subgraph"
    else:
        control["route"] = "chat_replier"
    return {**state, "task": task, "control": control}


async def music_ops_subgraph_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    runtime_messages = _build_runtime_messages(state, role="executor")
    result = await music_executor.ainvoke({"messages": runtime_messages})
    ai_msg = _extract_last_ai_message(result, fallback_name="MusicExecutor")

    messages = _extract_messages(state)
    task = dict(state.get("task", {}))
    control = dict(state.get("control", {}))

    content = str(ai_msg.content)
    looks_fail = any(k in content for k in ["失败", "报错", "异常", "无权限", "超时", "不支持"])
    task["status"] = "failed" if looks_fail else "done"
    if looks_fail:
        task["error_reason"] = content[:300]

    control["executor_reentry"] = int(control.get("executor_reentry", 0)) + 1
    return {**state, "messages": [*messages, ai_msg], "task": task, "control": control}


async def playback_subgraph_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    runtime_messages = _build_runtime_messages(state, role="playback")
    result = await playback_executor.ainvoke({"messages": runtime_messages})
    ai_msg = _extract_last_ai_message(result, fallback_name="PlayAgent")

    messages = _extract_messages(state)
    task = dict(state.get("task", {}))

    content = str(ai_msg.content)
    if "未接入" in content or "不支持" in content:
        task["status"] = "failed"
        task["error_reason"] = content[:300]
    else:
        task["status"] = "done"

    return {**state, "messages": [*messages, ai_msg], "task": task}


def memory_sync_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    messages = _extract_messages(state)
    memory = dict(state.get("memory", {}))
    control = dict(state.get("control", {}))
    task = dict(state.get("task", {}))

    should_summarize = _estimate_tokens(messages) >= SUMMARY_TRIGGER_TOKENS
    should_update_profile = bool(messages) and task.get("status") in {"done", "waiting_user"}
    should_update_soul = ENABLE_SOUL_AUTOTUNE and task.get("status") == "done"

    control["should_summarize"] = should_summarize
    control["should_update_profile"] = should_update_profile
    control["should_update_soul"] = should_update_soul

    if should_summarize:
        summary_input = "\n".join([
            f"{(m.get('type', 'unknown') if isinstance(m, dict) else getattr(m, 'type', 'unknown'))}:{_msg_content(m)}"
            for m in messages
        ])
        summary_result = llm0.invoke(summary_prompt.format(messages=summary_input))
        memory["summary"] = _msg_content(summary_result)
        memory["summary_version"] = int(memory.get("summary_version", 0)) + 1
        if len(messages) > SUMMARY_KEEP_MESSAGES:
            state["messages"] = messages[-SUMMARY_KEEP_MESSAGES:]

    profile_text = memory.get("user_profile", _read_text(USER_PROFILE_PATH))
    soul_text = memory.get("soul", _read_text(SOUL_PATH))

    if should_update_profile:
        latest = "\n".join([_msg_content(m) for m in messages[-6:]])
        new_profile = llm0.invoke(
            profile_update_prompt.format(profile=profile_text, messages=latest)
        )
        profile_text = _msg_content(new_profile)
        _write_text(USER_PROFILE_PATH, profile_text)
        memory["user_profile"] = profile_text
        memory["last_profile_update_at"] = _now_iso()

    if should_update_soul:
        latest = "\n".join([_msg_content(m) for m in messages[-6:]])
        tuned = llm0.invoke(soul_tune_prompt.format(soul=soul_text, messages=latest))
        candidate_soul = _msg_content(tuned)

        if _looks_like_valid_soul_markdown(candidate_soul):
            soul_text = candidate_soul
            _write_text(SOUL_PATH, soul_text)
            memory["soul"] = soul_text
            memory["last_soul_update_at"] = _now_iso()

    history_event = {
        "timestamp": _now_iso(),
        "event_id": str(uuid.uuid4()),
        "thread_id": state.get("thread_id", ""),
        "intent": task.get("intent", "music_ops"),
        "task_status": task.get("status", "pending"),
        "error_reason": task.get("error_reason", ""),
        "tool_calls": _collect_tool_calls(messages[-12:]),
        "message_count": len(messages),
        "message_tail": [
            {
                "type": (m.get("type", "unknown") if isinstance(m, dict) else getattr(m, "type", "unknown")),
                "name": (m.get("name", "") if isinstance(m, dict) else getattr(m, "name", "")),
                "preview": _safe_message_preview(m),
            }
            for m in messages[-3:]
        ],
        "memory_update": {
            "summary": should_summarize,
            "profile": should_update_profile,
            "soul": should_update_soul,
        },
    }
    _append_jsonl(HISTORY_PATH, history_event)
    memory["last_history_write_at"] = history_event["timestamp"]

    return {**state, "memory": memory, "control": control}


async def chat_replier_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    task = state.get("task", {})
    status = task.get("status", "done")

    messages = _extract_messages(state)
    guidance = SystemMessage(
        content=(
            f"TASK_STATUS={status}; "
            f"INTENT={task.get('intent', 'music_ops')}; "
            f"MISSING={','.join(task.get('missing_slots', []))}; "
            f"ERROR={task.get('error_reason', '')}"
        )
    )
    runtime_messages = [guidance, *_build_runtime_messages(state, role="replier")]

    result = await chat_replier.ainvoke({"messages": runtime_messages})
    ai_msg = _extract_last_ai_message(result, fallback_name="ChatReplier")

    control = dict(state.get("control", {}))
    control["executor_reentry"] = 0

    return {**state, "messages": [*messages, ai_msg], "control": control}


def finalizer_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    control = dict(state.get("control", {}))
    control.pop("route", None)
    return {**state, "control": control}


def route_after_supervisor(state: MusicGraphStateV31) -> str:
    control = state.get("control", {})
    return control.get("route", "chat_replier")


# ==========================================
# 7. Graph
# ==========================================
graph_builder = StateGraph(MusicGraphStateV31)

graph_builder.add_node("init_memory", init_memory_node)
graph_builder.add_node("intent_parser", intent_parser_node)
graph_builder.add_node("supervisor_router", supervisor_router_node)
graph_builder.add_node("music_ops_subgraph", music_ops_subgraph_node)
graph_builder.add_node("playback_subgraph", playback_subgraph_node)
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

graph_builder.add_edge("music_ops_subgraph", "memory_sync")
graph_builder.add_edge("playback_subgraph", "memory_sync")
graph_builder.add_edge("memory_sync", "chat_replier")
graph_builder.add_edge("chat_replier", "finalizer")
graph_builder.add_edge("finalizer", END)

graph = graph_builder.compile(name="MusicTeamGraphV31")
