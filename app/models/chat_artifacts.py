"""Backend-first artifact models.

All artifacts produced by the agent graph MUST pass through these Pydantic
models before reaching the API layer.  Unknown `type` values are rejected.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class PlayMusicArtifact(BaseModel):
    """A song the frontend should play."""

    type: Literal["play_music"] = "play_music"
    song_mid: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    artist: str = ""
    url: str = Field(..., min_length=1)
    cover: str = ""
    description: str = "已获取播放链接"


class PlaylistTrack(BaseModel):
    index: int = 0
    song_mid: str = Field(..., min_length=1)
    title: str = "未知歌曲"
    artist: str = ""
    cover: str = ""


class PlaylistBrowserArtifact(BaseModel):
    """A paginated playlist track listing the frontend can render."""

    type: Literal["playlist_browser"] = "playlist_browser"
    playlist_name: str = Field(..., min_length=1)
    dirid: int
    page: int = 1
    page_size: int = 10
    total_song_num: int = 0
    has_more: bool = False
    tracks: list[PlaylistTrack] = Field(default_factory=list)
    description: str = "已加载歌单"


ChatArtifact = Union[PlayMusicArtifact, PlaylistBrowserArtifact]

# Registry for safe lookup — unknown types rejected at parse time.
_ARTIFACT_MODELS: dict[str, type[ChatArtifact]] = {
    "play_music": PlayMusicArtifact,
    "playlist_browser": PlaylistBrowserArtifact,
}


def parse_artifact(raw: dict) -> ChatArtifact | None:
    """Parse a raw dict into a validated artifact, or None if invalid/unknown."""
    if not isinstance(raw, dict):
        return None

    artifact_type = raw.get("type")
    if not artifact_type or artifact_type not in _ARTIFACT_MODELS:
        return None

    model_cls = _ARTIFACT_MODELS[artifact_type]
    try:
        return model_cls.model_validate(raw)
    except Exception:
        return None
