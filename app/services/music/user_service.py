import logging
import qqmusic_api.user as qq_user
from qqmusic_api import get_session, Session
from typing import Dict, Any

logger = logging.getLogger(__name__)


class UserService:
    """
    用户相关服务。
    完全自动化 ID 管理：只需基础凭证，自动解析并缓存 encrypt_uin。
    """

    async def _get_current_ids(self) -> tuple[str, str]:
        """
        内部辅助方法：获取当前用户的 uin(普通ID) 和 euin(加密ID)
        【亮点】：如果凭证中缺失 euin，会自动调用原生 API 反查并缓存！
        """
        credential = get_session().credential
        if not credential or not credential.musicid:
            raise ValueError("⚠️ 未找到有效的全局凭证 (缺少 musicid)")

        uin_str = str(credential.musicid)
        euin_str = credential.encrypt_uin

        # 核心改进：如果 JSON 里没填 encrypt_uin，自动帮你查！
        if not euin_str:
            logger.info(f"🔍 凭证中缺失 encrypt_uin，正在通过 musicid ({uin_str}) 自动获取...")
            euin_str = await qq_user.get_euin(credential.musicid)

            if euin_str:
                # 顺手存回 credential 内存里，这样下一次调用就不用再发网络请求了
                credential.encrypt_uin = euin_str
                logger.info(f"✅ 成功补全 encrypt_uin: {euin_str}")
            else:
                logger.error("❌ 获取 encrypt_uin 失败，可能影响后续接口调用")

        return uin_str, euin_str

    # ================= 个人基础信息 =================

    async def get_homepage(self):
        session = get_session()
        """获取当前用户主页信息 (包含音乐基因、歌单等)"""
        # 注意：因为 _get_current_ids 变成了 async，这里需要 await
        _, euin = await self._get_current_ids()
        return await qq_user.get_homepage(euin=euin)

    async def get_vip_info(self):
        """获取当前登录账号的 VIP 信息"""
        return await qq_user.get_vip_info()

    async def get_music_gene(self):
        """获取当前用户的音乐基因数据"""
        _, euin = await self._get_current_ids()
        return await qq_user.get_music_gene(euin=euin)

    # ================= 社交与关注 =================

    async def get_follow_singers(self, page: int = 1, num: int = 20):
        """获取关注歌手列表"""
        _, euin = await self._get_current_ids()
        return await qq_user.get_follow_singers(euin=euin, page=page, num=num)

    async def get_follow_user(self, page: int = 1, num: int = 20):
        """获取关注用户列表"""
        _, euin = await self._get_current_ids()
        return await qq_user.get_follow_user(euin=euin, page=page, num=num)

    async def get_fans(self, page: int = 1, num: int = 20):
        """获取粉丝列表"""
        _, euin = await self._get_current_ids()
        return await qq_user.get_fans(euin=euin, page=page, num=num)

    async def get_friend(self, page: int = 1, num: int = 20):
        """获取好友列表 (原生不需要 euin)"""
        return await qq_user.get_friend(page=page, num=num)

    # ================= 音乐资产 (歌单/收藏) =================

    async def get_created_songlist(self) -> Dict[str, Any]:
        """
        【Agent 核心功能】获取创建的歌单列表并清洗标准化
        """
        try:
            # 获取用户 uin
            uin, _ = await self._get_current_ids()

            # 调用原生 API 获取数据
            raw_res = await qq_user.get_created_songlist(uin=uin)

            cleaned_data = []

            # 确保数据是列表
            items = raw_res if isinstance(raw_res, list) else []

            for item in items:
                cleaned_data.append({
                    "type": "songlist",
                    "dirName": item.get("dirName", "未知歌单"),
                    "dirId": str(item.get("dirId","")),
                    "tid": str(item.get("tid", "")),  # 最核心的歌单 ID
                    "song_num": item.get("songNum", 0),
                    "description": item.get("desc", ""),
                    "play_count": item.get("play_cnt", 0)
                })

            # 返回标准化结果
            return {
                "status": "success",
                "total_num": len(cleaned_data),
                "data": cleaned_data
            }

        except Exception as e:
            logger.error(f"❌ 获取自建歌单失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {"status": "error", "message": str(e)}

    async def get_fav_song(self, page: int = 1, num: int = 20) -> Dict[str, Any]:
        """
        【Agent 核心功能】获取收藏歌曲 (我喜欢) 并清洗标准化数据
        """
        try:
            # 1. 获取用户身份标识
            _, euin = await self._get_current_ids()

            # 2. 调用底层 API 获取原始数据
            raw_res = await qq_user.get_fav_song(euin=euin, page=page, num=num)

            cleaned_data = []

            # 3. 提取实际的歌曲列表和总数
            songlist = raw_res.get("songlist", [])
            total_song_num = raw_res.get("total_song_num", 0)

            # 4. 遍历清洗数据 (逻辑与 search_by_type 中的 SONG 类型一致)
            for item in songlist:
                singer_list = item.get("singer", [])
                singers = " & ".join([s.get("name", "未知") for s in singer_list])

                cleaned_data.append({
                    "type": "song",
                    # 兼容处理：有的接口叫 name，有的叫 title，防范取不到值
                    "title": item.get("title") or item.get("name", "未知"),
                    "singer": singers,
                    "album": item.get("album", {}).get("name", "未知"),
                    "id": item.get("id", ""),
                    "mid": item.get("mid", "")
                })

            # 5. 返回标准化结果，顺便把总歌数也带上，方便大模型做上下文推断
            return {
                "status": "success",
                "total_num": total_song_num,  # 告诉大模型用户一共收藏了多少首歌
                "data": cleaned_data
            }

        except Exception as e:
            logger.error(f"❌ 获取收藏歌曲失败 (page: {page}, num: {num}): {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {"status": "error", "message": str(e)}

    async def get_fav_songlist(self, page: int = 1, num: int = 20) -> Dict[str, Any]:
        """
        【Agent 核心功能】获取用户收藏的歌单列表并清洗标准化
        """
        try:
            # 获取用户身份标识
            _, euin = await self._get_current_ids()

            # 调用底层 API 获取原始数据
            raw_res = await qq_user.get_fav_songlist(euin=euin, page=page, num=num)

            cleaned_data = []

            # 提取实际的歌单列表和分页信息
            v_list = raw_res.get("v_list", [])
            total_num = raw_res.get("total", 0)
            has_more = bool(raw_res.get("hasmore", 0))  # 0为False, 1为True

            # 遍历清洗数据
            for item in v_list:
                cleaned_data.append({
                    "tid": str(item.get("tid", "")),  # 严格保留：歌单唯一标识 (转字符串防溢出)
                    "dirId": item.get("dirId"),  # 严格保留：目录ID
                    "name": item.get("name", "未知歌单"),  # 歌单名称
                    "creator": item.get("nickname", "未知"),  # 创建者昵称
                    "song_num": item.get("songnum", 0)  # 歌曲数量
                })

            # 返回标准化结果，带上大模型需要的分页状态
            return {
                "status": "success",
                "total_num": total_num,
                "has_more": has_more,
                "data": cleaned_data
            }

        except Exception as e:
            logger.error(f"❌ 获取收藏歌单失败 (page: {page}, num: {num}): {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {"status": "error", "message": str(e)}

    async def get_fav_album(self, page: int = 1, num: int = 20):
        """获取收藏专辑"""
        _, euin = await self._get_current_ids()
        return await qq_user.get_fav_album(euin=euin, page=page, num=num)

    async def get_fav_mv(self, page: int = 1, num: int = 20):
        """获取收藏 MV"""
        _, euin = await self._get_current_ids()
        return await qq_user.get_fav_mv(euin=euin, page=page, num=num)


# 实例化导出
user_service = UserService()