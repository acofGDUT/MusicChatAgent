import json
from langchain.tools import tool
from pydantic import BaseModel, Field
from qqmusic_api import Session
import app.core.auth as auth_module
from app.core.auth import ensure_credential_loaded

from app.services.music import user_service


async def _with_qqmusic_session() -> Session:
    ready = await ensure_credential_loaded()
    if not ready or auth_module.GLOBAL_CREDENTIAL is None:
        raise RuntimeError("QQ 音乐凭证未初始化，请检查 data/credential.json")
    return Session(credential=auth_module.GLOBAL_CREDENTIAL)


# 假设你把获取用户信息的 service 实例命名为 user_service
# from app.services.user import user_service

# ================= 1. 定义工具的输入结构 =================

class GetFavSongInput(BaseModel):
    page: int = Field(
        default=1,
        description="要获取的页码。默认为 1。如果大模型想看后面的收藏，可以传入 2、3 等。"
    )
    num: int = Field(
        default=20,
        description="每页获取的歌曲数量。推荐保持默认的 20，避免一次性返回数据过多导致记忆混乱。"
    )


# ================= 2. 定义大模型实际调用的工具 =================

@tool("get_fav_song_tool", args_schema=GetFavSongInput)
async def get_fav_song_tool(page: int = 1, num: int = 20) -> str:
    """
    【用户资产工具】用于获取用户收藏的歌曲（也就是“我喜欢”的歌曲）。
    """
    try:
        async with await _with_qqmusic_session():
            # 调用我们刚刚写好的、极其干净的 Service 层方法
            res = await user_service.get_fav_song(page=page, num=num)

        # 1. 处理报错情况
        if res.get("status") == "error":
            return f"获取收藏歌曲失败：{res.get('message')}"

        # 2. 拿到纯净的数据和总数
        total_num = res.get("total_num", 0)
        cleaned_results = res.get("data", [])

        if not cleaned_results:
            return f"未能获取到收藏歌曲。可能是用户的“我喜欢”列表为空，或者第 {page} 页已经没有数据了。"

        # 3. 动态添加序号（考虑了翻页情况，比如第2页的序号应该从 21 开始）
        start_index = (page - 1) * num + 1
        for idx, item in enumerate(cleaned_results):
            item["index"] = start_index + idx

        # 4. 把总数和当前页的数据打包在一起，给大模型提供全局视角
        agent_context = {
            "summary": f"用户共收藏了 {total_num} 首歌曲，当前展示的是第 {page} 页的数据。",
            "total_songs": total_num,
            "current_page": page,
            "songs": cleaned_results
        }

        # 转为 JSON 字符串喂给大模型
        return json.dumps(agent_context, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return f"工具执行时发生内部错误：{str(e)}"



# ================= 2. 定义大模型实际调用的工具 =================

@tool("get_created_songlist_tool")
async def get_created_songlist_tool() -> str:
    """
    【用户资产工具】用于获取用户自己创建的所有歌单列表（包含"我喜欢"、自建分类歌单等）。
    返回的 tid 字段是歌单的唯一标识，后续如果需要获取歌单内的歌曲，请使用该 tid。
    """
    try:
        async with await _with_qqmusic_session():
            # 调用保留了原始字段名的 Service
            res = await user_service.get_created_songlist()

        # 1. 处理报错情况
        if res.get("status") == "error":
            return f"获取创建的歌单失败：{res.get('message')}"

        # 2. 拿到纯净的数据
        total_num = res.get("total_num", 0)
        cleaned_results = res.get("data", [])

        if not cleaned_results:
            return "你目前还没有创建任何歌单。"

        # 3. 动态添加序号，方便大模型在对话中精准引用
        for idx, item in enumerate(cleaned_results):
            item["index"] = idx + 1

        # 4. 打包上下文
        agent_context = {
            "summary": f"用户共创建了 {total_num} 个歌单。",
            "total_songlists": total_num,
            "songlists": cleaned_results
        }

        # 转为 JSON 字符串喂给大模型
        return json.dumps(agent_context, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return f"工具执行时发生内部错误：{str(e)}"

# ================= 1. 定义工具的输入结构 =================

class GetFavSonglistInput(BaseModel):
    page: int = Field(
        default=1,
        description="要获取的页码。默认为 1。如果需要查看更多收藏歌单，可以传入 2、3 等。"
    )
    num: int = Field(
        default=20,
        description="每页获取的歌单数量。推荐保持默认的 20。"
    )

# ================= 2. 定义大模型实际调用的工具 =================

@tool("get_fav_songlist_tool", args_schema=GetFavSonglistInput)
async def get_fav_songlist_tool(page: int = 1, num: int = 20) -> str:
    """
    【用户资产工具】用于获取用户收藏的（别人创建的）歌单列表。
    返回的 tid 字段是歌单的唯一标识，后续如果需要获取歌单内的歌曲，请使用该 tid。
    比如需要添加歌曲到某某歌单（“我喜欢”也是一种歌单）。可以先用这个工具查询dirid。
    """
    try:
        async with await _with_qqmusic_session():
            # 调用清洗好的 Service
            res = await user_service.get_fav_songlist(page=page, num=num)

        # 1. 处理报错情况
        if res.get("status") == "error":
            return f"获取收藏歌单失败：{res.get('message')}"

        # 2. 拿到纯净的数据和分页信息
        total_num = res.get("total_num", 0)
        has_more = res.get("has_more", False)
        cleaned_results = res.get("data", [])

        if not cleaned_results:
            return f"未能获取到收藏歌单。可能是用户没有收藏任何歌单，或者第 {page} 页为空。"

        # 3. 动态添加跨页序号
        start_index = (page - 1) * num + 1
        for idx, item in enumerate(cleaned_results):
            item["index"] = start_index + idx

        # 4. 打包上下文，给大模型上帝视角
        more_info = "还有更多页可以获取。" if has_more else "这是最后一页。"
        agent_context = {
            "summary": f"用户共收藏了 {total_num} 个歌单，当前展示的是第 {page} 页的数据。{more_info}",
            "total_songlists": total_num,
            "current_page": page,
            "has_more": has_more,
            "songlists": cleaned_results
        }

        # 转为 JSON 字符串喂给大模型
        return json.dumps(agent_context, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return f"工具执行时发生内部错误：{str(e)}"