"use client";

import {
  ArtifactContent,
  ArtifactTitle,
  useArtifactOpen,
} from "@/components/local-chat/artifact";

export function LocalChatArtifactPanel() {
  const [artifactOpen, closeArtifact] = useArtifactOpen();

  if (!artifactOpen) {
    return (
      <aside className="w-[360px] shrink-0 rounded-2xl border border-neutral-200 bg-white p-4 text-neutral-500 shadow-sm">
        <h2 className="text-sm font-semibold text-neutral-800">工具面板</h2>
        <p className="mt-2 text-sm leading-6">当助手返回播放卡片或歌单卡片时，会显示在这里，方便你持续操作。</p>
      </aside>
    );
  }

  return (
    <aside className="w-[360px] shrink-0 overflow-hidden rounded-2xl border border-neutral-200 bg-white text-neutral-900 shadow-sm">
      <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
        <ArtifactTitle className="truncate text-sm font-semibold" />
        <button
          type="button"
          onClick={closeArtifact}
          className="rounded-lg border border-neutral-200 bg-neutral-50 px-2.5 py-1.5 text-xs text-neutral-600 transition hover:bg-neutral-100"
        >
          关闭
        </button>
      </div>
      <ArtifactContent className="h-[calc(100vh-210px)] overflow-auto bg-white" />
    </aside>
  );
}
