import logging
from typing import Any, Dict

from app.core.client import create_client
from qqmusic_api.modules.search import SearchType

logger = logging.getLogger(__name__)


class SearchService:
    """搜索相关服务（适配升级后的 qqmusic_api `modules.search` API）。"""

    async def get_hotkeys(self) -> Dict[str, Any]:
        """获取当前 QQ 音乐的热搜词榜单，并进行数据清洗。"""
        try:
            client = await create_client()
            raw_data = await client.search.get_hotkey()

            hotkey_list = raw_data.get("vec_hotkey", []) if isinstance(raw_data, dict) else []

            cleaned_hotkeys = []
            for index, item in enumerate(hotkey_list):
                title = str(item.get("title", "")).strip()
                if not title:
                    continue

                cleaned_hotkeys.append(
                    {
                        "rank": index + 1,
                        "title": title,
                        "hot_score": str(item.get("score", "0")),
                        "description": str(item.get("description", "")).strip(),
                        "type": "歌曲/热词",
                    }
                )

            rec_keys = raw_data.get("vec_reckey", []) if isinstance(raw_data, dict) else []
            recommendation = ""
            if rec_keys and isinstance(rec_keys[0], dict) and rec_keys[0].get("title"):
                recommendation = str(rec_keys[0]["title"])

            return {
                "status": "success",
                "top_search_keywords": cleaned_hotkeys,
                "special_recommendation": recommendation,
            }

        except Exception as e:
            logger.error(f"获取热搜词失败: {e}")
            return {"status": "error", "message": str(e), "top_search_keywords": []}

    async def search_by_type(
        self,
        keyword: str,
        search_type: SearchType = SearchType.SONG,
        num: int = 10,
        page: int = 1,
        highlight: bool = False,
    ) -> Dict[str, Any]:
        """按类型搜索并清洗数据（适配新版 `SearchByTypeResponse` 模型）。"""
        try:
            client = await create_client()
            resp = await client.search.search_by_type(
                keyword=keyword,
                search_type=search_type,
                num=num,
                page=page,
                highlight=highlight,
            )

            cleaned_data = []

            if search_type == SearchType.SONG:
                for item in (getattr(resp, "song", []) or [])[:num]:
                    singers = (
                        " & ".join([s.name for s in (getattr(item, "singer", None) or [])])
                        if getattr(item, "singer", None)
                        else "未知"
                    )
                    cleaned_data.append(
                        {
                            "type": "song",
                            "title": getattr(item, "name", "未知"),
                            "singer": singers,
                            "album": getattr(getattr(item, "album", None), "name", "未知"),
                            "id": getattr(item, "id", ""),
                            "mid": getattr(item, "mid", ""),
                        }
                    )

            elif search_type == SearchType.SONGLIST:
                for item in (getattr(resp, "songlist", []) or [])[:num]:
                    cleaned_data.append(
                        {
                            "type": "songlist",
                            "dissname": getattr(item, "name", "未知"),
                            "nickname": getattr(item, "nickname", "未知"),
                            "songnum": getattr(item, "song_num", 0),
                            "listennum_str": str(getattr(item, "listen_num", 0)),
                            "dissid": getattr(item, "id", ""),
                            "subhead": "",  # 新模型中未明确提供 subhead
                        }
                    )

            elif search_type == SearchType.ALBUM:
                for item in (getattr(resp, "album", []) or [])[:num]:
                    cleaned_data.append(
                        {
                            "type": "album",
                            "title": getattr(item, "name", "未知"),
                            "singer": getattr(item, "singer", "未知"),
                            "publish_date": getattr(item, "publish_date", "未知"),
                            "song_num": getattr(item, "song_num", 0),
                            "id": getattr(item, "id", ""),
                            "albummid": getattr(item, "mid", ""),
                        }
                    )

            elif search_type == SearchType.SINGER:
                for item in (getattr(resp, "singer", []) or [])[:num]:
                    cleaned_data.append(
                        {
                            "type": "singer",
                            "singerName": getattr(item, "name", "未知"),
                            "songNum": getattr(item, "song_num", 0),
                            "albumNum": getattr(item, "album_num", 0),
                            "subtitle": getattr(item, "subtitle", ""),
                            "singerID": getattr(item, "id", ""),
                            "singerMID": getattr(item, "mid", ""),
                        }
                    )

            elif search_type == SearchType.LYRIC:
                # 新版接口下，歌词搜索的结果同样挂在 song 列表里（content 字段存放命中文本片段）
                for item in (getattr(resp, "song", []) or [])[:num]:
                    singers = (
                        " & ".join([s.name for s in (getattr(item, "singer", None) or [])])
                        if getattr(item, "singer", None)
                        else "未知"
                    )
                    clean_lyric = str(getattr(item, "content", "") or "").replace("\\n", "\n")
                    cleaned_data.append(
                        {
                            "type": "lyric",
                            "name": getattr(item, "name", "未知"),
                            "singer": singers,
                            "album": getattr(getattr(item, "album", None), "name", "未知"),
                            "lyric": clean_lyric,
                            "id": getattr(item, "id", ""),
                            "mid": getattr(item, "mid", ""),
                        }
                    )

            elif search_type == SearchType.USER:
                for item in (getattr(resp, "user", []) or [])[:num]:
                    raw_title = str(item.get("title") or "") if isinstance(item, dict) else ""
                    clean_title = raw_title.replace("<em>", "").replace("</em>", "")
                    cleaned_data.append(
                        {
                            "type": "user",
                            "username": clean_title,
                            "subtitle": str(item.get("subtitle", "")) if isinstance(item, dict) else "",
                            "encrypt_uin": (
                                str(item.get("encrypt_uin", "") or item.get("uin", "")) if isinstance(item, dict) else ""
                            ),
                        }
                    )

            # elif search_type == SearchType.MV:
            #     新版有 mv 字段，但当前 Agent 逻辑暂未消费，先注释。
            # elif search_type in (SearchType.AUDIO, SearchType.AUDIO_ALBUM):
            #     新版支持音频节目搜索，当前未接入。

            return {"status": "success", "data": cleaned_data}

        except Exception as e:
            logger.error(f"分类搜索失败 (keyword: {keyword}, type: {search_type.name}): {e}")
            return {"status": "error", "message": str(e)}


search_service = SearchService()
