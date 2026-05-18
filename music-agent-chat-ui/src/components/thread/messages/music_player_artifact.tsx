import { useMemo } from "react";
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

export function extractPlayMusicPayload(text: string): PlayMusicPayload | null {
  const normalized = text.trim();
  if (!normalized) return null;

  const direct = tryParseJsonObject(normalized);
  if (isPlayMusicPayload(direct)) return direct;

  const fenced = normalized.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
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

  const fenced = normalized.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (!fenced?.[1]) return false;

  const parsed = tryParseJsonObject(fenced[1].trim());
  return isPlayMusicPayload(parsed);
}

export function MusicPlayerArtifact(props: { payload: PlayMusicPayload }) {
  const [Artifact, { open, setOpen }] = useArtifact();

  const title = useMemo(() => {
    if (props.payload.artist && props.payload.title) {
      return `${props.payload.title} - ${props.payload.artist}`;
    }
    return props.payload.title ?? "音乐播放器";
  }, [props.payload.artist, props.payload.title]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full cursor-pointer rounded-lg border bg-white p-4 text-left transition hover:bg-gray-50"
      >
        <p className="font-medium">🎵 {title}</p>
        <p className="mt-1 text-sm text-gray-500">
          {props.payload.description ?? "点击在右侧面板打开播放器"}
        </p>
      </button>

      <Artifact title={title}>
        <div className="flex h-full w-full flex-col gap-4 p-4">
          {props.payload.cover ? (
            <img
              src={props.payload.cover}
              alt={title}
              className="h-48 w-48 rounded-lg object-cover"
            />
          ) : null}

          <div>
            <p className="text-lg font-semibold">{props.payload.title ?? "正在播放"}</p>
            {props.payload.artist ? (
              <p className="text-sm text-gray-500">{props.payload.artist}</p>
            ) : null}
          </div>

          <audio
            controls
            preload="none"
            src={props.payload.url}
            className="w-full"
          />
        </div>
      </Artifact>
    </>
  );
}
