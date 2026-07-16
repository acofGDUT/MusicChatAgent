"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { LS_KEY } from "@/features/chat-local/constants";
import { ChatMsg } from "@/features/chat-local/types";
import {
  fetchLocalChatHistory,
  sendLocalChatMessage,
  verifyAuthStatus,
} from "@/features/chat-local/services/localChatApi";

export function useLocalChatSession() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [threadId, setThreadId] = useState("local-web-thread");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const hasHydratedRef = useRef(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const verify = async () => {
      try {
        const ok = await verifyAuthStatus();
        if (!ok) {
          router.replace("/login");
          return;
        }
        setReady(true);
      } catch {
        router.replace("/login");
      }
    };

    void verify();
  }, [router]);

  useEffect(() => {
    const loadInitialMessages = async () => {
      let nextThreadId = "local-web-thread";
      let localMessages: ChatMsg[] = [];

      try {
        const raw = window.localStorage.getItem(LS_KEY);
        if (raw) {
          const parsed = JSON.parse(raw) as {
            threadId?: string;
            messages?: ChatMsg[];
          };
          if (parsed.threadId?.trim()) {
            nextThreadId = parsed.threadId.trim();
            setThreadId(nextThreadId);
          }
          if (Array.isArray(parsed.messages)) {
            localMessages = parsed.messages.filter(
              (m) =>
                m &&
                (m.role === "user" || m.role === "assistant") &&
                typeof m.content === "string" &&
                typeof m.ts === "number",
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
        const remoteMessages = await fetchLocalChatHistory(nextThreadId);
        if (remoteMessages.length > 0) {
          setMessages(remoteMessages);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "历史记录加载失败");
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
      window.localStorage.setItem(
        LS_KEY,
        JSON.stringify({ threadId, messages }),
      );
    } catch {
      // ignore write errors
    }
  }, [threadId, messages]);

  const canSend = useMemo(
    () => input.trim().length > 0 && !sending,
    [input, sending],
  );

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;

    setError("");
    setSending(true);
    setInput("");
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text, ts: Date.now() },
    ]);

    try {
      const result = await sendLocalChatMessage({ message: text, threadId });
      if (result.threadId) setThreadId(result.threadId);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: result.reply,
          ts: Date.now(),
          trace: result.trace,
          artifacts: result.artifacts,
        },
      ]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "发送失败";
      setError(msg);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `请求失败：${msg}`, ts: Date.now() },
      ]);
    } finally {
      setSending(false);
    }
  };

  const resetChat = () => {
    const nextThreadId = `local-web-thread-${Date.now()}`;
    try {
      window.localStorage.setItem(
        LS_KEY,
        JSON.stringify({ threadId: nextThreadId, messages: [] }),
      );
    } catch {
      // ignore write errors
    }

    hasHydratedRef.current = true;
    setMessages([]);
    setError("");
    setInput("");
    setThreadId(nextThreadId);
  };

  return {
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
  };
}
