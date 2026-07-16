"use client";

import { MusicPlayerArtifact } from "@/components/local-chat/messages/music_player_artifact";
import { PlaylistBrowserArtifact } from "@/components/local-chat/messages/playlist_browser_artifact";
import {
  isPlayMusicArtifact,
  isPlaylistBrowserArtifact,
} from "@/features/chat-local/artifacts";
import type { ChatArtifact } from "@/features/chat-local/artifacts";
import type { ChatMsg } from "@/features/chat-local/types";
import {
  selectRenderableArtifacts,
  tryFormatJson,
} from "@/features/chat-local/utils";

type Props = {
  message: ChatMsg;
};

function renderArtifact(artifact: ChatArtifact, index: number) {
  if (isPlaylistBrowserArtifact(artifact)) {
    return (
      <div
        key={`${artifact.type}-${artifact.dirid ?? "unknown"}-${artifact.page}-${index}`}
      >
        <PlaylistBrowserArtifact payload={artifact} />
      </div>
    );
  }

  if (isPlayMusicArtifact(artifact)) {
    return (
      <div key={`${artifact.type}-${artifact.song_mid}-${index}`}>
        <MusicPlayerArtifact payload={artifact} />
      </div>
    );
  }

  return null;
}

export function AssistantMessageRenderer({ message: m }: Props) {
  const artifactSelection = selectRenderableArtifacts({
    content: m.content,
    artifacts: m.artifacts,
  });

  if (artifactSelection.artifacts.length > 0) {
    return (
      <div className="space-y-2">
        {!artifactSelection.isPureArtifactText &&
        m.content.trim().length > 0 ? (
          <div className="whitespace-pre-wrap">{m.content}</div>
        ) : null}
        {artifactSelection.artifacts.map(renderArtifact)}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="whitespace-pre-wrap">{m.content}</div>
      {Array.isArray(m.trace) && m.trace.length > 0 ? (
        <details className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
          <summary className="cursor-pointer text-xs font-medium text-neutral-600 select-none">
            执行过程（{m.trace.length} 个节点）
          </summary>
          <div className="mt-3 space-y-2">
            {m.trace.map((t, traceIdx) => {
              const jsonFormatted = t.is_json_like
                ? tryFormatJson(t.content)
                : t.content;

              return (
                <div
                  key={`${t.node}-${traceIdx}`}
                  className="rounded-md border border-neutral-200 bg-white p-2"
                >
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-neutral-700">
                      {t.node}
                    </span>
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          t.is_json_like
                            ? "bg-violet-100 text-violet-700"
                            : "bg-sky-100 text-sky-700"
                        }`}
                      >
                        {t.is_json_like ? "JSON" : "TEXT"}
                      </span>
                      {t.is_json_like ? (
                        <button
                          type="button"
                          onClick={() => {
                            void navigator.clipboard.writeText(jsonFormatted);
                          }}
                          className="rounded border border-neutral-200 bg-neutral-50 px-2 py-0.5 text-[10px] font-medium text-neutral-600 hover:bg-neutral-100"
                        >
                          复制格式化 JSON
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <pre className="text-xs leading-5 break-words whitespace-pre-wrap text-neutral-700">
                    {jsonFormatted}
                  </pre>
                </div>
              );
            })}
          </div>
        </details>
      ) : null}
    </div>
  );
}
