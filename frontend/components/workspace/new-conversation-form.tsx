"use client";

import { useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  ConversationComposer,
  type ConversationComposerHandle,
} from "./conversation-composer";
import { WorkspaceHowItWorks } from "./workspace-how-it-works";
import { WorkspaceIntroHero } from "./workspace-intro-hero";
import { WorkspaceUseCases } from "./workspace-use-cases";
import { createConversation, createProject } from "@/lib/copilot-api";
import { stashPendingMessage } from "@/lib/conversation-pending";
import { extractApiErrorMessage } from "@/lib/copilot-errors";
import { buildInitialProjectTitle } from "@/lib/project-title";

const COMPOSER_SECTION_ID = "workspace-input";

export function NewConversationForm() {
  const router = useRouter();
  const composerRef = useRef<ConversationComposerHandle>(null);
  const [draft, setDraft] = useState("");
  const [analysisMode, setAnalysisMode] = useState<"fast" | "full">("fast");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const scrollToInput = useCallback(() => {
    const el = document.getElementById(COMPOSER_SECTION_ID);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => composerRef.current?.focus(), 300);
  }, []);

  const fillExample = useCallback(
    (example: string) => {
      setError(null);
      setDraft(example);
      scrollToInput();
    },
    [scrollToInput],
  );

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
    <div className="mx-auto max-w-3xl space-y-10">
      <WorkspaceIntroHero onStartInput={scrollToInput} />
      <WorkspaceUseCases onSelectExample={fillExample} />
      <WorkspaceHowItWorks />
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
        placeholder="例如：为什么飞猪酒店最近增长下降？请对比美团和携程"
      />
      <p className="text-center text-xs text-muted-foreground">
        仍可使用{" "}
        <a href="/classic" className="text-primary hover:underline">
          旧版表单分析
        </a>
        （完整模式，约 12 分钟）
      </p>
    </div>
  );
}
