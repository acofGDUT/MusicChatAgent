"""Artifact collector for the agent graph.

Collects artifacts from tool results and AI messages during graph execution.
Deduplicates by (type, primary_key) so the same play/payload never appears twice.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.models.chat_artifacts import ChatArtifact, parse_artifact


def _dedup_key(artifact: ChatArtifact) -> str:
    """Stable dedup key based on artifact type + primary identifier."""
    if artifact.type == "play_music":
        return f"play_music:{artifact.song_mid}"
    if artifact.type == "playlist_browser":
        return f"playlist_browser:{artifact.dirid}:{artifact.page}"
    return f"{artifact.type}:{id(artifact)}"


class ArtifactCollector:
    """Thread-safe collector that accumulates validated artifacts.

    Usage in graph nodes:
        collector = ArtifactCollector()
        collector.ingest_raw(tool_result_json_string)
        ...
        artifacts = collector.to_list()
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._artifacts: list[ChatArtifact] = []

    def ingest_raw(self, raw: Any) -> bool:
        """Try to parse *raw* (str or dict) and add to collection.

        Returns True if an artifact was successfully parsed and added.
        """
        parsed = self._try_parse(raw)
        if parsed is None:
            return False

        key = _dedup_key(parsed)
        if key in self._seen:
            return False

        self._seen.add(key)
        self._artifacts.append(parsed)
        return True

    def collect_from_text(self, text: str) -> None:
        """Scan *text* for any embedded JSON artifacts (raw, fenced, or inline)."""
        if not text or not text.strip():
            return

        # 1. Try the whole text as pure JSON.
        self.ingest_raw(text)

        # 2. Try to find ```...``` fenced blocks.
        for block in re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL):
            self.ingest_raw(block.strip())

        # 3. Try to find bare JSON objects in prose, including nested objects.
        decoder = json.JSONDecoder()
        index = 0
        while index < len(text):
            start = text.find("{", index)
            if start < 0:
                break

            try:
                value, end_offset = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                index = start + 1
                continue

            if isinstance(value, dict):
                # ToolResult envelopes keep the validated artifact in `data`.
                # Recurse through known container keys instead of requiring the
                # outer object itself to be an artifact.
                self._collect_from_content(value)
            index = start + max(end_offset, 1)

    def collect_from_message(self, message: Any) -> None:
        """Scan a LangChain message or message-like dict for artifacts."""
        if isinstance(message, dict):
            self._collect_from_content(message)
            return

        self._collect_from_content(getattr(message, "content", None))

    def collect_from_messages(self, messages: list[Any] | tuple[Any, ...]) -> None:
        """Scan a sequence of LangChain messages or message-like dicts."""
        for message in messages:
            self.collect_from_message(message)

    def to_list(self) -> list[dict]:
        """Return validated artifacts as plain dicts for JSON serialization."""
        return [a.model_dump() for a in self._artifacts]

    @property
    def count(self) -> int:
        return len(self._artifacts)

    @staticmethod
    def _try_parse(raw: Any) -> ChatArtifact | None:
        """Best-effort parse: accept str (JSON), dict, or skip."""
        if isinstance(raw, dict):
            return parse_artifact(raw)

        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            # Strip markdown code fences if present
            if text.startswith("```"):
                lines = text.splitlines()
                if len(lines) >= 3:
                    text = "\n".join(lines[1:-1]).strip()
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return None
            if isinstance(data, dict):
                return parse_artifact(data)

        return None

    def _collect_from_content(self, content: Any) -> None:
        """Collect artifacts from strings, dict payloads, and content blocks."""
        if isinstance(content, str):
            self.collect_from_text(content)
            return

        if isinstance(content, dict):
            self.ingest_raw(content)
            for key in ("text", "json", "content", "data", "result"):
                if key in content:
                    self._collect_from_content(content.get(key))
            return

        if isinstance(content, list):
            for item in content:
                self._collect_from_content(item)
