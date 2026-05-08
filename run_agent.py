import asyncio

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

# 最新多智能体 Supervisor 推荐实现
try:
    from langgraph_supervisor import create_supervisor
except ImportError:
    # 兼容部分版本导出路径
    from langgraph.prebuilt import create_supervisor

from langgraph.prebuilt import create_react_agent

# 导入你的 QQ 音乐 Session 和 Auth 模块
from qqmusic_api import Session
import app.core.auth as auth_module
from app.core.auth import setup_global_credential

# 导入工具
from app.tools.search_tools import search_music_tool
from app.tools.playlist_tools import (
    add_songs_to_playlist_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
    add_by_keyword_to_playlist_tool,
)
from app.tools.user_tools import get_created_songlist_tool,get_fav_song_tool

# ==========================================
# 🧠 1. 定义各个智能体
# ==========================================
llm = ChatOpenAI(model="glm-4.6v", temperature=0)

# A. 执行任务专员（带工具）
tools = [
    search_music_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
    get_created_songlist_tool,
    get_fav_song_tool,
    add_by_keyword_to_playlist_tool,
]

executor_prompt =  """
## Role
你是一个专业的音乐助理 **MusicExecutor**，负责通过调用工具精确执行用户对 QQ 音乐账户的操作指令。

## Core Principles
1. **原生工具调用**：直接生成工具调用（Tool Calling），禁止输出 `Thought:`、`Action:` 或任何过程文本。
2. **目标优先**：确保操作准确触达目标歌单。如果目标歌单不存在，必须先创建。
3. **静默执行**：除了最终的简洁中文总结外，不要向用户输出任何中间步骤。

## Workflow Logic
1. **dirid 获取与校验（关键环节）**：
   - 任何涉及 `dirid` 参数的工具（尤其是 `add_songs_to_playlist_tool`），若你不知道目标歌单的 `dirid`，**必须**先调用 `get_created_songlist_tool` 获取用户创建的歌单列表，从中匹配名称并提取 `dirid`。
   - **自动创建**：若在列表中未找到目标歌单，必须先调用 `create_playlist_tool` 创建该歌单，获取返回的 `dirid` 后再执行后续操作。

2. **加歌策略**：
   - **场景 A（关键词驱动）**：用户说“给某歌单加点某人的歌”，优先使用 `add_by_keyword_to_playlist_tool`。其 `playlist_name` 传入歌单名。
   - **数量控制**：默认添加 5 首。若语义明确为单首（如“把这首歌加上”），则设为 1。

3. **异常重试机制**：
   - 调用 `add_songs_to_playlist_tool` 时，若返回“添加失败”（通常是歌曲已存在），你必须排除当前这批 `song_ids`，重新通过搜索获取**新的歌曲 ID** 再次尝试调用，直到成功数量达标。

## Output Requirement
任务结束后，仅回复一段简洁的中文总结，格式如下：
- **目标歌单**：[名称] (ID: [dirid])
- **成功执行**：[成功添加/操作的数量] 首
- **异常反馈**：[若所有尝试均失败，说明是哪个工具调用失败及原因；若最终成功则不显示此项]

## Tool-Specific Notes
- **add_by_keyword_to_playlist_tool**: 
  - `target_count`: 1-5 (默认 5)。
  - `search_page_size`: 20。
"""

music_executor = create_react_agent(
    model=llm,
    tools=tools,
    prompt=executor_prompt,
    name="MusicExecutor",
)

# B. 客服回复专员（无工具）
replier_prompt = (
    "你是 ChatReplier。你不调用工具，只负责把执行结果清晰地回复给用户。"
    "\n\n要求："
    "1) 忠实转述 MusicExecutor 的结果，不补造事实；"
    "2) 明确写出歌单名、dirid、成功数量、失败原因；"
    "3) 语气友好、简洁、自然。"
)

chat_replier = create_react_agent(
    model=llm,
    tools=[],
    prompt=replier_prompt,
    name="ChatReplier",
)

# ==========================================
# 🧭 2. 使用 create_supervisor 构建主管编排
# ==========================================
supervisor_prompt = """
你是 MusicTeamSupervisor，负责在 MusicExecutor（执行者）与 ChatReplier（回复者）之间高效调度。

## 核心路由规则：
1. **工具调用优先**：任何涉及 QQ 音乐具体操作（搜索、添加、删除、查歌单等）的请求，一律路由给 **MusicExecutor**。
2. **任务闭环校验**：仅当 MusicExecutor 明确反馈任务已完成，或因不可控原因（如版权、上限）明确无法继续时，才将当前上下文路由给 **ChatReplier**。
3. **最终响应标准**：
   - 对于“添加歌曲”类任务，必须确保上下文中包含【目标歌单名】、【dirid】、【成功数量】。
   - 若用户要求“加满 N 首”，在未达标且无充分失败说明前，不得路由给 ChatReplier。

## 输出要求（关键）：
- **禁止输出**冷冰冰的系统状态（如“流程已结束”、“感谢使用”）。
- **你的目标是让用户看到 ChatReplier 的最终回复**。
- 当任务进入结束阶段时，你应当直接采纳并输出 **ChatReplier** 生成的那个亲切、详尽的中文回复。这个回复必须包含操作的结果详情（如歌单名、ID、数量）以及后续的引导。
"""

app_graph = create_supervisor(
    agents=[music_executor, chat_replier],
    model=llm,
    prompt=supervisor_prompt,
).compile(name="MusicTeamSupervisor")


# ==========================================
# 🚀 3. 主函数与运行逻辑
# ==========================================
async def main():
    print("📋 正在初始化 QQ 音乐凭证...")
    try:
        await setup_global_credential()
        print("✅ 凭证加载成功，环境就绪！")
    except Exception as e:
        print(f"❌ 环境初始化失败: {e}")
        return

    user_input = (
        "帮我找一下陈奕迅的歌曲。注意：我只需要添加 3 首歌曲到我的“我喜欢”歌单里。"
        "如果添加时提示歌曲已存在，请忽略并尝试添加下一首，直到加满 3 首为止。"
    )

    print("\n========= 🚀 多智能体团队开始工作 =========")
    print(f"👤 用户: {user_input}\n")

    async with Session(credential=auth_module.GLOBAL_CREDENTIAL):
        result = await app_graph.ainvoke({"messages": [HumanMessage(content=user_input)]})

    final_messages = result.get("messages", [])
    if final_messages:
        print(f"🤖 最终回复: {final_messages[-1].content}")

    print("========= ✅ 任务最终彻底闭环 =========")


if __name__ == "__main__":
    asyncio.run(main())
