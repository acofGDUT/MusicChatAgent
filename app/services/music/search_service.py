import logging
from typing import Any, Dict, List
import qqmusic_api.search as qq_search
from qqmusic_api.search import SearchType

logger = logging.getLogger(__name__)


class SearchService:
    """
    搜索相关服务。
    用于获取热搜、关键词补全、综合搜索以及精准分类搜索。
    这是 AI Agent 把文本转换为实体 ID (songid, mid, dirid) 的核心桥梁。
    """

    from typing import Dict, Any, List
    from qqmusic_api import search as qq_search  # 假设你的底层包是这样导入的
    import logging

    logger = logging.getLogger(__name__)

    async def get_hotkeys(self) -> Dict[str, Any]:
        """
        获取当前 QQ 音乐的热搜词榜单，并进行数据清洗。
        (非常适合 Agent 在用户不知道听什么的时候，主动做推荐)
        """
        try:
            raw_data = await qq_search.hotkey()

            # 提取核心的热搜列表
            hotkey_list = raw_data.get("vec_hotkey", [])

            cleaned_hotkeys = []
            for index, item in enumerate(hotkey_list):
                # 过滤掉空的或者无效的数据
                title = item.get("title", "").strip()
                if not title:
                    continue

                score = item.get("score", "0")
                desc = item.get("description", "").strip()

                # 简化类型说明：通常 type/kind 不同代表不同的内容形态
                # 简单映射一下，如果需要更精确，可以根据 API 文档调整
                content_type = "歌曲/热词"
                if "巡回演唱会" in title:
                    content_type = "演唱会"
                elif "新专辑" in item.get("query", ""):
                    content_type = "专辑"

                cleaned_item = {
                    "rank": index + 1,  # 排名
                    "title": title,  # 热搜标题
                    "hot_score": score,  # 热度值
                    "description": desc,  # 描述（如：正在热搜）
                    "type": content_type  # 内容类型
                }
                cleaned_hotkeys.append(cleaned_item)

            # 顺便提取一下底部的推荐词 (vec_reckey)
            rec_keys = raw_data.get("vec_reckey", [])
            recommendation = ""
            if rec_keys and rec_keys[0].get("title"):
                recommendation = rec_keys[0].get("title")

            # 组装最终返回给 Agent 的干净数据
            return {
                "status": "success",
                "top_search_keywords": cleaned_hotkeys,
                "special_recommendation": recommendation  # 比如示例里的 "陈奕迅"
            }

        except Exception as e:
            logger.error(f"❌ 获取热搜词失败: {e}")
            return {
                "status": "error",
                "message": str(e),
                "top_search_keywords": []
            }

    import re
    from typing import Dict, Any, List
    # 假设你的 logger 和 SearchType 已经正确导入

    import logging
    from typing import Dict, Any

    # 假设 logger 和 SearchType 已经定义
    logger = logging.getLogger(__name__)

    async def search_by_type(
            self,
            keyword: str,
            search_type: SearchType = SearchType.SONG,
            num: int = 10,
            page: int = 1,
            highlight: bool = False
    ) -> Dict[str, Any]:
        """
        【Agent 核心功能】精确分类搜索并清洗数据 (当前仅展示 SONG 类型处理)
        """
        try:
            # 1. 调用底层 API 获取原始数据
            # raw_res 就是你提供的那个包含多个复杂字典的列表
            raw_res = await qq_search.search_by_type(
                keyword=keyword,
                search_type=search_type,
                num=num,
                page=page,
                highlight=highlight
            )

            cleaned_data = []
            items = raw_res if isinstance(raw_res, list) else []

            # 2. 检查返回类型并进行数据清洗
            if search_type == SearchType.SONG:
                # 确保 raw_res 是一个列表
                for item in items[:num]:
                    # 提取歌手列表 (可能是多人合唱)
                    singer_list = item.get("singer", [])
                    singers = " & ".join([s.get("name", "未知") for s in singer_list])

                    # 提取核心信息构建清洗后的字典
                    cleaned_item = {
                        "type": "song",
                        "title": item.get("name", "未知"),
                        "singer": singers,
                        "album": item.get("album", {}).get("name", "未知"),
                        "id": item.get("id", ""),
                        "mid": item.get("mid", "")
                    }
                    cleaned_data.append(cleaned_item)
            elif search_type == SearchType.SONGLIST:
                for item in items[:num]:
                    cleaned_data.append({
                        "type": "songlist",
                        "dissname": item.get("dissname", "未知"),  # 歌单名称
                        "nickname": item.get("nickname", "未知"),  # 创建者昵称
                        "songnum": item.get("songnum", 0),  # 包含歌曲数量
                        "listennum_str": item.get("listennum_str", "0"),  # 播放量(带万字)
                        "dissid": item.get("dissid", ""),  # 歌单ID
                        "subhead": item.get("subhead", "")[:50]  # 截取前50个字的描述防冗长
                    })

            elif search_type == SearchType.ALBUM:
                for item in items[:num]:
                    # 提取核心专辑信息
                    cleaned_data.append({
                        "type": "album",
                        "title": item.get("name", "未知"),  # 专辑名称
                        "singer": item.get("singer", "未知"),  # 歌手名称 (接口已经帮我们拼接好了)
                        "publish_date": item.get("publish_date", "未知"),  # 发行日期
                        "song_num": item.get("song_num", 0),  # 包含的歌曲数量
                        "id": item.get("id", ""),  # 专辑ID
                        "albummid": item.get("albummid", "")  # 专辑MID
                    })
            elif search_type == SearchType.SINGER:
                for item in items[:num]:
                    cleaned_data.append({
                        "type": "singer",
                        "singerName": item.get("singerName", "未知"),  # 歌手名称
                        "songNum": item.get("songNum", 0),  # 歌曲总数
                        "albumNum": item.get("albumNum", 0),  # 专辑总数
                        "subtitle": item.get("subtitle", ""),  # 补充描述 (如关联关系)
                        "singerID": item.get("singerID", ""),  # 歌手ID
                        "singerMID": item.get("singerMID", "")  # 歌手MID
                    })
            elif search_type == SearchType.LYRIC:
                for item in items[:num]:
                    singer_list = item.get("singer", [])
                    singers = " & ".join([s.get("name", "未知") for s in singer_list])

                    # 提取歌词并处理换行符，防范空值
                    raw_lyric = str(item.get("content") or "")
                    clean_lyric = raw_lyric.replace("\\n", "\n")

                    cleaned_data.append({
                        "type": "lyric",
                        "name": item.get("name", "未知"),  # 歌曲名称
                        "singer": singers,  # 歌手
                        "album": item.get("album", {}).get("name", "未知"),  # 所属专辑
                        "lyric": clean_lyric,  # 清洗后的歌词
                        "id": item.get("id", ""),  # 歌曲ID
                        "mid": item.get("mid", "")  # 歌曲MID
                    })
            elif search_type == SearchType.USER:
                for item in items[:num]:
                    # 强制转换为字符串，防范 NoneType 报错，并直接替换标签
                    raw_title = str(item.get("title") or "")
                    clean_title = raw_title.replace("<em>", "").replace("</em>", "")

                    cleaned_data.append({
                        "type": "user",
                        "username": clean_title,  # 清洗后的用户名
                        "subtitle": item.get("subtitle", ""),  # 粉丝数/身份描述
                        "encrypt_uin": item.get("encrypt_uin", "") or item.get("uin", "")  # 优先用加密UIN
                    })

            # 这里预留其他类型的处理分支...
            # elif search_type == SearchType.SINGER:
            #     pass

            # 3. 返回标准化、状态明确的结果
            return {
                "status": "success",
                "data": cleaned_data
            }

        except Exception as e:
            logger.error(f"❌ 分类搜索失败 (keyword: {keyword}, type: {search_type.name}): {e}")
            return {"status": "error", "message": str(e)}


# 实例化导出
search_service = SearchService()