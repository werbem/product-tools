"use client";

import { Button } from "@/components/ui/button";

export function WorkspaceIntroHero({ onStartInput }: { onStartInput: () => void }) {
  return (
    <section className="border-b border-border/80 pb-6 sm:pb-8">
      <div className="min-w-0 max-w-2xl">
        <p className="text-sm font-semibold tracking-tight text-foreground">
          竞品情报 Agent 工作台
        </p>
        <p className="mt-1 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          Competitive Intelligence Agent Workbench
        </p>
        <h1 className="mt-4 text-xl font-semibold leading-snug tracking-tight text-foreground sm:text-2xl">
          把商业问题交给多智能体，直接产出可追溯的竞品分析。
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          面向竞品对比、公开信息收集与快速问答；结论尽量回指公开来源。
        </p>
        <div className="mt-5">
          <Button type="button" size="sm" onClick={onStartInput}>
            提出分析问题
          </Button>
        </div>
      </div>
    </section>
  );
}
