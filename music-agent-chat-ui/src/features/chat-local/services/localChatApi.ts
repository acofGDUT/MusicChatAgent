import { API_BASE, API_PREFIX, HIDDEN_TRACE_NODES } from "@/features/chat-local/constants";
import { ChatMsg, LocalChatResp, LocalHistoryResp } from "@/features/chat-local/types";

export async function verifyAuthStatus(): Promise<boolean> {
  const resp = await fetch(`${API_BASE}${API_PREFIX}/auth/status`, { cache: "no-store" });
  if (!resp.ok) return false;
  const data = await resp.json();
  return Boolean(data?.authenticated);
}

export async function fetchLocalChatHistory(threadId: string): Promise<ChatMsg[]> {
  const resp = await fetch(
    `${API_BASE}${API_PREFIX}/chat/local/history?thread_id=${encodeURIComponent(threadId)}`,
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

  if (resp.ok && data?.status === "success") {
    return remoteMessages;
  }

  return [];
}

export async function sendLocalChatMessage(params: {
  message: string;
  threadId: string;
}): Promise<{ threadId?: string; reply: string; trace: NonNullable<ChatMsg["trace"]> }> {
  const resp = await fetch(`${API_BASE}${API_PREFIX}/chat/local`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: params.message, thread_id: params.threadId }),
  });

  const data: LocalChatResp = await resp.json();
  if (!resp.ok || data.status !== "success") {
    throw new Error(data.message || "本地聊天调用失败");
  }

  const nextThreadId = data.data?.thread_id?.trim();
  const reply = data.data?.reply?.trim() || "（助手暂无回复）";
  const trace = Array.isArray(data.data?.trace)
    ? data.data.trace.filter((t) => t && !HIDDEN_TRACE_NODES.has((t.node || "").trim()))
    : [];

  return {
    threadId: nextThreadId,
    reply,
    trace,
  };
}
