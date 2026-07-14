from __future__ import annotations

from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


class ToolResultCode(str, Enum):
    SUCCESS = "SUCCESS"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PLAYBACK_UNAVAILABLE = "PLAYBACK_UNAVAILABLE"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    WRITE_UNCERTAIN = "WRITE_UNCERTAIN"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    ARTIFACT_INVALID = "ARTIFACT_INVALID"
    INVALID_TOOL_RESULT = "INVALID_TOOL_RESULT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ToolResult(BaseModel):
    ok: bool
    code: ToolResultCode
    message: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False

    @model_validator(mode="after")
    def validate_result_state(self) -> Self:
        if self.ok != (self.code == ToolResultCode.SUCCESS):
            raise ValueError("ok=true if and only if code=SUCCESS")
        if self.code == ToolResultCode.WRITE_UNCERTAIN and self.retryable:
            raise ValueError("WRITE_UNCERTAIN cannot be retried automatically")
        return self

    @classmethod
    def success(cls, message: str, data: dict[str, Any] | None = None) -> Self:
        return cls(
            ok=True,
            code=ToolResultCode.SUCCESS,
            message=message,
            data=data or {},
            retryable=False,
        )

    @classmethod
    def failure(
        cls,
        *,
        code: ToolResultCode,
        message: str,
        data: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> Self:
        return cls(
            ok=False,
            code=code,
            message=message,
            data=data or {},
            retryable=retryable,
        )

    def to_json(self) -> str:
        return self.model_dump_json()


def parse_tool_result(value: object) -> ToolResult | None:
    try:
        if isinstance(value, ToolResult):
            return value
        if isinstance(value, str):
            return ToolResult.model_validate_json(value)
        if isinstance(value, dict):
            return ToolResult.model_validate(value)
    except (TypeError, ValueError):
        return None
    return None
