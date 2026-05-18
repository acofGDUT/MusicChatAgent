"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const API_PREFIX = "/api/v1";

type AuthStatus = {
  authenticated: boolean;
  refreshed?: boolean;
  reason?: string;
};

type QrCreateResp = {
  identifier: string;
  mime_type: string;
  image_base64: string;
};

export default function LoginPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [qr, setQr] = useState<QrCreateResp | null>(null);
  const [statusText, setStatusText] = useState("正在检查本地凭证...");
  const pollRef = useRef<number | null>(null);
  const doneRef = useRef(false);

  const qrSrc = useMemo(() => {
    if (!qr) return "";
    return `data:${qr.mime_type};base64,${qr.image_base64}`;
  }, [qr]);

  const clearPoll = () => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const stopAfterDone = () => {
    doneRef.current = true;
    clearPoll();
  };

  const checkStatus = async (): Promise<AuthStatus> => {
    const resp = await fetch(`${API_BASE}${API_PREFIX}/auth/status`, { cache: "no-store" });
    if (!resp.ok) throw new Error("状态检查失败");
    return await resp.json();
  };

  const createQr = async () => {
    doneRef.current = false;
    setStatusText("正在生成二维码...");
    const resp = await fetch(`${API_BASE}${API_PREFIX}/auth/qr/create`, {
      method: "POST",
    });
    if (!resp.ok) throw new Error("二维码生成失败");
    const data: QrCreateResp = await resp.json();
    setQr(data);
    setStatusText("请使用 QQ 扫码登录");
  };

  const startPoll = () => {
    clearPoll();
    pollRef.current = window.setInterval(async () => {
      if (doneRef.current) return;

      try {
        const resp = await fetch(`${API_BASE}${API_PREFIX}/auth/qr/check`, { cache: "no-store" });
        if (doneRef.current) return;

        if (!resp.ok) {
          setStatusText("登录状态检查失败，请查看后端日志");
          return;
        }

        const data = await resp.json();
        if (doneRef.current) return;

        console.log("[login] /auth/qr/check response:", data);
        console.log("[login] /auth/qr/check status:", data?.status);

        if (data.status === "done") {
          stopAfterDone();
          setStatusText("登录成功，凭证已保存到本地");
          router.replace("/home");
          return;
        }

        if (data.status === "scan") setStatusText("已扫码，请在手机确认登录");
        if (data.status === "confirm") setStatusText("等待手机确认...");
        if (data.status === "timeout") {
          clearPoll();
          setStatusText("二维码已过期，请重新生成");
        }
        if (data.status === "refuse") {
          clearPoll();
          setStatusText("已取消登录，请重新扫码");
        }
        if (data.status === "error") {
          if (data.message?.includes("二维码不存在") && doneRef.current) return;
          clearPoll();
          setStatusText(`登录失败: ${data.message ?? "未知错误"}`);
        }
      } catch {
        if (doneRef.current) return;
        setStatusText("网络异常，正在重试...");
      }
    }, 2000);
  };

  const bootstrap = async () => {
    try {
      const status = await checkStatus();
      if (status.authenticated) {
        router.replace("/home");
        return;
      }
      await createQr();
      startPoll();
    } catch {
      setStatusText("初始化失败，请检查后端服务是否启动");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    bootstrap();
    return () => clearPoll();
  }, []);

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-neutral-800 bg-neutral-900 p-6">
        <h1 className="text-xl font-semibold mb-2">登录 QQ 音乐</h1>
        <p className="text-sm text-neutral-400 mb-6">当前版本仅实现登录并保存凭证到本地。</p>

        <div className="bg-white rounded-lg p-3 w-64 h-64 mx-auto flex items-center justify-center">
          {qrSrc ? (
            <img src={qrSrc} alt="qr" className="w-full h-full" />
          ) : (
            <span className="text-neutral-500 text-sm">{loading ? "加载中..." : "暂无二维码"}</span>
          )}
        </div>

        <p className="text-sm text-neutral-300 mt-4 text-center">{statusText}</p>

        <button
          className="mt-4 w-full rounded-md bg-neutral-100 text-neutral-900 py-2 text-sm font-medium hover:bg-white"
          onClick={async () => {
            await createQr();
            startPoll();
          }}
        >
          重新生成二维码
        </button>
      </div>
    </main>
  );
}
