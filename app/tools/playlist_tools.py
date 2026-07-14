import logging
from typing import List

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.schemas import PlaylistBrowserArtifact
from app.services.music.playlist_service import playlist_service
from app.tools.tool_result import ToolResult, ToolResultCode

logger = logging.getLogger(__name__)


# ================= 1. 定义输入结构 =================

class AddSongsInput(BaseModel):
    song_ids: List[int] = Field(
        description=(
            "要添加的歌曲唯一ID列表(songid)。必须是整数列表，例如：[436514, 123456]。"
            "仅当你已经明确知道要添加哪些具体歌曲时再填写。"
        )
    )
    dirid: int = Field(
        description=(
            "目标歌单的短ID(dirid)，必须大于0。仅当你已经明确知道目标歌单 dirid 时再填写；"
            "若未明确，请先通过其他工具解析歌单。"
        )
    )


class CreatePlaylistInput(BaseModel):
    name: str = Field(
        description="想要创建的新歌单名称。例如：'AI推荐的陈奕迅精选'、'运动燃曲'"
    )


class AddByKeywordToPlaylistInput(BaseModel):
    playlist_name: str = Field(
        description="目标歌单名称。例如：'我喜欢'、'通勤歌单'。系统会自动解析对应 dirid。"
    )
    keyword: str = Field(
        description="搜索关键词，例如：'陈奕迅'、'周杰伦 慢歌'。"
    )
    target_count: int = Field(
        default=3,
        ge=1,
        description="希望最终添加的歌曲数量。"
    )
    search_page_size: int = Field(
        default=20,
        ge=1,
        le=50,
        description="每轮搜索拉取的候选数量。"
    )
    max_expand_rounds: int = Field(
        default=5,
        ge=1,
        le=20,
        description="搜索扩展轮数上限（按分页扩展）。"
    )


class GetPlaylistDetailInput(BaseModel):
    songlist_id: int = Field(
        default=0,
        description=(
            "歌单全局唯一ID，优先使用。若未知，可先调用 get_created_songlist_tool 获取 tid，"
            "或先调用 search_music_tool(search_type='SONGLIST') 搜索歌单获取dissi。"
        )
    )
    dirid: int = Field(
        default=0,
        description=(
            "歌单短ID。对于用户自建歌单常见。若 songlist_id 未知，可通过 get_created_songlist_tool 先获取 dirId。"
        )
    )
    num: int = Field(
        default=20,
        ge=1,
        le=50,
        description="每页返回歌曲数量。"
    )
    page: int = Field(
        default=1,
        ge=1,
        description="页码，从 1 开始。"
    )
    onlysong: bool = Field(
        default=True,
        description="是否仅返回歌曲列表。默认 True，减少冗余信息。"
    )


# ================= 2. 定义大模型实际调用的工具 =================
@tool("add_songs_to_playlist_tool", args_schema=AddSongsInput)
async def add_songs_to_playlist_tool(song_ids: List[int], dirid: int) -> str:
    """
    【精确加歌工具】必须在你“已经明确知道”以下两项信息时使用：
    1) 目标歌单 dirid；
    2) 待添加歌曲的明确 song_ids 列表。

    不确定歌单，请使用其他方法获取想要操作的歌单dirid。
    没有可直接使用的 song_ids，请不要调用本工具，
    应改用 add_by_keyword_to_playlist_tool（按歌单名 + 关键词自动搜索并添加）。

    仅在底层明确确认成功时报告成功。False 或异常表示写入结果不确定，禁止自动重试。
    """
    result_data = {
        "dirid": dirid,
        "song_ids": song_ids,
        "requested_count": len(song_ids),
    }
    if not song_ids:
        return ToolResult.failure(
            code=ToolResultCode.INVALID_ARGUMENT,
            message="song_ids 不能为空",
            data={**result_data, "field": "song_ids"},
        ).to_json()
    if dirid <= 0:
        return ToolResult.failure(
            code=ToolResultCode.INVALID_ARGUMENT,
            message="dirid 必须大于 0",
            data={**result_data, "field": "dirid"},
        ).to_json()

    try:
        success = await playlist_service.add_songs_to_playlist(song_ids=song_ids, dirid=dirid)
        if success:
            return ToolResult.success(
                message=f"已向歌单添加 {len(song_ids)} 首歌曲",
                data=result_data,
            ).to_json()
        return ToolResult.failure(
            code=ToolResultCode.WRITE_UNCERTAIN,
            message="加歌接口未返回可确认的写入结果",
            data=result_data,
        ).to_json()
    except Exception:
        logger.exception("add_songs_to_playlist_tool 执行异常 (dirid=%s)", dirid)
        return ToolResult.failure(
            code=ToolResultCode.WRITE_UNCERTAIN,
            message="加歌请求执行后无法确认写入结果",
            data=result_data,
        ).to_json()


