from http.client import HTTPException
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.music_team_v3_1 import graph


TRACE_NODE_NAMES = {
    "init_memory",
    "intent_parser",
    "supervisor_router",
    "music_ops_subgraph",
    "playback_subgraph",
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
    "init_memory": ["intent", "status", "summary_version", "executor_reentry", "max_reentry"],
    "intent_parser": ["intent", "status", "is_ready_to_execute", "missing_slots"],
    "supervisor_router": ["intent", "status", "route", "executor_reentry", "max_reentry"],
    "memory_sync": ["status", "should_summarize", "should_update_profile", "should_update_soul"],
    "finalizer": ["status", "intent"],
}


def _build_non_llm_trace_summary(node_name: str, node_output: dict) -> str:
    fields = NON_LLM_TRACE_FIELDS.get(node_name, [])
    if not fields:
        return ""

    task = node_output.get("task") if isinstance(node_output.get("task"), dict) else {}
    control = node_output.get("control") if isinstance(node_output.get("control"), dict) else {}
    memory = node_output.get("memory") if isinstance(node_output.get("memory"), dict) else {}

    values: dict[str, object] = {
        "intent": task.get("intent"),
        "status": task.get("status"),
        "missing_slots": task.get("missing_slots"),
        "route": control.get("route"),
        "executor_reentry": control.get("executor_reentry"),
        "max_reentry": control.get("max_reentry"),
        "is_ready_to_execute": control.get("is_ready_to_execute"),
        "should_summarize": control.get("should_summarize"),
        "should_update_profile": control.get("should_update_profile"),
        "should_update_soul": control.get("should_update_soul"),
        "summary_version": memory.get("summary_version"),
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


class LocalChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


class LocalHistoryMsg(BaseModel):
    role: str
    content: str
    ts: int


class LocalTraceEvent(BaseModel):
    node: str
    content: str
    is_json_like: bool


def _history_file_path() -> Path:
    return Path(__file__).resolve().parents[2] / "agents" / "memory" / "history.jsonl"


def _parse_history_timestamp(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return 0


@router.get("/chat/local/history")
async def local_chat_history(thread_id: str = Query("local-web-thread"), limit: int = Query(40, ge=1, le=100)):
    clean_thread_id = (thread_id or "").strip() or "local-web-thread"
    history_path = _history_file_path()
    if not history_path.exists():
        return {"status": "success", "data": {"thread_id": clean_thread_id, "messages": []}}

    messages: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    try:
        with history_path.open("r", encoding="utf-8") as fp:
            for raw_line in fp:
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_thread_id = str(entry.get("thread_id", "") or "").strip()
                if entry_thread_id != clean_thread_id:
                    continue

                tail = entry.get("message_tail", [])
                if not isinstance(tail, list):
                    continue

                base_ts = _parse_history_timestamp(str(entry.get("timestamp", "") or ""))
                for offset, item in enumerate(tail):
                    if not isinstance(item, dict):
                        continue
                    role = "user" if item.get("type") == "human" else "assistant" if item.get("type") == "ai" else ""
                    content = str(item.get("preview", "") or "").strip()
                    if not role or not content:
                        continue

                    key = (role, content)
                    if messages and messages[-1]["role"] == role and messages[-1]["content"] == content:
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    messages.append({"role": role, "content": content, "ts": base_ts + offset})
    except Exception:
        return {"status": "success", "data": {"thread_id": clean_thread_id, "messages": []}}

    return {"status": "success", "data": {"thread_id": clean_thread_id, "messages": messages[-limit:]}}


@router.post("/chat/local")
async def local_chat(req: LocalChatRequest):
    user_text = (req.message or "").strip()
    if not user_text:
        return {"status": "error", "message": "message 不能为空"}

    thread_id = (req.thread_id or "local-default-thread").strip() or "local-default-thread"

    trace: list[dict[str, object]] = []
    latest_messages: list[object] = []

    async for event in graph.astream(
        {
            "thread_id": thread_id,
            "messages": [HumanMessage(content=user_text)],
        },
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="updates",
    ):
        if not isinstance(event, dict):
            continue

        for node_name, node_output in event.items():
            if node_name not in TRACE_NODE_NAMES:
                continue

            content = _extract_trace_content(node_name, node_output)
            if not content:
                continue

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

    messages = latest_messages
    ai_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            ai_text = str(msg.content or "")
            break

    return {
        "status": "success",
        "data": {
            "thread_id": thread_id,
            "reply": ai_text,
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


@router.get("/playlist/{dirid}/tracks")
async def get_playlist_browser_page(
    dirid: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    playlist_name: str = Query("", description="可选：前端已知歌单名"),
):
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

    return {
        "type": "playlist_browser",
        "playlist_name": resolved_name,
        "dirid": dirid,
        "page": page,
        "page_size": page_size,
        "total_song_num": total_song_num,
        "has_more": has_more,
        "tracks": tracks,
        "description": f"已加载第 {page} 页，可点击歌曲直接播放",
    }


@router.get("/song/play-url")
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

    return {
        "type": "play_music",
        "song_mid": clean_mid,
        "title": title,
        "artist": artist,
        "url": playable_url,
        "cover": cover_url or "",
        "description": "已获取播放链接",
    }
