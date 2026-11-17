"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  getTaskProgress,
  listConversationMessages,
  listConversations,
} from "@/lib/copilot-api";
import type { Artifact, Project } from "@/types/copilot";

type RunStatus = "running" | "completed" | "failed" | "idle";

type RecentRunItem = {
  projectId: string;
  title: string;
  status: RunStatus;
  updatedAt: string;
  taskId: string | null;
  conversationId: string | null;
  artifactType: string | null;
  artifactTitle: string | null;
  primaryHref: string | null;
  primaryLabel: string | null;
  stageLabel: string | null;
  progressPct: number | null;
  stageHint: string | null;
};

const STATUS_RANK: Record<RunStatus, number> = {
  running: 0,
  completed: 1,
  failed: 2,
  idle: 3,
};

const STATUS_LABEL: Record<RunStatus, string> = {
  running: "进行中",
  completed: "已完成",
  failed: "失败",
  idle: "未开始",
};

/** Business labels for progress current_agent — no engineering node names. */
function agentToBusinessLabel(agent: string | null | undefined): string | null {
  const key = (agent || "").trim().toLowerCase();
  if (!key) return null;
  if (key === "gate" || key === "validated" || key === "initialized") return "确认分析对象";
  if (key === "planner" || key === "planned" || key === "plan") return "调研计划";
  if (
    key === "research"
    || key === "researched"
    || key === "researching"
    || key === "collection_processed"
  ) {
    return "检索证据";
  }
  if (key === "compare" || key === "compared") return "对比差异";
  if (key === "insight" || key === "insighting") return "关键洞察";
  if (key === "strategy" || key === "strategizing" || key === "strategized") return "策略建议";
  if (key === "report" || key === "reported" || key === "reporting") return "生成报告";
  if (key === "review" || key === "reviewed" || key === "reviewing") return "质量复核";
  return null;
}

function normalizeStatus(value: Project["analysis_status"]): RunStatus {
  if (value === "running" || value === "completed" || value === "failed") return value;
  return "idle";
}

function pickArtifactForProject(artifacts: Artifact[], projectId: string): Artifact | null {
  const matched = artifacts
    .filter((a) => a.project_id === projectId)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  return matched[0] ?? null;
}

function artifactHref(artifact: Artifact): { href: string; label: string; kindLabel: string } {
  const viewUrl =
    typeof artifact.metadata?.view_url === "string" ? artifact.metadata.view_url : null;
  if (artifact.type === "evidence_package") {
    return {
      href: viewUrl || `/workspace/collections/${artifact.task_id}`,
      label: "查看收集结果",
      kindLabel: "信息收集结果",
    };
  }
  return {
    href: viewUrl || `/report/${artifact.task_id || artifact.report_id}`,
    label: "查看报告",
    kindLabel: artifact.title || "竞品分析报告",
  };
}

function sortProjects(projects: Project[]): Project[] {
  return [...projects].sort((a, b) => {
    const sa = normalizeStatus(a.analysis_status);
    const sb = normalizeStatus(b.analysis_status);
    if (STATUS_RANK[sa] !== STATUS_RANK[sb]) return STATUS_RANK[sa] - STATUS_RANK[sb];
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });
}

async function resolveLatestConversation(projectId: string): Promise<{
  conversationId: string | null;
  taskId: string | null;
}> {
  const conversations = await listConversations(projectId);
  const latest = conversations[0];
  if (!latest) return { conversationId: null, taskId: null };
  const messages = await listConversationMessages(latest.id);
  const withTask = [...messages].reverse().find((m) => m.task_id);
  return { conversationId: latest.id, taskId: withTask?.task_id ?? null };
}

export function selectRecentProjects(
  projects: Project[],
  artifacts: Artifact[],
  limit = 3,
): Project[] {
  const sorted = sortProjects(projects);
  const selected: Project[] = [];
  for (const project of sorted) {
    const status = normalizeStatus(project.analysis_status);
    const hasArtifact = artifacts.some((a) => a.project_id === project.id);
    // Idle with no deliverable should not clutter the home feed.
    if (status === "idle" && !hasArtifact) continue;
    selected.push(project);
    if (selected.length >= limit) break;
  }
  return selected;
}