@tool("create_playlist_tool", args_schema=CreatePlaylistInput)
async def create_playlist_tool(name: str) -> str:
    """
    当你需要为用户创建一个全新的专属歌单时调用此工具。
    工具返回成功后，会告诉你新歌单的 dirid，请务必记住这个 dirid，后续你要往这个新歌单里加歌时需要用到它。
    """
    clean_name = (name or "").strip()
    if not clean_name:
        return ToolResult.failure(
            code=ToolResultCode.INVALID_ARGUMENT,
            message="歌单名称不能为空",
            data={"field": "name"},
        ).to_json()

    try:
        res = await playlist_service.create_playlist(name=clean_name)

        if not isinstance(res, dict):
            return ToolResult.failure(
                code=ToolResultCode.WRITE_UNCERTAIN,
                message="创建歌单接口返回格式异常，无法确认结果",
                data={"requested_name": clean_name},
            ).to_json()

        if "error" in res:
            return ToolResult.failure(
                code=ToolResultCode.WRITE_UNCERTAIN,
                message="创建歌单请求执行后无法确认结果",
                data={"requested_name": clean_name},
            ).to_json()

        raw_dirid = res.get("dirid")
        raw_tid = res.get("id")
        actual_name = res.get("name", clean_name)

        try:
            new_dirid = int(raw_dirid)
        except (TypeError, ValueError):
            return ToolResult.failure(
                code=ToolResultCode.WRITE_UNCERTAIN,
                message="创建歌单接口未返回有效 dirid，无法确认结果",
                data={"requested_name": clean_name},
            ).to_json()

        return ToolResult.success(
            message="歌单创建成功",
            data={
                "playlist": {
                    "id": raw_tid,
                    "dirid": new_dirid,
                    "name": actual_name,
                }
            },
        ).to_json()

    except Exception:
        logger.exception("create_playlist_tool 执行异常 (name=%s)", clean_name)
        return ToolResult.failure(
            code=ToolResultCode.WRITE_UNCERTAIN,
            message="创建歌单请求执行后无法确认结果",
            data={"requested_name": clean_name},
        ).to_json()


@tool("add_by_keyword_to_playlist_tool", args_schema=AddByKeywordToPlaylistInput)
async def add_by_keyword_to_playlist_tool(
    playlist_name: str,
    keyword: str,
    target_count: int = 3,
    search_page_size: int = 20,
    max_expand_rounds: int = 5,
) -> str:
    """
    一站式加歌工具：按关键词搜索歌曲，并自动过滤已在目标歌单中的歌曲，再补齐添加指定数量。
    适用于“给我的某歌单加N首某歌手歌曲”这类需求。
    """
    clean_playlist_name = (playlist_name or "").strip()
    clean_keyword = (keyword or "").strip()
    if not clean_playlist_name:
        return ToolResult.failure(
            code=ToolResultCode.INVALID_ARGUMENT,
            message="目标歌单名称不能为空",
            data={"field": "playlist_name"},
        ).to_json()
    if not clean_keyword:
        return ToolResult.failure(
            code=ToolResultCode.INVALID_ARGUMENT,
            message="搜索关键词不能为空",
            data={"field": "keyword", "playlist_name": clean_playlist_name},
        ).to_json()

    try:
        res = await playlist_service.add_songs_by_keyword_to_playlist(
            playlist_name=clean_playlist_name,
            keyword=clean_keyword,
            target_count=target_count,
            search_page_size=search_page_size,
            max_expand_rounds=max_expand_rounds,
        )

        status = res.get("status")
        result_data = {
            "dirid": res.get("dirid"),
            "songlist_name": res.get("songlist_name", clean_playlist_name),
            "keyword": clean_keyword,
            "target_count": target_count,
            "added_count": res.get("added_count", 0),
            "added_song_ids": res.get("added_song_ids", []),
            "already_in_playlist_count": res.get("already_in_playlist_count", 0),
            "searched_pages": res.get("searched_pages", []),
        }
        try:
            added_count = int(result_data["added_count"] or 0)
        except (TypeError, ValueError):
            added_count = 0
        result_data["added_count"] = added_count

        if status == "error":
            return ToolResult.failure(
                code=ToolResultCode.UPSTREAM_ERROR,
                message="关键词加歌服务执行失败",
                data=result_data,
            ).to_json()

        if status == "success":
            if added_count > 0:
                return ToolResult.success(
                    message=f"关键词加歌完成，成功添加 {added_count}/{target_count} 首",
                    data=result_data,
                ).to_json()
            return ToolResult.failure(
                code=ToolResultCode.NOT_FOUND,
                message="没有找到可添加的新歌曲",
                data=result_data,
            ).to_json()

        if status == "partial" and added_count > 0:
            return ToolResult.failure(
                code=ToolResultCode.PARTIAL_SUCCESS,
                message=f"关键词加歌部分完成，成功添加 {added_count}/{target_count} 首",
                data=result_data,
            ).to_json()

        result_data["candidate_song_ids"] = res.get("candidate_song_ids", [])
        return ToolResult.failure(
            code=ToolResultCode.WRITE_UNCERTAIN,
            message="关键词加歌后未能确认新增结果",
            data=result_data,
        ).to_json()
    except Exception:
        logger.exception(
            "add_by_keyword_to_playlist_tool 执行异常 (playlist_name=%s)",
            clean_playlist_name,
        )
        return ToolResult.failure(
            code=ToolResultCode.WRITE_UNCERTAIN,
            message="关键词加歌请求执行后无法确认写入结果",
            data={
                "playlist_name": clean_playlist_name,
                "keyword": clean_keyword,
                "target_count": target_count,
            },
        ).to_json()


