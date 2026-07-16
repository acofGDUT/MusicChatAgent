"use client";

import { RefObject } from "react";
import { ChatMsg } from "@/features/chat-local/types";
import { AssistantMessageRenderer } from "@/features/chat-local/components/AssistantMessageRenderer";

type Props = {
  listRef: RefObject<HTMLDivElement | null>;
  loadingHistory: boolean;
  messages: ChatMsg[];
  sending: boolean;
};

export function LocalChatMessageList({
  listRef,
  loadingHistory,
  messages,
  sending,
}: Props) {
  return (
    <div
      ref={listRef}
      className="flex-1 overflow-y-auto bg-neutral-50/60 px-5 py-4"
    >
      {loadingHistory ? (
        <div className="rounded-xl border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-500">
          正在加载历史对话...
        </div>
      ) : messages.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-300 bg-white px-5 py-6 text-sm text-neutral-500">
          开始发送第一条消息吧，例如：帮我推荐几首适合夜跑的歌。
        </div>
      ) : (
        <div className="space-y-4">
          {messages.map((m, idx) => (
            <div
              key={`${m.role}-${m.ts}-${idx}`}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[82%] rounded-2xl border px-4 py-3 text-sm leading-7 shadow-sm ${
                  m.role === "user"
                    ? "border-blue-200 bg-blue-50 text-blue-900"
                    : "border-neutral-200 bg-white text-neutral-800"
                }`}
              >
                {m.role !== "assistant" ? (
                  <div className="whitespace-pre-wrap">{m.content}</div>
                ) : (
                  <AssistantMessageRenderer message={m} />
                )}
              </div>
            </div>
          ))}

          {sending ? (
            <div className="text-xs text-neutral-400">助手正在思考...</div>
          ) : null}
        </div>
      )}
    </div>
  );
}