async function buildRecentRuns(
  projects: Project[],
  artifacts: Artifact[],
): Promise<RecentRunItem[]> {
  const selected = selectRecentProjects(projects, artifacts, 3);
  const items: RecentRunItem[] = [];

  for (const project of selected) {
    const status = normalizeStatus(project.analysis_status);
    const artifact = pickArtifactForProject(artifacts, project.id);
    let conversationId: string | null = artifact?.conversation_id ?? null;
    let taskId: string | null = artifact?.task_id ?? null;
    let stageLabel: string | null = null;
    let progressPct: number | null = null;
    let stageHint: string | null = null;
    let primaryHref: string | null = null;
    let primaryLabel: string | null = null;
    let artifactTitle: string | null = null;
    let artifactType: string | null = artifact?.type ?? null;

    if (status === "completed" && artifact) {
      const link = artifactHref(artifact);
      primaryHref = link.href;
      primaryLabel = link.label;
      artifactTitle = link.kindLabel;
      if (!conversationId) conversationId = artifact.conversation_id;
    } else if (status === "failed") {
      artifactTitle = "本次分析未完成";
      primaryLabel = "进入会话";
      if (!conversationId || !taskId) {
        try {
          const resolved = await resolveLatestConversation(project.id);
          conversationId = conversationId || resolved.conversationId;
          taskId = taskId || resolved.taskId;
        } catch {
          // keep nulls
        }
      }
      primaryHref = conversationId ? `/workspace/conversations/${conversationId}` : null;
    } else if (status === "running") {
      artifactTitle = "正在执行分析任务";
      primaryLabel = "进入会话";
      try {
        const resolved = await resolveLatestConversation(project.id);
        conversationId = conversationId || resolved.conversationId;
        taskId = taskId || resolved.taskId;
      } catch {
        // keep nulls
      }
      primaryHref = conversationId ? `/workspace/conversations/${conversationId}` : null;

      // Only request progress when we have a real task_id (avoid N+1 on history).
      if (taskId) {
        try {
          const progress = await getTaskProgress(taskId);
          if (progress.status === "running" || (progress.status && !["completed", "failed"].includes(progress.status))) {
            stageLabel = agentToBusinessLabel(progress.current_agent);
            stageHint = progress.stage_hint ?? null;
            if (typeof progress.progress === "number" && Number.isFinite(progress.progress)) {
              progressPct = Math.round(Math.min(100, Math.max(0, progress.progress)));
            }
          }
        } catch {
          // stay without progress details
        }
      }
    } else if (artifact) {
      // idle but has artifact — rare; treat as completed deliverable
      const link = artifactHref(artifact);
      primaryHref = link.href;
      primaryLabel = link.label;
      artifactTitle = link.kindLabel;
    } else {
      continue;
    }

    items.push({
      projectId: project.id,
      title: project.title,
      status: status === "idle" && artifact ? "completed" : status,
      updatedAt: project.updated_at,
      taskId,
      conversationId,
      artifactType,
      artifactTitle,
      primaryHref,
      primaryLabel,
      stageLabel,
      progressPct,
      stageHint,
    });
  }

  return items;
}

function RunDetailLine({ item }: { item: RecentRunItem }) {
  if (item.status === "running") {
    if (item.stageLabel) {
      const line =
        item.progressPct != null ? `${item.stageLabel} · ${item.progressPct}%` : item.stageLabel;
      return <span className="text-xs text-muted-foreground">{line}</span>;
    }
    if (item.stageHint) {
      return <span className="text-xs text-muted-foreground">{item.stageHint}</span>;
    }
    return (
      <span className="text-xs text-muted-foreground">
        {item.artifactTitle || "正在执行分析任务"}
      </span>
    );
  }
  if (item.status === "failed") {
    return <span className="text-xs text-muted-foreground">本次分析未完成</span>;
  }
  return (
    <span className="text-xs text-muted-foreground">
      {item.artifactTitle || (item.artifactType === "evidence_package" ? "信息收集结果" : "竞品分析报告")}
    </span>
  );
}

export function WorkspaceRecentRuns({
  projects,
  artifacts,
  overviewFailed = false,
  onStartInput,
}: {
  projects: Project[];
  artifacts: Artifact[];
  overviewFailed?: boolean;
  onStartInput: () => void;
}) {
  const [items, setItems] = useState<RecentRunItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      setLoading(true);
      setFailed(false);
      if (overviewFailed) {
        setItems([]);
        setFailed(true);
        setLoading(false);
        return;
      }
      try {
        const next = await buildRecentRuns(projects, artifacts);
        if (!cancelled) setItems(next);
      } catch {
        if (!cancelled) {
          setItems([]);
          setFailed(true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [projects, artifacts, overviewFailed]);

  return (
    <section className="space-y-3" aria-label="最近分析">
      <div>
        <h2 className="text-sm font-semibold tracking-tight text-foreground">最近分析</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          查看进行中的任务，以及已经生成的报告和收集结果。
        </p>
      </div>

      {loading ? (
        <p className="text-xs text-muted-foreground">正在加载最近任务…</p>
      ) : failed ? (
        <p className="text-xs text-muted-foreground">暂时无法读取最近分析，请稍后再试。</p>
      ) : items.length === 0 ? (
        <div className="flex flex-col gap-2 border-t border-border/60 pt-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            还没有分析任务。提交一个商业问题，让 Agent 开始第一次分析。
          </p>
          <Button type="button" size="sm" variant="outline" onClick={onStartInput}>
            提出分析问题
          </Button>
        </div>
      ) : (
        <ul className="divide-y divide-border/70 border-y border-border/70">
          {items.map((item) => (
            <li
              key={item.projectId}
              className="flex flex-col gap-1 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="text-[11px] font-medium text-muted-foreground">
                    {STATUS_LABEL[item.status]}
                  </span>
                  <span className="truncate text-sm text-foreground">{item.title}</span>
                </div>
                <div className="mt-0.5">
                  <RunDetailLine item={item} />
                </div>
              </div>
              {item.primaryHref && item.primaryLabel ? (
                <Link
                  href={item.primaryHref}
                  className="shrink-0 text-xs font-medium text-foreground underline-offset-2 hover:underline"
                >
                  {item.primaryLabel} →
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {items.length > 0 ? (
        <p className="text-[11px] text-muted-foreground">
          完整列表见{" "}
          <Link href="/workspace/projects" className="underline-offset-2 hover:underline">
            分析目录
          </Link>
          。
        </p>
      ) : null}
    </section>
  );
}
