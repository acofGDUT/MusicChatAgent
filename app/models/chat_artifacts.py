"""Compatibility exports for the canonical artifact schemas."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import ValidationError

from app.schemas.artifacts import (
    PlayMusicArtifact,
    PlaylistBrowserArtifact,
    PlaylistTrack,
)


ChatArtifact: TypeAlias = PlayMusicArtifact | PlaylistBrowserArtifact

_ARTIFACT_MODELS: dict[str, type[ChatArtifact]] = {
    "play_music": PlayMusicArtifact,
    "playlist_browser": PlaylistBrowserArtifact,
}


def parse_artifact(raw: object) -> ChatArtifact | None:
    """Validate a supported raw artifact without leaking schema errors."""
    if not isinstance(raw, dict):
        return None
    model = _ARTIFACT_MODELS.get(raw.get("type"))
    if model is None:
        return None
    try:
        return model.model_validate(raw)
    except (TypeError, ValueError, ValidationError):
        return None
