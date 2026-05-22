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
};

export type LocalChatResp = {
  status?: string;
  data?: {
    thread_id?: string;
    reply?: string;
    trace?: TraceItem[];
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
