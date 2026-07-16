"""Shared response schemas used by tools, agents, and API endpoints."""

from app.schemas.artifacts import (
    Artifact,
    PlayMusicArtifact,
    PlaylistBrowserArtifact,
    PlaylistTrack,
    artifact_to_json,
    parse_artifact_text,
)
from app.schemas.preferences import (
    PreferenceBucket,
    PreferenceMergeResult,
    PreferencePatch,
    PreferenceSignal,
    UserPreferences,
    merge_preferences,
)

__all__ = [
    "Artifact",
    "PlayMusicArtifact",
    "PlaylistBrowserArtifact",
    "PlaylistTrack",
    "artifact_to_json",
    "parse_artifact_text",
    "PreferenceBucket",
    "PreferenceMergeResult",
    "PreferencePatch",
    "PreferenceSignal",
    "UserPreferences",
    "merge_preferences",
]
