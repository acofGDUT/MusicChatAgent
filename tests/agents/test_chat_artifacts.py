"""Task 02 failure tests: artifact models & collector.

No real LLM or QQ Music calls — pure data validation tests.
"""

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.models.chat_artifacts import (
    PlayMusicArtifact,
    PlaylistBrowserArtifact,
    parse_artifact,
)
from app.agents.music_team_v3_1.artifacts import ArtifactCollector
from app.tools.tool_result import ToolResult


# ---------------------------------------------------------------------------
# 1. Pydantic model parsing
# ---------------------------------------------------------------------------


class TestPlayMusicArtifact:
    def test_valid_play_music_parsed(self):
        raw = {
            "type": "play_music",
            "song_mid": "abc123",
            "title": "Test Song",
            "artist": "Test Artist",
            "url": "https://example.com/song.mp3",
            "cover": "https://example.com/cover.jpg",
        }
        art = parse_artifact(raw)
        assert art is not None
        assert isinstance(art, PlayMusicArtifact)
        assert art.song_mid == "abc123"
        assert art.url == "https://example.com/song.mp3"

    def test_missing_url_rejected(self):
        raw = {
            "type": "play_music",
            "song_mid": "abc123",
            "title": "Test Song",
            # url missing
        }
        art = parse_artifact(raw)
        assert art is None

    def test_empty_song_mid_rejected(self):
        raw = {
            "type": "play_music",
            "song_mid": "",
            "title": "Test Song",
            "url": "https://example.com/song.mp3",
        }
        art = parse_artifact(raw)
        assert art is None


class TestPlaylistBrowserArtifact:
    def test_valid_playlist_browser_parsed(self):
        raw = {
            "type": "playlist_browser",
            "playlist_name": "My Playlist",
            "dirid": 12345,
            "page": 1,
            "page_size": 10,
            "total_song_num": 50,
            "has_more": True,
            "tracks": [
                {"index": 1, "song_mid": "mid1", "title": "Song 1", "artist": "A"},
            ],
        }
        art = parse_artifact(raw)
        assert art is not None
        assert isinstance(art, PlaylistBrowserArtifact)
        assert art.dirid == 12345
        assert len(art.tracks) == 1

    def test_empty_playlist_name_rejected(self):
        raw = {
            "type": "playlist_browser",
            "playlist_name": "",
            "dirid": 1,
        }
        art = parse_artifact(raw)
        assert art is None


class TestUnknownType:
    def test_unknown_type_rejected(self):
        raw = {"type": "unknown_widget", "data": "whatever"}
        art = parse_artifact(raw)
        assert art is None

    def test_missing_type_rejected(self):
        raw = {"song_mid": "abc", "url": "https://example.com/song.mp3"}
        art = parse_artifact(raw)
        assert art is None

    def test_non_dict_rejected(self):
        assert parse_artifact("just a string") is None
        assert parse_artifact(42) is None
        assert parse_artifact(None) is None


# ---------------------------------------------------------------------------
# 2. Collector — ingest, dedup, plain text filtering
# ---------------------------------------------------------------------------


