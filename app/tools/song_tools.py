import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.schemas import PlayMusicArtifact
from app.services.music import song_service
from app.tools.tool_result import ToolResult, ToolResultCode

logger = logging.getLogger(__name__)



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
    clean_mid = (song_mid or "").strip()
    clean_name = (song_name or "").strip()
    clean_singer = (singer_name or "").strip()

    if not clean_mid:
        return ToolResult.failure(
            code=ToolResultCode.INVALID_ARGUMENT,
            message="歌曲 song_mid 不能为空",
            data={"field": "song_mid"},
        ).to_json()
    if not clean_name:
        return ToolResult.failure(
            code=ToolResultCode.INVALID_ARGUMENT,
            message="歌曲名称不能为空",
            data={"field": "song_name", "song_mid": clean_mid},
        ).to_json()

    try:
        playable_url = await song_service.get_playable_url(clean_mid)
        if not playable_url:
            return ToolResult.failure(
                code=ToolResultCode.PLAYBACK_UNAVAILABLE,
                message=f"《{clean_name}》当前没有可用播放链接，可能受版权或账户权限限制",
                data={"song_mid": clean_mid, "title": clean_name, "artist": clean_singer},
            ).to_json()
        if not playable_url.startswith(("http://", "https://")):
            return ToolResult.failure(
                code=ToolResultCode.PLAYBACK_UNAVAILABLE,
                message=f"《{clean_name}》的播放链接格式无效",
                data={"song_mid": clean_mid, "title": clean_name, "artist": clean_singer},
            ).to_json()

        try:
            cover_url = await song_service.get_song_cover(song_mid=clean_mid, size=300)
        except Exception:
            logger.warning("获取歌曲封面失败 (song_mid=%s)", clean_mid, exc_info=True)
            cover_url = None

        artifact = PlayMusicArtifact(
            song_mid=clean_mid,
            title=clean_name,
            artist=clean_singer,
            url=playable_url,
            cover=cover_url or "",
        )
        return ToolResult.success(
            message="已获取歌曲播放信息",
            data=artifact.model_dump(mode="json"),
        ).to_json()

    except Exception:
        logger.exception("play_music_tool 执行异常 (song_mid=%s)", clean_mid)
        return ToolResult.failure(
            code=ToolResultCode.UPSTREAM_ERROR,
            message="播放服务暂时不可用",
            data={"song_mid": clean_mid, "title": clean_name, "artist": clean_singer},
            retryable=True,
        ).to_json()
