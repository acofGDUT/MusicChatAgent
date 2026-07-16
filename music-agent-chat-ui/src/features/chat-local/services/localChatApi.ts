import {
  API_BASE,
  API_PREFIX,
  HIDDEN_TRACE_NODES,
} from "@/features/chat-local/constants";
import {
  ChatMsg,
  LocalChatResp,
  LocalHistoryResp,
} from "@/features/chat-local/types";

type ErrorPayload = {
  message?: unknown;
  detail?: unknown;
};

async function readJsonBody(resp: Response): Promise<unknown> {
  try {
    return await resp.json();
  } catch {
    return undefined;
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const body = payload as ErrorPayload;
  if (typeof body.message === "string" && body.message.trim())
    return body.message;
  if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
  if (
    body.detail &&
    typeof body.detail === "object" &&
    "message" in body.detail &&
    typeof (body.detail as { message?: unknown }).message === "string"
  ) {
    const message = (body.detail as { message: string }).message.trim();
    if (message) return message;
  }
  return fallback;
}

export async function verifyAuthStatus(): Promise<boolean> {
  const resp = await fetch(`${API_BASE}${API_PREFIX}/auth/status`, {
    cache: "no-store",
  });
  if (!resp.ok) return false;
  const data = await resp.json();
  return Boolean(data?.authenticated);
}

export async function fetchLocalChatHistory(
  threadId: string,
): Promise<ChatMsg[]> {
  const resp = await fetch(
    `${API_BASE}${API_PREFIX}/chat/local/history?thread_id=${encodeURIComponent(threadId)}`,
    { cache: "no-store" },
  );
  const payload = await readJsonBody(resp);
  if (!resp.ok) {
    throw new Error(errorMessage(payload, "历史记录加载失败"));
  }
  const data = (payload || {}) as LocalHistoryResp;

  const remoteMessages = Array.isArray(data?.data?.messages)
    ? data.data.messages.filter(
        (m) =>
          m &&
          (m.role === "user" || m.role === "assistant") &&
          typeof m.content === "string" &&
          typeof m.ts === "number",
      )
    : [];

  if (data?.status === "success") {
    return remoteMessages;
  }
  throw new Error(errorMessage(payload, "历史记录加载失败"));
}

export async function sendLocalChatMessage(params: {
  message: string;
  threadId: string;
}): Promise<{
  threadId?: string;
  reply: string;
  trace: NonNullable<ChatMsg["trace"]>;
}> {
  const resp = await fetch(`${API_BASE}${API_PREFIX}/chat/local`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: params.message,
      thread_id: params.threadId,
    }),
  });

  const payload = await readJsonBody(resp);
  if (!resp.ok) {
    throw new Error(errorMessage(payload, "本地聊天调用失败"));
  }
  const data = (payload || {}) as LocalChatResp;
  if (data.status !== "success") {
    throw new Error(errorMessage(payload, "本地聊天调用失败"));
  }

  const nextThreadId = data.data?.thread_id?.trim();
  const reply = data.data?.reply?.trim() || "（助手暂无回复）";
  const trace = Array.isArray(data.data?.trace)
    ? data.data.trace.filter(
        (t) => t && !HIDDEN_TRACE_NODES.has((t.node || "").trim()),
      )
    : [];

  return {
    threadId: nextThreadId,
    reply,
    trace,
  };
}
