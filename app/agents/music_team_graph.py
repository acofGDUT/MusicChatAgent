import inspect
import os
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, BaseMessage
from langchain.agents.middleware import SummarizationMiddleware

try:
    from langgraph_supervisor import create_supervisor
except ImportError:
    from langgraph.prebuilt import create_supervisor

from langchain.agents import create_agent

from app.tools.search_tools import search_music_tool, get_hotkeys_tool
from app.tools.playlist_tools import (
    add_songs_to_playlist_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
    add_by_keyword_to_playlist_tool,
)
from app.tools.user_tools import get_created_songlist_tool, get_fav_song_tool


MODEL_NAME = os.getenv("MUSIC_AGENT_MODEL", "glm-4.6v")
MODEL_BASE_URL = os.getenv("MUSIC_AGENT_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MODEL_API_KEY = os.getenv("OPENAI_API_KEY", "")

MAX_CONTEXT_MESSAGES = int(os.getenv("MUSIC_AGENT_MAX_CONTEXT_MESSAGES", "16"))
MAX_EXECUTOR_VISIBLE_MESSAGES = int(os.getenv("MUSIC_AGENT_MAX_EXECUTOR_VISIBLE_MESSAGES", "8"))
SUMMARY_TRIGGER_MESSAGES = int(os.getenv("MUSIC_AGENT_SUMMARY_TRIGGER_MESSAGES", "24"))
MAX_EXECUTOR_REENTRY_WITHOUT_USER = int(os.getenv("MUSIC_AGENT_MAX_EXECUTOR_REENTRY_WITHOUT_USER", "1"))

# ==========================================
# 1. 官方 SummarizationMiddleware 配置
# ==========================================


llm = ChatOpenAI(
    temperature=0,
    model="glm-4.6v"
)
summary_prompt = (
    "请将以下对话总结为【记忆摘要】，必须包含："
    "1) 用户偏好；2) 当前任务状态(进行中/已完成/已中断待用户补充)；3) 实体记忆(歌单名/dirid)；4) 最近失败原因。"
    "严格要求：不要写下一步建议、不要写行动号召指令！输出简体中文，控制在180字内。\n\n{messages}"
)

# 定义全局的上下文压缩中间件
# 当 token 超过 4000 时，自动保留最新的 10 条消息，并将之前的压缩为系统摘要
summarization_mw = SummarizationMiddleware(
    model=llm,
    trigger=("tokens", 4000),
    keep=("messages", 10),
    summary_prompt=summary_prompt
)

def _safe_kwargs(func: Any, candidate_kwargs: dict[str, Any]) -> dict[str, Any]:
    """仅传入目标函数签名中支持的参数，避免版本差异导致报错。"""
    try:
        sig = inspect.signature(func)
        valid = set(sig.parameters.keys())
        return {k: v for k, v in candidate_kwargs.items() if k in valid and v is not None}
    except Exception:
        return {}


def _extract_messages(state: Any) -> list[BaseMessage]:
    if isinstance(state, dict):
        msgs = state.get("messages", [])
        return msgs if isinstance(msgs, list) else []
    return []


def _last_user_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            return content.strip().lower()
    return ""


def _is_smalltalk(text: str) -> bool:
    if not text:
        return False
    smalltalk_keywords = {
        "你好", "hi", "hello", "在吗", "谢谢", "thank", "早上好", "晚上好", "午安", "再见", "bye", "哈哈", "嗯", "ok"
    }
    music_action_keywords = {
        "歌", "音乐", "播放", "搜索", "添加", "删除", "歌单", "收藏", "qq音乐", "专辑", "歌手", "热搜", "推荐"
    }
    if any(k in text for k in music_action_keywords):
        return False
    return any(k in text for k in smalltalk_keywords) or len(text) <= 6


def _trim_keep_recent(messages: list[BaseMessage], keep: int) -> list[BaseMessage]:
    if len(messages) <= keep:
        return messages
    return messages[-keep:]


def _find_existing_summary(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, SystemMessage):
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            if text.startswith("CONVERSATION_SUMMARY:"):
                return text.replace("CONVERSATION_SUMMARY:", "", 1).strip()
    return ""


def _summarize_messages(messages: list[BaseMessage]) -> str:
    dialogue = []
    for m in messages[-SUMMARY_TRIGGER_MESSAGES:]:
        role = "user" if isinstance(m, HumanMessage) else "assistant"
        if isinstance(m, SystemMessage):
            continue
        content = m.content if isinstance(m.content, str) else str(m.content)
        if not content:
            continue
        dialogue.append(f"{role}: {content}")

    if not dialogue:
        return ""

    prompt = (
        "请将以下对话总结为【记忆摘要】，必须包含："
        "1) 用户偏好；2) 当前任务状态(进行中/已完成)；3) 实体记忆(歌单名/dirid/关键词)；4) 最近失败原因。"
        "严格要求：不要写下一步建议、不要写行动号召、不要写应继续执行之类指令。"
        "输出简体中文，控制在180字内。\n\n"
        + "\n".join(dialogue)
    )
    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        return (resp.content if isinstance(resp.content, str) else str(resp.content)).strip()
    except Exception:
        return ""


def _has_new_user_after_last_executor(messages: list[BaseMessage]) -> bool:
    """判断最近一次 MusicExecutor 结果后，是否出现了新的用户消息。"""
    last_executor_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        name = getattr(m, "name", "")
        if isinstance(name, str) and name == "MusicExecutor":
            last_executor_idx = i
            break

    if last_executor_idx < 0:
        return True

    for m in messages[last_executor_idx + 1:]:
        if isinstance(m, HumanMessage):
            return True
    return False


def _get_latest_executor_message(messages: list[BaseMessage]) -> BaseMessage | None:
    for m in reversed(messages):
        name = getattr(m, "name", "")
        if isinstance(name, str) and name == "MusicExecutor":
            return m
    return None


def _latest_executor_looks_done(messages: list[BaseMessage]) -> bool:
    """基于 MusicExecutor 最新输出判断任务是否已完成/终止，避免 supervisor 二次误调用。"""
    done_markers = ["已完成", "操作成功", "成功", "已添加", "已创建", "查询结果", "无法继续", "执行失败"]
    latest = _get_latest_executor_message(messages)
    if latest is None:
        return False
    content = latest.content if isinstance(latest.content, str) else str(latest.content)
    return any(marker in content for marker in done_markers)


def _latest_executor_looks_stuck(messages: list[BaseMessage]) -> bool:
    """识别执行失败/能力不足/参数不匹配等卡住状态，触发强制收敛。"""
    stuck_markers = [
        "失败",
        "可能不在目标歌单中",
        "ID有误",
        "id有误",
        "参数",
        "不支持",
        "无权限",
        "网络",
        "超时",
        "异常",
        "报错",
    ]
    latest = _get_latest_executor_message(messages)
    if latest is None:
        return False
    content = latest.content if isinstance(latest.content, str) else str(latest.content)
    lowered = content.lower()
    return any(marker in content for marker in stuck_markers) or "error" in lowered


def _count_executor_calls_since_last_user(messages: list[BaseMessage]) -> int:
    """统计最近一次用户发言后，MusicExecutor 被调用了多少次。"""
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_user_idx = i
            break

    if last_user_idx < 0:
        return 0

    count = 0
    for m in messages[last_user_idx + 1:]:
        name = getattr(m, "name", "")
        if isinstance(name, str) and name == "MusicExecutor":
            count += 1
    return count


def _supervisor_pre_model_hook(state: Any) -> dict[str, Any]:
    messages = _extract_messages(state)
    if not messages:
        return {}

    updated_messages = messages

    if len(messages) >= SUMMARY_TRIGGER_MESSAGES:
        summary = _summarize_messages(messages)
        trimmed = _trim_keep_recent(messages, MAX_CONTEXT_MESSAGES)
        if summary:
            summary_msg = SystemMessage(content=f"CONVERSATION_SUMMARY: {summary}")
            updated_messages = [summary_msg, *trimmed]
        else:
            updated_messages = trimmed

    # 防重入与死循环收敛：
    # 1) 最新执行已完成且无新用户输入 -> 直接收口到 ChatReplier。
    # 2) 最新执行看起来卡住(工具失败/能力不足)且无新用户输入 -> 不再重试，交给 ChatReplier 解释并请求用户澄清。
    # 3) 同一轮用户输入下，MusicExecutor 调用次数超过阈值 -> 强制停止重试。
    executor_calls = _count_executor_calls_since_last_user(updated_messages)
    no_new_user_after_executor = not _has_new_user_after_last_executor(updated_messages)

    if _latest_executor_looks_done(updated_messages) and no_new_user_after_executor:
        finish_hint = SystemMessage(
            content=(
                "ROUTING_HINT: 最新一次 MusicExecutor 已给出完成/终止结果，"
                "且之后没有新的用户输入。当前轮次请直接路由 ChatReplier 产出最终回复，"
                "禁止再次调用 MusicExecutor。"
            )
        )
        updated_messages = [*updated_messages, finish_hint]

    if _latest_executor_looks_stuck(updated_messages) and no_new_user_after_executor:
        stuck_hint = SystemMessage(
            content=(
                "ROUTING_HINT: 最新一次 MusicExecutor 出现失败/能力边界/参数问题，"
                "且用户尚未提供新信息。请直接路由 ChatReplier："
                "1) 清晰说明失败原因；2) 给出可执行替代方案；3) 请求用户补充信息。"
                "禁止再次调用 MusicExecutor 进行同条件重试。"
            )
        )
        updated_messages = [*updated_messages, stuck_hint]

    if executor_calls > MAX_EXECUTOR_REENTRY_WITHOUT_USER:
        retry_cap_hint = SystemMessage(
            content=(
                "ROUTING_HINT: 同一条用户请求下，MusicExecutor 调用次数已达到上限。"
                "请立即停止继续调用 MusicExecutor，改由 ChatReplier 总结现状与下一步所需信息。"
            )
        )
        updated_messages = [*updated_messages, retry_cap_hint]

    user_text = _last_user_text(updated_messages)
    if _is_smalltalk(user_text):
        route_hint = SystemMessage(
            content=(
                "ROUTING_HINT: 当前用户消息属于寒暄/闲聊，优先直接路由 ChatReplier，"
                "不要调用 MusicExecutor 和任何工具。"
            )
        )
        updated_messages = [*updated_messages, route_hint]

    return {"messages": updated_messages}


def _executor_pre_model_hook(state: Any) -> dict[str, Any]:
    """为 MusicExecutor 做最小可见上下文裁剪：仅保留相关窗口 + 摘要。"""
    messages = _extract_messages(state)
    if not messages:
        return {}

    summary = _find_existing_summary(messages)

    relevant_keywords = {
        "歌", "音乐", "播放", "搜索", "添加", "删除", "歌单", "收藏", "qq音乐", "dirid", "songid", "专辑", "歌手", "热搜"
    }

    relevant: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            continue
        content = m.content if isinstance(m.content, str) else str(m.content)
        if any(k in content.lower() for k in relevant_keywords):
            relevant.append(m)

    if not relevant:
        relevant = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]

    packet = _trim_keep_recent(relevant, MAX_EXECUTOR_VISIBLE_MESSAGES)
    if summary:
        packet = [SystemMessage(content=f"CONTEXT_PACKET_SUMMARY: {summary}"), *packet]

    packet_guard = SystemMessage(
        content=(
            "EXECUTION_PACKET_RULE: 你当前只可依据本执行包中的上下文工作。"
            "忽略与音乐操作无关的历史内容；若信息不足，请先调用必要工具补齐。"
        )
    )

    return {"messages": [packet_guard, *packet]}


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

