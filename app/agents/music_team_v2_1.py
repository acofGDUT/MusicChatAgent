import inspect
import os
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage

# 根据你提供的文档，导入官方的中间件
try:
    from langchain.agents.middleware import SummarizationMiddleware
except ImportError:
    SummarizationMiddleware = None

try:
    from langgraph_supervisor import create_supervisor
except ImportError:
    from langgraph.prebuilt import create_supervisor

from langchain.agents import create_agent

# ==========================================
# 0. 导入工具
# ==========================================
from app.tools.search_tools import search_music_tool, get_hotkeys_tool
from app.tools.playlist_tools import (
    add_songs_to_playlist_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
    add_by_keyword_to_playlist_tool,
)
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

llm0 = ChatOpenAI(temperature=0, model="gpt-4o-mini", openai_api_key=MODEL_API_KEY, openai_api_base=MODEL_BASE_URL)
llm1 = ChatOpenAI(temperature=0, model=MODEL_NAME, openai_api_key=MUSIC_MODEL_API_KEY, openai_api_base=MUSIC_MODEL_BASE_URL)

# ==========================================
# 2. 官方 SummarizationMiddleware 配置
# ==========================================
summary_prompt = (
    "请将以下对话总结为【记忆摘要】，必须包含："
    "1) 用户偏好；2) 当前任务状态(进行中/已完成/已中断待用户补充)；3) 实体记忆(歌单名/dirid/关键词)；4) 最近失败原因。"
    "严格要求：不要写下一步建议、不要写行动号召、不要写应继续执行之类指令。"
    "输出简体中文，控制在400字内。\n\n{messages}"
)

if SummarizationMiddleware:
    summarization_mw = SummarizationMiddleware(model=llm0, trigger=("tokens", 5000), keep=("messages", 10), summary_prompt=summary_prompt)
else:
    summarization_mw = None

# ==========================================
# 3. 辅助函数
# ==========================================
def _safe_kwargs(func: Any, candidate_kwargs: dict[str, Any]) -> dict[str, Any]:
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


def _get_latest_worker_msg(messages: list[BaseMessage]) -> BaseMessage | None:
    # 同时查找 MusicExecutor 和 PlayAgent 的最新消息
    for m in reversed(messages):
        if getattr(m, "name", "") in ["MusicExecutor", "PlayAgent"]:
            return m
    return None


def _is_smalltalk(text: str) -> bool:
    if not text:
        return False
    smalltalk_keywords = {"你好", "hi", "hello", "在吗", "谢谢", "thank", "早上好", "晚上好", "午安", "再见", "bye", "哈哈", "嗯", "ok"}
    return any(k in text.lower() for k in smalltalk_keywords) and len(text) <= 6


# ==========================================
# 4. 路由与执行 Hook
# ==========================================
def _supervisor_pre_model_hook(state: Any) -> dict[str, Any]:
    messages = _extract_messages(state)
    if not messages:
        return {}

    updated_messages = list(messages)
    last_user_text = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "").lower()

    if _is_smalltalk(last_user_text):
        updated_messages.append(SystemMessage(content="ROUTING_HINT: 用户正在闲聊，直接路由 ChatReplier，严禁调用其他 Worker。"))
        return {"messages": updated_messages}

    latest_worker_msg = _get_latest_worker_msg(messages)
    if not latest_worker_msg:
        return {"messages": updated_messages}

    no_new_user = not isinstance(messages[-1], HumanMessage)
    content = str(latest_worker_msg.content)

    looks_done = any(k in content for k in ["已完成", "操作成功", "成功", "已添加", "已创建", "查询结果", "<audio", "<div"])
    looks_stuck = any(k in content for k in ["失败", "有误", "参数", "无权限", "异常", "可能不在目标歌单中", "报错", "超时", "不支持", "无法获取"])

    if no_new_user and (looks_done or looks_stuck):
        status_str = "已成功/结束" if looks_done else "已失败/卡住"
        worker_name = latest_worker_msg.name
        updated_messages.append(SystemMessage(
            content=f"ROUTING_HINT: 最新一次 {worker_name} 任务 {status_str}，且用户未提供新指令。"
                    "【强制指令】：立即路由给 ChatReplier 进行转述或最终渲染，禁止再次调用任何工具 Agent 重试！"
        ))

    return {"messages": updated_messages}