@tool("get_playlist_detail_tool", args_schema=GetPlaylistDetailInput)
async def get_playlist_detail_tool(
    songlist_id: int = 0,
    dirid: int = 0,
    num: int = 20,
    page: int = 1,
    onlysong: bool = True,
) -> str:
    """
    获取歌单详情/歌曲列表工具。

    使用规则（非常重要）：
    1) 优先传 songlist_id；若没有，可仅传 dirid。
    2) songlist_id 和 dirid 至少提供一个。
    3) 如果你不知道 songlist_id 或 dirid，必须先调用其他工具获取：
       - get_created_songlist_tool：查用户已创建歌单，拿到 tid(dirid)。
       - search_music_tool(search_type='SONGLIST')：先搜索公开歌单，再从结果中提取对应标识。
    4) 需要尽量只看歌时，onlysong=True；需要歌单标题/创建者等信息时，onlysong=False。
    """
    if not songlist_id and not dirid:
        return ToolResult.failure(
            code=ToolResultCode.INVALID_ARGUMENT,
            message="songlist_id 与 dirid 至少要提供一个",
            data={"songlist_id": songlist_id, "dirid": dirid},
        ).to_json()

    try:
        res = await playlist_service.get_playlist_detail(
            songlist_id=songlist_id,
            dirid=dirid,
            num=num,
            page=page,
            onlysong=onlysong,
        )
        if not isinstance(res, dict) or res.get("status") == "error":
            return ToolResult.failure(
                code=ToolResultCode.UPSTREAM_ERROR,
                message="歌单详情服务暂时不可用",
                data={"songlist_id": songlist_id, "dirid": dirid, "page": page},
                retryable=True,
            ).to_json()

        raw_songs = res.get("songlist", [])
        raw_songs = raw_songs if isinstance(raw_songs, list) else []
        tracks: list[dict] = []
        seen_mids: set[str] = set()
        for idx, song in enumerate(raw_songs):
            if not isinstance(song, dict):
                continue
            song_mid = str(song.get("mid", "") or "").strip()
            if not song_mid or song_mid in seen_mids:
                continue
            seen_mids.add(song_mid)
            tracks.append(
                {
                    "index": (page - 1) * num + idx + 1,
                    "song_mid": song_mid,
                    "title": str(song.get("title", "") or "未知歌曲").strip() or "未知歌曲",
                    "artist": str(song.get("singer", "") or "").strip(),
                    "cover": "",
                }
            )

        playlist_info = res.get("playlist_info", {})
        playlist_info = playlist_info if isinstance(playlist_info, dict) else {}
        resolved_dirid = dirid or playlist_info.get("dirid") or None
        try:
            resolved_dirid = int(resolved_dirid) if resolved_dirid is not None else None
        except (TypeError, ValueError):
            resolved_dirid = None
        if resolved_dirid is not None and resolved_dirid <= 0:
            resolved_dirid = None

        raw_total = res.get("total_song_num", 0)
        try:
            total_song_num = max(int(raw_total or 0), len(tracks))
        except (TypeError, ValueError):
            total_song_num = len(tracks)
        playlist_name = str(playlist_info.get("title", "") or "").strip()
        if not playlist_name:
            identifier = resolved_dirid or songlist_id
            playlist_name = f"歌单({identifier})"

        artifact = PlaylistBrowserArtifact(
            playlist_name=playlist_name,
            dirid=resolved_dirid,
            tracks=tracks,
            page=page,
            page_size=num,
            total_song_num=total_song_num,
            has_more=page * num < total_song_num,
            description=f"已加载第 {page} 页，可点击歌曲播放",
        )
        return ToolResult.success(
            message="歌单详情查询成功",
            data=artifact.model_dump(mode="json"),
        ).to_json()
    except Exception:
        logger.exception(
            "get_playlist_detail_tool 执行异常 (songlist_id=%s, dirid=%s)",
            songlist_id,
            dirid,
        )
        return ToolResult.failure(
            code=ToolResultCode.UPSTREAM_ERROR,
            message="歌单详情工具执行时发生内部错误",
            data={"songlist_id": songlist_id, "dirid": dirid, "page": page},
            retryable=True,
        ).to_json()


