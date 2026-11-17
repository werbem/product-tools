"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { AnalysisMode } from "./conversation-composer";
import {
  getTaskProgress,
  listConversationMessages,
  listConversations,
} from "@/lib/copilot-api";
import type { Project } from "@/types/copilot";

export type PipelineStageId =
  | "confirm"
  | "plan"
  | "research"
  | "compare"
  | "insight"
  | "strategy"
  | "report"
  | "review";

export type PipelineStage = {
  id: PipelineStageId;
  name: string;
  output: string;
};

const FULL_STAGES: PipelineStage[] = [
  { id: "confirm", name: "确认分析对象", output: "明确公司、竞品、产品与分析目标" },
  { id: "plan", name: "调研计划", output: "自动拆解研究维度与检索任务" },
  { id: "research", name: "检索证据", output: "从公开信息中检索并整理可引用证据" },
  { id: "compare", name: "对比差异", output: "建立双方功能与能力差距" },
  { id: "insight", name: "关键洞察", output: "从证据中提炼事实、观察与假设" },
  { id: "strategy", name: "策略建议", output: "形成机会、风险与产品建议" },
  { id: "report", name: "生成报告", output: "将分析结果组织成结构化报告" },
  { id: "review", name: "质量复核", output: "检查完整性、逻辑与来源" },
];

const FAST_STAGE_IDS: PipelineStageId[] = ["confirm", "plan", "research", "report"];

const MODE_BLURB: Record<AnalysisMode, string> = {
  fast: "适合快速了解市场动态、竞品信息与核心差异。",
  full: "适合需要完整竞品对比、战略判断与产品建议的分析任务。",
};

/** Map progress API current_agent / phase → business stage. */
function mapAgentToStage(agent: string | null | undefined): PipelineStageId | null {
  const key = (agent || "").trim().toLowerCase();
  if (!key) return null;
  if (key === "gate" || key === "validated" || key === "initialized" || key === "validation_failed") {
    return "confirm";
  }
  if (key === "planner" || key === "planned" || key === "plan") return "plan";
  if (
    key === "research"
    || key === "researched"
    || key === "researching"
    || key === "collection_processed"
    || key === "need_more_research"
  ) {
    return "research";
  }
  if (key === "compare" || key === "compared") return "compare";
  if (key === "insight" || key === "insighting") return "insight";
  if (key === "strategy" || key === "strategizing" || key === "strategized") return "strategy";
  if (key === "report" || key === "reported" || key === "reporting") return "report";
  if (key === "review" || key === "reviewed" || key === "reviewing" || key === "review_failed") {
    return "review";
  }
  if (key === "completed" || key === "finalize" || key === "finalized") return null;
  return null;
}

function stagesForMode(mode: AnalysisMode): PipelineStage[] {
  if (mode === "fast") {
    return FULL_STAGES.filter((s) => FAST_STAGE_IDS.includes(s.id));
  }
  return FULL_STAGES;
}

type StageVisualState = "pending" | "active" | "done";

function resolveStageStates(
  stages: PipelineStage[],
  activeStageId: PipelineStageId | null,
  isLive: boolean,
): StageVisualState[] {
  if (!isLive || !activeStageId) {
    return stages.map(() => "pending");
  }
  const activeIndex = stages.findIndex((s) => s.id === activeStageId);
  if (activeIndex < 0) {
    return stages.map(() => "pending");
  }
  return stages.map((_, i) => {
    if (i < activeIndex) return "done";
    if (i === activeIndex) return "active";
    return "pending";
  });
}

export type PipelineLiveState = {
  taskId: string;
  conversationId?: string | null;
  reportHref?: string | null;
  currentAgent: string;
  stageHint?: string | null;
  progress?: number;
  status: string;
};

/** Progress API often returns the phase name as status while a task is active — not only "running". */
function isActiveProgressStatus(status: string | null | undefined): boolean {
  const key = (status || "").trim().toLowerCase();
  if (!key) return false;
  return key !== "completed" && key !== "failed";
}

async function discoverRunningPipeline(projects: Project[]): Promise<PipelineLiveState | null> {
  const running = projects.find((p) => p.analysis_status === "running");
  if (!running) return null;

  const conversations = await listConversations(running.id);
  const latest = conversations[0];
  if (!latest) return null;

  const messages = await listConversationMessages(latest.id);
  const withTask = [...messages].reverse().find((m) => m.task_id);
  if (!withTask?.task_id) return null;

  const progress = await getTaskProgress(withTask.task_id);
  if (!isActiveProgressStatus(progress.status)) return null;

  return {
    taskId: progress.task_id,
    conversationId: latest.id,
    reportHref: null,
    currentAgent: progress.current_agent,
    stageHint: progress.stage_hint,
    progress: progress.progress,
    status: "running",
  };
}

