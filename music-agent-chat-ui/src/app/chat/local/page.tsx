"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { ArtifactProvider } from "@/components/local-chat/artifact";
import { LocalChatArtifactPanel } from "@/features/chat-local/components/LocalChatArtifactPanel";
import { LocalChatHeader } from "@/features/chat-local/components/LocalChatHeader";
import { LocalChatInput } from "@/features/chat-local/components/LocalChatInput";
import { LocalChatMessageList } from "@/features/chat-local/components/LocalChatMessageList";
import { useLocalChatSession } from "@/features/chat-local/hooks/useLocalChatSession";

export default function LocalChatPage() {
  const router = useRouter();
  const listRef = useRef<HTMLDivElement | null>(null);

  const {
    ready,
    threadId,
    messages,
    loadingHistory,
    input,
    sending,
    error,
    canSend,
    setInput,
    sendMessage,
    resetChat,
  } = useLocalChatSession();

  useEffect(() => {
    if (!listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, sending]);

  if (!ready) {
    return <div className="p-6 text-sm text-neutral-500">Checking login status...</div>;
  }

  return (
    <main className="h-screen overflow-hidden bg-gradient-to-b from-neutral-50 to-white p-6 text-neutral-900">
      <ArtifactProvider>
        <div className="mx-auto flex h-full w-full max-w-[1440px] flex-col gap-4">
          <LocalChatHeader onReset={resetChat} onGoHome={() => router.push("/home")} />

          <div className="flex min-h-0 flex-1 gap-4">
            <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm">
              <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3">
                <div className="text-sm text-neutral-500">
                  当前会话：<span className="font-mono text-neutral-700">{threadId}</span>
                </div>
                <div className="text-xs text-neutral-400">Enter 发送 · Shift+Enter 换行</div>
              </div>

              <LocalChatMessageList
                listRef={listRef}
                loadingHistory={loadingHistory}
                messages={messages}
                sending={sending}
              />

              {error ? <div className="border-t border-red-100 bg-red-50 px-5 py-3 text-sm text-red-600">{error}</div> : null}

              <LocalChatInput
                input={input}
                sending={sending}
                canSend={canSend}
                onInputChange={setInput}
                onSend={() => void sendMessage()}
              />
            </section>

            <LocalChatArtifactPanel />
          </div>
        </div>
      </ArtifactProvider>
    </main>
  );
}