class TestArtifactCollector:
    def test_ingest_valid_play_music(self):
        collector = ArtifactCollector()
        raw = {
            "type": "play_music",
            "song_mid": "abc",
            "title": "Song",
            "url": "https://x.com/s.mp3",
        }
        assert collector.ingest_raw(raw) is True
        assert collector.count == 1
        arts = collector.to_list()
        assert arts[0]["type"] == "play_music"

    def test_ingest_json_string(self):
        collector = ArtifactCollector()
        raw_str = json.dumps(
            {
                "type": "play_music",
                "song_mid": "xyz",
                "title": "Song2",
                "url": "https://x.com/s2.mp3",
            },
            ensure_ascii=False,
        )
        assert collector.ingest_raw(raw_str) is True
        assert collector.count == 1

    def test_ingest_markdown_fenced_json(self):
        collector = ArtifactCollector()
        inner = json.dumps(
            {
                "type": "play_music",
                "song_mid": "fenced",
                "title": "Fenced Song",
                "url": "https://x.com/f.mp3",
            },
            ensure_ascii=False,
        )
        fenced = f"```json\n{inner}\n```"
        assert collector.ingest_raw(fenced) is True
        assert collector.count == 1

    def test_plain_text_produces_no_artifact(self):
        collector = ArtifactCollector()
        assert collector.ingest_raw("今天天气不错，适合听歌") is False
        assert collector.count == 0

    def test_unrelated_json_produces_no_artifact(self):
        collector = ArtifactCollector()
        assert collector.ingest_raw({"status": "ok", "data": [1, 2, 3]}) is False
        assert collector.count == 0

    def test_duplicate_not_added(self):
        collector = ArtifactCollector()
        raw = {
            "type": "play_music",
            "song_mid": "dup",
            "title": "Dup Song",
            "url": "https://x.com/d.mp3",
        }
        assert collector.ingest_raw(raw) is True
        assert collector.ingest_raw(raw) is False  # second time rejected
        assert collector.count == 1

    def test_different_songs_both_added(self):
        collector = ArtifactCollector()
        raw1 = {
            "type": "play_music",
            "song_mid": "s1",
            "title": "Song 1",
            "url": "https://x.com/1.mp3",
        }
        raw2 = {
            "type": "play_music",
            "song_mid": "s2",
            "title": "Song 2",
            "url": "https://x.com/2.mp3",
        }
        assert collector.ingest_raw(raw1) is True
        assert collector.ingest_raw(raw2) is True
        assert collector.count == 2

    def test_playlist_browser_ingested(self):
        collector = ArtifactCollector()
        raw = {
            "type": "playlist_browser",
            "playlist_name": "Test Playlist",
            "dirid": 99,
            "page": 1,
            "page_size": 10,
            "total_song_num": 3,
            "has_more": False,
            "tracks": [
                {"index": 1, "song_mid": "m1", "title": "T1"},
            ],
        }
        assert collector.ingest_raw(raw) is True
        arts = collector.to_list()
        assert arts[0]["type"] == "playlist_browser"
        assert arts[0]["playlist_name"] == "Test Playlist"

    def test_ingest_none_rejected(self):
        collector = ArtifactCollector()
        assert collector.ingest_raw(None) is False
        assert collector.count == 0

    def test_ingest_empty_string_rejected(self):
        collector = ArtifactCollector()
        assert collector.ingest_raw("") is False
        assert collector.ingest_raw("   ") is False

    def test_collects_artifact_from_tool_message(self):
        collector = ArtifactCollector()
        payload = {
            "type": "play_music",
            "song_mid": "tool-mid",
            "title": "Tool Song",
            "url": "https://x.com/tool.mp3",
        }

        collector.collect_from_messages(
            [
                ToolMessage(
                    content=ToolResult.success(
                        message="playback link ready",
                        data=payload,
                    ).to_json(),
                    tool_call_id="call-play-music",
                    name="play_music_tool",
                ),
                AIMessage(content="已为你准备播放卡片", name="ChatReplier"),
            ]
        )

        assert collector.count == 1
        assert collector.to_list()[0]["song_mid"] == "tool-mid"

    def test_collects_nested_playlist_json_from_ai_text(self):
        collector = ArtifactCollector()
        payload = {
            "type": "playlist_browser",
            "playlist_name": "Nested Playlist",
            "dirid": 42,
            "page": 1,
            "page_size": 10,
            "total_song_num": 1,
            "has_more": False,
            "tracks": [
                {"index": 1, "song_mid": "nested-mid", "title": "Nested Song"},
            ],
        }

        collector.collect_from_text(f"这里是歌单：{json.dumps(payload, ensure_ascii=False)}")

        assert collector.count == 1
        assert collector.to_list()[0]["type"] == "playlist_browser"