function StageGlyph({ state }: { state: StageVisualState }) {
  if (state === "done") {
    return (
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-foreground/30 bg-foreground text-[10px] text-background"
        aria-hidden
      >
        ✓
      </span>
    );
  }
  if (state === "active") {
    return (
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 border-foreground bg-foreground/10"
        aria-hidden
      >
        <span className="h-2 w-2 rounded-full bg-foreground" />
      </span>
    );
  }
  return (
    <span
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-border text-[10px] text-muted-foreground"
      aria-hidden
    >
      ○
    </span>
  );
}

export function WorkspaceAgentPipeline({
  mode: controlledMode,
  onModeChange,
  live: liveProp,
  /** Shared homepage projects — avoids a second listProjects. When undefined, skip live discovery. */
  projects,
}: {
  /** Presentation-only mode for path preview; does not affect Composer submit. */
  mode?: AnalysisMode;
  onModeChange?: (mode: AnalysisMode) => void;
  /** Injected live progress (tests / parent). When omitted, optional discovery runs from `projects`. */
  live?: PipelineLiveState | null;
  projects?: Project[] | null;
}) {
  const [internalMode, setInternalMode] = useState<AnalysisMode>("fast");
  const [discovered, setDiscovered] = useState<PipelineLiveState | null>(null);
  const [discoveryDone, setDiscoveryDone] = useState(liveProp !== undefined || projects === undefined);

  const mode = controlledMode ?? internalMode;
  const setMode = (next: AnalysisMode) => {
    if (controlledMode === undefined) setInternalMode(next);
    onModeChange?.(next);
  };

  useEffect(() => {
    if (liveProp !== undefined) {
      setDiscoveryDone(true);
      return;
    }
    // undefined = overview not ready yet; null/[] = ready but no projects / failed empty
    if (projects === undefined) {
      setDiscovered(null);
      setDiscoveryDone(false);
      return;
    }
    const projectList = projects ?? [];
    if (!projectList.length) {
      setDiscovered(null);
      setDiscoveryDone(true);
      return;
    }

    let cancelled = false;
    setDiscoveryDone(false);
    discoverRunningPipeline(projectList)
      .then((live) => {
        if (!cancelled) setDiscovered(live);
      })
      .catch(() => {
        if (!cancelled) setDiscovered(null);
      })
      .finally(() => {
        if (!cancelled) setDiscoveryDone(true);
      });
    return () => {
      cancelled = true;
    };
  }, [liveProp, projects]);

  const live = liveProp !== undefined ? liveProp : discovered;
  const isLive = Boolean(live && isActiveProgressStatus(live.status));
  const stages = useMemo(() => stagesForMode(mode), [mode]);

  const activeStageId = useMemo(() => {
    if (!isLive || !live) return null;
    const mapped = mapAgentToStage(live.currentAgent);
    if (!mapped) return null;
    if (mode === "fast" && !FAST_STAGE_IDS.includes(mapped)) {
      // Full-only agent while previewing fast path — don't fake highlight.
      return null;
    }
    return mapped;
  }, [isLive, live, mode]);

  const visualStates = useMemo(
    () => resolveStageStates(stages, activeStageId, isLive && Boolean(activeStageId)),
    [stages, activeStageId, isLive],
  );

  const activeStage = stages.find((s) => s.id === activeStageId) ?? null;
  const conversationHref = live?.conversationId
    ? `/workspace/conversations/${live.conversationId}`
    : null;
  const reportHref = live?.reportHref ?? null;

  return (
    <section
      className="rounded-lg border border-border/80 bg-muted/20 px-4 py-4 sm:px-5 sm:py-5"
      aria-label="Agent 分析流程"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight text-foreground">
            Agent 如何完成一次分析
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            从问题理解到证据检索，再到分析与成稿；完整尽调会进一步执行对比、洞察、策略与质量复核。
          </p>
        </div>
        <div
          className="flex shrink-0 gap-1 rounded-md border border-border/80 bg-background p-0.5"
          role="group"
          aria-label="预览分析路径"
        >
          {(
            [
              { value: "fast" as const, label: "快速洞察" },
              { value: "full" as const, label: "完整尽调" },
            ] as const
          ).map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setMode(opt.value)}
              className={`rounded px-2.5 py-1 text-xs transition-colors ${
                mode === opt.value
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              aria-pressed={mode === opt.value}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <p className="mt-3 text-xs text-muted-foreground">{MODE_BLURB[mode]}</p>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground/80">
          {isLive ? "分析进行中" : "分析流程"}
        </span>
        <span aria-hidden>·</span>
        <span>
          {isLive
            ? "高亮来自当前运行任务的真实进度"
            : discoveryDone
              ? "示意路径，非实时运行状态"
              : projects === undefined
                ? "示意路径，非实时运行状态"
                : "正在检查是否有进行中的任务…"}
        </span>
        {isLive && conversationHref ? (
          <>
            <span aria-hidden>·</span>
            <Link href={conversationHref} className="text-foreground underline-offset-2 hover:underline">
              查看会话进度
            </Link>
          </>
        ) : null}
      </div>

      {/* Desktop: horizontal flow */}
      <ol className="mt-4 hidden md:flex md:flex-wrap md:items-start md:gap-y-3">
        {stages.map((stage, index) => {
          const state = visualStates[index];
          const isActive = state === "active";
          const canLinkReport = Boolean(reportHref) && stage.id === "report";
          return (
            <li key={stage.id} className="flex min-w-0 items-start">
              <div
                className={`min-w-[7.5rem] max-w-[9.5rem] ${
                  isActive ? "rounded-md bg-foreground/[0.04] px-1.5 py-1 -mx-1.5" : ""
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <StageGlyph state={state} />
                  {canLinkReport && reportHref ? (
                    <Link
                      href={reportHref}
                      className={`text-sm font-medium underline-offset-2 hover:underline ${
                        isActive ? "text-foreground" : "text-foreground/90"
                      }`}
                    >
                      {stage.name}
                    </Link>
                  ) : (
                    <span
                      className={`text-sm font-medium ${
                        isActive ? "text-foreground" : "text-foreground/90"
                      }`}
                    >
                      {stage.name}
                    </span>
                  )}
                </div>
                <p className="mt-1 pl-6 text-[11px] leading-snug text-muted-foreground">
                  {isActive && live?.stageHint ? live.stageHint : stage.output}
                </p>
              </div>
              {index < stages.length - 1 ? (
                <span
                  className="mx-1 mt-2 shrink-0 text-xs text-border"
                  aria-hidden
                >
                  →
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>

      {/* Mobile: vertical timeline */}
      <ol className="mt-4 space-y-0 md:hidden">
        {stages.map((stage, index) => {
          const state = visualStates[index];
          const isActive = state === "active";
          const canLinkReport = Boolean(reportHref) && stage.id === "report";
          return (
            <li key={stage.id} className="flex gap-3">
              <div className="flex w-5 flex-col items-center">
                <StageGlyph state={state} />
                {index < stages.length - 1 ? (
                  <span className="my-0.5 w-px flex-1 bg-border" aria-hidden />
                ) : null}
              </div>
              <div className={`min-w-0 flex-1 ${index < stages.length - 1 ? "pb-3" : ""}`}>
                <div className="flex items-baseline gap-2">
                  <span className="text-[11px] tabular-nums text-muted-foreground">
                    {index + 1}
                  </span>
                  {canLinkReport && reportHref ? (
                    <Link
                      href={reportHref}
                      className={`text-sm font-medium underline-offset-2 hover:underline ${
                        isActive ? "text-foreground" : "text-foreground/90"
                      }`}
                    >
                      {stage.name}
                    </Link>
                  ) : (
                    <span
                      className={`text-sm font-medium ${
                        isActive ? "text-foreground" : "text-foreground/90"
                      }`}
                    >
                      {stage.name}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                  {isActive && live?.stageHint ? live.stageHint : stage.output}
                </p>
              </div>
            </li>
          );
        })}
      </ol>

      {isLive && activeStage && live?.stageHint ? (
        <p className="mt-3 text-xs text-muted-foreground">
          当前：{activeStage.name}
          {typeof live.progress === "number" ? ` · ${Math.round(live.progress)}%` : null}
        </p>
      ) : null}
    </section>
  );
}

/** Exported for unit-style checks / Story reuse. */
export const PIPELINE_STAGE_CATALOG = { FULL_STAGES, FAST_STAGE_IDS, mapAgentToStage };
