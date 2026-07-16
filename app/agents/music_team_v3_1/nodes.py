import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.schemas import artifact_to_json, parse_artifact_text
from app.schemas.preferences import PreferencePatch, UserPreferences
from app.services.memory import DISABLED_PREFERENCES, PreferenceRepository
from app.services.music.playlist_service import playlist_service
from app.tools.tool_result import ToolResult, ToolResultCode, parse_tool_result

from .agents import chat_replier, music_executor, music_retry_executor, playback_executor
from .config import (
    MAX_EXECUTOR_REENTRY_WITHOUT_USER,
    SOUL_PATH,
    SUMMARY_TRIGGER_TOKENS,
    llm0,
)
from .prompts import intent_parser_prompt, preference_extraction_prompt, summary_prompt
from .state import IntentParserDecision, MusicGraphStateV31
from .utils import (
    build_runtime_messages,
    extract_agent_delta_messages,
    ensure_memory_files,
    estimate_tokens,
    extract_current_tool_run,
    extract_last_ai_message,
    extract_last_tool_result,
    extract_messages,
    current_run_has_write_tool,
    current_tool_names,
    has_required_tool_messages,
    is_json_like_text,
    has_explicit_preference_cue,
    last_user_text,
    mark_ai_message_user_visible,
    msg_content,
    read_text,
    sanitize_ai_message_metadata,
    update_last_search_results,
)

logger = logging.getLogger(__name__)


def _agent_result_messages(result: Any) -> list[Any]:
    if isinstance(result, dict):
        messages = result.get("messages", [])
        if isinstance(messages, list):
            return messages
    return []


def _apply_tool_result_status(
    *,
    task: dict[str, Any],
    extensions: dict[str, Any],
    result_messages: list[Any],
) -> None:
    last_result = extract_last_tool_result(result_messages)
    if last_result is not None:
        extensions["last_tool_result"] = last_result.model_dump(mode="json")
        if last_result.ok:
            task["status"] = "done"
            task.pop("error_code", None)
            task.pop("error_reason", None)
        else:
            task["status"] = "failed"
            task["error_code"] = last_result.code.value
            task["error_reason"] = last_result.message
        return

    if has_required_tool_messages(result_messages):
        invalid_result = ToolResult.failure(
            code=ToolResultCode.INVALID_TOOL_RESULT,
            message="核心工具返回结果不符合 ToolResult 协议",
        )
        extensions["last_tool_result"] = invalid_result.model_dump(mode="json")
        task["status"] = "failed"
        task["error_code"] = invalid_result.code.value
        task["error_reason"] = invalid_result.message
        return

    extensions.pop("last_tool_result", None)
    task["status"] = "done"
    task.pop("error_code", None)
    task.pop("error_reason", None)


def _internal_agent_error(*, task: dict[str, Any], extensions: dict[str, Any], agent_name: str) -> AIMessage:
    error_result = ToolResult.failure(
        code=ToolResultCode.INTERNAL_ERROR,
        message="Agent 执行服务暂时不可用",
    )
    extensions["last_tool_result"] = error_result.model_dump(mode="json")
    task["status"] = "failed"
    task["error_code"] = error_result.code.value
    task["error_reason"] = error_result.message
    return AIMessage(content=error_result.message, name=agent_name)


def _last_extension_tool_result(extensions: dict[str, Any]) -> ToolResult | None:
    return parse_tool_result(extensions.get("last_tool_result"))


def _apply_result_to_task(task: dict[str, Any], result: ToolResult) -> None:
    if result.ok:
        task["status"] = "done"
        task.pop("error_code", None)
        task.pop("error_reason", None)
        return
    task["status"] = "failed"
    task["error_code"] = result.code.value
    task["error_reason"] = result.message


def _last_protocol_tool_name(extensions: dict[str, Any]) -> str:
    current_run = extensions.get("current_tool_run", [])
    if not isinstance(current_run, list):
        return ""
    for item in reversed(current_run):
        if isinstance(item, dict) and isinstance(item.get("result"), dict):
            return str(item.get("tool_name", "") or "")
    return ""


