"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const API_PREFIX = "/api/v1";

type BaseInfo = {
  encrypted_uin?: string;
  name?: string;
  avatar?: string;
  background_image?: string;
  user_type?: number;
};

type HomepageResp = {
  status?: string;
  data?: {
    base_info?: BaseInfo;
    [key: string]: unknown;
  };
  message?: string;
};

export default function HomePage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [rawData, setRawData] = useState<HomepageResp["data"] | null>(null);

  const userInfo = useMemo(() => {
    const baseInfo = rawData?.base_info ?? {};
    const name = baseInfo.name || "未命名用户";
    const avatar = baseInfo.avatar || "";
    const background = baseInfo.background_image || "";
    const encryptedUin = baseInfo.encrypted_uin || "";
    const userType = baseInfo.user_type;
    return { name, avatar, background, encryptedUin, userType };
  }, [rawData]);

  const bootstrap = async () => {
    try {
      const statusResp = await fetch(`${API_BASE}${API_PREFIX}/auth/status`, { cache: "no-store" });
      if (!statusResp.ok) throw new Error("登录状态检查失败");
      const status = await statusResp.json();

      if (!status?.authenticated) {
        router.replace("/login");
        return;
      }

      const homeResp = await fetch(`${API_BASE}${API_PREFIX}/user/homepage`, { cache: "no-store" });
      if (!homeResp.ok) throw new Error("获取用户主页失败");
      const homeData: HomepageResp = await homeResp.json();

      if (homeData.status && homeData.status !== "success") {
        throw new Error(homeData.message || "获取用户信息失败");
      }

      setRawData(homeData.data || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    bootstrap();
  }, []);

  const logout = async () => {
    try {
      await fetch(`${API_BASE}${API_PREFIX}/auth/logout`, { method: "POST" });
    } finally {
      router.replace("/login");
    }
  };

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 flex items-center justify-center p-6">
      <div className="w-full max-w-3xl rounded-2xl border border-neutral-800 bg-neutral-900 p-6 shadow-2xl shadow-black/20">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-semibold mb-2">欢迎回来</h1>
            <p className="text-sm text-neutral-400">已登录成功，请选择聊天模式。</p>
          </div>
          <button
            onClick={logout}
            className="inline-flex items-center rounded-md border border-neutral-700 bg-neutral-800 px-4 py-2 text-sm font-medium text-neutral-200 hover:bg-neutral-700"
          >
            退出登录
          </button>
        </div>

        {loading ? (
          <div className="rounded-lg bg-neutral-800/60 border border-neutral-700 p-4 text-sm text-neutral-300">
            正在加载用户信息...
          </div>
        ) : error ? (
          <div className="rounded-lg bg-red-950/50 border border-red-800 p-4 text-sm text-red-200">{error}</div>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-neutral-700 bg-neutral-800/60">
            {userInfo.background ? (
              <div className="h-40 w-full">
                <img src={userInfo.background} alt="背景图" className="h-full w-full object-cover" />
              </div>
            ) : (
              <div className="h-24 w-full bg-neutral-700" />
            )}

            <div className="p-5 flex items-center gap-4">
              <div className="h-16 w-16 rounded-full overflow-hidden bg-neutral-700 border border-neutral-600 shrink-0">
                {userInfo.avatar ? <img src={userInfo.avatar} alt="头像" className="h-full w-full object-cover" /> : null}
              </div>
              <div>
                <div className="text-sm text-neutral-400">用户名</div>
                <div className="text-lg font-medium">{userInfo.name}</div>
                {userInfo.encryptedUin ? <div className="text-xs text-neutral-500 mt-1">UIN: {userInfo.encryptedUin}</div> : null}
                {typeof userInfo.userType === "number" ? <div className="text-xs text-neutral-500">用户类型: {userInfo.userType}</div> : null}
              </div>
            </div>
          </div>
        )}

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <button
            onClick={() => router.push("/chat/local")}
            className="rounded-2xl border border-neutral-700 bg-neutral-800 p-5 text-left transition hover:bg-neutral-700"
          >
            <div className="text-lg font-semibold">本地聊天</div>
            <div className="mt-2 text-sm text-neutral-400">已接入 FastAPI 本地聊天，无需启动 langgraph dev。</div>
          </button>
          <button
            onClick={() => router.push("/chat/online")}
            className="rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-5 text-left transition hover:bg-emerald-500/20"
          >
            <div className="text-lg font-semibold text-emerald-300">在线聊天</div>
            <div className="mt-2 text-sm text-neutral-400">进入当前已接入的在线聊天界面。</div>
          </button>
        </div>
      </div>
    </main>
  );
}
