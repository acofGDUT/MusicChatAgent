/** Shared artifact types consumed from backend `data.artifacts`. */

export type PlayMusicArtifactData = {
  type: "play_music";
  song_mid: string;
  title: string;
  artist?: string;
  url: string;
  cover?: string;
  description?: string;
};

export type PlaylistTrackData = {
  index: number;
  song_mid: string;
  title: string;
  artist?: string;
  cover?: string;
};

export type PlaylistBrowserArtifactData = {
  type: "playlist_browser";
  playlist_name: string;
  dirid?: number;
  page: number;
  page_size: number;
  total_song_num: number;
  has_more: boolean;
  tracks: PlaylistTrackData[];
  description?: string;
};

export type ChatArtifact = PlayMusicArtifactData | PlaylistBrowserArtifactData;

// ---- Type guards ----

export function isPlayMusicArtifact(v: unknown): v is PlayMusicArtifactData {
  if (!v || typeof v !== "object") return false;
  const d = v as Record<string, unknown>;
  return (
    d.type === "play_music" &&
    typeof d.song_mid === "string" &&
    d.song_mid.length > 0 &&
    typeof d.title === "string" &&
    d.title.length > 0 &&
    typeof d.url === "string" &&
    d.url.length > 0
  );
}

export function isPlaylistBrowserArtifact(v: unknown): v is PlaylistBrowserArtifactData {
  if (!v || typeof v !== "object") return false;
  const d = v as Record<string, unknown>;
  return (
    d.type === "playlist_browser" &&
    typeof d.playlist_name === "string" &&
    Array.isArray(d.tracks)
  );
}

export function isChatArtifact(v: unknown): v is ChatArtifact {
  return isPlayMusicArtifact(v) || isPlaylistBrowserArtifact(v);
}

/** Filter + validate raw array from API into typed artifacts. */
export function parseArtifacts(raw: unknown): ChatArtifact[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isChatArtifact);
}
