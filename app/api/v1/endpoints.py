import logging
import time
from functools import wraps

from fastapi import APIRouter, HTTPException, Query

from app.services.music import playlist_service, search_service, song_service, user_service
from qqmusic_api import search, songlist, get_session
from qqmusic_api.search import SearchType

router = APIRouter()
logger = logging.getLogger(__name__)


def log_timing(endpoint_name: str | None = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.info("[API Timing] %s took %.2f ms", endpoint_name or func.__name__, elapsed_ms)

        return wrapper

    return decorator


@router.get("/user/status")
@log_timing()
async def get_status():
    return await search.general_search(keyword="周杰伦")


@router.get("/")
@log_timing()
async def get_vip():
    return await user_service.get_vip_info()


@router.get("/my/homepage")
@log_timing()
async def my_homepage():
    return await user_service.get_homepage()


@router.get("/playlist/detail/SONG")
@log_timing()
async def search_song():
    return await search_service.search_by_type(keyword="陈奕迅", search_type=SearchType.SONG)


@router.get("/playlist/detail/SINGER")
@log_timing()
async def search_singer():
    return await search_service.search_by_type(keyword="陈奕迅", search_type=SearchType.SINGER)


@router.get("/playlist/detail/ALBUM")
@log_timing()
async def search_album():
    return await search_service.search_by_type(keyword="陈奕迅", search_type=SearchType.ALBUM)


@router.get("/playlist/detail/LYRIC")
@log_timing()
async def search_lyric():
    return await search_service.search_by_type(keyword="陈奕迅", search_type=SearchType.LYRIC)


@router.get("/playlist/detail/SONGLIST")
@log_timing()
async def search_songlist():
    return await search_service.search_by_type(keyword="陈奕迅", search_type=SearchType.SONGLIST)


@router.get("/playlist/detail/USER")
@log_timing()
async def search_user():
    return await search_service.search_by_type(keyword="陈奕迅", search_type=SearchType.USER)


@router.get("/my/csonglist")
@log_timing()
async def my_created_songlist():
    return await user_service.get_created_songlist()


@router.get("/my/songlist")
@log_timing()
async def my_fav_songlist():
    return await user_service.get_fav_songlist()


@router.get("/my/song")
@log_timing()
async def my_fav_song():
    return await user_service.get_fav_song()


@router.get("/create/songlist")
@log_timing()
async def create_songlist(name: str):
    return await playlist_service.create_playlist(name)


@router.get("/hot")
@log_timing()
async def hot():
    return await search_service.get_hotkeys()


@router.get("/add")
@log_timing()
async def add_demo_song():
    return await songlist.add_songs(
        201,
        [
            97773,
            449205,
            449198,
            102065756,
            410316,
            1960263,
            637006554,
            632345595,
            633998473,
            634012138,
            647659111,
            644422335,
            646809372,
            646157639,
            647387011,
            650618258,
            649797583,
            650364986,
            213349697,
            204246853,
            105754951,
            644437468,
            230436791,
            650537157,
            646575276,
        ],
    )


@router.get("/delete")
@log_timing()
async def remove_demo_song():
    return await songlist.del_songs(201, [646157639])


@router.get("/playlist/song")
@log_timing()
async def get_playlist_song_raw():
    return await songlist.get_detail(9680571790)


@router.get("/playlist/So")
@log_timing()
async def get_playlist_song_service():
    return await playlist_service.get_playlist_detail(9680571790)

@router.get("/canrefresh")
async def can_refresh():
    return await get_session().credential.can_refresh()

@router.get("/refresh")
async def refresh():
    return await get_session().credential.refresh()

@router.get("/json")
async def asjson():
    return  get_session().credential.as_json()

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

    url_map = await song_service.get_play_urls([clean_mid])
    raw_url = url_map.get(clean_mid) if isinstance(url_map, dict) else None

    playable_url = raw_url[0] if isinstance(raw_url, tuple) else raw_url

    if not playable_url:
        raise HTTPException(status_code=404, detail="无法获取播放链接，可能受版权或权限限制")

    return {
        "type": "play_music",
        "song_mid": clean_mid,
        "title": title,
        "artist": artist,
        "url": playable_url,
        "description": "已获取播放链接",
    }