async def _verify_uncertain_direct_add(
    *,
    task: dict[str, Any],
    extensions: dict[str, Any],
) -> tuple[ToolResult | None, str | None]:
    last_result = _last_extension_tool_result(extensions)
    if (
        last_result is None
        or last_result.code != ToolResultCode.WRITE_UNCERTAIN
        or _last_protocol_tool_name(extensions) != "add_songs_to_playlist_tool"
    ):
        return last_result, None

    try:
        dirid = int(last_result.data.get("dirid"))
        requested_ids = list(dict.fromkeys(int(item) for item in last_result.data.get("song_ids", [])))
    except (TypeError, ValueError):
        return last_result, "inconclusive"
    if dirid <= 0 or not requested_ids:
        return last_result, "inconclusive"

    try:
        songs = await playlist_service.get_all_songs_in_playlist(songlist_id=0, dirid=dirid)
    except Exception:
        logger.exception("加歌后置验证查询异常 (dirid=%s)", dirid)
        return last_result, "inconclusive"
    if not isinstance(songs, list) or not songs:
        return last_result, "inconclusive"

    existing_ids: set[int] = set()
    for song in songs:
        if not isinstance(song, dict):
            continue
        try:
            existing_ids.add(int(song.get("id")))
        except (TypeError, ValueError):
            continue

    verified_ids = [song_id for song_id in requested_ids if song_id in existing_ids]
    missing_ids = [song_id for song_id in requested_ids if song_id not in existing_ids]
    verified_data = {
        **last_result.data,
        "verified_song_ids": verified_ids,
        "missing_song_ids": missing_ids,
    }
    if verified_ids and not missing_ids:
        verified_result = ToolResult.success(
            message="加歌结果已通过查询确认",
            data=verified_data,
        )
        extensions["last_tool_result"] = verified_result.model_dump(mode="json")
        _apply_result_to_task(task, verified_result)
        return verified_result, "passed"
    if verified_ids:
        partial_result = ToolResult.failure(
            code=ToolResultCode.PARTIAL_SUCCESS,
            message=f"加歌结果仅确认 {len(verified_ids)}/{len(requested_ids)} 首",
            data=verified_data,
        )
        extensions["last_tool_result"] = partial_result.model_dump(mode="json")
        _apply_result_to_task(task, partial_result)
        return partial_result, "failed"
    return last_result, "inconclusive"


def _artifact_expectation(
    *,
    state: MusicGraphStateV31,
    last_result: ToolResult | None,
    final_text: str,
) -> str | None:
    if last_result is not None and not last_result.ok:
        return None
    names = current_tool_names(state)
    if "play_music_tool" in names:
        return "play_music"
    if "get_playlist_detail_tool" in names:
        return "playlist_browser"

    parsed = parse_artifact_text(final_text)
    if parsed is not None:
        return parsed.type
    if state.get("task", {}).get("intent") == "playback" and is_json_like_text(final_text):
        return "artifact"
    return None


def _replace_last_ai_content(messages: list[Any], content: str) -> tuple[list[Any], bool]:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, AIMessage):
            replacement = message.model_copy(update={"content": content})
            updated = list(messages)
            updated[index] = replacement
            return updated, True
    return messages, False


def _mark_last_playback_visible(messages: list[Any]) -> tuple[list[Any], bool]:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, AIMessage) and str(message.name or "") == "PlayAgent":
            updated = list(messages)
            updated[index] = mark_ai_message_user_visible(message, name="PlayAgent")
            return updated, True
    return messages, False


def _changed_message_delta(before: list[Any], after: list[Any]) -> list[Any]:
    """Return only additions or replacements for the add_messages reducer."""
    return [
        message
        for index, message in enumerate(after)
        if index >= len(before) or message != before[index]
    ]


def _sanitize_agent_delta(messages: list[Any], *, name: str) -> list[Any]:
    return [
        sanitize_ai_message_metadata(message, name=name)
        if isinstance(message, AIMessage)
        else message
        for message in messages
    ]