# ================= 追加到 app/tools/playlist_tools.py 底部 =================

class DeletePlaylistInput(BaseModel):
    dirid: int = Field(
        description="要删除的歌单的短ID(dirid)。注意：不能删除系统的默认歌单（如 dirid=1 的我喜欢）。"
    )


class RemoveSongsInput(BaseModel):
    song_ids: List[int] = Field(
        description=(
            "要移除的歌曲唯一ID列表(songid)，必须是整数列表，例如：[436514, 123456]。"
            "仅当你已经明确知道要删除哪些 song_id 时再传入；"
            "若未知，需先通过查询工具获取歌曲列表并定位 song_id。"
        )
    )
    dirid: int = Field(
        description=(
            "目标歌单的短ID(dirid)。这是必填项，不再存在默认歌单。"
            "若你不知道 dirid，必须先通过歌单查询工具定位目标歌单并获取 dirid。"
        )
    )


# ================= 补充的删除类工具 =================

@tool("delete_playlist_tool", args_schema=DeletePlaylistInput)
async def delete_playlist_tool(dirid: int) -> str:
    """
    当你需要帮用户删除一整个自建歌单时调用此工具。
    注意：在调用此工具前，你最好先通过搜索或其他工具确认该歌单的 dirid 是准确的。
    千万不要把 dirid=1 传进来，那是系统默认的“我喜欢”歌单，无法直接删除整个歌单。
    """
    if dirid == 1:
        return "❌ 拒绝执行：dirid=1 是用户的系统默认'我喜欢'歌单，无法整体删除。如果你想取消喜欢某首歌，请使用 remove_songs_from_playlist_tool。"

    try:
        success = await playlist_service.delete_playlist(dirid=dirid)

        if success:
            return f"🗑️ 歌单(dirid={dirid})已成功删除！"
        else:
            return f"❌ 删除失败：可能是该歌单(dirid={dirid})不存在，或者用户没有权限删除它。"

    except Exception as e:
        return f"删除歌单时发生底层报错：{str(e)}"


@tool("remove_songs_from_playlist_tool", args_schema=RemoveSongsInput)
async def remove_songs_from_playlist_tool(song_ids: List[int], dirid: int) -> str:
    """
    当你需要从指定歌单中删除歌曲时调用此工具。

    使用前提（必须满足）：
    1) 已明确目标歌单的 dirid；
    2) 已明确要删除的 song_ids。

    如果 dirid 或 song_ids 未知，必须先通过查询工具定位：
    - 先查歌单列表拿到目标歌单 dirid；
    - 再查目标歌单内歌曲，拿到准确 song_id 后再调用本工具。
    """
    if not song_ids:
        return "❌ 移除失败：song_ids 不能为空。请先查询歌单内歌曲并确定要移除的 song_id。"

    try:
        success = await playlist_service.remove_songs_from_playlist(song_ids=song_ids, dirid=dirid)

        if success:
            return f"✂️ 成功将 {len(song_ids)} 首歌曲从歌单(dirid={dirid})中移除了！"
        else:
            return (
                "❌ 移除失败：目标歌曲可能不在该歌单中，或传入的 song_id/dirid 有误。"
                "请先重新查询该歌单中的歌曲清单后再尝试。"
            )

    except Exception as e:
        return f"移除歌曲时发生底层报错：{str(e)}"
