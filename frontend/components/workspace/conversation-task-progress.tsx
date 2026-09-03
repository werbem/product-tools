"use client";

import { useEffect, useMemo, useState } from "react";
import { PHASE_LABELS } from "@/types";

const PHASE_STAGE_FALLBACK: Record<string, string> = {
  researching: "正在检索公开信息…",
  compared: "正在对比分析…",
  insighting: "正在生成洞察…",
  strategizing: "正在制定策略…",
  reporting: "正在撰写报告…",
  reviewing: "正在审阅报告…",
};

function formatElapsed(seconds?: number): string | null {
  if (seconds == null || seconds <= 0 || !Number.isFinite(seconds)) return null;
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  if (minutes <= 0) return `已用时 ${secs} 秒`;
  return `已用时 ${minutes} 分 ${secs} 秒`;
}

export type TaskPhaseState = {
  phase?: string;
  progress?: number;
  status?: string;
  stage_hint?: string;
  total_elapsed_s?: number;
  updated_at?: number;
};

export function ConversationTaskProgress({
  phase,
  analysisMode,
  workflowType,
}: {
  phase?: TaskPhaseState | null;
  analysisMode?: "fast" | "full";
  workflowType?: string;
}) {
  const isCollection = workflowType === "intelligence_collection";
  const status = phase?.status || "running";
  const progress = Math.min(Math.max(phase?.progress ?? 0, 0), 100);
  const phaseKey = phase?.phase || "";
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (status !== "running") return;
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, [status]);

  const stageHint = useMemo(() => {
    if (phase?.stage_hint) return phase.stage_hint;
    if (phaseKey && PHASE_STAGE_FALLBACK[phaseKey]) return PHASE_STAGE_FALLBACK[phaseKey];
    if (progress >= 32 && progress < 40) return "正在分析网页内容…";
    return null;
  }, [phase?.stage_hint, phaseKey, progress]);

  const label =
    status === "completed"
      ? isCollection ? "信息收集完成" : "分析完成"
      : status === "failed"
        ? isCollection ? "收集失败" : "分析失败"
        : stageHint
          || (phaseKey ? PHASE_LABELS[phaseKey] || phaseKey : isCollection ? "正在启动信息收集…" : "正在启动深度分析…");

  const etaHint =
    status === "completed" || status === "failed"
      ? null
      : analysisMode === "full"
        ? "预计约 12 分钟完成"
        : analysisMode === "fast"
          ? "预计约 6 分钟完成"
          : isCollection
            ? "预计 1–3 分钟"
            : null;

  const elapsedText = formatElapsed(phase?.total_elapsed_s);
  const stale =
    status === "running"
    && phase?.updated_at
    && now - phase.updated_at > 30_000
    && progress > 0
    && progress < 100;

  const detailLine =
    status === "completed"
      ? isCollection
        ? "公开信息已整理为摘要，可查看收集结果。"
        : "报告已生成，可查看完整结果。"
      : status === "failed"
        ? isCollection ? "信息收集未能完成，可稍后重试。" : "分析未能完成，可稍后重试。"
        : [
            progress > 0 ? `已完成约 ${Math.round(progress)}%` : null,
            etaHint,
            elapsedText,
          ]
            .filter(Boolean)
            .join(" · ") || "请稍候…";

  return (
    <>
      <div className="mt-1 text-muted-foreground">{label}</div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full transition-all ${
            status === "failed" ? "bg-destructive" : "bg-primary"
          }`}
          style={{ width: `${status === "completed" ? 100 : progress}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{detailLine}</p>
      {stale ? (
        <p className="mt-1 text-xs text-muted-foreground/80">
          该步骤耗时较长，请稍候…
        </p>
      ) : null}
    </>
  );
}