async def init_memory_node(
    state: MusicGraphStateV31,
    *,
    preference_repository: PreferenceRepository = DISABLED_PREFERENCES,
) -> MusicGraphStateV31:
    ensure_memory_files()
    memory = dict(state.get("memory", {}))
    memory["soul"] = read_text(SOUL_PATH)
    memory.setdefault("summary_version", 0)
    memory.setdefault("summary_message_count", 0)

    user_id = str(state.get("user_id", "") or "")
    storage_backend = str(getattr(preference_repository, "storage_backend", "disabled"))
    if storage_backend not in {"sqlite", "disabled"}:
        storage_backend = "disabled"
    update_status = "skipped"
    signal_count = 0
    preferences = UserPreferences()
    load_failed = False
    try:
        preferences = await preference_repository.get(user_id)
    except Exception as exc:
        logger.warning("用户偏好读取失败 | error_type=%s", type(exc).__name__)
        update_status = "failed"
        load_failed = True

    latest_user_message = last_user_text(extract_messages(state))
    if (
        storage_backend == "sqlite"
        and not load_failed
        and has_explicit_preference_cue(latest_user_message)
    ):
        try:
            extractor = llm0.with_structured_output(PreferencePatch)
            extracted = extractor.invoke(
                [
                    SystemMessage(content=preference_extraction_prompt),
                    HumanMessage(content=latest_user_message),
                ]
            )
            patch = (
                extracted
                if isinstance(extracted, PreferencePatch)
                else PreferencePatch.model_validate(extracted)
            )
            signal_count = len(patch.signals)
            if patch.signals:
                merge_result = await preference_repository.merge(user_id, patch)
                preferences = merge_result.preferences
                update_status = merge_result.status
            else:
                update_status = "unchanged"
        except Exception as exc:
            logger.warning("用户偏好更新失败 | error_type=%s", type(exc).__name__)
            update_status = "failed"

    memory.update(
        {
            "preferences": preferences.model_dump(
                mode="json", exclude={"version", "updated_at"}
            ),
            "preference_version": preferences.version,
            "last_preference_update_at": (
                preferences.updated_at.isoformat() if preferences.updated_at else ""
            ),
            "preference_update_status": update_status,
            "preference_signal_count": signal_count,
            "storage_backend": storage_backend,
            "user_id_present": bool(user_id),
        }
    )

    control = dict(state.get("control", {}))
    control.setdefault("max_reentry", MAX_EXECUTOR_REENTRY_WITHOUT_USER)
    control.setdefault("executor_reentry", 0)
    control["retry_count"] = 0
    control["max_retries"] = 1
    control.pop("retry_reason", None)
    control.pop("retry_tool_name", None)
    control.pop("retry_artifact_type", None)
    control.pop("verifier_route", None)

    extensions = dict(state.get("extensions", {}))
    extensions.pop("current_tool_run", None)
    extensions.pop("verification", None)
    extensions.pop("retry_original_result", None)

    task = dict(state.get("task", {}))
    task.setdefault("status", "pending")
    task.setdefault("retries", 0)

    return {
        **state,
        "memory": memory,
        "control": control,
        "task": task,
        "extensions": extensions,
    }


def intent_parser_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    task = dict(state.get("task", {}))
    control = dict(state.get("control", {}))
    messages = extract_messages(state)

    parser_messages: list[BaseMessage] = [SystemMessage(content=intent_parser_prompt)]
    parser_messages.extend(build_runtime_messages(state, role="intent_parser"))

    parsed: dict[str, Any] = {}
    parser_failed = False
    parser_error_reason = ""
    try:
        structured_llm = llm0.with_structured_output(IntentParserDecision)
        structured_decision = structured_llm.invoke(parser_messages)
        parsed = structured_decision.model_dump() if hasattr(structured_decision, "model_dump") else dict(structured_decision)
    except Exception as structured_err:
        try:
            raw_decision = llm0.invoke(parser_messages)
            raw_text = msg_content(raw_decision).strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                raw_text = re.sub(r"\s*```$", "", raw_text).strip()
            parsed = json.loads(raw_text)
        except Exception as raw_err:
            parser_failed = True
            parser_error_reason = f"intent_parser模型不可用: structured={type(structured_err).__name__}; raw={type(raw_err).__name__}"
            parsed = {}

    intent = parsed.get("intent", "music_ops")
    if intent not in {"smalltalk", "music_ops", "playback"}:
        intent = "music_ops"
    extracted_slots = parsed.get("extracted_slots", {})
    if not isinstance(extracted_slots, dict):
        extracted_slots = {}

    task.update(
        {
            "intent": intent,
            "goal": last_user_text(messages),
            "required_slots": {},
            "missing_slots": [],
            "extracted_slots": extracted_slots,
            "status": "pending",
        }
    )

    if parser_failed:
        task["status"] = "failed"
        task["error_reason"] = parser_error_reason or "intent_parser模型不可用"
        control["is_ready_to_execute"] = False
    else:
        control["is_ready_to_execute"] = intent in {"music_ops", "playback"}

    return {**state, "task": task, "control": control}


