# app/tools/play_tools.py (或者你存放 tool 的对应文件)
from typing import Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# 导入你之前的凭证上下文管理器和刚写好的 Service
from app.tools.user_tools import _with_qqmusic_session 
from app.services.music import song_service

class PlayMusicInput(BaseModel):
    song_mid: str = Field(description="必须提供：歌曲的唯一标识符 (mid)。通过搜索工具获取。")
    song_name: str = Field(description="必须提供：歌曲的名称，用于在播放器中展示。")
    singer_name: str = Field(default="", description="可选：歌手名称，用于在播放器中展示。")

@tool("play_music_tool", args_schema=PlayMusicInput)
async def play_music_tool(song_mid: str, song_name: str, singer_name: str = "") -> str:
    """
    【音乐播放核心工具】当用户要求“播放”、“听”某首歌时，必须调用此工具。
    你需要先通过搜索工具拿到目标歌曲的 song_mid。
    本工具会返回一串带有 <audio> 标签的 HTML 代码，用于在前端渲染网页播放器。
    """
    try:
        # 在带着 QQ 音乐登录态的上下文中调用 Service
        async with await _with_qqmusic_session():
            playable_url = await song_service.get_playable_url(song_mid)

        # 边界情况拦截：没拿到链接（被底层版权/VIP挡住了）
        if not playable_url:
            return (
                f"❌ 获取《{song_name}》的播放源失败。\n"
                f"【真实原因】：这首歌受版权保护或是 VIP 专属，当前账号无权限提取直链。\n"
                f"【行动指令】：任务失败。请向用户温柔致歉，解释版权原因，并询问是否需要换一首免费的歌听听。"
            )

        # 组装展示名称
        display_name = f"{singer_name} - {song_name}" if singer_name else song_name

        # 🔥 核心魔法：将直链包装成前端 HTML，并写下死命令，要求 Agent 原样输出
        return (
            f"✅ 成功获取到《{display_name}》的播放源！\n"
            f"【行动指令】：任务已圆满完成。请你在向 ChatReplier 汇报（或者直接回复用户）时，"
            f"**务必原封不动地包含以下 HTML 代码片段**，千万不要修改或转义里面的任何字符！\n"
            f"配合一句温柔的开场白即可。\n\n"
            f"【前端渲染代码】:\n"
            f"<div class='custom-music-player' style='margin: 10px 0; padding: 10px; background: #f5f5f5; border-radius: 8px;'>\n"
            f"  <p style='margin: 0 0 10px 0; font-weight: bold; color: #333;'>🎵 正在为您播放: {display_name}</p>\n"
            f"  <audio controls autoplay style='width: 100%; outline: none;'>\n"
            f"    <source src='{playable_url}' type='audio/mpeg'>\n"
            f"    您的浏览器不支持音频播放。\n"
            f"  </audio>\n"
            f"</div>"
        )

    except Exception as e:
        return f"❌ 获取播放链接时发生系统报错：{str(e)}。请告知用户系统开小差了，暂时无法播放。"