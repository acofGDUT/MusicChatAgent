import logging
from typing import Any

from qqmusic_api.modules.song import EncryptedSongFileType, SongFileInfo, SongFileType, SpecialSongFileType

from app.core.client import create_client

logger = logging.getLogger(__name__)

QQMUSIC_STREAM_PREFIX = "https://isure.stream.qqmusic.qq.com/"


class SongService:
    """歌曲相关服务，统一通过 client 调用底层 API。"""

    async def get_song_info(self, values: list[int] | list[str]) -> list[dict[str, Any]]:
        """根据歌曲 ID 或 MID 批量获取基础信息。"""
        if not values:
            return []

        try:
            async with await create_client() as client:
                resp = await client.song.query_song(value=values)
            return [song.model_dump() for song in resp.tracks]
        except Exception as e:
            logger.error(f"获取歌曲基础信息失败: {e}")
            return []

    async def get_song_detail(self, value: str | int) -> dict[str, Any]:
        """获取单首歌曲详细信息。"""
        try:
            async with await create_client() as client:
                resp = await client.song.get_detail(value=value)
            return resp.model_dump()
        except Exception as e:
            logger.error(f"获取歌曲详情失败 (ID/MID: {value}): {e}")
            return {"error": str(e)}

    async def get_song_cover(self, song_mid: str, size: int = 300) -> str | None:
        """根据歌曲 MID 获取歌曲封面 URL。"""
        if not song_mid:
            return None

        try:
            async with await create_client() as client:
                # get_detail 返回 GetSongDetailResponse, 其中 track 对应 track_info(Song)
                resp = await client.song.get_detail(value=song_mid)

            # Song.cover_url(size) 定义在 qqmusic_api.models.base.Song
            cover_url = resp.track.cover_url(size=size)
            return cover_url or None
        except Exception as e:
            logger.error(f"获取歌曲封面失败 (MID: {song_mid}, size: {size}): {e}")
            return None

    async def get_play_urls(
        self,
        mids: list[str],
        file_type: SongFileType | EncryptedSongFileType | SpecialSongFileType = SongFileType.MP3_128,
    ) -> dict[str, str | tuple[str, str]]:
        """批量获取歌曲播放链接。"""
        if not mids:
            return {}

        try:
            file_info = [SongFileInfo(mid=mid) for mid in mids]
            async with await create_client() as client:
                resp = await client.song.get_song_urls(file_info=file_info, file_type=file_type)
                print(resp)

            result: dict[str, str | tuple[str, str]] = {}
            for item in resp.data:
                if not item.mid:
                    continue
                if isinstance(file_type, EncryptedSongFileType):
                    result[item.mid] = (item.purl or "", item.ekey or "")
                else:
                    result[item.mid] = item.purl or ""
            return result
        except Exception as e:
            error_data = getattr(e, "data", None)
            logger.exception(
                "获取歌曲播放链接失败 | 异常类型=%s | file_type=%s | mids=%s | data=%r | 错误=%s",
                type(e).__name__,
                file_type,
                mids,
                error_data,
                e,
            )
            return {}

    async def get_similar_songs(self, songid: int) -> list[dict[str, Any]]:
        try:
            async with await create_client() as client:
                resp = await client.song.get_similar_song(songid=songid)
            return [group.model_dump() for group in resp.song]
        except Exception as e:
            logger.error(f"获取相似歌曲失败 (ID: {songid}): {e}")
            return []

    async def get_other_versions(self, value: str | int) -> list[dict[str, Any]]:
        try:
            async with await create_client() as client:
                resp = await client.song.get_other_version(value=value)
            return [song.model_dump() for song in resp.data]
        except Exception as e:
            logger.error(f"获取其他版本失败 (ID/MID: {value}): {e}")
            return []

    async def get_related_playlists(self, songid: int) -> list[dict[str, Any]]:
        try:
            async with await create_client() as client:
                resp = await client.song.get_related_songlist(songid=songid)
            return [item.model_dump() for item in resp.songlist]
        except Exception as e:
            logger.error(f"获取相关歌单失败 (ID: {songid}): {e}")
            return []

    async def get_related_mvs(self, songid: int, last_mvid: str | None = None) -> list[dict[str, Any]]:
        try:
            async with await create_client() as client:
                resp = await client.song.get_related_mv(songid=songid, last_mvid=last_mvid)
            return [item.model_dump() for item in resp.mv]
        except Exception as e:
            logger.error(f"获取相关 MV 失败 (ID: {songid}): {e}")
            return []

    async def get_labels(self, songid: int) -> list[dict[str, Any]]:
        try:
            async with await create_client() as client:
                resp = await client.song.get_labels(songid=songid)
            return [item.model_dump() for item in resp.labels]
        except Exception as e:
            logger.error(f"获取歌曲标签失败 (ID: {songid}): {e}")
            return []

    async def get_producers(self, value: str | int) -> list[dict[str, Any]]:
        try:
            async with await create_client() as client:
                resp = await client.song.get_producer(value=value)
            return [item.model_dump() for item in resp.data]
        except Exception as e:
            logger.error(f"获取制作者信息失败 (ID/MID: {value}): {e}")
            return []

    async def get_sheet_music(self, mid: str) -> dict[str, Any]:
        try:
            async with await create_client() as client:
                resp = await client.song.get_sheet(mid=mid)
            return resp.model_dump()
        except Exception as e:
            logger.error(f"获取曲谱失败 (MID: {mid}): {e}")
            return {}

    async def get_favorite_counts(self, songids: list[int]) -> dict[str, Any]:
        try:
            async with await create_client() as client:
                resp = await client.song.get_fav_num(song_ids=songids)
            return resp.model_dump()
        except Exception as e:
            logger.error(f"获取收藏数量失败: {e}")
            return {}

    async def get_playable_url(self, song_mid: str) -> str | None:
        """获取单首歌曲可供前端播放的直链。"""
        if not song_mid:
            return None

        urls = await self.get_play_urls(mids=[song_mid], file_type=SongFileType.MP3_128)
        value = urls.get(song_mid)
        if not value:
            return None

        raw_url = value[0] if isinstance(value, tuple) else value
        if not raw_url:
            return None

        if raw_url.startswith(("http://", "https://")):
            return raw_url

        return f"{QQMUSIC_STREAM_PREFIX}{raw_url.lstrip('/')}"


song_service = SongService()