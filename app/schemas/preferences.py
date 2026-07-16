"""Validated, checkpoint-safe user preference models and deterministic merge."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


PreferenceValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=60),
]


def _deduplicate(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


class PreferenceBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    liked: list[PreferenceValue] = Field(default_factory=list, max_length=20)
    disliked: list[PreferenceValue] = Field(default_factory=list, max_length=20)

    @field_validator("liked", "disliked", mode="after")
    @classmethod
    def deduplicate_values(cls, values: list[str]) -> list[str]:
        return _deduplicate(values)

    @model_validator(mode="after")
    def validate_mutual_exclusion(self) -> "PreferenceBucket":
        liked = {value.casefold() for value in self.liked}
        disliked = {value.casefold() for value in self.disliked}
        if liked & disliked:
            raise ValueError("同一偏好不能同时标记为喜欢和不喜欢")
        return self


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artists: PreferenceBucket = Field(default_factory=PreferenceBucket)
    genres: PreferenceBucket = Field(default_factory=PreferenceBucket)
    languages: PreferenceBucket = Field(default_factory=PreferenceBucket)
    scenes: PreferenceBucket = Field(default_factory=PreferenceBucket)
    version: int = Field(default=0, ge=0)
    updated_at: datetime | None = None

    @field_validator("updated_at", mode="after")
    @classmethod
    def normalize_updated_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at 必须包含时区")
        return value.astimezone(timezone.utc)


class PreferenceSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["artist", "genre", "language", "scene"]
    action: Literal["like", "dislike", "clear"]
    value: PreferenceValue


class PreferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: list[PreferenceSignal] = Field(default_factory=list, max_length=10)


class PreferenceMergeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferences: UserPreferences
    status: Literal["updated", "unchanged"]


_CATEGORY_BUCKET = {
    "artist": "artists",
    "genre": "genres",
    "language": "languages",
    "scene": "scenes",
}


def _remove_casefold(values: list[str], target: str) -> bool:
    key = target.casefold()
    original_length = len(values)
    values[:] = [value for value in values if value.casefold() != key]
    return len(values) != original_length


def merge_preferences(
    current: UserPreferences,
    patch: PreferencePatch,
    *,
    updated_at: datetime | None = None,
) -> PreferenceMergeResult:
    """Apply a patch in order without database or model side effects."""
    bucket_data = current.model_dump(mode="python", exclude={"version", "updated_at"})
    original = current.model_dump(mode="python", exclude={"version", "updated_at"})

    for signal in patch.signals:
        bucket = bucket_data[_CATEGORY_BUCKET[signal.category]]
        liked: list[str] = bucket["liked"]
        disliked: list[str] = bucket["disliked"]
        value = signal.value

        if signal.action == "clear":
            _remove_casefold(liked, value)
            _remove_casefold(disliked, value)
            continue

        target = liked if signal.action == "like" else disliked
        opposite = disliked if signal.action == "like" else liked
        _remove_casefold(opposite, value)
        if not any(existing.casefold() == value.casefold() for existing in target):
            target.append(value)
            if len(target) > 20:
                del target[:-20]

    if bucket_data == original:
        return PreferenceMergeResult(preferences=current.model_copy(deep=True), status="unchanged")

    timestamp = updated_at or datetime.now(timezone.utc)
    merged = UserPreferences(
        **bucket_data,
        version=current.version + 1,
        updated_at=timestamp,
    )
    return PreferenceMergeResult(preferences=merged, status="updated")
