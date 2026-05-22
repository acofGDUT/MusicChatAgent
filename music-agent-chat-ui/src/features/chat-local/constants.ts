export const HIDDEN_TRACE_NODES = new Set(["memory_sync", "finalizer"]);

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
export const API_PREFIX = "/api/v1";

export const LS_KEY = "music-agent:local-chat:v1";
