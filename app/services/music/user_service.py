import logging
from typing import Any

from app.core.client import create_client

logger = logging.getLogger(__name__)


class UserService:
    """用户相关服务（基于 client.user 调用底层 API）。"""

    async def _get_current_ids(self) -> tuple[str, str]:
        """
        从 client 实例的 credential 中读取当前账号的 uin 与 euin。
        返回 (uin, euin)，均为字符串。
        """
        try:
            async with await create_client() as client:
                credential = client.credential

            musicid = credential.musicid or credential.str_musicid
            euin = credential.encrypt_uin

            if musicid is None:
                raise ValueError("credential 缺少 musicid/str_musicid")
            if not euin:
                raise ValueError("credential 缺少 encrypt_uin")

            return str(musicid), str(euin)
        except Exception as e:
            logger.error(f"❌ 从 client credential 读取用户 ID 失败: {e}")
            raise ValueError("未找到有效凭证或凭证字段不完整") from e

    # ================= 个人基础信息 =================

    async def get_homepage(self) -> dict[str, Any]:
        """获取当前用户主页信息（包含基础信息与标签详情）。"""
        try:
            _, euin = await self._get_current_ids()
            async with await create_client() as client:
                data = await client.user.get_homepage(euin=euin)
            return {"status": "success", "data": data.model_dump()}
        except Exception as e:
            logger.error(f"❌ 获取用户主页失败: {e}")
            return {"status": "error", "message": str(e)}

    async def get_vip_info(self) -> dict[str, Any]:
        """获取当前登录账号的 VIP 信息。"""
        try:
            async with await create_client() as client:
                data = await client.user.get_vip_info()
            return {"status": "success", "data": data.model_dump()}
        except Exception as e:
            logger.error(f"❌ 获取 VIP 信息失败: {e}")
            return {"status": "error", "message": str(e)}

    async def get_music_gene(self) -> dict[str, Any]:
        """获取当前用户的音乐基因数据。"""
        try:
            _, euin = await self._get_current_ids()
            async with await create_client() as client:
                data = await client.user.get_music_gene(euin=euin)
            return {"status": "success", "data": data.model_dump()}
        except Exception as e:
            logger.error(f"❌ 获取音乐基因失败: {e}")
            return {"status": "error", "message": str(e)}

    # ================= 社交与关注 =================

    async def get_follow_singers(self, page: int = 1, num: int = 20) -> dict[str, Any]:
        """获取关注歌手列表。"""
        try:
            _, euin = await self._get_current_ids()
            async with await create_client() as client:
                res = await client.user.get_follow_singers(euin=euin, page=page, num=num)
            return {
                "status": "success",
                "total_num": res.total,
                "has_more": res.has_more,
                "data": [u.model_dump() for u in res.users],
            }
        except Exception as e:
            logger.error(f"❌ 获取关注歌手失败 (page={page}, num={num}): {e}")
            return {"status": "error", "message": str(e)}

    async def get_follow_user(self, page: int = 1, num: int = 20) -> dict[str, Any]:
        """获取关注用户列表。"""
        try:
            _, euin = await self._get_current_ids()
            async with await create_client() as client:
                res = await client.user.get_follow_user(euin=euin, page=page, num=num)
            return {
                "status": "success",
                "total_num": res.total,
                "has_more": res.has_more,
                "data": [u.model_dump() for u in res.users],
            }
        except Exception as e:
            logger.error(f"❌ 获取关注用户失败 (page={page}, num={num}): {e}")
            return {"status": "error", "message": str(e)}

    async def get_fans(self, page: int = 1, num: int = 20) -> dict[str, Any]:
        """获取粉丝列表。"""
        try:
            _, euin = await self._get_current_ids()
            async with await create_client() as client:
                res = await client.user.get_fans(euin=euin, page=page, num=num)
            return {
                "status": "success",
                "total_num": res.total,
                "has_more": res.has_more,
                "data": [u.model_dump() for u in res.users],
            }
        except Exception as e:
            logger.error(f"❌ 获取粉丝失败 (page={page}, num={num}): {e}")
            return {"status": "error", "message": str(e)}

    async def get_friend(self, page: int = 1, num: int = 20) -> dict[str, Any]:
        """获取好友列表。"""
        try:
            async with await create_client() as client:
                res = await client.user.get_friend(page=page, num=num)
            return {
                "status": "success",
                "has_more": res.has_more,
                "data": [f.model_dump() for f in res.friends],
            }
        except Exception as e:
            logger.error(f"❌ 获取好友列表失败 (page={page}, num={num}): {e}")
            return {"status": "error", "message": str(e)}

    # ================= 音乐资产 (歌单/收藏) =================

    async def get_created_songlist(self) -> dict[str, Any]:
        """获取当前用户创建的歌单列表并标准化输出。"""
        try:
            uin, _ = await self._get_current_ids()
            async with await create_client() as client:
                raw_res = await client.user.get_created_songlist(uin=int(uin))

            cleaned_data = [
                {
                    "type": "songlist",
                    "dirName": item.title,
                    "dirId": str(item.dirid),
                    "tid": str(item.id),
                    "song_num": item.songnum,
                    "description": item.desc,
                    "play_count": item.play_cnt,
                }
                for item in raw_res.playlists
            ]

            return {
                "status": "success",
                "total_num": raw_res.total,
                "data": cleaned_data,
            }
        except Exception as e:
            logger.error(f"❌ 获取自建歌单失败: {e}")
            return {"status": "error", "message": str(e)}

    async def get_fav_song(self, page: int = 1, num: int = 20) -> dict[str, Any]:
        """获取收藏歌曲（我喜欢）并标准化输出。"""
        try:
            _, euin = await self._get_current_ids()
            async with await create_client() as client:
                raw_res = await client.user.get_fav_song(euin=euin, page=page, num=num)

            cleaned_data = []
            for song in raw_res.songs:
                singers = " & ".join([s.name for s in song.singer])
                cleaned_data.append(
                    {
                        "type": "song",
                        "title": song.title or song.name,
                        "singer": singers,
                        "album": song.album.title if song.album else "",
                        "id": song.id,
                        "mid": song.mid,
                    }
                )

            return {
                "status": "success",
                "total_num": raw_res.total,
                "data": cleaned_data,
            }
        except Exception as e:
            logger.error(f"❌ 获取收藏歌曲失败 (page: {page}, num: {num}): {e}")
            return {"status": "error", "message": str(e)}

    async def get_fav_songlist(self, page: int = 1, num: int = 20) -> dict[str, Any]:
        """获取收藏歌单并标准化输出。"""
        try:
            _, euin = await self._get_current_ids()
            async with await create_client() as client:
                raw_res = await client.user.get_fav_songlist(euin=euin, page=page, num=num)

            cleaned_data = [
                {
                    "tid": str(item.id),
                    "dirId": item.dirid,
                    "name": item.title,
                    "creator": item.nickname,
                    "song_num": item.songnum,
                }
                for item in raw_res.playlists
            ]

            return {
                "status": "success",
                "total_num": raw_res.total,
                "has_more": bool(raw_res.hasmore),
                "data": cleaned_data,
            }
        except Exception as e:
            logger.error(f"❌ 获取收藏歌单失败 (page: {page}, num: {num}): {e}")
            return {"status": "error", "message": str(e)}

    async def get_fav_album(self, page: int = 1, num: int = 20) -> dict[str, Any]:
        """获取收藏专辑。"""
        try:
            _, euin = await self._get_current_ids()
            async with await create_client() as client:
                res = await client.user.get_fav_album(euin=euin, page=page, num=num)
            return {
                "status": "success",
                "total_num": res.total,
                "has_more": bool(res.hasmore),
                "data": [a.model_dump() for a in res.albums],
            }
        except Exception as e:
            logger.error(f"❌ 获取收藏专辑失败 (page: {page}, num: {num}): {e}")
            return {"status": "error", "message": str(e)}

    async def get_fav_mv(self, page: int = 1, num: int = 20) -> dict[str, Any]:
        """获取收藏 MV。"""
        try:
            _, euin = await self._get_current_ids()
            async with await create_client() as client:
                res = await client.user.get_fav_mv(euin=euin, page=page, num=num)
            return {
                "status": "success",
                "data": [mv.model_dump() for mv in res.mv_list],
            }
        except Exception as e:
            logger.error(f"❌ 获取收藏 MV 失败 (page: {page}, num: {num}): {e}")
            return {"status": "error", "message": str(e)}


# 实例化导出
user_service = UserService()
