# app/tools/play_tools.py (或者你存放 tool 的对应文件)
import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.services.music import song_service

class PlayMusicInput(BaseModel):
    song_mid: str = Field(description="必须提供：歌曲的唯一标识符 (mid)。通过搜索工具获取。")
    song_name: str = Field(description="必须提供：歌曲的名称，用于在播放器中展示。")
    singer_name: str = Field(default="", description="可选：歌手名称，用于在播放器中展示。")

@tool("play_music_tool", args_schema=PlayMusicInput)
async def play_music_tool(song_mid: str, song_name: str, singer_name: str = "") -> str:
    """
    【音乐播放核心工具】当用户要求“播放”、“听”某首歌时，必须调用此工具。
    返回前端 `music_player_artifact` 可直接识别的 JSON 字符串。
    """
    try:
        playable_url = await song_service.get_playable_url(song_mid)
        if not playable_url:
            return (
                f"❌ 获取《{song_name}》的播放源失败。\n"
                f"【真实原因】：这首歌受版权保护或是 VIP 专属，当前账号无权限提取直链。\n"
                f"【行动指令】：任务失败。请向用户温柔致歉，解释版权原因，并询问是否需要换一首免费的歌听听。"
            )

        cover_url = await song_service.get_song_cover(song_mid=song_mid, size=300)

        payload = {
            "type": "play_music",
            "song_mid": song_mid,
            "title": song_name,
            "artist": singer_name,
            "url": playable_url,
            "cover": cover_url or "",
            "description": "已获取播放链接",
        }
        return json.dumps(payload, ensure_ascii=False)

    except Exception as e:
        return f"❌ 获取播放链接时发生系统报错：{str(e)}。请告知用户系统开小差了，暂时无法播放。"