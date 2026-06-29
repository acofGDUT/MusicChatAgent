import json
import re
import uuid
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .agents import chat_replier, music_executor, playback_executor
from .config import (
    ENABLE_SOUL_AUTOTUNE,
    HISTORY_PATH,
    MAX_EXECUTOR_REENTRY_WITHOUT_USER,
    SOUL_PATH,
    SUMMARY_KEEP_MESSAGES,
    SUMMARY_TRIGGER_TOKENS,
    USER_PROFILE_PATH,
    llm0,
)
from .prompts import intent_parser_prompt, profile_update_prompt, soul_tune_prompt, summary_prompt
from .state import IntentParserDecision, MusicGraphStateV31
from .utils import (
    append_jsonl,
    build_runtime_messages,
    collect_tool_calls,
    extract_agent_delta_messages,
    ensure_memory_files,
    estimate_tokens,
    extract_last_ai_message,
    extract_messages,
    last_user_text,
    looks_like_valid_soul_markdown,
    msg_content,
    now_iso,
    read_text,
    safe_message_preview,
    write_text,
)


def init_memory_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    ensure_memory_files()
    memory = dict(state.get("memory", {}))
    memory.setdefault("user_profile_path", str(USER_PROFILE_PATH))
    memory.setdefault("soul_path", str(SOUL_PATH))
    memory.setdefault("history_path", str(HISTORY_PATH))
    memory["user_profile"] = read_text(USER_PROFILE_PATH)
    memory["soul"] = read_text(SOUL_PATH)

    control = dict(state.get("control", {}))
    control.setdefault("max_reentry", MAX_EXECUTOR_REENTRY_WITHOUT_USER)
    control.setdefault("executor_reentry", 0)

    task = dict(state.get("task", {}))
    task.setdefault("status", "pending")
    task.setdefault("retries", 0)

    return {**state, "memory": memory, "control": control, "task": task}


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
    result = await music_executor.ainvoke({"messages": runtime_messages})
    delta_messages = extract_agent_delta_messages(result, runtime_messages, fallback_name="MusicExecutor")
    ai_msg = extract_last_ai_message({"messages": delta_messages}, fallback_name="MusicExecutor")

    task = dict(state.get("task", {}))
    control = dict(state.get("control", {}))

    content = str(ai_msg.content)
    looks_fail = any(k in content for k in ["失败", "报错", "异常", "无权限", "超时", "不支持"])
    task["status"] = "failed" if looks_fail else "done"
    if looks_fail:
        task["error_reason"] = content[:300]

    control["executor_reentry"] = int(control.get("executor_reentry", 0)) + 1
    return {**state, "messages": delta_messages, "task": task, "control": control}


async def playback_subgraph_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    runtime_messages = build_runtime_messages(state, role="playback")
    result = await playback_executor.ainvoke({"messages": runtime_messages})
    delta_messages = extract_agent_delta_messages(result, runtime_messages, fallback_name="PlayAgent")
    ai_msg = extract_last_ai_message({"messages": delta_messages}, fallback_name="PlayAgent")

    task = dict(state.get("task", {}))

    content = str(ai_msg.content)
    if "未接入" in content or "不支持" in content:
        task["status"] = "failed"
        task["error_reason"] = content[:300]
    else:
        task["status"] = "done"

    return {**state, "messages": delta_messages, "task": task}


def memory_sync_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    messages = extract_messages(state)
    memory = dict(state.get("memory", {}))
    control = dict(state.get("control", {}))
    task = dict(state.get("task", {}))

    should_summarize = estimate_tokens(messages) >= SUMMARY_TRIGGER_TOKENS
    should_update_profile = bool(messages) and task.get("status") in {"done", "waiting_user"}
    should_update_soul = ENABLE_SOUL_AUTOTUNE and task.get("status") == "done"

    control.update(
        {
            "should_summarize": should_summarize,
            "should_update_profile": should_update_profile,
            "should_update_soul": should_update_soul,
        }
    )

    if should_summarize:
        summary_input = "\n".join([f"{(m.get('type', 'unknown') if isinstance(m, dict) else getattr(m, 'type', 'unknown'))}:{msg_content(m)}" for m in messages])
        memory["summary"] = msg_content(llm0.invoke(summary_prompt.format(messages=summary_input)))
        memory["summary_version"] = int(memory.get("summary_version", 0)) + 1
        if len(messages) > SUMMARY_KEEP_MESSAGES:
            state["messages"] = messages[-SUMMARY_KEEP_MESSAGES:]

    profile_text = memory.get("user_profile", read_text(USER_PROFILE_PATH))
    soul_text = memory.get("soul", read_text(SOUL_PATH))

    if should_update_profile:
        latest = "\n".join([msg_content(m) for m in messages[-6:]])
        profile_text = msg_content(llm0.invoke(profile_update_prompt.format(profile=profile_text, messages=latest)))
        write_text(USER_PROFILE_PATH, profile_text)
        memory["user_profile"] = profile_text
        memory["last_profile_update_at"] = now_iso()

    if should_update_soul:
        latest = "\n".join([msg_content(m) for m in messages[-6:]])
        candidate_soul = msg_content(llm0.invoke(soul_tune_prompt.format(soul=soul_text, messages=latest)))
        if looks_like_valid_soul_markdown(candidate_soul):
            soul_text = candidate_soul
            write_text(SOUL_PATH, soul_text)
            memory["soul"] = soul_text
            memory["last_soul_update_at"] = now_iso()

    history_event = {
        "timestamp": now_iso(),
        "event_id": str(uuid.uuid4()),
        "thread_id": state.get("thread_id", ""),
        "intent": task.get("intent", "music_ops"),
        "task_status": task.get("status", "pending"),
        "error_reason": task.get("error_reason", ""),
        "tool_calls": collect_tool_calls(messages[-12:]),
        "message_count": len(messages),
        "message_tail": [
            {
                "type": (m.get("type", "unknown") if isinstance(m, dict) else getattr(m, "type", "unknown")),
                "name": (m.get("name", "") if isinstance(m, dict) else getattr(m, "name", "")),
                "preview": safe_message_preview(m),
            }
            for m in messages[-3:]
        ],
        "memory_update": {"summary": should_summarize, "profile": should_update_profile, "soul": should_update_soul},
    }
    append_jsonl(HISTORY_PATH, history_event)
    memory["last_history_write_at"] = history_event["timestamp"]

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

    control = dict(state.get("control", {}))
    control["executor_reentry"] = 0
    return {**state, "messages": delta_messages, "control": control}


def finalizer_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    control = dict(state.get("control", {}))
    control.pop("route", None)
    return {**state, "control": control}


def route_after_supervisor(state: MusicGraphStateV31) -> str:
    return state.get("control", {}).get("route", "chat_replier")