music_executor_kwargs = {
    "model": llm,
    "tools": tools,
    "prompt": executor_prompt,
    "name": "MusicExecutor",
    "pre_model_hook": _executor_pre_model_hook,
}
music_executor = create_agent(**_safe_kwargs(create_agent, music_executor_kwargs) | {
    "model": llm,
    "tools": tools,
    "prompt": executor_prompt,
    "name": "MusicExecutor",
})

replier_prompt = (
    "你是 ChatReplier。你不调用工具，只负责把执行结果清晰地回复给用户。"
    "\n\n要求："
    "1) 忠实转述 MusicExecutor 的结果，不补造事实；"
    "2) 明确写出歌单名、dirid、成功数量、失败原因；"
    "3) 若用户是寒暄/闲聊，直接自然回应，不要进入工具流程；"
    "4) 若上游提示执行卡住/能力边界：必须停止建议继续重试，改为给出替代方案并请求用户补充必要信息；"
    "5) 语气友好、简洁、自然。"
)

chat_replier = create_agent(
    model=llm,
    tools=[],
    prompt=replier_prompt,
    name="ChatReplier",
)

supervisor_prompt = """
你是 MusicTeamSupervisor，负责在 MusicExecutor（执行者）与 ChatReplier（回复者）之间高效调度。

## 一级路由（先判断是否需要工具）
1. 若用户是寒暄、感谢、闲聊、非音乐账户操作请求：优先路由 ChatReplier。
2. 仅当用户请求涉及 QQ 音乐账户具体操作（搜索/查歌单/增删歌曲/创建歌单等）时，路由 MusicExecutor。

## 二级闭环规则
1. 对于工具任务，仅在 MusicExecutor 明确“已完成”或“已无法继续（且说明原因）”后，才交给 ChatReplier。
2. 添加歌曲类任务在结束前，尽量确保结果里包含：目标歌单名、dirid、成功数量。
3. 若 MusicExecutor 已返回失败/参数错误/能力不足，且用户没有提供新信息，禁止再次调用 MusicExecutor 做同条件重试。
4. 同一条用户请求下，MusicExecutor 重入次数不得超过阈值；超过后必须直接收口给 ChatReplier。

## 输出标准
- 禁止输出“流程已结束”等系统话术。
- 结束阶段应直接输出 ChatReplier 的自然中文回复。
"""

supervisor_kwargs = {
    "agents": [music_executor, chat_replier],
    "model": llm,
    "prompt": supervisor_prompt,
    "pre_model_hook": _supervisor_pre_model_hook,
}
app_graph = create_supervisor(**_safe_kwargs(create_supervisor, supervisor_kwargs) | {
    "agents": [music_executor, chat_replier],
    "model": llm,
    "prompt": supervisor_prompt,
}).compile(name="MusicTeamSupervisor")

graph = app_graph
