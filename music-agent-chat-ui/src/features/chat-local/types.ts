import type { ChatArtifact } from "./artifacts";

export type TraceItem = {
  node: string;
  content: string;
  is_json_like: boolean;
};

export type ChatMsg = {
  role: "user" | "assistant";
  content: string;
  ts: number;
  trace?: TraceItem[];
  artifacts?: ChatArtifact[];
};

export type LocalChatResp = {
  status?: string;
  data?: {
    thread_id?: string;
    reply?: string;
    trace?: TraceItem[];
    run?: { status?: string };
    artifacts?: ChatArtifact[];
  };
  message?: string;
};

export type LocalHistoryResp = {
  status?: string;
  data?: {
    thread_id?: string;
    messages?: ChatMsg[];
  };
  message?: string;
};

export type ArtifactSource = "content" | "trace";
