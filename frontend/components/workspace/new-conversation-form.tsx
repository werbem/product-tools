"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ConversationComposer,
  type ConversationComposerHandle,
} from "./conversation-composer";
import { WorkspaceAgentPipeline } from "./workspace-agent-pipeline";
import { WorkspaceIntroHero } from "./workspace-intro-hero";
import { WorkspaceMemoryGlance } from "./workspace-memory-glance";
import { WorkspaceTrustStrip } from "./workspace-trust-strip";
import { createConversation, createProject, listArtifacts, listProjects } from "@/lib/copilot-api";
import { stashPendingMessage } from "@/lib/conversation-pending";
import { extractApiErrorMessage } from "@/lib/copilot-errors";
import { buildInitialProjectTitle } from "@/lib/project-title";
import type { Artifact, Project } from "@/types/copilot";

const COMPOSER_SECTION_ID = "workspace-input";

type HomeOverview = {
  projects: Project[];
  artifacts: Artifact[];
};

export function NewConversationForm() {
  const router = useRouter();
  const composerRef = useRef<ConversationComposerHandle>(null);
  const [draft, setDraft] = useState("");
  const [analysisMode, setAnalysisMode] = useState<"fast" | "full">("fast");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  /** Shared once for Pipeline / Trust / Memory — single listProjects + listArtifacts. */
  const [overview, setOverview] = useState<HomeOverview | null>(null);
  const [overviewReady, setOverviewReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listProjects(), listArtifacts()])
      .then(([projects, artifacts]) => {
        if (cancelled) return;
        setOverview({ projects, artifacts });
      })
      .catch(() => {
        if (cancelled) return;
        setOverview(null);
      })
      .finally(() => {
        if (!cancelled) setOverviewReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const scrollToInput = useCallback(() => {
    const el = document.getElementById(COMPOSER_SECTION_ID);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => composerRef.current?.focus(), 300);
  }, []);

  const startConversation = async (content: string, mode: "fast" | "full") => {
    setLoading(true);
    setError(null);
    try {
      const project = await createProject({
        title: buildInitialProjectTitle(content),
        objective: "product_improvement",
      });
      const conversation = await createConversation(project.id);
      stashPendingMessage(conversation.id, { content, analysis_mode: mode });
      router.push(`/workspace/conversations/${conversation.id}`);
    } catch (err) {
      setError(extractApiErrorMessage(err, "创建对话失败，请确认后端已启动并包含 Copilot API"));
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 sm:space-y-7">
      {/* Final IA: Hero → Pipeline → Trust → Composer → Memory（最近分析 / 常见任务已隐藏） */}
      <WorkspaceIntroHero onStartInput={scrollToInput} />

      <WorkspaceAgentPipeline
        projects={overviewReady ? (overview?.projects ?? []) : undefined}
      />

      {overviewReady ? (
        <WorkspaceTrustStrip artifacts={overview?.artifacts ?? []} overviewFailed={!overview} />
      ) : (
        <p className="text-xs text-muted-foreground">正在加载工作台概览…</p>
      )}

      {error ? <div className="text-sm text-destructive">{error}</div> : null}

      <ConversationComposer
        ref={composerRef}
        sectionId={COMPOSER_SECTION_ID}
        value={draft}
        onValueChange={setDraft}
        analysisMode={analysisMode}
        onAnalysisModeChange={setAnalysisMode}
        onSubmit={startConversation}
        disabled={loading}
      />
      {loading ? (
        <p className="text-center text-xs text-muted-foreground animate-pulse">
          正在创建会话并识别意图…
        </p>
      ) : null}

      {overviewReady && overview ? (
        <WorkspaceMemoryGlance
          projects={overview.projects}
          artifacts={overview.artifacts}
          overviewFailed={false}
        />
      ) : null}

      <p className="text-center text-[11px] text-muted-foreground">
        兼容入口：{" "}
        <a href="/classic" className="hover:underline">
          旧版表单分析
        </a>
      </p>
    </div>
  );
}
