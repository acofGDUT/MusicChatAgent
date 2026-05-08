import logging
from typing import Any
import qqmusic_api.songlist as qq_songlist

from qqmusic_api.search import SearchType
from app.services.music.search_service import search_service
from app.services.music.user_service import user_service

logger = logging.getLogger(__name__)


class PlaylistService:
    """
    歌单相关服务。
    用于管理用户的歌单资产（查、建、删、加歌、删歌）。
    依赖底层中间件提供的全局 Session 凭证。
    """

    # ================= 查询类操作 =================

    async def get_playlist_detail(
            self,
            songlist_id: int = 0,
            dirid: int = 0,
            num: int = 10,
            page: int = 1,
            onlysong: bool = False
    ) -> dict[str, Any]:
        """
        分页获取歌单的详细信息和包含的歌曲（经过数据瘦身处理，适合 Agent 读取）。

        :param songlist_id: 歌单的全局唯一 ID (优先使用)
        :param dirid: 歌单的短 ID (常用于个人创建的歌单)
        :param num: 每页返回数量
        :param page: 页码
        :param onlysong: 是否只返回歌曲列表 (跳过歌单标签、创建者等冗余信息)
        """
        # 1. 参数校验：必须提供其中至少一个 ID
        if not songlist_id and not dirid:
            logger.warning("⚠️ 调用获取歌单详情失败：必须提供 songlist_id 或 dirid")
            return {"status": "error", "message": "必须提供 songlist_id 或 dirid 其中之一"}

        try:
            # 调用底层 API
            raw_data = await qq_songlist.get_detail(
                songlist_id=songlist_id,
                dirid=dirid,
                num=num,
                page=page,
                onlysong=onlysong,
                tag=not onlysong,
                userinfo=not onlysong
            )

            # 2. 初始化瘦身后的返回结构
            result = {
                "status": "success",
                "total_song_num": raw_data.get("total_song_num", 0),
                "songlist": []
            }

            # 3. 提取歌单的基本信息 (仅在 onlysong 为 False 且数据存在时)
            if not onlysong and "dirinfo" in raw_data:
                dirinfo = raw_data["dirinfo"]
                creator = dirinfo.get("creator", {})
                result["playlist_info"] = {
                    "title": dirinfo.get("title", "未知歌单"),
                    "description": dirinfo.get("desc", ""),
                    "creator": creator.get("nick", "未知"),
                    "dirid": dirinfo.get("dirid", 0),
                    "songlist_id": dirinfo.get("id", 0)
                }

            # 4. 提取歌曲的核心信息 (mid, 歌名, 歌手, 专辑)
            for song in raw_data.get("songlist", []):
                # 将歌手列表拼装成一个字符串，例如 "陈奕迅 & 王菲"
                singers = [s.get("name", "") for s in song.get("singer", [])]
                singer_names = " & ".join(filter(None, singers))

                cleaned_song = {
                    "mid": song.get("mid", ""),
                    "title": song.get("title", song.get("name", "")),
                    "singer": singer_names,
                    "album": song.get("album", {}).get("title", ""),
                    "publish_time": song.get("time_public", "")
                }
                result["songlist"].append(cleaned_song)

            return result

        except Exception as e:
            logger.error(f"❌ 获取歌单详情失败 (songlist_id: {songlist_id}, dirid: {dirid}): {e}")
            return {
                "status": "error",
                "message": str(e),
                "songlist": []
            }

    async def get_all_songs_in_playlist(self, songlist_id: int, dirid: int = 0) -> list[dict[str, Any]]:
        """
        [高能消耗] 获取一个歌单里的**所有**歌曲。
        库底层会自动并发请求拉取所有页的数据并合并，适合用来做数据分析或全量备份。
        """
        try:
            return await qq_songlist.get_songlist(songlist_id=songlist_id, dirid=dirid)
        except Exception as e:
            logger.error(f"❌ 获取歌单全量歌曲失败 (ID: {songlist_id}): {e}")
            return []

    # ================= 写入类操作 (需登录态) =================

    async def create_playlist(self, name: str) -> dict[str, Any]:
        """
        创建一个新歌单。
        注意：如果重名，QQ音乐会自动在后面加时间戳。

        :return: 返回创建成功的歌单信息 (包含新生成的 dirid 和 songlist_id)
        """
        try:
            result = await qq_songlist.create(dirname=name)
            logger.info(f"✅ 成功创建歌单: {name}")
            return result
        except Exception as e:
            logger.error(f"❌ 创建歌单失败 ({name}): {e}")
            return {"error": str(e)}

    async def delete_playlist(self, dirid: int) -> bool:
        """
        删除一个自己创建的歌单。

        :param dirid: 歌单的短 ID (dirid)
        :return: bool 是否删除成功
        """
        try:
            success = await qq_songlist.delete(dirid=dirid)
            if success:
                logger.info(f"🗑️ 成功删除歌单 (dirid: {dirid})")
            else:
                logger.warning(f"⚠️ 删除歌单失败，可能不存在或无权限 (dirid: {dirid})")
            return success
        except Exception as e:
            logger.error(f"❌ 删除歌单异常 (dirid: {dirid}): {e}")
            return False

    async def add_songs_to_playlist(self, song_ids: list[int], dirid: int = 1) -> bool:
        """
        批量添加歌曲到指定歌单。

        :param song_ids: 歌曲的 songid 列表，例如 [234123, 532342]
        :param dirid: 歌单 ID。默认为 1
        :return: bool 是否添加成功 (如果歌曲全都在里面了，会返回 False)
        """
        if not song_ids:
            return False

        try:
            success = await qq_songlist.add_songs(dirid=dirid, song_ids=song_ids)
            logger.info(f"🎵 向歌单 {dirid} 添加 {len(song_ids)} 首歌曲结果: {success}")
            return success
        except Exception as e:
            logger.error(f"❌ 批量加歌失败 (dirid: {dirid}): {e}")
            return False

    async def remove_songs_from_playlist(self, song_ids: list[int], dirid: int = 1) -> bool:
        """
        批量从指定歌单中移除歌曲。
        """
        if not song_ids:
            return False

        try:
            success = await qq_songlist.del_songs(dirid=dirid, song_ids=song_ids)
            logger.info(f"✂️ 从歌单 {dirid} 移除 {len(song_ids)} 首歌曲结果: {success}")
            return success
        except Exception as e:
            logger.error(f"❌ 批量删歌失败 (dirid: {dirid}): {e}")
            return False

    async def add_songs_by_keyword_to_playlist(
            self,
            playlist_name: str,
            keyword: str,
            target_count: int,
            search_page_size: int = 20,
            max_expand_rounds: int = 5,
    ) -> dict[str, Any]:
        """
        按关键词搜索歌曲，并向指定歌单补齐 target_count 首“当前不在歌单中”的歌曲。

        执行逻辑：
        1) 先通过 playlist_name 在当前用户创建歌单中找到对应 dirid 与 songlist_id(tid)
        2) 拉取该歌单全部歌曲，建立 existing_song_ids 集合
        3) 多轮 search_by_type(keyword, SONG) 获取候选歌曲
        4) 仅把“不在 existing_song_ids 且本次未尝试过”的歌曲加入待添加列表
        5) 调用 add_songs_to_playlist 批量添加

        返回结构中会给出：目标数量、实际添加数量、已存在数量、候选耗尽说明等。
        """
        if not playlist_name or not playlist_name.strip():
            return {"status": "error", "message": "playlist_name 不能为空"}
        if not keyword or not keyword.strip():
            return {"status": "error", "message": "keyword 不能为空"}
        if target_count <= 0:
            return {"status": "error", "message": "target_count 必须大于 0"}
        if search_page_size <= 0:
            return {"status": "error", "message": "search_page_size 必须大于 0"}
        if max_expand_rounds <= 0:
            return {"status": "error", "message": "max_expand_rounds 必须大于 0"}

        try:
            created_res = await user_service.get_created_songlist()
            if created_res.get("status") == "error":
                return {
                    "status": "error",
                    "message": f"获取用户歌单失败: {created_res.get('message', 'unknown error')}"
                }

            target_songlist = None
            normalized_target = playlist_name.strip().lower()
            for item in created_res.get("data", []):
                current_name = str(item.get("dirName", "")).strip()
                if current_name.lower() == normalized_target:
                    target_songlist = item
                    break

            if not target_songlist:
                return {
                    "status": "error",
                    "message": f"未找到名为『{playlist_name}』的用户歌单，无法继续"
                }

            item_dirid_raw = target_songlist.get("dirId")
            try:
                dirid = int(item_dirid_raw)
            except (TypeError, ValueError):
                return {
                    "status": "error",
                    "message": f"歌单『{playlist_name}』的 dirid 无效: {item_dirid_raw}"
                }

            songlist_tid_raw = target_songlist.get("tid")
            try:
                songlist_tid = int(songlist_tid_raw)
            except (TypeError, ValueError):
                return {
                    "status": "error",
                    "message": f"歌单(dirid={dirid}) 的 tid 无效: {songlist_tid_raw}"
                }

            existing_songs = await self.get_all_songs_in_playlist(songlist_id=songlist_tid, dirid=dirid)
            existing_song_ids: set[int] = set()
            for song in existing_songs:
                sid = song.get("id")
                try:
                    if sid is not None:
                        existing_song_ids.add(int(sid))
                except (TypeError, ValueError):
                    continue

            pending_song_ids: list[int] = []
            tried_song_ids: set[int] = set()
            already_in_playlist_count = 0
            search_pages_used: list[int] = []

            for page in range(1, max_expand_rounds + 1):
                search_res = await search_service.search_by_type(
                    keyword=keyword,
                    search_type=SearchType.SONG,
                    num=search_page_size,
                    page=page,
                )

                if search_res.get("status") == "error":
                    return {
                        "status": "error",
                        "message": f"搜索失败: {search_res.get('message', 'unknown error')}",
                        "playlist_name": playlist_name,
                        "dirid": dirid,
                        "keyword": keyword,
                    }

                songs = search_res.get("data", [])
                if not songs:
                    break

                search_pages_used.append(page)

                for song in songs:
                    sid_raw = song.get("id")
                    try:
                        sid = int(sid_raw)
                    except (TypeError, ValueError):
                        continue

                    if sid in tried_song_ids:
                        continue
                    tried_song_ids.add(sid)

                    if sid in existing_song_ids:
                        already_in_playlist_count += 1
                        continue

                    pending_song_ids.append(sid)
                    if len(pending_song_ids) >= target_count:
                        break

                if len(pending_song_ids) >= target_count:
                    break

            if not pending_song_ids:
                return {
                    "status": "success",
                    "message": "未找到可添加歌曲：候选歌曲都已在歌单中，或搜索结果不足",
                    "dirid": dirid,
                    "songlist_name": target_songlist.get("dirName", "未知歌单"),
                    "keyword": keyword,
                    "target_count": target_count,
                    "added_count": 0,
                    "added_song_ids": [],
                    "already_in_playlist_count": already_in_playlist_count,
                    "searched_pages": search_pages_used,
                }

            to_add = pending_song_ids[:target_count]
            add_ok = await self.add_songs_to_playlist(song_ids=to_add, dirid=dirid)

            # 关键改进：底层 add_songs 的布尔值可能与“实际是否已入歌单”不完全一致。
            # 因此统一做一次写后校验，避免把“实际成功”误判为失败。
            latest_songs = await self.get_all_songs_in_playlist(songlist_id=songlist_tid, dirid=dirid)
            latest_song_ids: set[int] = set()
            for song in latest_songs:
                sid = song.get("id")
                try:
                    if sid is not None:
                        latest_song_ids.add(int(sid))
                except (TypeError, ValueError):
                    continue

            actual_added_ids = [sid for sid in to_add if sid in latest_song_ids]
            actual_added_count = len(actual_added_ids)

            if actual_added_count > 0:
                status = "success" if actual_added_count >= target_count else "partial"
                return {
                    "status": status,
                    "message": (
                        "添加完成"
                        if status == "success"
                        else "部分添加完成：候选中仅部分歌曲成功写入歌单"
                    ),
                    "dirid": dirid,
                    "songlist_name": target_songlist.get("dirName", "未知歌单"),
                    "keyword": keyword,
                    "target_count": target_count,
                    "added_count": actual_added_count,
                    "added_song_ids": actual_added_ids,
                    "already_in_playlist_count": already_in_playlist_count,
                    "searched_pages": search_pages_used,
                    "raw_add_ok": add_ok,
                }

            return {
                "status": "partial",
                "message": "找到了可添加歌曲，但写后校验未发现新增（可能接口拒绝、并发冲突或短暂可见性延迟）",
                "dirid": dirid,
                "songlist_name": target_songlist.get("dirName", "未知歌单"),
                "keyword": keyword,
                "target_count": target_count,
                "candidate_song_ids": to_add,
                "added_count": 0,
                "already_in_playlist_count": already_in_playlist_count,
                "searched_pages": search_pages_used,
                "raw_add_ok": add_ok,
            }
        except Exception as e:
            logger.error(
                f"❌ add_songs_by_keyword_to_playlist 执行失败 (playlist_name={playlist_name}, keyword={keyword}): {e}"
            )
            return {"status": "error", "message": str(e)}


# 实例化导出，供其他模块（或 Agent 的 Tool）直接引入使用
playlist_service = PlaylistService()