"use client";

type Props = {
  onReset: () => void;
  onGoHome: () => void;
};

export function LocalChatHeader({ onReset, onGoHome }: Props) {
  return (
    <div className="sticky top-0 z-20 flex items-center justify-between rounded-2xl border border-neutral-200 bg-white/90 px-5 py-4 shadow-sm backdrop-blur">
      <div>
        <h1 className="text-xl font-semibold text-neutral-900">
          Music Agent Workspace
        </h1>
        <p className="mt-1 text-sm text-neutral-500">
          对话推荐 + 音乐工具操作，一体化聊天工作台
        </p>
      </div>
      <div className="flex gap-2">
        <button
          onClick={onReset}
          className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 transition hover:bg-neutral-50"
        >
          新会话
        </button>
        <button
          onClick={onGoHome}
          className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 transition hover:bg-neutral-50"
        >
          回到主页
        </button>
      </div>
    </div>
  );
}
