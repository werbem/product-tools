"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { listConversations } from "@/lib/copilot-api";
import { extractApiErrorMessage } from "@/lib/copilot-errors";
import { useState } from "react";

/** 兼容旧链接：/workspace/projects/[id] 自动跳转到最新会话 */
export function ProjectDetailPageContent({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listConversations(projectId)
      .then((conversations) => {
        if (cancelled) return;
        const latest = conversations[0];
        if (!latest) {
          setError("该项目暂无会话");
          return;
        }
        router.replace(`/workspace/conversations/${latest.id}`);
      })
      .catch((err) => {
        if (!cancelled) setError(extractApiErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, router]);

  if (error) {
    return <div className="text-sm text-destructive">{error}</div>;
  }

  return <div className="text-sm text-muted-foreground">正在进入分析会话…</div>;
}
