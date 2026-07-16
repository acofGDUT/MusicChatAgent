import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.music_team_v3_1.utils import (
    IdentityContext,
    build_identity_context,
    is_user_visible_ai_message,
    msg_content,
    now_ms,
)
from app.core.auth import (
    AuthenticationRequiredError,
    AuthenticationUnavailableError,
    get_authenticated_user_id,
)
from app.schemas import PlayMusicArtifact, PlaylistBrowserArtifact


TRACE_NODE_NAMES = {
    "init_memory",
    "intent_parser",
    "supervisor_router",
    "music_ops_subgraph",
    "playback_subgraph",
    "result_verifier",
    "memory_sync",
    "chat_replier",
    "finalizer",
}

NODE_TO_AI_NAME = {
    "music_ops_subgraph": "MusicExecutor",
    "playback_subgraph": "PlayAgent",
    "chat_replier": "ChatReplier",
}

NON_LLM_TRACE_FIELDS = {
    "init_memory": [
        "intent",
        "status",
        "summary_version",
        "preference_update_status",
        "preference_version",
        "preference_signal_count",
        "storage_backend",
        "user_id_present",
        "executor_reentry",
        "max_reentry",
    ],
    "intent_parser": ["intent", "status", "is_ready_to_execute", "missing_slots"],
    "supervisor_router": ["intent", "status", "route", "executor_reentry", "max_reentry"],
    "result_verifier": [
        "verification_status",
        "verification_code",
        "retry_scheduled",
        "retry_count",
        "verifier_route",
    ],
    "memory_sync": ["status", "should_summarize", "summary_version"],
    "finalizer": ["status", "intent"],
}


def _build_non_llm_trace_summary(node_name: str, node_output: dict) -> str:
    fields = NON_LLM_TRACE_FIELDS.get(node_name, [])
    if not fields:
        return ""

    task = node_output.get("task") if isinstance(node_output.get("task"), dict) else {}
    control = node_output.get("control") if isinstance(node_output.get("control"), dict) else {}
    memory = node_output.get("memory") if isinstance(node_output.get("memory"), dict) else {}
    extensions = node_output.get("extensions") if isinstance(node_output.get("extensions"), dict) else {}
    verification = extensions.get("verification") if isinstance(extensions.get("verification"), dict) else {}

    values: dict[str, object] = {
        "intent": task.get("intent"),
        "status": task.get("status"),
        "missing_slots": task.get("missing_slots"),
        "route": control.get("route"),
        "executor_reentry": control.get("executor_reentry"),
        "max_reentry": control.get("max_reentry"),
        "is_ready_to_execute": control.get("is_ready_to_execute"),
        "should_summarize": control.get("should_summarize"),
        "summary_version": memory.get("summary_version"),
        "preference_update_status": memory.get("preference_update_status"),
        "preference_version": memory.get("preference_version"),
        "preference_signal_count": memory.get("preference_signal_count"),
        "storage_backend": memory.get("storage_backend"),
        "user_id_present": memory.get("user_id_present"),
        "verification_status": verification.get("status"),
        "verification_code": verification.get("code"),
        "retry_scheduled": verification.get("retry_scheduled"),
        "retry_count": verification.get("retry_count", control.get("retry_count")),
        "verifier_route": control.get("verifier_route"),
    }

    picked = {k: values.get(k) for k in fields if values.get(k) not in (None, "", [])}
    if not picked:
        return ""

    return json.dumps(picked, ensure_ascii=False)


def _extract_trace_content(node_name: str, node_output: object) -> str:
    if not isinstance(node_output, dict):
        return ""

    expected_ai_name = NODE_TO_AI_NAME.get(node_name)

    # 仅在“应当产出 AIMessage 的节点”中提取 AI 文本，避免读取到上一轮残留消息。
    if expected_ai_name:
        messages = node_output.get("messages", [])
        if isinstance(messages, list) and messages:
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    msg_name = str(getattr(msg, "name", "") or "").strip()
                    text = str(msg.content or "").strip()
                    if msg_name == expected_ai_name and text:
                        return text
                elif isinstance(msg, dict) and str(msg.get("type", "")).strip() == "ai":
                    msg_name = str(msg.get("name", "") or "").strip()
                    text = str(msg.get("content", "") or "").strip()
                    if msg_name == expected_ai_name and text:
                        return text

    # 非 LLM 节点或未命中预期 AIMessage 时，优先输出结构化摘要。
    summary = _build_non_llm_trace_summary(node_name, node_output)
    if summary:
        return summary

    # 最后回退到错误原因。
    task = node_output.get("task")
    if isinstance(task, dict):
        reason = str(task.get("error_reason", "") or "").strip()
        if reason:
            return reason

    return ""

