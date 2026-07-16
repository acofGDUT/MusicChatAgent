from typing import Any, Annotated, Dict, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

TaskStatus = Literal["pending", "running", "waiting_user", "done", "failed"]
IntentType = Literal["smalltalk", "music_ops", "playback"]
RouteType = Literal["chat_replier", "music_ops_subgraph", "playback_subgraph"]
VerifierRoute = Literal[
    "retry_music_ops",
    "retry_playback",
    "music_done",
    "playback_done",
]


class IntentParserDecision(BaseModel):
    intent: Literal["smalltalk", "music_ops", "playback"] = Field(
        description="判断用户的真实意图"
    )
    extracted_slots: Dict[str, str] = Field(
        default_factory=dict,
        description="从上下文中提取的参数，如 playlist_name, keyword 等",
    )
    missing_slots: list[str] = Field(
        default_factory=list,
        description="执行当前 intent 仍然缺失的【必填】参数名。如果全齐则为空列表",
    )
    is_ready_to_execute: bool = Field(
        description="intent 明确且 missing_slots 为空时为 True，否则为 False"
    )


class TaskMeta(TypedDict, total=False):
    id: str
    intent: IntentType
    status: TaskStatus
    goal: str
    required_slots: dict[str, Any]
    extracted_slots: dict[str, str]
    missing_slots: list[str]
    retries: int
    error_code: str | None
    error_reason: str | None


class MemoryMeta(TypedDict, total=False):
    summary: str
    summary_version: int
    summary_message_count: int
    preferences: dict[str, Any]
    preference_version: int
    preference_update_status: Literal["skipped", "unchanged", "updated", "failed"]
    preference_signal_count: int
    storage_backend: Literal["sqlite", "disabled"]
    user_id_present: bool
    soul: str
    last_preference_update_at: str


class RuntimeControl(TypedDict, total=False):
    route: RouteType
    executor_reentry: int
    max_reentry: int
    retry_count: int
    max_retries: int
    retry_reason: str
    retry_tool_name: str
    retry_artifact_type: str
    verifier_route: VerifierRoute
    should_summarize: bool
    is_ready_to_execute: bool


class MusicGraphStateV31(TypedDict, total=False):
    user_id: str
    thread_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    task: TaskMeta
    memory: MemoryMeta
    control: RuntimeControl
    extensions: dict[str, Any]
