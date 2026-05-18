"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Thread } from "@/components/thread";
import { StreamProvider } from "@/providers/Stream";
import { ThreadProvider } from "@/providers/Thread";
import { ArtifactProvider } from "@/components/thread/artifact";
import { Toaster } from "@/components/ui/sonner";
import React from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const API_PREFIX = "/api/v1";

export default function ChatPage(): React.ReactNode {
  const router = useRouter();
  const [ready, setReady] = useState(false);

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

  if (!ready) {
    return <div className="p-6 text-sm text-neutral-500">Checking login status...</div>;
  }

  return (
    <React.Suspense fallback={<div>Loading (layout)...</div>}>
      <Toaster />
      <ThreadProvider>
        <StreamProvider>
          <ArtifactProvider>
            <Thread />
          </ArtifactProvider>
        </StreamProvider>
      </ThreadProvider>
    </React.Suspense>
  );
}