def _looks_like_json(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False

    candidates = [raw]
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3:
            candidates.append("\n".join(lines[1:-1]).strip())

    for candidate in candidates:
        if not candidate:
            continue
        if not ((candidate.startswith("{") and candidate.endswith("}")) or (candidate.startswith("[") and candidate.endswith("]"))):
            continue
        try:
            json.loads(candidate)
            return True
        except Exception:
            continue

    return False
from app.core.auth import check_or_refresh_credential, clear_credential, qr_login_manager
from app.services.music import playlist_service
from app.services.music.song_service import song_service
from app.services.music.user_service import user_service

router = APIRouter()
logger = logging.getLogger(__name__)


class LocalChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class LocalHistoryMsg(BaseModel):
    role: str
    content: str
    ts: int


class LocalTraceEvent(BaseModel):
    node: str
    content: str
    is_json_like: bool


def _music_graph_from_request(request: Request):
    graph = getattr(request.app.state, "music_graph", None)
    if graph is None:
        raise HTTPException(
            status_code=503,
            detail="本地会话存储暂时不可用，请稍后重试",
        )
    return graph


async def _resolve_identity(raw_thread_id: str | None) -> IdentityContext:
    try:
        user_id = await get_authenticated_user_id()
    except AuthenticationRequiredError as exc:
        raise HTTPException(status_code=401, detail="请先登录 QQ 音乐") from exc
    except AuthenticationUnavailableError as exc:
        raise HTTPException(status_code=503, detail="认证状态暂时不可用") from exc

    try:
        return build_identity_context(user_id, raw_thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="thread_id 格式无效") from exc


def _checkpoint_config(identity: IdentityContext) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": identity.checkpoint_thread_id}}


def _is_storage_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, sqlite3.Error):
            return True
        module = type(current).__module__
        if module.startswith(("aiosqlite", "langgraph.checkpoint.sqlite")):
            return True
        current = current.__cause__ or current.__context__
    return False


def _snapshot_base_ms(created_at: Any, message_count: int) -> int:
    try:
        if isinstance(created_at, datetime):
            value = created_at
        elif isinstance(created_at, str) and created_at:
            value = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            raise ValueError
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(1, int(value.timestamp() * 1000))
    except (TypeError, ValueError, OverflowError):
        return max(1, message_count)


