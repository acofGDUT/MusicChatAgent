import { useEffect, useMemo, useRef, useState } from "react";
import { useArtifact } from "../artifact";

export type PlaylistTrack = {
  index: number;
  song_mid: string;
  title: string;
  artist?: string;
  cover?: string;
};

export type PlaylistBrowserPayload = {
  type: "playlist_browser";
  playlist_name: string;
  dirid?: number;
  tracks: PlaylistTrack[];
  page: number;
  page_size: number;
  total_song_num: number;
  has_more: boolean;
  description?: string;
};

type PlayMusicPayload = {
  type: "play_music";
  song_mid?: string;
  title?: string;
  artist?: string;
  url: string;
};

type LoopMode = "none" | "single" | "list";

function isPlaylistTrack(value: unknown): value is PlaylistTrack {
  if (!value || typeof value !== "object") return false;
  const data = value as Record<string, unknown>;
  return (
    typeof data.index === "number" &&
    typeof data.song_mid === "string" &&
    typeof data.title === "string"
  );
}

function isPlaylistBrowserPayload(value: unknown): value is PlaylistBrowserPayload {
  if (!value || typeof value !== "object") return false;
  const data = value as Record<string, unknown>;
  return (
    data.type === "playlist_browser" &&
    typeof data.playlist_name === "string" &&
    Array.isArray(data.tracks) &&
    data.tracks.every(isPlaylistTrack) &&
    typeof data.page === "number" &&
    typeof data.page_size === "number" &&
    typeof data.total_song_num === "number" &&
    typeof data.has_more === "boolean"
  );
}

function isPlayMusicPayload(value: unknown): value is PlayMusicPayload {
  if (!value || typeof value !== "object") return false;
  const data = value as Record<string, unknown>;
  return data.type === "play_music" && typeof data.url === "string";
}

function tryParseJsonObject(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function formatSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function extractPlaylistBrowserPayload(text: string): PlaylistBrowserPayload | null {
  const normalized = text.trim();
  if (!normalized) return null;

  const direct = tryParseJsonObject(normalized);
  if (isPlaylistBrowserPayload(direct)) return direct;

  const fenced = normalized.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  if (fenced?.[1]) {
    const fencedParsed = tryParseJsonObject(fenced[1].trim());
    if (isPlaylistBrowserPayload(fencedParsed)) return fencedParsed;
  }

  return null;
}

export function isPurePlaylistBrowserPayloadText(text: string): boolean {
  const normalized = text.trim();
  if (!normalized) return false;

  const direct = tryParseJsonObject(normalized);
  if (isPlaylistBrowserPayload(direct)) return true;

  const fenced = normalized.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (!fenced?.[1]) return false;

  const parsed = tryParseJsonObject(fenced[1].trim());
  return isPlaylistBrowserPayload(parsed);
}

function getBackendBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

async function fetchPlaylistPage(params: {
  dirid: number;
  page: number;
  pageSize: number;
  playlistName: string;
}): Promise<PlaylistBrowserPayload> {
  const base = getBackendBaseUrl();
  const query = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize),
    playlist_name: params.playlistName,
  });

  const res = await fetch(`${base}/api/v1/playlist/${params.dirid}/tracks?${query.toString()}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "加载歌单失败");
  }

  const data: unknown = await res.json();
  if (!isPlaylistBrowserPayload(data)) {
    throw new Error("歌单接口返回格式不正确");
  }

  return data;
}

async function fetchPlayUrl(track: PlaylistTrack): Promise<PlayMusicPayload> {
  const base = getBackendBaseUrl();
  const query = new URLSearchParams({
    song_mid: track.song_mid,
    title: track.title,
    artist: track.artist ?? "",
  });

  const res = await fetch(`${base}/api/v1/song/play-url?${query.toString()}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "获取播放链接失败");
  }

  const data: unknown = await res.json();
  if (!isPlayMusicPayload(data)) {
    throw new Error("播放接口返回格式不正确");
  }

  return data;
}

