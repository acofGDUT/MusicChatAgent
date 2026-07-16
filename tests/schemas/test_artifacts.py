import json

import pytest
from pydantic import ValidationError

from app.schemas.artifacts import (
    PlayMusicArtifact,
    PlaylistBrowserArtifact,
    PlaylistTrack,
    artifact_to_json,
    parse_artifact_text,
)


def play_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "play_music",
        "song_mid": "mid-1",
        "title": "晴天",
        "artist": "周杰伦",
        "url": "https://example.com/song.mp3",
        "cover": "https://example.com/cover.jpg",
        "description": "已获取播放链接",
    }
    payload.update(overrides)
    return payload


def playlist_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "playlist_browser",
        "playlist_name": "通勤歌单",
        "dirid": 42,
        "tracks": [
            {
                "index": 1,
                "song_mid": "mid-1",
                "title": "晴天",
                "artist": "周杰伦",
                "cover": "",
            },
            {
                "index": 2,
                "song_mid": "mid-2",
                "title": "夜曲",
                "artist": "周杰伦",
                "cover": "https://example.com/night.jpg",
            },
        ],
        "page": 1,
        "page_size": 20,
        "total_song_num": 2,
        "has_more": False,
        "description": "歌单曲目",
    }
    payload.update(overrides)
    return payload


def test_play_artifact_json_round_trip() -> None:
    artifact = PlayMusicArtifact.model_validate(play_payload())

    raw = artifact_to_json(artifact)
    restored = parse_artifact_text(raw)

    assert restored == artifact
    assert json.loads(raw) == artifact.model_dump(mode="json")
    assert "```" not in raw


@pytest.mark.parametrize("url", ["", "ftp://example.com/song.mp3", "/song.mp3"])
def test_play_artifact_rejects_non_http_url(url: str) -> None:
    with pytest.raises(ValidationError):
        PlayMusicArtifact.model_validate(play_payload(url=url))


@pytest.mark.parametrize(
    ("field", "value"),
    [("song_mid", ""), ("song_mid", "   "), ("title", ""), ("title", "  ")],
)
def test_play_artifact_rejects_blank_required_text(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        PlayMusicArtifact.model_validate(play_payload(**{field: value}))


def test_play_artifact_strips_required_text() -> None:
    artifact = PlayMusicArtifact.model_validate(
        play_payload(song_mid=" mid-1 ", title=" 晴天 ")
    )

    assert artifact.song_mid == "mid-1"
    assert artifact.title == "晴天"


def test_empty_cover_is_valid_but_non_http_cover_is_not() -> None:
    assert PlayMusicArtifact.model_validate(play_payload(cover="")).cover == ""

    with pytest.raises(ValidationError):
        PlayMusicArtifact.model_validate(play_payload(cover="cover.jpg"))


def test_playlist_artifact_json_round_trip() -> None:
    artifact = PlaylistBrowserArtifact.model_validate(playlist_payload())

    raw = artifact_to_json(artifact)

    assert parse_artifact_text(raw) == artifact
    assert json.loads(raw) == artifact.model_dump(mode="json")


@pytest.mark.parametrize(
    "overrides",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 51},
        {"total_song_num": -1},
        {"dirid": 0},
        {"playlist_name": "   "},
    ],
)
def test_playlist_artifact_rejects_invalid_page_fields(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        PlaylistBrowserArtifact.model_validate(playlist_payload(**overrides))


def test_playlist_track_rejects_invalid_index() -> None:
    with pytest.raises(ValidationError):
        PlaylistTrack(index=0, song_mid="mid-1", title="晴天")


def test_playlist_artifact_rejects_duplicate_indexes() -> None:
    tracks = playlist_payload()["tracks"]
    assert isinstance(tracks, list)
    duplicate = [dict(tracks[0]), {**dict(tracks[1]), "index": 1}]

    with pytest.raises(ValidationError):
        PlaylistBrowserArtifact.model_validate(playlist_payload(tracks=duplicate))


def test_playlist_artifact_rejects_duplicate_song_mids() -> None:
    tracks = playlist_payload()["tracks"]
    assert isinstance(tracks, list)
    duplicate = [dict(tracks[0]), {**dict(tracks[1]), "song_mid": "mid-1"}]

    with pytest.raises(ValidationError):
        PlaylistBrowserArtifact.model_validate(playlist_payload(tracks=duplicate))


def test_playlist_artifact_rejects_total_smaller_than_current_page() -> None:
    with pytest.raises(ValidationError):
        PlaylistBrowserArtifact.model_validate(playlist_payload(total_song_num=1))


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (PlayMusicArtifact, play_payload(unexpected=True)),
        (PlaylistTrack, {"index": 1, "song_mid": "mid-1", "title": "晴天", "x": 1}),
        (PlaylistBrowserArtifact, playlist_payload(unexpected=True)),
    ],
)
def test_artifacts_reject_unknown_fields(model: type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_parse_accepts_pure_json() -> None:
    parsed = parse_artifact_text(json.dumps(play_payload(), ensure_ascii=False))

    assert isinstance(parsed, PlayMusicArtifact)


def test_parse_accepts_single_json_code_block() -> None:
    raw = json.dumps(playlist_payload(), ensure_ascii=False)

    parsed = parse_artifact_text(f"```json\n{raw}\n```")

    assert isinstance(parsed, PlaylistBrowserArtifact)


@pytest.mark.parametrize(
    "text",
    [
        "下面是播放器：\n" + json.dumps(play_payload(), ensure_ascii=False),
        json.dumps(play_payload(), ensure_ascii=False) + "\n播放愉快",
        json.dumps([play_payload()], ensure_ascii=False),
        json.dumps({**play_payload(), "type": "unknown"}, ensure_ascii=False),
        "```json\n{}\n```\n额外说明",
        "not json",
        "",
    ],
)
def test_parse_rejects_invalid_or_mixed_text(text: str) -> None:
    assert parse_artifact_text(text) is None
