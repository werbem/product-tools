"use client";

import Link from "next/link";
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
}: {
  taskId: string;
  phase?: TaskPhaseState | null;
  workflowType?: string;
  analysisMode?: "fast" | "full";
}) {
  const isCollection = workflowType === "intelligence_collection";
  const status = phase?.status || "running";

  const href = isCollection
    ? `/workspace/collections/${taskId}`
    : `/report/${taskId}`;
  const linkLabel = isCollection ? "查看收集结果" : "查看报告";
  const cardTitle = isCollection ? "信息收集进度" : "深度分析进度";

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
    </div>
  );
}