def supervisor_router_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    task = dict(state.get("task", {}))
    control = dict(state.get("control", {}))

    if not bool(control.get("is_ready_to_execute", False)):
        task["status"] = "done"
        control["route"] = "chat_replier"
        return {**state, "task": task, "control": control}

    reentry = int(control.get("executor_reentry", 0))
    max_reentry = int(control.get("max_reentry", MAX_EXECUTOR_REENTRY_WITHOUT_USER))
    if reentry >= max_reentry:
        task["status"] = "failed"
        task["error_reason"] = "达到最大重入次数，停止同条件重试"
        control["route"] = "chat_replier"
        return {**state, "task": task, "control": control}

    task["status"] = "running"
    task.pop("error_reason", None)
    route_map = {"music_ops": "music_ops_subgraph", "playback": "playback_subgraph"}
    control["route"] = route_map.get(task.get("intent", "music_ops"), "chat_replier")
    return {**state, "task": task, "control": control}


async def music_ops_subgraph_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    runtime_messages = build_runtime_messages(state, role="executor")
    task = dict(state.get("task", {}))
    control = dict(state.get("control", {}))
    extensions = dict(state.get("extensions", {}))

    try:
        is_retry_attempt = (
            int(control.get("retry_count", 0) or 0) > 0
            and control.get("verifier_route") == "retry_music_ops"
        )
        executor = music_retry_executor if is_retry_attempt else music_executor
        result = await executor.ainvoke({"messages": runtime_messages})
        delta_messages = _sanitize_agent_delta(
            extract_agent_delta_messages(
                result,
                runtime_messages,
                fallback_name="MusicExecutor",
            ),
            name="MusicExecutor",
        )
        ai_msg = extract_last_ai_message(
            {"messages": delta_messages}, fallback_name="MusicExecutor"
        )
        result_messages = _agent_result_messages(result)
        extensions["current_tool_run"] = extract_current_tool_run(result_messages)
        _apply_tool_result_status(
            task=task,
            extensions=extensions,
            result_messages=result_messages,
        )
    except Exception:
        logger.exception("MusicExecutor 执行异常")
        extensions["current_tool_run"] = []
        ai_msg = _internal_agent_error(task=task, extensions=extensions, agent_name="MusicExecutor")
        delta_messages = [ai_msg]

    control["executor_reentry"] = int(control.get("executor_reentry", 0)) + 1
    return {
        **state,
        "messages": delta_messages,
        "task": task,
        "control": control,
        "extensions": extensions,
    }


async def playback_subgraph_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    runtime_messages = build_runtime_messages(state, role="playback")
    task = dict(state.get("task", {}))
    extensions = dict(state.get("extensions", {}))

    try:
        result = await playback_executor.ainvoke({"messages": runtime_messages})
        delta_messages = _sanitize_agent_delta(
            extract_agent_delta_messages(
                result,
                runtime_messages,
                fallback_name="PlayAgent",
            ),
            name="PlayAgent",
        )
        ai_msg = extract_last_ai_message(
            {"messages": delta_messages}, fallback_name="PlayAgent"
        )
        result_messages = _agent_result_messages(result)
        extensions["current_tool_run"] = extract_current_tool_run(result_messages)
        _apply_tool_result_status(
            task=task,
            extensions=extensions,
            result_messages=result_messages,
        )
    except Exception:
        logger.exception("PlayAgent 执行异常")
        extensions["current_tool_run"] = []
        ai_msg = _internal_agent_error(task=task, extensions=extensions, agent_name="PlayAgent")
        delta_messages = [ai_msg]

    return {
        **state,
        "messages": delta_messages,
        "task": task,
        "extensions": extensions,
    }


