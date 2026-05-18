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
  cover?: string;
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

function tryExtractFirstJsonObject(text: string): unknown {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  return tryParseJsonObject(text.slice(start, end + 1));
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

  const embedded = tryExtractFirstJsonObject(normalized);
  if (isPlaylistBrowserPayload(embedded)) return embedded;

  const regex = new RegExp("\\x60\\x60\\x60(?:json)?\\s*([\\s\\S]*?)\\s*\\x60\\x60\\x60", "i");
  const fenced = normalized.match(regex);
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

  const regex = new RegExp("^\\x60\\x60\\x60(?:json)?\\s*([\\s\\S]*?)\\s*\\x60\\x60\\x60$", "i");
  const fenced = normalized.match(regex);
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

  if (track.cover && !(data as PlayMusicPayload).cover) {
    (data as PlayMusicPayload).cover = track.cover;
  }

  return data as PlayMusicPayload;
}

// --- Icons ---
const PlayIcon = () => <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5"><path d="M8 5v14l11-7z" /></svg>;
const PauseIcon = () => <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg>;
const NextIcon = () => <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" /></svg>;
const StopIcon = () => <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4"><path d="M6 6h12v12H6z" /></svg>;


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

  const playByUrl = (track: PlaylistTrack, url: string, cover?: string) => {
    setCurrentTrack({ ...track, cover: cover ?? track.cover });
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
      playByUrl(track, cachedPlayData.url, cachedPlayData.cover);
      return;
    }

    try {
      setIsPlayLoading(true);
      setError("");
      const playData = await fetchPlayUrl(track);
      playUrlCacheRef.current.set(track.song_mid, playData);
      playByUrl(track, playData.url, playData.cover);
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
      <style>{`
        @keyframes vinyl-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .animate-vinyl {
          animation: vinyl-spin 12s linear infinite;
        }
        /* 隐藏原始 range 滑块样式并自定义 */
        .custom-slider {
          -webkit-appearance: none;
          background: transparent;
        }
        .custom-slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          height: 10px;
          width: 10px;
          border-radius: 50%;
          background: #3b82f6;
          cursor: pointer;
          margin-top: -3px;
          box-shadow: 0 0 0 1px #fff;
        }
        .custom-slider::-webkit-slider-runnable-track {
          width: 100%;
          height: 4px;
          cursor: pointer;
          background: #e5e7eb;
          border-radius: 2px;
        }
        .custom-slider:focus { outline: none; }
      `}</style>

      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full cursor-pointer rounded-lg border bg-white p-4 text-left transition hover:bg-gray-50 flex items-center gap-4"
      >
        <div
          className="w-12 h-12 rounded-full bg-black shrink-0 p-0.5 flex items-center justify-center overflow-hidden animate-vinyl"
          style={{ animationPlayState: isPlaying ? 'running' : 'paused' }}
        >
           <img
             src={currentTrack?.cover || "https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?q=80&w=150&auto=format&fit=crop"}
             className="w-full h-full rounded-full object-cover"
             alt="cover_thumbnail"
           />
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-medium truncate">🎵 歌单：{title}</p>
          <p className="mt-0.5 text-sm text-gray-500 truncate">
            {currentTrack
              ? `正在播放: ${currentTrack.title}`
              : (payload.description ?? `共 ${payload.total_song_num} 首，当前第 ${payload.page} 页`)}
          </p>
        </div>
      </button>

      <Artifact title={`歌单 · ${title}`}>
        <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-white">
          <div className="border-b px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-lg font-bold text-gray-800">{title}</p>
                <p className="text-sm text-gray-500 mt-1">
                  第 {payload.page} 页 · 每页 {payload.page_size} 首 · 共 {payload.total_song_num} 首
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  disabled={!canPrev}
                  onClick={() => requestPage(payload.page - 1)}
                  className="rounded-full border px-4 py-1.5 text-sm font-medium transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  上一页
                </button>
                <button
                  type="button"
                  disabled={!canNext}
                  onClick={() => requestPage(payload.page + 1)}
                  className="rounded-full border px-4 py-1.5 text-sm font-medium transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  下一页
                </button>
              </div>
            </div>

            {error ? <p className="mt-2 text-sm text-red-500">{error}</p> : null}
            {isPageLoading ? <p className="mt-2 text-sm text-blue-500 animate-pulse">正在加载页面...</p> : null}

            <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
              <label className="flex items-center gap-1.5 cursor-pointer text-gray-600 hover:text-gray-900 transition">
                <input
                  type="checkbox"
                  checked={autoPlayNext}
                  onChange={(e) => setAutoPlayNext(e.target.checked)}
                  className="rounded text-blue-600 focus:ring-blue-500"
                />
                自动下一首
              </label>
              <div className="w-px h-4 bg-gray-300"></div>
              <button
                type="button"
                onClick={() =>
                  setLoopMode((prev) =>
                    prev === "none" ? "single" : prev === "single" ? "list" : "none",
                  )
                }
                className="text-gray-600 hover:text-gray-900 transition font-medium"
              >
                循环模式: <span className="text-blue-600">{loopMode === "none" ? "关闭" : loopMode === "single" ? "单曲" : "列表"}</span>
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {payload.tracks.map((track) => {
              const isCurrent = currentTrack?.song_mid === track.song_mid;
              return (
                <div
                  key={`${track.index}-${track.song_mid}`}
                  className={`flex items-center justify-between gap-3 border-b border-gray-100 p-3 px-5 transition group ${
                    isCurrent ? 'bg-blue-50/50' : 'hover:bg-gray-50'
                  }`}
                  onDoubleClick={() => requestSongPlay(track)}
                >
                  <div className="min-w-0 flex items-center gap-4">
                    <span className={`w-6 text-right text-sm ${isCurrent ? 'text-blue-600 font-bold' : 'text-gray-400'}`}>
                       {isCurrent && isPlaying ? (
                          <span className="flex items-center justify-end gap-0.5 h-3">
                             <span className="w-1 bg-blue-500 h-full animate-pulse"></span>
                             <span className="w-1 bg-blue-500 h-2/3 animate-pulse" style={{ animationDelay: '0.2s'}}></span>
                             <span className="w-1 bg-blue-500 h-full animate-pulse" style={{ animationDelay: '0.4s'}}></span>
                          </span>
                       ) : track.index}
                    </span>
                    <div className="min-w-0">
                      <p className={`truncate font-medium ${isCurrent ? 'text-blue-700' : 'text-gray-800'}`}>
                        {track.title}
                      </p>
                      {track.artist ? (
                        <p className="truncate text-xs text-gray-500 mt-0.5">{track.artist}</p>
                      ) : null}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => requestSongPlay(track)}
                    disabled={isPlayLoading}
                    className={`shrink-0 rounded-full border px-4 py-1 text-xs font-medium transition ${
                      isCurrent 
                        ? 'border-blue-200 bg-blue-100 text-blue-700' 
                        : 'border-gray-200 text-gray-600 opacity-0 group-hover:opacity-100 focus:opacity-100'
                    } disabled:cursor-not-allowed disabled:opacity-50`}
                  >
                    {isCurrent && isPlaying ? "播放中" : "播放"}
                  </button>
                </div>
              );
            })}
          </div>

          {/* 底部现代化播放控制条 */}
          <div className="shrink-0 bg-white border-t border-gray-200 p-3 px-5 shadow-[0_-4px_16px_rgba(0,0,0,0.04)] z-10">
            <div className="flex items-center gap-4 relative">
              {/* 左侧：旋转封面与歌曲信息 */}
              <div className="flex items-center gap-3 flex-1 min-w-0">
                 <div
                   className="w-12 h-12 sm:w-14 sm:h-14 rounded-full bg-black shrink-0 p-[2px] flex items-center justify-center animate-vinyl shadow-md border border-gray-800"
                   style={{ animationPlayState: isPlaying ? 'running' : 'paused' }}
                 >
                    <img
                      src={currentTrack?.cover || "https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?q=80&w=150&auto=format&fit=crop"}
                      className="w-full h-full rounded-full object-cover"
                      alt="playing_cover"
                    />
                 </div>
                 <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-gray-800">
                      {currentTrack ? currentTrack.title : "未选择歌曲"}
                    </p>
                    <p className="truncate text-xs text-gray-500 mt-0.5">
                      {currentTrack?.artist || (isPlayLoading ? "正在获取音频..." : "点击列表播放")}
                    </p>
                 </div>
              </div>

              {/* 中间：控制按钮 */}
              <div className="flex items-center justify-center gap-3 sm:gap-6 flex-1 max-w-[200px]">
                 <button
                   type="button"
                   onClick={stopPlayback}
                   disabled={!audioUrl}
                   className="p-2 text-gray-400 hover:text-gray-700 disabled:opacity-30 transition"
                   title="停止"
                 >
                   <StopIcon />
                 </button>
                 <button
                   type="button"
                   onClick={togglePlayPause}
                   disabled={!audioUrl}
                   className="w-10 h-10 sm:w-12 sm:h-12 flex items-center justify-center rounded-full bg-blue-600 text-white shadow-md hover:bg-blue-700 hover:scale-105 active:scale-95 disabled:opacity-50 disabled:hover:scale-100 transition transform"
                 >
                   {isPlaying ? <PauseIcon /> : <PlayIcon />}
                 </button>
                 <button
                   type="button"
                   onClick={playNextTrack}
                   disabled={!currentTrack || isPlayLoading}
                   className="p-2 text-gray-600 hover:text-blue-600 disabled:opacity-30 transition"
                   title="下一首"
                 >
                     <NextIcon />
                 </button>
              </div>

              {/* 右侧：预留给音量等 */}
              <div className="flex-1 hidden sm:block"></div>
            </div>

            {/* 底部：精美的进度条 */}
            <div className="flex items-center gap-3 mt-2 text-[11px] font-medium text-gray-400">
              <span className="w-9 text-right">{formatSeconds(currentTime)}</span>
              <div className="relative flex-1 flex items-center h-4 group">
                 <input
                    type="range"
                    min={0}
                    max={duration > 0 ? duration : 0}
                    step={0.1}
                    value={duration > 0 ? currentTime : 0}
                    onChange={(e) => onSeek(Number(e.target.value))}
                    disabled={!audioUrl || duration <= 0}
                    className="custom-slider w-full absolute z-10"
                  />
                  {/* 自定义进度填充 */}
                  <div
                    className="absolute h-1 bg-blue-500 rounded-l-full pointer-events-none group-hover:bg-blue-600 transition-colors"
                    style={{ width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%` }}
                  ></div>
              </div>
              <span className="w-9 text-left">{formatSeconds(duration)}</span>
            </div>

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