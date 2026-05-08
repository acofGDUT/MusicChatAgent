import inspect
import json
import os
import re
from typing import Any, Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

try:
    from langgraph.checkpoint.memory import MemorySaver
except Exception:
    MemorySaver = None

from app.tools.playlist_tools import (
    add_by_keyword_to_playlist_tool,
    add_songs_to_playlist_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
)
from app.tools.search_tools import get_hotkeys_tool, search_music_tool
from app.tools.user_tools import get_created_songlist_tool, get_fav_song_tool

MODEL_NAME = os.getenv("MUSIC_AGENT_MODEL", "glm-5")
MUSIC_MODEL_BASE_URL = os.getenv("MUSIC_AGENT_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MUSIC_MODEL_API_KEY = os.getenv("MUSIC_AGENT_API_KEY", "")
MODEL_BASE_URL = os.getenv("OPENAI_API_BASE", "")
MODEL_API_KEY = os.getenv("OPENAI_API_KEY", "")

MAX_EXECUTOR_REENTRY_WITHOUT_USER = int(os.getenv("MUSIC_AGENT_MAX_EXECUTOR_REENTRY_WITHOUT_USER", "1"))
SUMMARY_TRIGGER_TOKENS = int(os.getenv("MUSIC_AGENT_SUMMARY_TRIGGER_TOKENS", "5000"))
SUMMARY_KEEP_MESSAGES = int(os.getenv("MUSIC_AGENT_SUMMARY_KEEP_MESSAGES", "10"))

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

summary_prompt = (
    "请将以下对话总结为【记忆摘要】，必须包含："
    "1) 用户偏好；2) 当前任务状态(进行中/已完成/已中断待用户补充)；3) 实体记忆(歌单名/dirid/关键词)；4) 最近失败原因。"
    "严格要求：不要写下一步建议、不要写行动号召、不要写应继续执行之类指令。"
    "输出简体中文，控制在400字内。\n\n{messages}"
)

supervisor_router_prompt = """
你是 MusicTeamSupervisor。你只负责下一步路由决策，不执行工具。

可选 route：executor / memory_manager / replier / end

决策规则：
1) 用户是闲聊/感谢/寒暄，优先 replier。
2) 若音乐任务仍需工具执行，选 executor。
3) 若执行结果已完成、失败、卡住或需用户补充，选 replier。
4) 当一个完整任务已结束（done/stuck）或你认为需要归档时，可选 memory_manager。
5) 若已经给出最终用户答复，可选 end。
6) 不允许同条件下无限重试 executor。
7) 若本轮已执行过 memory_manager，不要再次选择 memory_manager。

你必须只输出 JSON：
{"route":"executor|memory_manager|replier|end","task_status":"idle|running|done|stuck","reason":"简短原因"}
"""

executor_prompt = """
## Role
你是一个专业的音乐助理 **MusicExecutor**，负责通过调用工具精确执行用户对 QQ 音乐账户的操作指令。

## Core Principles
1. **原生工具调用**：直接生成工具调用（Tool Calling），禁止输出 `Thought:`、`Action:` 或任何过程文本。
2. **目标优先**：确保操作准确触达目标歌单。如果目标歌单不存在，必须先创建。
3. **最小上下文**：你只能使用当前执行包中的信息，不要引用无关闲聊历史。
4. **静默执行**：除了最终的简洁中文总结外，不要向用户输出任何中间步骤。

## Workflow Logic
1. **dirid 获取与校验（关键环节）**：
   - 任何涉及 `dirid` 参数的工具，若你不知道目标歌单的 `dirid`，必须先调用 `get_created_songlist_tool` 获取并匹配。
   - 若未找到目标歌单，先调用 `create_playlist_tool` 创建，再继续。

2. **加歌策略**：
   - 用户说“给某歌单加点某人的歌”，优先使用 `add_by_keyword_to_playlist_tool`。
   - 数量默认添加 5 首。若语义明确为单首，则设为 1。

3. **关于 add_songs_to_playlist_tool 的规则**：
   - 该工具已内置“成功/静默去重/已知异常”的兜底语义。
   - 调用后不要因 False 或已知异常再次更换 song_ids 重复重试。

## Output Requirement
任务结束后，仅回复简洁中文总结：
- 目标歌单：[名称]
- dirid：[若可得]
- 成功执行：[数量]
- 异常反馈：[仅在最终失败时说明]

查询类任务请结构化回复，并严格基于工具结果，不得编造。
"""

replier_prompt = (
    "你是 ChatReplier。你不调用工具，只负责把执行结果清晰地回复给用户。"
    "\n\n要求："
    "1) 忠实转述 MusicExecutor 的结果，不补造事实；"
    "2) 明确写出歌单名、dirid、成功数量、失败原因；"
    "3) 若用户是寒暄/闲聊，直接自然回应，不要进入工具流程；"
    "4) 若上游提示执行卡住/能力边界：必须停止建议继续重试，改为给出替代方案并请求用户补充必要信息；"
    "5) 语气友好、简洁、自然。"
)


class MusicGraphState(TypedDict, total=False):
    messages: list[BaseMessage]
    summary: str
    route: Literal["executor", "memory_manager", "replier", "end"]
    executor_reentry: int
    last_executor_output: str | None
    task_status: Literal["idle", "running", "done", "stuck"]
    supervisor_reason: str
    memory_managed_this_turn: bool
    last_user_message_fingerprint: str
    extensions: dict[str, Any]


def _safe_kwargs(func: Any, candidate_kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        sig = inspect.signature(func)
        valid = set(sig.parameters.keys())
        return {k: v for k, v in candidate_kwargs.items() if k in valid and v is not None}
    except Exception:
        return {}


def _extract_messages(state: MusicGraphState) -> list[BaseMessage]:
    msgs = state.get("messages", [])
    return msgs if isinstance(msgs, list) else []


def _estimate_tokens(messages: list[BaseMessage]) -> int:
    return sum(len(str(m.content)) for m in messages)


def _build_runtime_messages(state: MusicGraphState, role: Literal["executor", "replier"]) -> list[BaseMessage]:
    messages = _extract_messages(state)
    summary = state.get("summary", "")

    runtime: list[BaseMessage] = []
    if summary:
        runtime.append(SystemMessage(content=f"MEMORY_SUMMARY:\n{summary}"))

    if role == "executor":
        runtime.append(
            SystemMessage(
                content=(
                    "EXECUTION_PACKET_RULE: 你当前只可依据本执行包中的上下文工作。"
                    "若缺乏目标歌单 dirid，必须先查再建。不要因单个错误反复更换参数重试。"
                )
            )
        )

    runtime.extend(messages)
    return runtime


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


def _current_user_fingerprint(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return ""


def _sync_turn_state(state: MusicGraphState) -> MusicGraphState:
    messages = _extract_messages(state)
    current_fp = _current_user_fingerprint(messages)
    previous_fp = state.get("last_user_message_fingerprint", "")

    if current_fp and current_fp != previous_fp:
        return {
            **state,
            "memory_managed_this_turn": False,
            "last_user_message_fingerprint": current_fp,
            "executor_reentry": 0,
        }
    return state


def _precheck_route(state: MusicGraphState) -> str:
    messages = _extract_messages(state)
    overloaded = _estimate_tokens(messages) >= SUMMARY_TRIGGER_TOKENS
    already_managed = bool(state.get("memory_managed_this_turn", False))
    if overloaded and not already_managed:
        return "memory_manager"
    return "supervisor"


def _supervisor_fallback_route(state: MusicGraphState) -> tuple[str, str, str]:
    messages = _extract_messages(state)
    reentry = int(state.get("executor_reentry", 0))

    if reentry >= MAX_EXECUTOR_REENTRY_WITHOUT_USER:
        return "replier", "stuck", "达到最大重试次数，强制收口回复用户"

    if _estimate_tokens(messages) >= SUMMARY_TRIGGER_TOKENS and not state.get("memory_managed_this_turn", False):
        return "memory_manager", state.get("task_status", "running"), "消息过长，先记忆管理"

    if messages and isinstance(messages[-1], HumanMessage):
        return "executor", "running", "最后一条是用户消息，进入执行"

    return "replier", state.get("task_status", "idle"), "默认收口为用户回复"


def _extract_json_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()

    # 1) 直接 JSON
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 2) markdown fenced code block
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    # 3) 文本中抽取第一个平衡花括号对象
    start = cleaned.find("{")
    if start != -1:
        depth = 0
        for idx in range(start, len(cleaned)):
            ch = cleaned[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start: idx + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        break

    raise ValueError("unable to parse supervisor json payload")


def _normalize_supervisor_decision(data: dict[str, Any]) -> tuple[str, str, str]:
    route = str(data.get("route", "")).strip()
    task_status = str(data.get("task_status", "running")).strip()
    reason = str(data.get("reason", "")).strip() or "llm supervisor decision"

    if route not in {"executor", "memory_manager", "replier", "end"}:
        # 容错：尝试别名映射
        alias_map = {
            "summarizer": "memory_manager",
            "summary": "memory_manager",
            "reply": "replier",
            "chat": "replier",
            "finish": "end",
            "stop": "end",
        }
        route = alias_map.get(route, "")

    if route not in {"executor", "memory_manager", "replier", "end"}:
        raise ValueError("invalid route")

    if task_status not in {"idle", "running", "done", "stuck"}:
        task_status = "running"

    return route, task_status, reason


def _supervisor_llm_route(state: MusicGraphState) -> tuple[str, str, str]:
    messages = _extract_messages(state)
    summary = state.get("summary", "")
    reentry = int(state.get("executor_reentry", 0))
    already_managed = bool(state.get("memory_managed_this_turn", False))

    recent_messages = messages[-12:]
    compact = "\n".join([f"{getattr(m, 'type', 'unknown')}:{m.content}" for m in recent_messages])
    prompt = (
        f"当前 executor_reentry={reentry}, 最大允许={MAX_EXECUTOR_REENTRY_WITHOUT_USER}\n"
        f"本轮 memory_manager 是否已执行={already_managed}\n"
        f"当前已有摘要（可空）:\n{summary}\n\n"
        f"最近消息:\n{compact}\n"
    )

    try:
        decision = llm0.invoke(
            [
                SystemMessage(content=supervisor_router_prompt),
                HumanMessage(content=prompt),
            ]
        )
        raw = str(decision.content).strip()
        data = _extract_json_payload(raw)
        route, task_status, reason = _normalize_supervisor_decision(data)

        if route == "executor" and reentry >= MAX_EXECUTOR_REENTRY_WITHOUT_USER:
            return "replier", "stuck", "达到最大重试次数，覆盖LLM路由"

        if route == "memory_manager" and already_managed:
            return "replier", task_status, "本轮已做记忆管理，阻断循环"

        return route, task_status, reason
    except Exception:
        return _supervisor_fallback_route(state)


tools = [
    search_music_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
    get_created_songlist_tool,
    get_fav_song_tool,
    add_songs_to_playlist_tool,
    get_hotkeys_tool,
    add_by_keyword_to_playlist_tool,
]

music_executor = create_agent(
    **_safe_kwargs(
        create_agent,
        {
            "model": llm1,
            "tools": tools,
            "system_prompt": executor_prompt,
            "name": "MusicExecutor",
        },
    )
    | {
        "model": llm1,
        "tools": tools,
        "system_prompt": executor_prompt,
        "name": "MusicExecutor",
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


def precheck_node(state: MusicGraphState) -> MusicGraphState:
    return _sync_turn_state(state)


def supervisor_node(state: MusicGraphState) -> MusicGraphState:
    route, task_status, reason = _supervisor_llm_route(state)
    return {**state, "route": route, "task_status": task_status, "supervisor_reason": reason}


def executor_node(state: MusicGraphState) -> MusicGraphState:
    runtime_messages = _build_runtime_messages(state, role="executor")
    result = music_executor.invoke({"messages": runtime_messages})
    ai_msg = _extract_last_ai_message(result, fallback_name="MusicExecutor")

    messages = _extract_messages(state)
    return {
        **state,
        "messages": [*messages, ai_msg],
        "last_executor_output": str(ai_msg.content),
        "executor_reentry": int(state.get("executor_reentry", 0)) + 1,
    }


def memory_manager_node(state: MusicGraphState) -> MusicGraphState:
    messages = _extract_messages(state)
    if not messages:
        return {**state, "memory_managed_this_turn": True}

    if _estimate_tokens(messages) < SUMMARY_TRIGGER_TOKENS:
        return {**state, "memory_managed_this_turn": True}

    keep_messages = messages[-SUMMARY_KEEP_MESSAGES:]
    summary_input = "\n".join([f"{getattr(m, 'type', 'unknown')}:{m.content}" for m in messages])
    summary_result = llm0.invoke(summary_prompt.format(messages=summary_input))
    summary_text = str(summary_result.content)

    return {
        **state,
        "summary": summary_text,
        "messages": keep_messages,
        "memory_managed_this_turn": True,
    }


def replier_node(state: MusicGraphState) -> MusicGraphState:
    runtime_messages = _build_runtime_messages(state, role="replier")
    result = chat_replier.invoke({"messages": runtime_messages})
    ai_msg = _extract_last_ai_message(result, fallback_name="ChatReplier")

    messages = _extract_messages(state)
    return {
        **state,
        "messages": [*messages, ai_msg],
        "executor_reentry": 0,
    }


def route_after_precheck(state: MusicGraphState) -> str:
    return _precheck_route(state)


def route_after_supervisor(state: MusicGraphState) -> str:
    route = state.get("route", "replier")
    return route if route in {"executor", "memory_manager", "replier", "end"} else "replier"


graph_builder = StateGraph(MusicGraphState)

graph_builder.add_node("precheck", precheck_node)
graph_builder.add_node("supervisor", supervisor_node)
graph_builder.add_node("executor", executor_node)
graph_builder.add_node("memory_manager", memory_manager_node)
graph_builder.add_node("replier", replier_node)

graph_builder.add_edge(START, "precheck")

graph_builder.add_conditional_edges(
    "precheck",
    route_after_precheck,
    {
        "memory_manager": "memory_manager",
        "supervisor": "supervisor",
    },
)

graph_builder.add_conditional_edges(
    "supervisor",
    route_after_supervisor,
    {
        "executor": "executor",
        "memory_manager": "memory_manager",
        "replier": "replier",
        "end": END,
    },
)

graph_builder.add_edge("executor", "supervisor")
graph_builder.add_edge("memory_manager", "supervisor")
graph_builder.add_edge("replier", END)

if MemorySaver:
    graph = graph_builder.compile(checkpointer=MemorySaver())
else:
    graph = graph_builder.compile()
