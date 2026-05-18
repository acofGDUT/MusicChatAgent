import { useMemo, useRef, useState } from "react";
import { useArtifact } from "../artifact";

export type PlayMusicPayload = {
  type: "play_music";
  url: string;
  title?: string;
  artist?: string;
  cover?: string;
  description?: string;
};

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

export function extractPlayMusicPayload(text: string): PlayMusicPayload | null {
  const normalized = text.trim();
  if (!normalized) return null;

  const direct = tryParseJsonObject(normalized);
  if (isPlayMusicPayload(direct)) return direct;

  const embedded = tryExtractFirstJsonObject(normalized);
  if (isPlayMusicPayload(embedded)) return embedded;

  const regex = new RegExp("\\x60\\x60\\x60(?:json)?\\s*([\\s\\S]*?)\\s*\\x60\\x60\\x60", "i");
  const fenced = normalized.match(regex);
  if (fenced?.[1]) {
    const fencedParsed = tryParseJsonObject(fenced[1].trim());
    if (isPlayMusicPayload(fencedParsed)) return fencedParsed;
  }

  return null;
}

export function isPurePlayMusicPayloadText(text: string): boolean {
  const normalized = text.trim();
  if (!normalized) return false;

  const direct = tryParseJsonObject(normalized);
  if (isPlayMusicPayload(direct)) return true;

  const regex = new RegExp("^\\x60\\x60\\x60(?:json)?\\s*([\\s\\S]*?)\\s*\\x60\\x60\\x60$", "i");
  const fenced = normalized.match(regex);
  if (!fenced?.[1]) return false;

  const parsed = tryParseJsonObject(fenced[1].trim());
  return isPlayMusicPayload(parsed);
}

function formatSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// --- Icons ---
const PlayIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" className="w-8 h-8">
    <path d="M8 5v14l11-7z" />
  </svg>
);
const PauseIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" className="w-8 h-8">
    <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
  </svg>
);