async def result_verifier_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    """Validate the current executor attempt and choose a bounded next route."""
    task = dict(state.get("task", {}))
    control = dict(state.get("control", {}))
    extensions = dict(state.get("extensions", {}))
    original_messages = list(extract_messages(state))
    messages = list(original_messages)

    update_last_search_results(extensions)
    last_result, write_verification = await _verify_uncertain_direct_add(
        task=task,
        extensions=extensions,
    )

    original_retry_result = parse_tool_result(extensions.get("retry_original_result"))
    retry_tool_name = str(control.get("retry_tool_name", "") or "")
    is_retry_attempt = (
        int(control.get("retry_count", 0) or 0) > 0
        and str(control.get("verifier_route", "") or "").startswith("retry_")
        and original_retry_result is not None
    )
    if (
        is_retry_attempt
        and original_retry_result.code != ToolResultCode.ARTIFACT_INVALID
        and retry_tool_name
    ):
        current_run = extensions.get("current_tool_run", [])
        matching_results: list[ToolResult] = []
        if isinstance(current_run, list):
            for item in current_run:
                if not isinstance(item, dict) or item.get("tool_name") != retry_tool_name:
                    continue
                parsed = parse_tool_result(item.get("result"))
                if parsed is not None:
                    matching_results.append(parsed)
        if not matching_results:
            last_result = original_retry_result
            extensions["last_tool_result"] = original_retry_result.model_dump(mode="json")
            _apply_result_to_task(task, original_retry_result)
        elif not matching_results[-1].ok:
            last_result = matching_results[-1]
            extensions["last_tool_result"] = last_result.model_dump(mode="json")
            _apply_result_to_task(task, last_result)

    final_ai_text = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            final_ai_text = msg_content(message)
            break

    state_for_checks: MusicGraphStateV31 = {
        **state,
        "task": task,
        "extensions": extensions,
    }
    expected_artifact_type = _artifact_expectation(
        state=state_for_checks,
        last_result=last_result,
        final_text=final_ai_text,
    )
    retry_artifact_type = str(control.get("retry_artifact_type", "") or "")
    if (
        is_retry_attempt
        and original_retry_result is not None
        and original_retry_result.code == ToolResultCode.ARTIFACT_INVALID
        and retry_artifact_type in {"play_music", "playlist_browser"}
    ):
        expected_artifact_type = retry_artifact_type
    artifact_invalid = False
    artifact_validated = False
    if expected_artifact_type is not None:
        artifact = parse_artifact_text(final_ai_text)
        if artifact is None or (
            expected_artifact_type != "artifact" and artifact.type != expected_artifact_type
        ):
            artifact_invalid = True
            artifact_result = ToolResult.failure(
                code=ToolResultCode.ARTIFACT_INVALID,
                message="播放结果格式校验失败",
                retryable=(
                    expected_artifact_type in {"play_music", "playlist_browser"}
                    and not current_run_has_write_tool(state_for_checks)
                ),
            )
            extensions.pop("last_artifact", None)
            extensions["last_tool_result"] = artifact_result.model_dump(mode="json")
            _apply_result_to_task(task, artifact_result)
            last_result = artifact_result
        else:
            artifact_validated = True
            canonical_json = artifact_to_json(artifact)
            messages, _ = _replace_last_ai_content(messages, canonical_json)
            extensions["last_artifact"] = artifact.model_dump(mode="json")
            task["status"] = "done"
            task.pop("error_code", None)
            task.pop("error_reason", None)

    intent = task.get("intent")
    if intent not in {"music_ops", "playback"}:
        intent = "playback" if expected_artifact_type is not None else "music_ops"

    retry_count = max(0, int(control.get("retry_count", 0) or 0))
    control["max_retries"] = 1
    blocked_codes = {
        ToolResultCode.INVALID_ARGUMENT,
        ToolResultCode.NOT_FOUND,
        ToolResultCode.AUTH_REQUIRED,
        ToolResultCode.PERMISSION_DENIED,
        ToolResultCode.PARTIAL_SUCCESS,
        ToolResultCode.WRITE_UNCERTAIN,
    }
    retryable_failure = bool(
        last_result is not None
        and not last_result.ok
        and last_result.retryable
        and last_result.code not in blocked_codes
    )
    state_for_checks = {
        **state,
        "task": task,
        "control": control,
        "extensions": extensions,
    }
    can_retry = (
        retry_count < 1
        and retryable_failure
        and not current_run_has_write_tool(state_for_checks)
        and intent in {"music_ops", "playback"}
    )

    if can_retry:
        retry_count += 1
        control["retry_count"] = retry_count
        control["retry_reason"] = last_result.message if last_result is not None else "执行失败"
        control["retry_tool_name"] = _last_protocol_tool_name(extensions)
        if last_result is not None:
            extensions["retry_original_result"] = last_result.model_dump(mode="json")
        if artifact_invalid and expected_artifact_type in {"play_music", "playlist_browser"}:
            control["retry_artifact_type"] = expected_artifact_type
        else:
            control.pop("retry_artifact_type", None)
        control["verifier_route"] = (
            "retry_playback" if intent == "playback" else "retry_music_ops"
        )
        task["status"] = "running"
    else:
        control["retry_count"] = retry_count
        control["verifier_route"] = "playback_done" if intent == "playback" else "music_done"
        if last_result is not None:
            _apply_result_to_task(task, last_result)
        if artifact_invalid:
            messages, _ = _replace_last_ai_content(
                messages,
                "播放结果格式校验失败，暂时无法展示。",
            )
        if intent == "playback":
            if last_result is not None and not last_result.ok and not artifact_invalid:
                messages, _ = _replace_last_ai_content(
                    messages,
                    last_result.message or "播放服务暂时不可用，请稍后重试。",
                )
            messages, _ = _mark_last_playback_visible(messages)

    if write_verification is not None:
        verification_status = write_verification
    elif artifact_validated:
        verification_status = "passed"
    elif last_result is None:
        verification_status = "skipped"
    elif last_result.ok:
        verification_status = "passed"
    else:
        verification_status = "failed"

    extensions["verification"] = {
        "status": verification_status,
        "code": (
            last_result.code.value
            if last_result is not None
            else ToolResultCode.SUCCESS.value if artifact_validated else ""
        ),
        "message": (
            last_result.message
            if last_result is not None
            else "Artifact 校验通过"
            if artifact_validated
            else "当前执行尝试没有可校验的 ToolResult"
        ),
        "retry_scheduled": can_retry,
        "retry_count": retry_count,
    }
    return {
        **state,
        "messages": _changed_message_delta(original_messages, messages),
        "task": task,
        "control": control,
        "extensions": extensions,
    }


