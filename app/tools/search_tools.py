import json
from langchain.tools import tool
from pydantic import BaseModel, Field

from app.services.music import search_service
from qqmusic_api.modules.search import SearchType

# ================= 1. 定义工具的输入结构 (给大模型戴上紧箍咒) =================

class SearchMusicInput(BaseModel):
    keyword: str = Field(
        description="搜索关键词，例如：'陈奕迅'、'孤勇者'、'周杰伦 晴天'。"
    )
    search_type: str = Field(
        default="SONG",
        description=(
            "【关键参数】决定你要搜索的数据类型。请严格根据用户的意图从以下枚举字符串中选择：\n"
            "- 'SONG': 默认。用户找歌、听歌时使用（例如：'播放富士山下'）。\n"
            "- 'SINGER': 用户查询歌手信息、歌手MID时使用（例如：'查一下王菲'）。\n"
            "- 'ALBUM': 用户查询专辑信息时使用（例如：'陈奕迅最新的专辑'）。\n"
            "- 'SONGLIST': 用户想找别人整理好的歌单时使用（例如：'推荐一些粤语歌单'）。\n"
            "- 'LYRIC': 用户通过歌词找歌时使用（例如：'歌词里有得不到的永远在骚动'）。\n"
            "- 'USER': 用户想找QQ音乐上的某个特定用户或粉丝会时使用。"
        )
    )
    num: int = Field(
        default=5,
        description="需要返回的搜索结果数量。"
    )

class GetHotkeysInput(BaseModel):
    pass  # 不需要参数的工具，直接用空的 BaseModel


# ================= 2. 定义大模型实际调用的工具 =================

@tool("search_music_tool", args_schema=SearchMusicInput)
async def search_music_tool(keyword: str, search_type: str = "SONG", num: int = 5) -> str:
    """
    【核心搜索工具】全能搜索引擎，可以根据用户意图搜索网络上的歌曲、歌手、专辑、歌单、歌词等。
    """
    try:
        # 1. 将大模型传入的字符串映射为真正的 Enum 对象
        type_map = {
            "SONG": SearchType.SONG,
            "SINGER": SearchType.SINGER,
            "ALBUM": SearchType.ALBUM,
            "SONGLIST": SearchType.SONGLIST,
            "LYRIC": SearchType.LYRIC,
            "USER": SearchType.USER
        }
        # 如果大模型瞎传，默认 fallback 到 SONG
        actual_enum_type = type_map.get(search_type.upper(), SearchType.SONG)

        # 2. 调用 Service 层洗数据方法
        res = await search_service.search_by_type(
            keyword=keyword,
            search_type=actual_enum_type,
            num=num,
            highlight=False
        )

        # 3. 错误处理
        if res.get("status") == "error":
            return f"搜索失败：{res.get('message')}"

        # 4. 拿到清洗好的纯净数据
        cleaned_results = res.get("data", [])

        if not cleaned_results:
             return f"未能在类型为 '{search_type}' 的分类下搜索到关于 '{keyword}' 的内容，请尝试更换搜索类型或关键词。"

        # 5. 为了方便大模型在多轮对话中引用（比如：“播放第2首”），动态加上 index 序号
        for idx, item in enumerate(cleaned_results):
            item["index"] = idx + 1

        # 6. 转为格式化的 JSON 字符串给大模型阅读
        return json.dumps(cleaned_results, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return f"工具执行时发生内部错误：{str(e)}"


@tool("get_hotkeys_tool", args_schema=GetHotkeysInput)
async def get_hotkeys_tool() -> str:
    """
    当用户不知道听什么，让你推荐歌曲，或者询问现在的热门搜索时调用此工具。
    它会返回当前 QQ 音乐的实时热搜榜单以及特别推荐。
    """
    try:
        res = await search_service.get_hotkeys()

        # 1. 错误拦截：适配新版 service 返回的 status 字段
        if res.get("status") == "error":
            return "获取热搜失败，请直接根据你的系统常识，随便推荐几首好听的经典华语歌曲即可。"

        # 2. 获取瘦身后的热搜列表
        keywords = res.get("top_search_keywords", [])
        if not keywords:
            return "当前热搜榜为空，请直接向用户推荐几首时下流行的歌曲。"

        # 3. 格式化输出给大模型：用清晰的文本列表呈现，方便它理解和复述
        formatted_lines = ["【当前 QQ 音乐热搜榜单】"]

        # 为了节省 Token 并保持专注，我们只取前 10 个最热的词
        for item in keywords[:10]:
            rank = item.get("rank")
            title = item.get("title")
            desc = item.get("description")
            c_type = item.get("type")

            # 拼装成一句话：1. 周杰伦 太阳之子 (专辑) - 全新数字专辑开启预售！
            line = f"{rank}. {title} [{c_type}] - {desc}"
            formatted_lines.append(line)

        # 4. 追加特别推荐（如果有的话）
        recommendation = res.get("special_recommendation")
        if recommendation:
            formatted_lines.append(f"\n【今日特别推荐歌手】: {recommendation}")

        # 将列表合并成一段带换行的长文本返回给大模型
        return "\n".join(formatted_lines)
    except Exception as e:
        return f"工具执行异常：{str(e)}。请自行安抚用户并随便推荐两首歌。"
