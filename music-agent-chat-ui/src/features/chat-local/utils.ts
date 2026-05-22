import { extractPlayMusicPayload, isPurePlayMusicPayloadText } from "@/components/local-chat/messages/music_player_artifact";
import { extractPlaylistBrowserPayload, isPurePlaylistBrowserPayloadText } from "@/components/local-chat/messages/playlist_browser_artifact";
import { ChatMsg } from "./types";

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

export { isPurePlayMusicPayloadText, isPurePlaylistBrowserPayloadText };
