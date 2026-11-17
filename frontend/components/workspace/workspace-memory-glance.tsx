"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getProjectMemory, listKnowledgeNotes } from "@/lib/copilot-api";
import type { Artifact, Project, ProjectMemory } from "@/types/copilot";

const FINDING_PREVIEW_CHARS = 96;
const MAX_FINDINGS_SHOWN = 2;

/** True when Memory has any user-meaningful project context (not an empty skeleton). */
export function isNonEmptyProjectMemory(memory: ProjectMemory | null | undefined): boolean {
  if (!memory) return false;
  const ents = memory.entities;
  if (ents?.our_company?.trim()) return true;
  if ((ents?.competitors || []).some((c) => c.trim())) return true;
  if (ents?.product?.trim()) return true;
  if ((memory.key_findings || []).some((f) => (f.text || "").trim())) return true;
  if ((memory.open_questions || []).some((q) => q.trim())) return true;
  if (memory.last_task_id || memory.last_report_id || memory.last_collection_id) return true;
  return false;
}

/**
 * Pick one recent meaningful project from shared overview data.
 * Prefer projects with artifacts or non-idle analysis; then newest updated_at.
 */
export function pickMemoryGlanceProject(
  projects: Project[],
  artifacts: Artifact[],
): Project | null {
  if (!projects.length) return null;
  const artifactProjectIds = new Set(artifacts.map((a) => a.project_id).filter(Boolean));

  const ranked = [...projects].sort((a, b) => {
    const score = (p: Project) => {
      let s = 0;
      if (artifactProjectIds.has(p.id)) s += 2;
      const status = p.analysis_status || "idle";
      if (status === "completed" || status === "running" || status === "failed") s += 1;
      return s;
    };
    const diff = score(b) - score(a);
    if (diff !== 0) return diff;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });

  const preferred = ranked.find((p) => {
    const status = p.analysis_status || "idle";
    return artifactProjectIds.has(p.id) || status !== "idle";
  });
  return preferred ?? ranked[0] ?? null;
}

function entityChips(memory: ProjectMemory): string[] {
  const ents = memory.entities;
  const chips: string[] = [];
  if (ents.our_company?.trim()) chips.push(ents.our_company.trim());
  for (const c of ents.competitors || []) {
    const name = c.trim();
    if (name && !chips.includes(name)) chips.push(name);
  }
  if (ents.product?.trim()) chips.push(ents.product.trim());
  return chips;
}

function truncateFinding(text: string): string {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (cleaned.length <= FINDING_PREVIEW_CHARS) return cleaned;
  return `${cleaned.slice(0, FINDING_PREVIEW_CHARS - 1).trimEnd()}…`;
}

export function WorkspaceMemoryGlance({
  projects,
  artifacts,
  overviewFailed = false,
}: {
  projects: Project[];
  artifacts: Artifact[];
  overviewFailed?: boolean;
}) {
  const [visible, setVisible] = useState(false);
  const [memory, setMemory] = useState<ProjectMemory | null>(null);
  const [hasNotes, setHasNotes] = useState(false);
  const [projectId, setProjectId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    if (overviewFailed) {
      setVisible(false);
      setMemory(null);
      setHasNotes(false);
      setProjectId(null);
      return;
    }

    const project = pickMemoryGlanceProject(projects, artifacts);
    if (!project) {
      setVisible(false);
      setMemory(null);
      setHasNotes(false);
      setProjectId(null);
      return;
    }

    setProjectId(project.id);

    const run = async () => {
      try {
        const [nextMemory, notes] = await Promise.all([
          getProjectMemory(project.id),
          listKnowledgeNotes(project.id).catch(() => []),
        ]);
        if (cancelled) return;
        if (!isNonEmptyProjectMemory(nextMemory)) {
          setVisible(false);
          setMemory(null);
          setHasNotes(false);
          return;
        }
        setMemory(nextMemory);
        setHasNotes(Array.isArray(notes) && notes.length > 0);
        setVisible(true);
      } catch {
        if (cancelled) return;
        // Fail soft: hide module; do not disturb the rest of the homepage.
        setVisible(false);
        setMemory(null);
        setHasNotes(false);
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [projects, artifacts, overviewFailed]);

  if (!visible || !memory || !projectId) return null;

  const chips = entityChips(memory);
  const findings = (memory.key_findings || [])
    .map((f) => (f.text || "").trim())
    .filter(Boolean);
  const findingCount = findings.length;
  const previewFindings = findings.slice(0, MAX_FINDINGS_SHOWN).map(truncateFinding);
  const href = `/workspace/projects`;

  return (
    <section
      className="rounded-md border border-border/70 bg-muted/15 px-3 py-3 sm:px-4"
      aria-label="项目记忆"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0 space-y-2.5">
          <div>
            <h2 className="text-sm font-semibold tracking-tight text-foreground">项目记忆</h2>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              同一项目的后续追问，会参考已经沉淀的背景与关键结论。
            </p>
          </div>

          {chips.length > 0 ? (
            <div className="flex flex-wrap gap-1.5" aria-label="分析对象">
              {chips.map((chip) => (
                <span
                  key={chip}
                  className="rounded border border-border/80 bg-background px-2 py-0.5 text-xs text-foreground/90"
                >
                  {chip}
                </span>
              ))}
            </div>
          ) : null}

          {findingCount > 0 ? (
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground">已沉淀 {findingCount} 条关键结论</p>
              <ul className="space-y-1">
                {previewFindings.map((text) => (
                  <li key={text} className="flex gap-1.5 text-xs leading-relaxed text-foreground/85">
                    <span className="shrink-0 text-muted-foreground" aria-hidden>
                      •
                    </span>
                    <span className="min-w-0 break-words">{text}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {hasNotes ? (
            <p className="text-[11px] text-muted-foreground">内部笔记可被后续分析引用</p>
          ) : (
            <p className="text-[11px] text-muted-foreground">
              项目记忆是此前分析沉淀的上下文，不是公开 Evidence。
            </p>
          )}
        </div>

        <Link
          href={href}
          className="shrink-0 self-start text-xs font-medium text-foreground underline-offset-2 hover:underline sm:mt-0.5"
        >
          在分析目录中继续 →
        </Link>
      </div>
    </section>
  );
}
