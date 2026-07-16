import asyncio
import re
from types import SimpleNamespace

import pytest

from app.agents.music_team_v3_1.utils import (
    build_checkpoint_thread_id,
    normalize_thread_id,
)
import app.core.auth as auth


@pytest.mark.parametrize("value", ["", " ", " bad", "bad ", "中文", "a/b", "x" * 129])
def test_thread_id_rejects_ambiguous_or_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_thread_id(value)


def test_thread_id_defaults_only_for_missing_value() -> None:
    assert normalize_thread_id(None) == "local-web-thread"
    assert normalize_thread_id("local-web-thread-123") == "local-web-thread-123"


def test_checkpoint_key_is_deterministic_and_scoped() -> None:
    first = build_checkpoint_thread_id("user-a", "thread-x")
    assert first == build_checkpoint_thread_id("user-a", "thread-x")
    assert first != build_checkpoint_thread_id("user-b", "thread-x")
    assert first != build_checkpoint_thread_id("user-a", "thread-y")
    assert re.fullmatch(r"music:[0-9a-f]{64}", first)


def test_authenticated_user_id_reads_lazy_loaded_global(monkeypatch) -> None:
    auth.GLOBAL_CREDENTIAL = None

    async def load_now() -> bool:
        auth.GLOBAL_CREDENTIAL = SimpleNamespace(musicid=12345, str_musicid="fallback")
        return True

    monkeypatch.setattr(auth, "ensure_credential_loaded", load_now)
    assert asyncio.run(auth.get_authenticated_user_id()) == "12345"


def test_authenticated_user_id_falls_back_to_str_musicid(monkeypatch) -> None:
    auth.GLOBAL_CREDENTIAL = SimpleNamespace(musicid=0, str_musicid=" 67890 ")

    async def ready() -> bool:
        return True

    monkeypatch.setattr(auth, "ensure_credential_loaded", ready)
    assert asyncio.run(auth.get_authenticated_user_id()) == "67890"


def test_authenticated_user_id_separates_missing_and_unavailable(monkeypatch) -> None:
    auth.GLOBAL_CREDENTIAL = None

    async def missing() -> bool:
        return False

    monkeypatch.setattr(auth, "ensure_credential_loaded", missing)
    with pytest.raises(auth.AuthenticationRequiredError):
        asyncio.run(auth.get_authenticated_user_id())

    async def broken() -> bool:
        raise OSError("secret credential path")

    monkeypatch.setattr(auth, "ensure_credential_loaded", broken)
    with pytest.raises(auth.AuthenticationUnavailableError) as captured:
        asyncio.run(auth.get_authenticated_user_id())
    assert "secret credential path" not in str(captured.value)