export function MusicPlayerArtifact(props: { payload: PlayMusicPayload }) {
  const [Artifact, { open, setOpen }] = useArtifact();

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rafRef = useRef<number | null>(null);

  const title = useMemo(() => {
    if (props.payload.artist && props.payload.title) {
      return `${props.payload.title} - ${props.payload.artist}`;
    }
    return props.payload.title ?? "音乐播放器";
  }, [props.payload.artist, props.payload.title]);

  const stopRaf = () => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  };

  const syncProgressFromPlayer = () => {
    const player = audioRef.current;
    if (!player) return;
    setCurrentTime(player.currentTime || 0);
    const mediaDuration = Number.isFinite(player.duration) ? player.duration : 0;
    setDuration(mediaDuration > 0 ? mediaDuration : 0);
  };

  const startRaf = () => {
    stopRaf();
    const tick = () => {
      syncProgressFromPlayer();
      const player = audioRef.current;
      if (player && !player.paused && !player.ended) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        rafRef.current = null;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
  };

  const togglePlayPause = () => {
    const player = audioRef.current;
    if (!player) return;

    if (player.paused) {
      void player.play().catch(() => {
        setIsPlaying(false);
        stopRaf();
      });
    } else {
      player.pause();
      setIsPlaying(false);
      stopRaf();
      syncProgressFromPlayer();
    }
  };

  const onSeek = (value: number) => {
    const player = audioRef.current;
    if (!player || !Number.isFinite(duration) || duration <= 0) return;
    const nextTime = Math.max(0, Math.min(value, duration));
    player.currentTime = nextTime;
    setCurrentTime(nextTime);
  };

  return (
    <>
      <style>{`
        @keyframes vinyl-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .animate-vinyl {
          animation: vinyl-spin 15s linear infinite;
        }
        /* 美化进度条 */
        .range-slider {
          -webkit-appearance: none;
          background: transparent;
        }
        .range-slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          height: 12px;
          width: 12px;
          border-radius: 50%;
          background: #3b82f6;
          cursor: pointer;
          margin-top: -4px;
          box-shadow: 0 0 0 2px #fff, 0 1px 3px rgba(0,0,0,0.3);
        }
        .range-slider::-webkit-slider-runnable-track {
          width: 100%;
          height: 4px;
          cursor: pointer;
          background: #e5e7eb;
          border-radius: 2px;
        }
        .range-slider:focus { outline: none; }
      `}</style>

      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full cursor-pointer rounded-lg border bg-white p-4 text-left transition hover:bg-gray-50 flex items-center gap-4"
      >
        <div
          className="w-12 h-12 rounded-full bg-black shrink-0 p-[2px] flex items-center justify-center overflow-hidden animate-vinyl"
          style={{ animationPlayState: isPlaying ? 'running' : 'paused' }}
        >
           <img
             src={props.payload.cover || "https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?q=80&w=200&auto=format&fit=crop"}
             className="w-full h-full rounded-full object-cover"
             alt="cover_thumbnail"
           />
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-medium truncate">{title}</p>
          <p className="mt-0.5 text-xs text-gray-500 truncate">
            {props.payload.description ?? (isPlaying ? "正在播放..." : "点击在右侧面板打开播放器")}
          </p>
        </div>
      </button>

      <Artifact title={title}>
        <div className="flex h-full w-full min-h-0 flex-col overflow-hidden p-6 bg-gradient-to-b from-gray-50 to-gray-100">

          {/* 唱片展示区 */}
          <div className="flex-1 min-h-0 flex flex-col items-center justify-center">
            <div className="relative mb-8">
              {/* 黑胶外盘 */}
              <div
                className="w-64 h-64 sm:w-80 sm:h-80 rounded-full bg-black shadow-2xl flex items-center justify-center p-2 relative animate-vinyl border border-gray-800"
                style={{
                  animationPlayState: isPlaying ? 'running' : 'paused',
                  background: 'radial-gradient(circle, #1a1a1a 40%, #000 100%)'
                }}
              >
                {/* 唱片纹理光影圈 */}
                <div className="absolute inset-0 rounded-full border border-gray-700/30 m-4"></div>
                <div className="absolute inset-0 rounded-full border border-gray-700/20 m-8"></div>

                {/* 封面内盘 */}
                <img
                  src={props.payload.cover || "https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?q=80&w=600&auto=format&fit=crop"}
                  alt={title}
                  className="w-40 h-40 sm:w-52 sm:h-52 rounded-full object-cover z-10"
                />

                {/* 中心轴孔 */}
                <div className="absolute w-4 h-4 bg-gray-100 rounded-full z-20 border border-gray-300 shadow-inner flex items-center justify-center">
                  <div className="w-1.5 h-1.5 bg-gray-400 rounded-full"></div>
                </div>
              </div>
            </div>

            <div className="text-center w-full px-4">
              <p className="text-2xl font-bold truncate text-gray-800">{props.payload.title ?? "未知曲目"}</p>
              <p className="text-base text-gray-500 mt-2 truncate">{props.payload.artist ?? "未知歌手"}</p>
            </div>
          </div>

          {/* 控制区 */}
          <div className="shrink-0 w-full max-w-md mx-auto pt-6 pb-4">
            {/* 进度条 */}
            <div className="flex items-center gap-3 text-xs text-gray-500 mb-6 font-medium">
              <span className="w-10 text-right">{formatSeconds(currentTime)}</span>
              <div className="relative flex-1 flex items-center h-4">
                 <input
                    type="range"
                    min={0}
                    max={duration > 0 ? duration : 0}
                    step={0.1}
                    value={duration > 0 ? currentTime : 0}
                    onChange={(e) => onSeek(Number(e.target.value))}
                    disabled={duration <= 0}
                    className="range-slider w-full absolute z-10"
                  />
                  {/* 已播放进度填充层 */}
                  <div
                    className="absolute h-1 bg-blue-500 rounded-l-full pointer-events-none"
                    style={{ width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%` }}
                  ></div>
              </div>
              <span className="w-10 text-left">{formatSeconds(duration)}</span>
            </div>

            {/* 按钮 */}
            <div className="flex items-center justify-center gap-6">
              <button
                type="button"
                onClick={togglePlayPause}
                className="w-16 h-16 flex items-center justify-center rounded-full bg-blue-600 text-white shadow-lg hover:bg-blue-700 transition transform hover:scale-105 active:scale-95"
              >
                {isPlaying ? <PauseIcon /> : <PlayIcon />}
              </button>
            </div>

            <audio
              ref={audioRef}
              controls
              preload="metadata"
              src={props.payload.url}
              className="hidden"
              onLoadedMetadata={() => syncProgressFromPlayer()}
              onDurationChange={() => syncProgressFromPlayer()}
              onTimeUpdate={() => syncProgressFromPlayer()}
              onPlay={() => {
                setIsPlaying(true);
                startRaf();
              }}
              onPause={() => {
                setIsPlaying(false);
                stopRaf();
                syncProgressFromPlayer();
              }}
              onEnded={() => {
                setIsPlaying(false);
                stopRaf();
                syncProgressFromPlayer();
              }}
            />
          </div>
        </div>
      </Artifact>
    </>
  );
}