export function PlaylistBrowserArtifact(props: { payload: PlaylistBrowserPayload }) {
  const [Artifact, { open, setOpen }] = useArtifact();

  const [payload, setPayload] = useState<PlaylistBrowserPayload>(props.payload);
  const pageCacheRef = useRef<Map<number, PlaylistBrowserPayload>>(
    new Map([[props.payload.page, props.payload]]),
  );
  const playUrlCacheRef = useRef<Map<string, PlayMusicPayload>>(new Map());

  const [currentTrack, setCurrentTrack] = useState<PlaylistTrack | null>(null);
  const [audioUrl, setAudioUrl] = useState<string>("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const [isPageLoading, setIsPageLoading] = useState(false);
  const [isPlayLoading, setIsPlayLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [autoPlayNext, setAutoPlayNext] = useState(true);
  const [loopMode, setLoopMode] = useState<LoopMode>("none");
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string>("");

  const title = useMemo(() => payload.playlist_name || "歌单浏览", [payload.playlist_name]);

  const canPrev = payload.page > 1 && !isPageLoading;
  const canNext = payload.has_more && !isPageLoading;

  const requestPage = async (targetPage: number) => {
    if (!payload.dirid || targetPage < 1 || isPageLoading) return;

    const cachedPage = pageCacheRef.current.get(targetPage);
    if (cachedPage) {
      setError("");
      setPayload(cachedPage);
      return;
    }

    try {
      setIsPageLoading(true);
      setError("");
      const next = await fetchPlaylistPage({
        dirid: payload.dirid,
        page: targetPage,
        pageSize: payload.page_size,
        playlistName: payload.playlist_name,
      });
      pageCacheRef.current.set(targetPage, next);
      setPayload(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "翻页失败，请稍后再试");
    } finally {
      setIsPageLoading(false);
    }
  };

  const playByUrl = (track: PlaylistTrack, url: string) => {
    setCurrentTrack(track);
    setAudioUrl(url);
    setCurrentTime(0);
    setDuration(0);
    requestAnimationFrame(() => {
      const player = audioRef.current;
      if (!player) return;
      player.load();
      void player.play().catch(() => {
        setIsPlaying(false);
      });
    });
  };

  const requestSongPlay = async (track: PlaylistTrack) => {
    if (isPlayLoading) return;

    const cachedPlayData = playUrlCacheRef.current.get(track.song_mid);
    if (cachedPlayData?.url) {
      setError("");
      playByUrl(track, cachedPlayData.url);
      return;
    }

    try {
      setIsPlayLoading(true);
      setError("");
      const playData = await fetchPlayUrl(track);
      playUrlCacheRef.current.set(track.song_mid, playData);
      playByUrl(track, playData.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "播放失败，请稍后再试");
    } finally {
      setIsPlayLoading(false);
    }
  };

  const togglePlayPause = () => {
    const player = audioRef.current;
    if (!player || !audioUrl) return;

    if (player.paused) {
      void player.play().catch(() => setIsPlaying(false));
    } else {
      player.pause();
      setIsPlaying(false);
    }
  };

  const stopPlayback = () => {
    const player = audioRef.current;
    if (!player) return;
    player.pause();
    player.currentTime = 0;
    setCurrentTime(0);
    setIsPlaying(false);
  };

  const onSeek = (value: number) => {
    const player = audioRef.current;
    if (!player || !Number.isFinite(duration) || duration <= 0) return;
    const nextTime = Math.max(0, Math.min(value, duration));
    player.currentTime = nextTime;
    setCurrentTime(nextTime);
  };

  const playNextTrack = async () => {
    if (!currentTrack || isPlayLoading) return;

    const currentIndex = payload.tracks.findIndex(
      (track) => track.song_mid === currentTrack.song_mid,
    );
    if (currentIndex < 0) return;

    const nextIndex = currentIndex + 1;
    if (nextIndex < payload.tracks.length) {
      await requestSongPlay(payload.tracks[nextIndex]);
      return;
    }

    if (loopMode === "list" && payload.tracks.length > 0) {
      await requestSongPlay(payload.tracks[0]);
      return;
    }

    if (autoPlayNext && payload.has_more) {
      const nextPage = payload.page + 1;
      await requestPage(nextPage);
      const loadedPage = pageCacheRef.current.get(nextPage);
      if (loadedPage?.tracks?.length) {
        await requestSongPlay(loadedPage.tracks[0]);
      }
    }
  };

  const handleAudioEnded = () => {
    setIsPlaying(false);
    setCurrentTime(0);

    if (loopMode === "single" && currentTrack) {
      void requestSongPlay(currentTrack);
      return;
    }

    if (autoPlayNext || loopMode === "list") {
      void playNextTrack();
    }
  };

  useEffect(() => {
    const player = audioRef.current;
    if (!player) return;

    const updateProgress = () => {
      setCurrentTime(player.currentTime || 0);
      const mediaDuration = Number.isFinite(player.duration) ? player.duration : 0;
      setDuration(mediaDuration > 0 ? mediaDuration : 0);
    };

    const onLoaded = () => updateProgress();
    const onDurationChange = () => updateProgress();
    const onTime = () => updateProgress();

    player.addEventListener("loadedmetadata", onLoaded);
    player.addEventListener("durationchange", onDurationChange);
    player.addEventListener("timeupdate", onTime);

    updateProgress();

    return () => {
      player.removeEventListener("loadedmetadata", onLoaded);
      player.removeEventListener("durationchange", onDurationChange);
      player.removeEventListener("timeupdate", onTime);
    };
  }, [audioUrl]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full cursor-pointer rounded-lg border bg-white p-4 text-left transition hover:bg-gray-50"
      >
        <p className="font-medium">🎵 歌单：{title}</p>
        <p className="mt-1 text-sm text-gray-500">
          {payload.description ?? `共 ${payload.total_song_num} 首，当前第 ${payload.page} 页`}
        </p>
      </button>

      <Artifact title={`歌单 · ${title}`}>
        <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-white">
          <div className="border-b p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-lg font-semibold">{title}</p>
                <p className="text-sm text-gray-500">
                  第 {payload.page} 页 · 每页 {payload.page_size} 首 · 共 {payload.total_song_num} 首
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  disabled={!canPrev}
                  onClick={() => requestPage(payload.page - 1)}
                  className="rounded border px-3 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-50"
                >
                  上一页
                </button>
                <button
                  type="button"
                  disabled={!canNext}
                  onClick={() => requestPage(payload.page + 1)}
                  className="rounded border px-3 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-50"
                >
                  下一页
                </button>
              </div>
            </div>

            {error ? <p className="mt-2 text-sm text-red-500">{error}</p> : null}
            {isPageLoading ? <p className="mt-2 text-sm text-gray-500">正在加载页面...</p> : null}

            <div className="mt-3 flex flex-wrap items-center gap-2 rounded border bg-gray-50 p-2 text-sm">
              <label className="flex items-center gap-1 text-xs text-gray-700">
                <input
                  type="checkbox"
                  checked={autoPlayNext}
                  onChange={(e) => setAutoPlayNext(e.target.checked)}
                />
                自动下一首
              </label>
              <button
                type="button"
                onClick={() =>
                  setLoopMode((prev) =>
                    prev === "none" ? "single" : prev === "single" ? "list" : "none",
                  )
                }
                className="rounded border bg-white px-2 py-1 text-xs"
              >
                循环：{loopMode === "none" ? "关闭" : loopMode === "single" ? "单曲" : "列表"}
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {payload.tracks.map((track) => {
              const isCurrent = currentTrack?.song_mid === track.song_mid;
              return (
                <div
                  key={`${track.index}-${track.song_mid}`}
                  className="flex items-center justify-between gap-3 border-b p-3"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {track.index}. {track.title}
                    </p>
                    {track.artist ? (
                      <p className="truncate text-sm text-gray-500">{track.artist}</p>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    onClick={() => requestSongPlay(track)}
                    disabled={isPlayLoading}
                    className="ml-3 shrink-0 rounded border px-3 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isCurrent && isPlaying ? "播放中" : "播放"}
                  </button>
                </div>
              );
            })}
          </div>

          <div className="shrink-0 border-t bg-white p-3 shadow-[0_-2px_8px_rgba(0,0,0,0.04)]">
            <p className="mb-2 text-sm font-medium">
              {currentTrack
                ? `正在播放：${currentTrack.title}${currentTrack.artist ? ` - ${currentTrack.artist}` : ""}`
                : "请选择歌曲播放"}
            </p>

            {isPlayLoading ? <p className="mb-2 text-sm text-gray-500">正在获取播放链接...</p> : null}

            <div className="mb-2 flex items-center gap-2">
              <button
                type="button"
                onClick={togglePlayPause}
                disabled={!audioUrl}
                className="rounded border px-3 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isPlaying ? "暂停" : "播放"}
              </button>
              <button
                type="button"
                onClick={stopPlayback}
                disabled={!audioUrl}
                className="rounded border px-3 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-50"
              >
                停止
              </button>
              <span className="ml-auto text-xs text-gray-500">
                {formatSeconds(currentTime)} / {formatSeconds(duration)}
              </span>
            </div>

            <input
              type="range"
              min={0}
              max={duration > 0 ? duration : 0}
              step={0.1}
              value={duration > 0 ? currentTime : 0}
              onChange={(e) => onSeek(Number(e.target.value))}
              disabled={!audioUrl || duration <= 0}
              className="w-full accent-blue-600"
            />

            <audio
              ref={audioRef}
              preload="none"
              src={audioUrl}
              className="hidden"
              onPlay={() => setIsPlaying(true)}
              onPause={() => setIsPlaying(false)}
              onEnded={handleAudioEnded}
            />
          </div>
        </div>
      </Artifact>
    </>
  );
}
