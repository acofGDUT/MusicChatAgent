"""Validated frontend artifact contracts and strict text parsing helpers."""

from __future__ import annotations

import json
import re
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)


_JSON_CODE_BLOCK = re.compile(
    r"\A```json[ \t]*\r?\n(?P<body>[\s\S]*?)\r?\n```[ \t]*\Z"
)


def _strip_required_string(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


def _validate_http_url(value: str, *, allow_empty: bool) -> str:
    if allow_empty and value == "":
        return value
    if not value.startswith(("http://", "https://")):
        raise ValueError("must be an HTTP(S) URL")
    return value


class PlayMusicArtifact(BaseModel):
    """Frontend payload used to render and start the music player."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["play_music"] = "play_music"
    song_mid: str = Field(min_length=1)
    title: str = Field(min_length=1)
    artist: str = ""
    url: str = Field(min_length=1)
    cover: str = ""
    description: str = "已获取播放链接"

    _strip_required_fields = field_validator("song_mid", "title", mode="before")(
        _strip_required_string
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_http_url(value, allow_empty=False)

    @field_validator("cover")
    @classmethod
    def validate_cover(cls, value: str) -> str:
        return _validate_http_url(value, allow_empty=True)


class PlaylistTrack(BaseModel):
    """One track displayed in a playlist-browser artifact."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    song_mid: str = Field(min_length=1)
    title: str = Field(min_length=1)
    artist: str = ""
    cover: str = ""

    _strip_required_fields = field_validator("song_mid", "title", mode="before")(
        _strip_required_string
    )

    @field_validator("cover")
    @classmethod
    def validate_cover(cls, value: str) -> str:
        return _validate_http_url(value, allow_empty=True)


class PlaylistBrowserArtifact(BaseModel):
    """Paginated frontend payload for browsing tracks in a playlist."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["playlist_browser"] = "playlist_browser"
    playlist_name: str = Field(min_length=1)
    dirid: int | None = Field(default=None, gt=0)
    tracks: list[PlaylistTrack] = Field(default_factory=list)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    total_song_num: int = Field(ge=0)
    has_more: bool
    description: str = ""

    _strip_playlist_name = field_validator("playlist_name", mode="before")(
        _strip_required_string
    )

    @model_validator(mode="after")
    def validate_track_page(self) -> PlaylistBrowserArtifact:
        if self.total_song_num < len(self.tracks):
            raise ValueError("total_song_num cannot be smaller than tracks length")

        indexes = [track.index for track in self.tracks]
        if len(indexes) != len(set(indexes)):
            raise ValueError("track indexes must be unique within a page")

        song_mids = [track.song_mid for track in self.tracks]
        if len(song_mids) != len(set(song_mids)):
            raise ValueError("song_mid values must be unique within a page")

        return self


Artifact: TypeAlias = Annotated[
    PlayMusicArtifact | PlaylistBrowserArtifact,
    Field(discriminator="type"),
]

_ARTIFACT_ADAPTER = TypeAdapter(Artifact)


def parse_artifact_text(
    text: str,
) -> PlayMusicArtifact | PlaylistBrowserArtifact | None:
    """Parse a pure JSON object or a single JSON Markdown code block.

    Invalid JSON, mixed prose, arrays, unknown artifact types, and schema errors
    intentionally return ``None`` so callers can handle protocol failures without
    leaking validation exceptions across layer boundaries.
    """

    if not isinstance(text, str):
        return None

    candidate = text.strip()
    code_block = _JSON_CODE_BLOCK.fullmatch(candidate)
    if code_block is not None:
        candidate = code_block.group("body").strip()

    try:
        payload = json.loads(candidate)
        if not isinstance(payload, dict):
            return None
        return _ARTIFACT_ADAPTER.validate_python(payload)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
        return None


def artifact_to_json(
    artifact: PlayMusicArtifact | PlaylistBrowserArtifact,
) -> str:
    """Serialize a validated artifact as canonical, unwrapped JSON."""

    validated = _ARTIFACT_ADAPTER.validate_python(artifact)
    return validated.model_dump_json()
