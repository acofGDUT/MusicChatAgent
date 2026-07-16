"use client";

type Props = {
  input: string;
  sending: boolean;
  canSend: boolean;
  onInputChange: (value: string) => void;
  onSend: () => void;
};

export function LocalChatInput({
  input,
  sending,
  canSend,
  onInputChange,
  onSend,
}: Props) {
  return (
    <div className="border-t border-neutral-100 bg-white p-4">
      <div className="flex items-end gap-3">
        <textarea
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          placeholder="输入你想问的内容，比如：推荐通勤听的轻快歌单"
          rows={3}
          className="flex-1 resize-none rounded-xl border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-800 transition outline-none placeholder:text-neutral-400 focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
        />
        <button
          type="button"
          onClick={onSend}
          disabled={!canSend}
          className="h-[44px] rounded-xl bg-blue-600 px-6 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-blue-300"
        >
          {sending ? "发送中..." : "发送"}
        </button>
      </div>
    </div>
  );
}
