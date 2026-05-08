import inspect
import os
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, BaseMessage

# 根据你提供的文档，导入官方的中间件
try:
    from langchain.agents.middleware import SummarizationMiddleware
except ImportError:
    # 兼容性预留：如果你本地的 langchain 版本还不支持该路径，请确保更新版本
    SummarizationMiddleware = None

try:
    from langgraph_supervisor import create_supervisor
except ImportError:
    from langgraph.prebuilt import create_supervisor

# 按照要求替换为 create_agent
from langchain.agents import create_agent

# 导入你的工具
from app.tools.search_tools import search_music_tool, get_hotkeys_tool
from app.tools.playlist_tools import (
    add_songs_to_playlist_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
    add_by_keyword_to_playlist_tool,
)
from app.tools.user_tools import get_created_songlist_tool, get_fav_song_tool

# ==========================================
# 1. 环境变量与模型初始化
# ==========================================
MODEL_NAME = os.getenv("MUSIC_AGENT_MODEL", "glm-5")
MUSIC_MODEL_BASE_URL = os.getenv("MUSIC_AGENT_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MUSIC_MODEL_API_KEY = os.getenv("MUSIC_AGENT_API_KEY", "")
MODEL_BASE_URL = os.getenv("OPENAI_API_BASE", "")
MODEL_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 这里的数字可以根据实际情况微调，不再需要手动 trigger summary 的数字了
MAX_EXECUTOR_REENTRY_WITHOUT_USER = int(os.getenv("MUSIC_AGENT_MAX_EXECUTOR_REENTRY_WITHOUT_USER", "1"))

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
# 2. 官方 SummarizationMiddleware 配置
# ==========================================
summary_prompt = (
    "请将以下对话总结为【记忆摘要】，必须包含："
    "1) 用户偏好；2) 当前任务状态(进行中/已完成/已中断待用户补充)；3) 实体记忆(歌单名/dirid/关键词)；4) 最近失败原因。"
    "严格要求：不要写下一步建议、不要写行动号召、不要写应继续执行之类指令。"
    "输出简体中文，控制在400字内。\n\n{messages}"
)

if SummarizationMiddleware:
    summarization_mw = SummarizationMiddleware(
        model=llm0,
        trigger=("tokens", 5000),
        keep=("messages", 10),
        summary_prompt=summary_prompt
    )
else:
    summarization_mw = None


# ==========================================
# 3. 辅助函数 (已大幅精简)
# ==========================================
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


def _get_latest_executor_msg(messages: list[BaseMessage]) -> BaseMessage | None:
    for m in reversed(messages):
        if getattr(m, "name", "") == "MusicExecutor":
            return m
    return None


def _is_smalltalk(text: str) -> bool:
    if not text: return False
    # 仅保留基础寒暄拦截，音乐动作交给模型自己判断
    smalltalk_keywords = {"你好", "hi", "hello", "在吗", "谢谢", "thank", "早上好", "晚上好", "午安", "再见", "bye",
                          "哈哈", "嗯", "ok"}
    return any(k in text.lower() for k in smalltalk_keywords) and len(text) <= 6


# ==========================================
# 4. 路由与执行 Hook (剥离摘要，专注拦截死循环)
# ==========================================
def _supervisor_pre_model_hook(state: Any) -> dict[str, Any]:
    """主管专属 Hook：只负责巡视状态并下达路由暗示，防止死循环。"""
    messages = _extract_messages(state)
    if not messages:
        return {}

    updated_messages = list(messages)

    # 提取最后一条用户消息的内容
    last_user_text = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "").lower()

    # 拦截1：纯闲聊
    if _is_smalltalk(last_user_text):
        updated_messages.append(SystemMessage(
            content="ROUTING_HINT: 用户正在闲聊，直接路由 ChatReplier，严禁调用 MusicExecutor。"
        ))
        return {"messages": updated_messages}

    # 分析执行器状态
    latest_executor_msg = _get_latest_executor_msg(messages)
    if not latest_executor_msg:
        return {"messages": updated_messages}

    # 判断最后发言的是不是用户 (如果不是，说明系统正在自己跟自己对话)
    no_new_user = not isinstance(messages[-1], HumanMessage)
    content = str(latest_executor_msg.content)

    # 拦截2：执行已结束 或 明确卡住报错
    looks_done = any(k in content for k in ["已完成", "操作成功", "成功", "已添加", "已创建", "查询结果"])
    looks_stuck = any(k in content for k in
                      ["失败", "有误", "参数", "无权限", "异常", "可能不在目标歌单中", "报错", "超时", "不支持"])

    if no_new_user and (looks_done or looks_stuck):
        status_str = "已成功/结束" if looks_done else "已失败/卡住"
        updated_messages.append(SystemMessage(
            content=f"ROUTING_HINT: 最新一次 MusicExecutor 任务 {status_str}，且用户未提供新指令。"
                    "【强制指令】：立即路由给 ChatReplier 进行转述或请求澄清，禁止再次调用 MusicExecutor 进行重试！"
        ))

    return {"messages": updated_messages}


def _executor_pre_model_hook(state: Any) -> dict[str, Any]:
    """执行者专属 Hook：去掉危险的关键字过滤，仅注入本地规则约束。"""
    messages = _extract_messages(state)
    if not messages:
        return {}

    rule_guard = SystemMessage(
        content=(
            "EXECUTION_PACKET_RULE: 你当前只可依据本执行包中的上下文工作。"
            "若缺乏目标歌单 dirid，必须先查再建。不要因单个错误反复更换参数重试。"
        )
    )
    return {"messages": [rule_guard, *messages]}


# ==========================================
# 5. 工具、提示词与 Agent 构建
# ==========================================
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
    "model": llm1,
    "tools": tools,
    "system_prompt": executor_prompt,
    "name": "MusicExecutor",
    "pre_model_hook": _executor_pre_model_hook,
}
# 加入中间件配置 (通过 _safe_kwargs 防止版本不兼容报错)
if summarization_mw:
    music_executor_kwargs["middleware"] = [summarization_mw]

music_executor = create_agent(**_safe_kwargs(create_agent, music_executor_kwargs) | {
    "model": llm1,
    "tools": tools,
    "system_prompt": executor_prompt,
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
    model=llm0,
    tools=[],
    system_prompt=replier_prompt,
    name="ChatReplier",
)

supervisor_prompt = """
你是 MusicTeamSupervisor，负责在 MusicExecutor（执行者）与 ChatReplier（回复者）之间高效调度。

## 一级路由（先判断是否需要工具）
1. 若用户是寒暄、感谢、闲聊、非音乐账户操作请求：优先路由 ChatReplier。
2. 仅当用户请求涉及 QQ 音乐账户具体操作（搜索/查歌单/增删歌曲/创建歌单等）时，路由 MusicExecutor。
3. 若用户并不没有明确指定是QQ音乐的操作，自动归到QQ音乐操作，因为你的功能目前只有操作QQ音乐，路由 MusicExecutor。

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
    "model": llm0,
    "prompt": supervisor_prompt,
    "pre_model_hook": _supervisor_pre_model_hook,
}
if summarization_mw:
    supervisor_kwargs["middleware"] = [summarization_mw]

app_graph = create_supervisor(**_safe_kwargs(create_supervisor, supervisor_kwargs) | {
    "agents": [music_executor, chat_replier],
    "model": llm0,
    "prompt": supervisor_prompt,
}).compile(name="MusicTeamSupervisor")

graph = app_graph