def memory_sync_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    messages = extract_messages(state)
    memory = dict(state.get("memory", {}))
    control = dict(state.get("control", {}))
    summary_count = max(0, int(memory.get("summary_message_count", 0) or 0))
    summary_count = min(summary_count, len(messages))
    delta = messages[summary_count:]
    should_summarize = estimate_tokens(delta) >= SUMMARY_TRIGGER_TOKENS
    control["should_summarize"] = should_summarize

    if should_summarize:
        summary_input = "\n".join(
            f"{getattr(message, 'type', 'unknown')}:{msg_content(message)}"
            for message in delta
        )
        try:
            memory["summary"] = msg_content(
                llm0.invoke(
                    summary_prompt.format(
                        previous_summary=str(memory.get("summary", "") or ""),
                        messages=summary_input,
                    )
                )
            )
            memory["summary_version"] = int(memory.get("summary_version", 0) or 0) + 1
            memory["summary_message_count"] = len(messages)
        except Exception as exc:
            logger.warning("会话摘要更新失败 | error_type=%s", type(exc).__name__)

    return {**state, "memory": memory, "control": control}


async def chat_replier_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    task = state.get("task", {})

    guidance = SystemMessage(
        content=(
            f"TASK_STATUS={task.get('status', 'done')}; "
            f"INTENT={task.get('intent', 'music_ops')}; "
            f"MISSING={','.join(task.get('missing_slots', []))}; "
            f"ERROR={task.get('error_reason', '')}"
        )
    )
    runtime_messages = [guidance, *build_runtime_messages(state, role="replier")]
    result = await chat_replier.ainvoke({"messages": runtime_messages})
    delta_messages = extract_agent_delta_messages(result, runtime_messages, fallback_name="ChatReplier")
    ai_msg = mark_ai_message_user_visible(
        extract_last_ai_message(
            {"messages": delta_messages}, fallback_name="ChatReplier"
        ),
        name="ChatReplier",
    )
    for index in range(len(delta_messages) - 1, -1, -1):
        if isinstance(delta_messages[index], AIMessage):
            delta_messages[index] = ai_msg
            break
    else:
        delta_messages = [ai_msg]

    control = dict(state.get("control", {}))
    control["executor_reentry"] = 0
    return {**state, "messages": delta_messages, "control": control}


def finalizer_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    control = dict(state.get("control", {}))
    control.pop("route", None)
    return {**state, "control": control}


def route_after_supervisor(state: MusicGraphStateV31) -> str:
    return state.get("control", {}).get("route", "chat_replier")


def route_after_verifier(state: MusicGraphStateV31) -> str:
    route = state.get("control", {}).get("verifier_route", "")
    if route in {
        "retry_music_ops",
        "retry_playback",
        "music_done",
        "playback_done",
    }:
        return route
    intent = state.get("task", {}).get("intent")
    return "playback_done" if intent == "playback" else "music_done"
