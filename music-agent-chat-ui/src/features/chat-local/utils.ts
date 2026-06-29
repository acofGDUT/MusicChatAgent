import {
  extractPlayMusicPayload,
  isPurePlayMusicPayloadText,
} from "@/components/local-chat/messages/music_player_artifact";
import {
  extractPlaylistBrowserPayload,
  isPurePlaylistBrowserPayloadText,
} from "@/components/local-chat/messages/playlist_browser_artifact";
import { parseArtifacts } from "./artifacts";
import type { ChatArtifact } from "./artifacts";
import type { ChatMsg } from "./types";

export function tryFormatJson(text: string): string {
  try {
    const parsed = JSON.parse(text);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return text;
  }
}

export function findPlaylistPayloadFromMessage(msg: ChatMsg): ReturnType<typeof extractPlaylistBrowserPayload> | null {
  return extractPlaylistBrowserPayload(msg.content);
}

export function findPlayMusicPayloadFromMessage(msg: ChatMsg): ReturnType<typeof extractPlayMusicPayload> | null {
  return extractPlayMusicPayload(msg.content);
}

export type ArtifactRenderSelection = {
  artifacts: ChatArtifact[];
  source: "structured" | "legacy" | "none";
  isPureArtifactText: boolean;
};

export function selectRenderableArtifacts(input: {
  content: string;
  artifacts?: unknown;
}): ArtifactRenderSelection {
  const structured = parseArtifacts(input.artifacts);
  if (structured.length > 0) {
    return {
      artifacts: structured,
      source: "structured",
      isPureArtifactText:
        isPurePlaylistBrowserPayloadText(input.content) ||
        isPurePlayMusicPayloadText(input.content),
    };
  }

  const playlistPayload = extractPlaylistBrowserPayload(input.content);
  if (playlistPayload) {
    return {
      artifacts: [playlistPayload],
      source: "legacy",
      isPureArtifactText: isPurePlaylistBrowserPayloadText(input.content),
    };
  }

  const playPayload = extractPlayMusicPayload(input.content);
  if (playPayload) {
    return {
      artifacts: [
        {
          type: "play_music",
          song_mid: playPayload.song_mid ?? `legacy:${playPayload.url}`,
          title: playPayload.title ?? "未知歌曲",
          artist: playPayload.artist,
          url: playPayload.url,
          cover: playPayload.cover,
          description: playPayload.description,
        },
      ],
      source: "legacy",
      isPureArtifactText: isPurePlayMusicPayloadText(input.content),
    };
  }

  return {
    artifacts: [],
    source: "none",
    isPureArtifactText: false,
  };
}

export { isPurePlayMusicPayloadText, isPurePlaylistBrowserPayloadText };