def _message_created_at_ms(message: Any) -> int | None:
    additional_kwargs = getattr(message, "additional_kwargs", {})
    value = additional_kwargs.get("created_at_ms") if isinstance(additional_kwargs, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _visible_history_messages(messages: list[Any], snapshot_created_at: Any) -> list[dict[str, object]]:
    visible: list[tuple[str, Any]] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            visible.append(("user", message))
        elif is_user_visible_ai_message(message):
            visible.append(("assistant", message))

    base_ms = _snapshot_base_ms(snapshot_created_at, len(visible))
    previous = 0
    result: list[dict[str, object]] = []
    for index, (role, message) in enumerate(visible):
        fallback = base_ms - (len(visible) - 1 - index)
        candidate = _message_created_at_ms(message) or fallback
        timestamp = max(candidate, previous + 1)
        previous = timestamp
        result.append(
            {
                "role": role,
                "content": msg_content(message),
                "ts": timestamp,
            }
        )
    return result


@router.get("/chat/local/history")
async def local_chat_history(
    request: Request,
    thread_id: str | None = Query(None),
    limit: int = Query(40, ge=1, le=100),
):
    identity = await _resolve_identity(thread_id)
    graph = _music_graph_from_request(request)
    try:
        snapshot = await graph.aget_state(_checkpoint_config(identity))
    except Exception as exc:
        if _is_storage_error(exc):
            logger.error("读取本地会话历史失败 | error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="本地会话存储暂时不可用，请稍后重试",
            ) from exc
        logger.error("读取本地会话历史异常 | error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="本地 Agent 执行失败，请稍后重试") from exc

    values = snapshot.values if snapshot is not None and isinstance(snapshot.values, dict) else {}
    raw_messages = values.get("messages", [])
    messages = raw_messages if isinstance(raw_messages, list) else []
    visible = _visible_history_messages(messages, getattr(snapshot, "created_at", None))
    return {
        "status": "success",
        "data": {"thread_id": identity.thread_id, "messages": visible[-limit:]},
    }


@router.post("/chat/local")
async def local_chat(req: LocalChatRequest, request: Request):
    user_text = (req.message or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="message 不能为空")

    identity = await _resolve_identity(req.thread_id)
    graph = _music_graph_from_request(request)
    config = _checkpoint_config(identity)

    trace: list[dict[str, object]] = []
    latest_messages: list[object] = []
    human_message = HumanMessage(
        content=user_text,
        additional_kwargs={"created_at_ms": now_ms()},
    )

    try:
        async for event in graph.astream(
            {
                "user_id": identity.user_id,
                "thread_id": identity.thread_id,
                "messages": [human_message],
            },
            config=config,
            stream_mode="updates",
        ):
            if not isinstance(event, dict):
                continue
            for node_name, node_output in event.items():
                if node_name not in TRACE_NODE_NAMES:
                    continue
                content = _extract_trace_content(node_name, node_output)
                if content:
                    trace.append(
                        {
                            "node": node_name,
                            "content": content,
                            "is_json_like": _looks_like_json(content),
                        }
                    )
                if isinstance(node_output, dict):
                    maybe_messages = node_output.get("messages", [])
                    if isinstance(maybe_messages, list) and maybe_messages:
                        latest_messages = maybe_messages
    except Exception as exc:
        if _is_storage_error(exc):
            logger.error("写入本地会话失败 | error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="本地会话存储暂时不可用，请稍后重试",
            ) from exc
        logger.error("本地 Agent 执行异常 | error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="本地 Agent 执行失败，请稍后重试") from exc

    visible_reply = next(
        (
            message
            for message in reversed(latest_messages)
            if is_user_visible_ai_message(message)
        ),
        None,
    )
    if visible_reply is None:
        raise HTTPException(status_code=500, detail="本地 Agent 执行失败，请稍后重试")

    return {
        "status": "success",
        "data": {
            "thread_id": identity.thread_id,
            "reply": msg_content(visible_reply),
            "trace": trace,
        },
    }


@router.get("/auth/status")
async def auth_status():
    return await check_or_refresh_credential()


@router.post("/auth/qr/create")
async def auth_qr_create():
    return await qr_login_manager.create_qr()


@router.get("/auth/qr/check")
async def auth_qr_check():
    return await qr_login_manager.check_qr()


@router.post("/auth/logout")
async def auth_logout():
    return await clear_credential()


@router.get("/user/homepage")
async def user_homepage():
    return await user_service.get_homepage()


@router.get("/user/vip-info")
async def user_vip_info():
    return await user_service.get_vip_info()


@router.get("/user/music-gene")
async def user_music_gene():
    return await user_service.get_music_gene()


@router.get("/user/created-songlist")
async def user_created_songlist():
    return await user_service.get_created_songlist()


@router.get("/user/fav-song")
async def user_fav_song(page: int = 1, num: int = 20):
    return await user_service.get_fav_song(page=page, num=num)


@router.get("/user/fav-songlist")
async def user_fav_songlist(page: int = 1, num: int = 20):
    return await user_service.get_fav_songlist(page=page, num=num)


@router.get("/user/fav-album")
async def user_fav_album(page: int = 1, num: int = 20):
    return await user_service.get_fav_album(page=page, num=num)


@router.get("/user/fav-mv")
async def user_fav_mv(page: int = 1, num: int = 20):
    return await user_service.get_fav_mv(page=page, num=num)


@router.get("/user/follow-singers")
async def user_follow_singers(page: int = 1, num: int = 20):
    return await user_service.get_follow_singers(page=page, num=num)


@router.get("/user/follow-user")
async def user_follow_user(page: int = 1, num: int = 20):
    return await user_service.get_follow_user(page=page, num=num)


@router.get("/user/fans")
async def user_fans(page: int = 1, num: int = 20):
    return await user_service.get_fans(page=page, num=num)


@router.get("/user/friend")
async def user_friend(page: int = 1, num: int = 20):
    return await user_service.get_friend(page=page, num=num)


@router.get("/song/info")
async def song_info(values: str):
    raw_items = [item.strip() for item in values.split(",") if item.strip()]
    parsed: list[int] | list[str]
    if raw_items and all(item.isdecimal() for item in raw_items):
        parsed = [int(item) for item in raw_items]
    else:
        parsed = raw_items
    return await song_service.get_song_info(values=parsed)


@router.get("/song/detail")
async def song_detail(value: str):
    parsed_value: str | int = int(value) if value.isdecimal() else value
    return await song_service.get_song_detail(value=parsed_value)


@router.get("/song/play-urls")
async def song_play_urls(mids: str):
    mid_list = [item.strip() for item in mids.split(",") if item.strip()]
    return await song_service.get_play_urls(mids=mid_list)


@router.get("/song/playable-url")
async def song_playable_url(song_mid: str):
    return await song_service.get_playable_url(song_mid=song_mid)


@router.get("/song/cover")
async def song_cover(song_mid: str, size: int = Query(300, ge=150, le=1500)):
    cover_url = await song_service.get_song_cover(song_mid=song_mid, size=size)
    if not cover_url:
        return {"status": "error", "message": "未能获取歌曲封面"}
    return {"status": "success", "data": {"song_mid": song_mid, "cover_url": cover_url, "size": size}}


@router.get("/song/similar")
async def song_similar(songid: int):
    return await song_service.get_similar_songs(songid=songid)


@router.get("/song/other-versions")
async def song_other_versions(value: str):
    parsed_value: str | int = int(value) if value.isdecimal() else value
    return await song_service.get_other_versions(value=parsed_value)


@router.get("/song/related-playlists")
async def song_related_playlists(songid: int):
    return await song_service.get_related_playlists(songid=songid)


@router.get("/song/related-mvs")
async def song_related_mvs(songid: int, last_mvid: str | None = None):
    return await song_service.get_related_mvs(songid=songid, last_mvid=last_mvid)


@router.get("/song/labels")
async def song_labels(songid: int):
    return await song_service.get_labels(songid=songid)


@router.get("/song/producers")
async def song_producers(value: str):
    parsed_value: str | int = int(value) if value.isdecimal() else value
    return await song_service.get_producers(value=parsed_value)


@router.get("/song/sheet-music")
async def song_sheet_music(mid: str):
    return await song_service.get_sheet_music(mid=mid)


@router.get("/song/favorite-counts")
async def song_favorite_counts(songids: str):
    ids = [int(item.strip()) for item in songids.split(",") if item.strip() and item.strip().isdecimal()]
    return await song_service.get_favorite_counts(songids=ids)


@router.get("/tools/user/fav-song")
async def tool_user_fav_song(page: int = 1, num: int = 20):
    try:
        res = await user_service.get_fav_song(page=page, num=num)

        if res.get("status") == "error":
            return {"result": f"获取收藏歌曲失败：{res.get('message')}"}

        total_num = res.get("total_num", 0)
        cleaned_results = res.get("data", [])

        if not cleaned_results:
            return {"result": f"未能获取到收藏歌曲。可能是用户的“我喜欢”列表为空，或者第 {page} 页已经没有数据了。"}

        start_index = (page - 1) * num + 1
        for idx, item in enumerate(cleaned_results):
            item["index"] = start_index + idx

        agent_context = {
            "summary": f"用户共收藏了 {total_num} 首歌曲，当前展示的是第 {page} 页的数据。",
            "total_songs": total_num,
            "current_page": page,
            "songs": cleaned_results,
        }

        return {"result": agent_context}
    except Exception as e:
        return {"result": f"工具执行时发生内部错误：{str(e)}"}


@router.get("/tools/user/created-songlist")
async def tool_user_created_songlist():
    try:
        res = await user_service.get_created_songlist()

        if res.get("status") == "error":
            return {"result": f"获取创建的歌单失败：{res.get('message')}"}

        total_num = res.get("total_num", 0)
        cleaned_results = res.get("data", [])

        if not cleaned_results:
            return {"result": "你目前还没有创建任何歌单。"}

        for idx, item in enumerate(cleaned_results):
            item["index"] = idx + 1

        agent_context = {
            "summary": f"用户共创建了 {total_num} 个歌单。",
            "total_songlists": total_num,
            "songlists": cleaned_results,
        }

        return {"result": agent_context}
    except Exception as e:
        return {"result": f"工具执行时发生内部错误：{str(e)}"}


@router.get("/tools/user/fav-songlist")
async def tool_user_fav_songlist(page: int = 1, num: int = 20):
    try:
        res = await user_service.get_fav_songlist(page=page, num=num)

        if res.get("status") == "error":
            return {"result": f"获取收藏歌单失败：{res.get('message')}"}

        total_num = res.get("total_num", 0)
        has_more = res.get("has_more", False)
        cleaned_results = res.get("data", [])

        if not cleaned_results:
            return {"result": f"未能获取到收藏歌单。可能是用户没有收藏任何歌单，或者第 {page} 页为空。"}

        start_index = (page - 1) * num + 1
        for idx, item in enumerate(cleaned_results):
            item["index"] = start_index + idx

        more_info = "还有更多页可以获取。" if has_more else "这是最后一页。"
        agent_context = {
            "summary": f"用户共收藏了 {total_num} 个歌单，当前展示的是第 {page} 页的数据。{more_info}",
            "total_songlists": total_num,
            "current_page": page,
            "has_more": has_more,
            "songlists": cleaned_results,
        }

        return {"result": agent_context}
    except Exception as e:
        return {"result": f"工具执行时发生内部错误：{str(e)}"}


# ===============================
# Direct API for frontend player
# ===============================


@router.get("/playlist/{dirid}/tracks", response_model=PlaylistBrowserArtifact)
async def get_playlist_browser_page(
    dirid: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    playlist_name: str = Query("", description="可选：前端已知歌单名"),
):
    if dirid <= 0:
        raise HTTPException(status_code=400, detail="dirid 必须大于 0")

    res = await playlist_service.get_playlist_detail(
        dirid=dirid,
        page=page,
        num=page_size,
        onlysong=False,
    )

    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "获取歌单失败"))

    total_song_num = int(res.get("total_song_num", 0) or 0)
    playlist_info = res.get("playlist_info", {}) if isinstance(res.get("playlist_info"), dict) else {}
    resolved_name = playlist_info.get("title") or playlist_name or f"歌单(dirid={dirid})"

    playlist_songlist = res.get("songlist", []) if isinstance(res.get("songlist"), list) else []
    tracks = []
    for idx, song in enumerate(playlist_songlist):
        song_mid = str(song.get("mid", "") or "").strip()
        if not song_mid:
            continue

        tracks.append(
            {
                "index": (page - 1) * page_size + idx + 1,
                "song_mid": song_mid,
                "title": str(song.get("title", "") or "未知歌曲"),
                "artist": str(song.get("singer", "") or ""),
                "cover": "",
            }
        )

    has_more = page * page_size < total_song_num

    return PlaylistBrowserArtifact(
        type="playlist_browser",
        playlist_name=str(resolved_name).strip() or f"歌单(dirid={dirid})",
        dirid=dirid,
        page=page,
        page_size=page_size,
        total_song_num=max(total_song_num, len(tracks)),
        has_more=has_more,
        tracks=tracks,
        description=f"已加载第 {page} 页，可点击歌曲直接播放",
    )


@router.get("/song/play-url", response_model=PlayMusicArtifact)
async def get_play_url_by_song_mid(
    song_mid: str = Query(..., description="歌曲 mid"),
    title: str = Query("", description="可选：歌曲标题"),
    artist: str = Query("", description="可选：歌手名"),
):
    clean_mid = (song_mid or "").strip()
    if not clean_mid:
        raise HTTPException(status_code=400, detail="song_mid 不能为空")

    playable_url = await song_service.get_playable_url(clean_mid)

    if not playable_url:
        raise HTTPException(status_code=404, detail="无法获取播放链接，可能受版权或权限限制")

    cover_url = await song_service.get_song_cover(song_mid=clean_mid, size=300)

    return PlayMusicArtifact(
        type="play_music",
        song_mid=clean_mid,
        title=(title or "").strip() or "未知歌曲",
        artist=(artist or "").strip(),
        url=playable_url,
        cover=cover_url or "",
        description="已获取播放链接",
    )