def _worker_pre_model_hook(state: Any) -> dict[str, Any]:
    messages = _extract_messages(state)
    if not messages:
        return {}
    rule_guard = SystemMessage(
        content="EXECUTION_PACKET_RULE: 你当前只可依据本执行包中的上下文工作。不要因单个错误反复更换参数重试。"
    )
    return {"messages": [rule_guard, *messages]}


# ==========================================
# 5. Agent 构建
# ==========================================

# --- A. 账户操作专员 (MusicExecutor) ---
executor_tools = [
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

music_executor = create_agent(**_safe_kwargs(create_agent, {
    "model": llm1,
    "tools": executor_tools,
    "system_prompt": executor_prompt,
    "name": "MusicExecutor",
    "pre_model_hook": _worker_pre_model_hook,
    "middleware": [summarization_mw] if summarization_mw else [],
}) | {
    "model": llm1,
    "tools": executor_tools,
    "system_prompt": executor_prompt,
    "name": "MusicExecutor",
})

# --- B. 音乐播放专员 (PlayAgent) ---
playagent_tools = [search_music_tool, play_music_tool]
playagent_prompt = """
你是一个专门负责提供音乐播放服务的 **PlayAgent**。
当用户明确要求“播放”、“听”某首歌时，由你来执行。

执行流程：
1. 提取用户想听的歌名/歌手。如果你不知道该歌曲的 song_mid，必须先调用 `search_music_tool` 搜索获取。
2. 拿到 song_mid 后，调用 `play_music_tool` 获取播放链接。
3. `play_music_tool` 会返回一段包含 <audio> 标签的 HTML 代码。你拿到后，将其作为最终结果输出即可，不要做额外修改。
"""

play_agent = create_agent(**_safe_kwargs(create_agent, {
    "model": llm1,
    "tools": playagent_tools,
    "system_prompt": playagent_prompt,
    "name": "PlayAgent",
    "pre_model_hook": _worker_pre_model_hook,
    "middleware": [summarization_mw] if summarization_mw else [],
}) | {
    "model": llm1,
    "tools": playagent_tools,
    "system_prompt": playagent_prompt,
    "name": "PlayAgent",
})

# --- C. 客服专员 (ChatReplier) ---
replier_prompt = (
    "你是 ChatReplier。你不调用工具，只负责把执行结果清晰地回复给用户。\n\n"
    "要求：\n"
    "1) 忠实转述 MusicExecutor 的结果。\n"
    "2) 核心规则：如果上游 Agent (如 PlayAgent) 的反馈中包含 `<audio>`、`<div>` 等 HTML 播放器代码，"
    "你必须在最终回复中原封不动地输出这些 HTML 代码，绝对不可删除、精简或转义它们！\n"
    "3) 若用户是寒暄/闲聊，直接自然回应；\n"
    "4) 语气友好、自然。"
)

chat_replier = create_agent(model=llm0, tools=[], system_prompt=replier_prompt, name="ChatReplier")

# --- D. 路由主管 (Supervisor) ---
supervisor_prompt = """
你是 MusicTeamSupervisor，负责在 MusicExecutor（账户操作）、PlayAgent（播放音乐）与 ChatReplier（回复者）之间高效调度。

## 一级路由（场景判断）
1. 若用户明确要求“播放”、“听”某首歌，立刻路由给 **PlayAgent**。
2. 若用户请求涉及 QQ 音乐账户具体操作（搜歌单/加歌单/删歌单），路由给 **MusicExecutor**。
3. 若用户是纯寒暄、感谢，或者上游任务已完成/报错，路由给 **ChatReplier** 总结输出。
4. 如果用户表达模糊（如只说了一首歌名），默认当做搜索/播放处理，路由给 **PlayAgent**。

## 二级闭环规则
1. 仅在干活的 Agent 明确完成任务，或反馈无法继续（版权限制/报错）时，才交给 ChatReplier。
2. 结束阶段应直接输出 ChatReplier 的最终回复，禁止输出“流程已结束”等废话。
"""

app_graph = create_supervisor(**_safe_kwargs(create_supervisor, {
    "agents": [music_executor, play_agent, chat_replier],
    "model": llm0,
    "prompt": supervisor_prompt,
    "pre_model_hook": _supervisor_pre_model_hook,
    "middleware": [summarization_mw] if summarization_mw else [],
}) | {
    "agents": [music_executor, play_agent, chat_replier],
    "model": llm0,
    "prompt": supervisor_prompt,
}).compile(name="MusicTeamSupervisor")
