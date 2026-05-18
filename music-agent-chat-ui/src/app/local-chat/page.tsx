"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  MusicPlayerArtifact,
  extractPlayMusicPayload,
  isPurePlayMusicPayloadText,
} from "@/components/local-chat/messages/music_player_artifact";
import {
  PlaylistBrowserArtifact,
  extractPlaylistBrowserPayload,
  isPurePlaylistBrowserPayloadText,
} from "@/components/local-chat/messages/playlist_browser_artifact";
import {
  ArtifactContent,
  ArtifactProvider,
  ArtifactTitle,
  useArtifactOpen,
} from "@/components/local-chat/artifact";

const HIDDEN_TRACE_NODES = new Set(["memory_sync", "finalizer"]);

function tryFormatJson(text: string): string {
  try {
    const parsed = JSON.parse(text);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return text;
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const API_PREFIX = "/api/v1";

const LS_KEY = "music-agent:local-chat:v1";

type TraceItem = {
  node: string;
  content: string;
  is_json_like: boolean;
};

type ChatMsg = {
  role: "user" | "assistant";
  content: string;
  ts: number;
  trace?: TraceItem[];
};

type LocalChatResp = {
  status?: string;
  data?: {
    thread_id?: string;
    reply?: string;
    trace?: TraceItem[];
  };
  message?: string;
};

type LocalHistoryResp = {
  status?: string;
  data?: {
    thread_id?: string;
    messages?: ChatMsg[];
  };
  message?: string;
};

function LocalChatArtifactPanel() {
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

export default function LocalChatPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [threadId, setThreadId] = useState("local-web-thread");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const hasHydratedRef = useRef(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const verify = async () => {
      try {
        const resp = await fetch(`${API_BASE}${API_PREFIX}/auth/status`, { cache: "no-store" });
        if (!resp.ok) throw new Error("auth check failed");
        const data = await resp.json();
        if (!data?.authenticated) {
          router.replace("/login");
          return;
        }
        setReady(true);
      } catch {
        router.replace("/login");
      }
    };

    verify();
  }, [router]);

  useEffect(() => {
    const loadInitialMessages = async () => {
      let nextThreadId = "local-web-thread";
      let localMessages: ChatMsg[] = [];

      try {
        const raw = window.localStorage.getItem(LS_KEY);
        if (raw) {
          const parsed = JSON.parse(raw) as { threadId?: string; messages?: ChatMsg[] };
          if (parsed.threadId && parsed.threadId.trim()) {
            nextThreadId = parsed.threadId.trim();
            setThreadId(nextThreadId);
          }
          if (Array.isArray(parsed.messages)) {
            localMessages = parsed.messages.filter(
              (m) =>
                m &&
                (m.role === "user" || m.role === "assistant") &&
                typeof m.content === "string" &&
                typeof m.ts === "number"
            );
          }
        }
      } catch {
        // ignore localStorage parse errors
      }

      if (localMessages.length > 0) {
        setMessages(localMessages);
        hasHydratedRef.current = true;
        return;
      }

      setLoadingHistory(true);
      try {
        const resp = await fetch(
          `${API_BASE}${API_PREFIX}/chat/local/history?thread_id=${encodeURIComponent(nextThreadId)}`,
          { cache: "no-store" }
        );
        const data: LocalHistoryResp = await resp.json();
        const remoteMessages = Array.isArray(data?.data?.messages)
          ? data.data.messages.filter(
              (m) =>
                m &&
                (m.role === "user" || m.role === "assistant") &&
                typeof m.content === "string" &&
                typeof m.ts === "number"
            )
          : [];
        if (resp.ok && data?.status === "success" && remoteMessages.length > 0) {
          setMessages(remoteMessages);
        }
      } catch {
        // ignore history fetch errors
      } finally {
        setLoadingHistory(false);
        hasHydratedRef.current = true;
      }
    };

    void loadInitialMessages();
  }, []);

  useEffect(() => {
    if (!hasHydratedRef.current) return;
    try {
      window.localStorage.setItem(LS_KEY, JSON.stringify({ threadId, messages }));
    } catch {
      // ignore write errors
    }
  }, [threadId, messages]);

  useEffect(() => {
    if (!listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, sending]);

  const canSend = useMemo(() => input.trim().length > 0 && !sending, [input, sending]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;

    setError("");
    setSending(true);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text, ts: Date.now() }]);

    try {
      const resp = await fetch(`${API_BASE}${API_PREFIX}/chat/local`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, thread_id: threadId }),
      });

      const data: LocalChatResp = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || "本地聊天调用失败");
      }

      const nextThreadId = data.data?.thread_id?.trim();
      if (nextThreadId) setThreadId(nextThreadId);

      const reply = data.data?.reply?.trim() || "（助手暂无回复）";
      const trace = Array.isArray(data.data?.trace)
        ? data.data.trace.filter((t) => t && !HIDDEN_TRACE_NODES.has((t.node || "").trim()))
        : [];
      setMessages((prev) => [...prev, { role: "assistant", content: reply, ts: Date.now(), trace }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "发送失败";
      setError(msg);
      setMessages((prev) => [...prev, { role: "assistant", content: `请求失败：${msg}`, ts: Date.now() }]);
    } finally {
      setSending(false);
    }
  };

  const resetChat = () => {
    const nextThreadId = `local-web-thread-${Date.now()}`;
    try {
      window.localStorage.setItem(LS_KEY, JSON.stringify({ threadId: nextThreadId, messages: [] }));
    } catch {
      // ignore
    }
    hasHydratedRef.current = true;

    setMessages([]);
    setError("");
    setInput("");
    setThreadId(nextThreadId);
  };

  if (!ready) {
    return <div className="p-6 text-sm text-neutral-500">Checking login status...</div>;
  }

  return (
    <main className="h-screen overflow-hidden bg-gradient-to-b from-neutral-50 to-white p-6 text-neutral-900">
      <ArtifactProvider>
        <div className="mx-auto flex h-full w-full max-w-[1440px] flex-col gap-4">
          <div className="sticky top-0 z-20 flex items-center justify-between rounded-2xl border border-neutral-200 bg-white/90 px-5 py-4 shadow-sm backdrop-blur">
            <div>
              <h1 className="text-xl font-semibold text-neutral-900">Music Agent Workspace</h1>
              <p className="mt-1 text-sm text-neutral-500">对话推荐 + 音乐工具操作，一体化聊天工作台</p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={resetChat}
                className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 transition hover:bg-neutral-50"
              >
                新会话
              </button>
              <button
                onClick={() => router.push("/home")}
                className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 transition hover:bg-neutral-50"
              >
                回到主页
              </button>
            </div>
          </div>

          <div className="flex min-h-0 flex-1 gap-4">
            <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm">
              <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3">
                <div className="text-sm text-neutral-500">
                  当前会话：<span className="font-mono text-neutral-700">{threadId}</span>
                </div>
                <div className="text-xs text-neutral-400">Enter 发送 · Shift+Enter 换行</div>
              </div>

              <div ref={listRef} className="flex-1 overflow-y-auto bg-neutral-50/60 px-5 py-4">
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
                      <div key={`${m.role}-${m.ts}-${idx}`} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                        <div
                          className={`max-w-[82%] rounded-2xl border px-4 py-3 text-sm leading-7 shadow-sm ${
                            m.role === "user"
                              ? "border-blue-200 bg-blue-50 text-blue-900"
                              : "border-neutral-200 bg-white text-neutral-800"
                          }`}
                        >
                          {(() => {
                            if (m.role !== "assistant") return <div className="whitespace-pre-wrap">{m.content}</div>;

                            const playlistPayload = extractPlaylistBrowserPayload(m.content);
                            if (playlistPayload) {
                              const pureArtifact = isPurePlaylistBrowserPayloadText(m.content);
                              return (
                                <div className="space-y-2">
                                  {!pureArtifact ? <div className="whitespace-pre-wrap">{m.content}</div> : null}
                                  <PlaylistBrowserArtifact payload={playlistPayload} />
                                </div>
                              );
                            }

                            const playPayload = extractPlayMusicPayload(m.content);
                            if (playPayload) {
                              const pureArtifact = isPurePlayMusicPayloadText(m.content);
                              return (
                                <div className="space-y-2">
                                  {!pureArtifact ? <div className="whitespace-pre-wrap">{m.content}</div> : null}
                                  <MusicPlayerArtifact payload={playPayload} />
                                </div>
                              );
                            }

                            return (
                              <div className="space-y-3">
                                <div className="whitespace-pre-wrap">{m.content}</div>
                                {Array.isArray(m.trace) && m.trace.length > 0 ? (
                                  <details className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                                    <summary className="cursor-pointer select-none text-xs font-medium text-neutral-600">
                                      执行过程（{m.trace.length} 个节点）
                                    </summary>
                                    <div className="mt-3 space-y-2">
                                      {m.trace.map((t, traceIdx) => {
                                        const jsonFormatted = t.is_json_like ? tryFormatJson(t.content) : t.content;

                                        return (
                                          <div key={`${t.node}-${traceIdx}`} className="rounded-md border border-neutral-200 bg-white p-2">
                                            <div className="mb-1 flex items-center justify-between gap-2">
                                              <span className="font-mono text-xs text-neutral-700">{t.node}</span>
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
                                            <pre className="whitespace-pre-wrap break-words text-xs leading-5 text-neutral-700">{jsonFormatted}</pre>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  </details>
                                ) : null}
                              </div>
                            );
                          })()}
                        </div>
                      </div>
                    ))}
                    {sending ? <div className="text-xs text-neutral-400">助手正在思考...</div> : null}
                  </div>
                )}
              </div>

              {error ? <div className="border-t border-red-100 bg-red-50 px-5 py-3 text-sm text-red-600">{error}</div> : null}

              <div className="border-t border-neutral-100 bg-white p-4">
                <div className="flex items-end gap-3">
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void sendMessage();
                      }
                    }}
                    placeholder="输入你想问的内容，比如：推荐通勤听的轻快歌单"
                    rows={3}
                    className="flex-1 resize-none rounded-xl border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-800 outline-none transition placeholder:text-neutral-400 focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
                  />
                  <button
                    type="button"
                    onClick={() => void sendMessage()}
                    disabled={!canSend}
                    className="h-[44px] rounded-xl bg-blue-600 px-6 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-blue-300"
                  >
                    {sending ? "发送中..." : "发送"}
                  </button>
                </div>
              </div>
            </section>

            <LocalChatArtifactPanel />
          </div>
        </div>
      </ArtifactProvider>
    </main>
  );
}
