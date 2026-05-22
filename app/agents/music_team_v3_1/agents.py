from langchain.agents import create_agent

from app.tools.playlist_tools import (
    add_by_keyword_to_playlist_tool,
    add_songs_to_playlist_tool,
    create_playlist_tool,
    get_playlist_detail_tool,
    remove_songs_from_playlist_tool,
)
from app.tools.search_tools import get_hotkeys_tool, search_music_tool
from app.tools.song_tools import play_music_tool
from app.tools.user_tools import get_created_songlist_tool, get_fav_song_tool

from .config import llm0, llm1
from .prompts import executor_prompt, playback_prompt, replier_prompt
from .utils import safe_kwargs


music_ops_tools = [
    search_music_tool,
    create_playlist_tool,
    remove_songs_from_playlist_tool,
    get_created_songlist_tool,
    get_fav_song_tool,
    add_songs_to_playlist_tool,
    get_hotkeys_tool,
    add_by_keyword_to_playlist_tool,
    get_playlist_detail_tool,
]

playback_tools = [search_music_tool, get_created_songlist_tool, get_playlist_detail_tool, play_music_tool]


def build_agent(*, model, tools, system_prompt: str, name: str):
    base = {"model": model, "tools": tools, "system_prompt": system_prompt, "name": name}
    return create_agent(**(safe_kwargs(create_agent, base) | base))


music_executor = build_agent(
    model=llm1,
    tools=music_ops_tools,
    system_prompt=executor_prompt,
    name="MusicExecutor",
)

playback_executor = build_agent(
    model=llm1,
    tools=playback_tools,
    system_prompt=playback_prompt,
    name="PlayAgent",
)

chat_replier = build_agent(
    model=llm0,
    tools=[],
    system_prompt=replier_prompt,
    name="ChatReplier",
)
