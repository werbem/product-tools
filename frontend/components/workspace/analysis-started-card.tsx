"use client";

import Link from "next/link";
import { useState } from "react";
import { cancelTask } from "@/lib/copilot-api";
import { extractApiErrorMessage } from "@/lib/copilot-errors";
import {
  ConversationTaskProgress,
  type TaskPhaseState,
} from "./conversation-task-progress";

export type { TaskPhaseState };

export function AnalysisStartedCard({
  taskId,
  phase,
  workflowType,
  analysisMode,
  onCancelled,
}: {
  taskId: string;
  phase?: TaskPhaseState | null;
  workflowType?: string;
  analysisMode?: "fast" | "full";
  onCancelled?: (taskId: string) => void;
}) {
  const isCollection = workflowType === "intelligence_collection";
  const status = phase?.status || "running";
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const href = isCollection
    ? `/workspace/collections/${taskId}`
    : `/report/${taskId}`;
  const linkLabel = isCollection ? "查看收集结果" : "查看报告";
  const cardTitle = isCollection ? "信息收集进度" : "深度分析进度";
  const canCancel = status !== "completed" && status !== "failed";

  const handleCancel = async () => {
    if (cancelling || !canCancel) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await cancelTask(taskId);
      onCancelled?.(taskId);
    } catch (err) {
      setCancelError(extractApiErrorMessage(err, "取消失败，请稍后重试"));
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div className="ml-1 rounded-xl border bg-background p-4 text-sm shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium">{cardTitle}</div>
        <span className="text-xs text-muted-foreground">任务 {taskId.slice(0, 8)}…</span>
      </div>
      <ConversationTaskProgress
        phase={phase}
        analysisMode={analysisMode}
        workflowType={workflowType}
      />
      {status === "completed" ? (
        <div className="mt-3 text-xs">
          <Link href={href} className="text-primary hover:underline">
            {linkLabel}
          </Link>
        </div>
      ) : null}
      {canCancel ? (
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            onClick={() => void handleCancel()}
            disabled={cancelling}
            className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
          >
            {cancelling ? "取消中…" : "终止任务"}
          </button>
          {cancelError ? (
            <span className="text-xs text-destructive">{cancelError}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
