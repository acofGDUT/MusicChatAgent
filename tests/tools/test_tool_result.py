import pytest
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from app.tools.tool_result import ToolResult, ToolResultCode, parse_tool_result


def test_success_round_trip() -> None:
    result = ToolResult.success("ok", {"items": [1, 2]})

    parsed = ToolResult.model_validate_json(result.to_json())

    assert parsed == result


def test_failure_round_trip() -> None:
    result = ToolResult.failure(
        code=ToolResultCode.NOT_FOUND,
        message="missing",
        data={"query": "x"},
    )

    assert parse_tool_result(result.to_json()) == result


def test_default_data_is_not_shared() -> None:
    first = ToolResult.success("first")
    second = ToolResult.success("second")

    first.data["changed"] = True

    assert second.data == {}


@pytest.mark.parametrize("value", [None, "", "plain text", "{bad json", [], 1])
def test_parse_invalid_value_returns_none(value: object) -> None:
    assert parse_tool_result(value) is None


def test_unknown_code_returns_none() -> None:
    raw = '{"ok":false,"code":"UNKNOWN","message":"x","data":{},"retryable":false}'

    assert parse_tool_result(raw) is None


@pytest.mark.parametrize(
    ("ok", "code"),
    [
        (True, ToolResultCode.NOT_FOUND),
        (False, ToolResultCode.SUCCESS),
    ],
)
def test_ok_and_code_must_be_consistent(ok: bool, code: ToolResultCode) -> None:
    with pytest.raises(ValidationError):
        ToolResult(ok=ok, code=code, message="x")


def test_uncertain_write_cannot_be_retried_automatically() -> None:
    with pytest.raises(ValidationError):
        ToolResult.failure(
            code=ToolResultCode.WRITE_UNCERTAIN,
            message="uncertain",
            retryable=True,
        )


def test_non_json_serializable_data_fails_explicitly() -> None:
    result = ToolResult.success("ok", {"value": object()})

    with pytest.raises(PydanticSerializationError):
        result.to_json()
