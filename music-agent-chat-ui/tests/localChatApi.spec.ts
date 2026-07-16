import { expect, test } from "@playwright/test";

import {
  fetchLocalChatHistory,
  sendLocalChatMessage,
} from "../src/features/chat-local/services/localChatApi";

test("history non-2xx rejects with FastAPI detail", async () => {
  global.fetch = async () =>
    new Response(
      JSON.stringify({ detail: "本地会话存储暂时不可用，请稍后重试" }),
      {
        status: 503,
        headers: { "Content-Type": "application/json" },
      },
    );

  await expect(fetchLocalChatHistory("thread-1")).rejects.toThrow(
    "本地会话存储暂时不可用，请稍后重试",
  );
});

test("post reads nested detail.message", async () => {
  global.fetch = async () =>
    new Response(
      JSON.stringify({ detail: { message: "认证状态暂时不可用" } }),
      {
        status: 503,
        headers: { "Content-Type": "application/json" },
      },
    );

  await expect(
    sendLocalChatMessage({ message: "你好", threadId: "thread-1" }),
  ).rejects.toThrow("认证状态暂时不可用");
});

test("post uses safe fallback for an unknown body", async () => {
  global.fetch = async () => new Response("not-json", { status: 500 });

  await expect(
    sendLocalChatMessage({ message: "你好", threadId: "thread-1" }),
  ).rejects.toThrow("本地聊天调用失败");
});
