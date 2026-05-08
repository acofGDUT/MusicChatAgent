import logging
from typing import Any, Union, List, Dict, Optional
import qqmusic_api.song as qq_song
from qqmusic_api.song import SongFileType, EncryptedSongFileType

logger = logging.getLogger(__name__)


class SongService:
    """
    歌曲相关服务。
    用于获取歌曲详情、播放链接、相似推荐、其他版本等。
    """

    # ================= 基础信息获取 =================

    async def get_song_info(self, values: Union[List[int], List[str]]) -> List[Dict[str, Any]]:
        """
        根据歌曲 ID (int) 或 MID (str) 批量获取基础信息。

        :param values: 歌曲 id 列表或 mid 列表 (如 [436514] 或 ["0039MnYb0qxYhV"])
        """
        try:
            return await qq_song.query_song(value=values)
        except Exception as e:
            logger.error(f"❌ 获取歌曲基础信息失败: {e}")
            return []

    async def get_song_detail(self, value: Union[str, int]) -> Dict[str, Any]:
        """
        获取单首歌曲的详细信息。
        """
        try:
            return await qq_song.get_detail(value=value)
        except Exception as e:
            logger.error(f"❌ 获取歌曲详情失败 (ID/MID: {value}): {e}")
            return {"error": str(e)}

    # ================= 播放与音源 =================

    async def get_play_urls(
            self,
            mids: List[str],
            file_type: Union[SongFileType, EncryptedSongFileType] = SongFileType.MP3_128
    ) -> Union[Dict[str, str], Dict[str, tuple[str, str]]]:
        """
        获取歌曲真实的物理文件播放链接 (这是实现“播放”功能的核心)。

        :param mids: 歌曲的 mid 列表，例如 ["0039MnYb0qxYhV"]
        :param file_type: 音质/文件类型，默认普通 MP3 (128kbps)。如果要无损可传入 SongFileType.FLAC 等
        :return: 返回字典，普通音质为 {mid: url}，加密音质为 {mid: (url, ekey)}
        """
        try:
            return await qq_song.get_song_urls(mid=mids, file_type=file_type)
        except Exception as e:
            logger.error(f"❌ 获取歌曲播放链接失败 (MIDs: {mids}): {e}")
            return {}

    async def get_trial_url(self, mid: str, vs: str) -> str:
        """
        获取试听文件的链接 (通常用于需要付费但没买 VIP 的情况)。
        注意：参数 `vs` 需要从 `query_song` 查出来的基础信息里的 `vs` 字段获取。
        """
        try:
            url = await qq_song.get_try_url(mid=mid, vs=vs)
            return url or ""
        except Exception as e:
            logger.error(f"❌ 获取试听链接失败 (MID: {mid}): {e}")
            return ""

    # ================= 扩展与关联信息 =================

    async def get_similar_songs(self, songid: int) -> List[Dict[str, Any]]:
        """获取相似歌曲 (Agent 猜你喜欢/自动电台的核心)"""
        try:
            return await qq_song.get_similar_song(songid=songid)
        except Exception as e:
            logger.error(f"❌ 获取相似歌曲失败 (ID: {songid}): {e}")
            return []

    async def get_other_versions(self, value: Union[str, int]) -> List[Dict[str, Any]]:
        """获取这首歌曲的其他版本 (比如 Live 版、Remix 版、纯音乐伴奏版)"""
        try:
            return await qq_song.get_other_version(value=value)
        except Exception as e:
            logger.error(f"❌ 获取其他版本失败 (ID/MID: {value}): {e}")
            return []

    async def get_related_playlists(self, songid: int) -> List[Dict[str, Any]]:
        """获取包含这首歌的其他相关歌单"""
        try:
            return await qq_song.get_related_songlist(songid=songid)
        except Exception as e:
            logger.error(f"❌ 获取相关歌单失败 (ID: {songid}): {e}")
            return []

    async def get_related_mvs(self, songid: int, last_mvid: str = None) -> List[Dict[str, Any]]:
        """获取这首歌相关的 MV"""
        try:
            return await qq_song.get_related_mv(songid=songid, last_mvid=last_mvid)
        except Exception as e:
            logger.error(f"❌ 获取相关 MV 失败 (ID: {songid}): {e}")
            return []

    async def get_labels(self, songid: int) -> List[Dict[str, Any]]:
        """获取歌曲标签 (如 曲风、语种、心情)"""
        try:
            return await qq_song.get_lables(songid=songid)
        except Exception as e:
            logger.error(f"❌ 获取歌曲标签失败 (ID: {songid}): {e}")
            return []

    async def get_producers(self, value: Union[str, int]) -> List[Dict[str, Any]]:
        """获取歌曲背后的制作者信息 (词曲作者、编曲、制作人等)"""
        try:
            return await qq_song.get_producer(value=value)
        except Exception as e:
            logger.error(f"❌ 获取制作者信息失败 (ID/MID: {value}): {e}")
            return []

    async def get_sheet_music(self, mid: str) -> Dict[str, Any]:
        """获取歌曲相关的吉他/钢琴等曲谱"""
        try:
            return await qq_song.get_sheet(mid=mid)
        except Exception as e:
            logger.error(f"❌ 获取曲谱失败 (MID: {mid}): {e}")
            return {}

    async def get_favorite_counts(self, songids: List[int]) -> Dict[str, Any]:
        """获取歌曲的收藏数量 (可用来判断歌曲的热度)"""
        try:
            return await qq_song.get_fav_num(songid=songids)
        except Exception as e:
            logger.error(f"❌ 获取收藏数量失败: {e}")
            return {}
    async def get_playable_url(self, song_mid: str) -> Optional[str]:
        """
        获取可供前端直接播放的音频直链。
        强制请求 MP3_128 格式，规避加密格式前端无法解析的问题。
        
        :param song_mid: 歌曲的唯一标识符 (mid)
        :return: 成功返回 URL 字符串，失败（如无版权/VIP限制）返回 None
        """
        if not song_mid:
            return None

        try:
            # 请求 MP3 格式，注意 mid 参数需要传入列表
            urls_dict = await qq_song.get_song_urls(mid=[song_mid], file_type=SongFileType.MP3_128)
            
            # 从返回的字典中提取对应的直链
            song_url = urls_dict.get(song_mid)
            
            # 如果是 VIP 歌曲且当前账号无权限，或者版权受限，URL 会是空字符串或 None
            if not song_url:
                logger.warning(f"⚠️ 无法获取歌曲 {song_mid} 的播放直链（受限于 VIP 或版权）。")
                return None
                
            logger.info(f"🎵 成功获取歌曲 {song_mid} 的播放直链")
            return song_url
            
        except Exception as e:
            logger.error(f"❌ 获取播放链接时发生底层报错 (mid: {song_mid}): {e}")
            # 服务层不抛出异常给上层，而是返回 None 代表获取失败
            return None

# 实例化导出
song_service = SongService()