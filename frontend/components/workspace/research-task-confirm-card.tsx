"use client";

import { useMemo, useState } from "react";
import type { ConversationTurnResponse, ResearchFieldSource, ResearchTask } from "@/types/copilot";
import { confirmResearchTask } from "@/lib/copilot-api";
import { extractApiErrorMessage } from "@/lib/copilot-errors";
import { Button } from "@/components/ui/button";

const SOURCE_LABEL: Record<ResearchFieldSource, string> = {
  user_input: "用户输入",
  system_inferred: "系统推荐",
  system_default: "系统默认",
  unresolved: "待补充",
};

function sourceHint(source: ResearchFieldSource | undefined): string | null {
  if (!source || source === "user_input") return null;
  return SOURCE_LABEL[source];
}

export function parseResearchTask(raw: unknown): ResearchTask | null {
  if (!raw || typeof raw !== "object") return null;
  const data = raw as Partial<ResearchTask>;
  if (typeof data.id !== "string" || !data.id) return null;
  if (data.status !== "pending" && data.status !== "confirmed" && data.status !== "cancelled") {
    return null;
  }
  return data as ResearchTask;
}

export function ResearchTaskConfirmCard({
  conversationId,
  task,
  onConfirmed,
}: {
  conversationId: string;
  task: ResearchTask;
  onConfirmed: (turn: ConversationTurnResponse) => void;
}) {
  const locked = task.status !== "pending";
  const [editing, setEditing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collectionTargets, setCollectionTargets] = useState(task.collection_targets?.value || "");
  const [collectionTopics, setCollectionTopics] = useState(task.collection_topics?.value || "");
  const [researchScope, setResearchScope] = useState(task.research_scope?.value || "");
  const [analysisSubject, setAnalysisSubject] = useState(task.analysis_subject?.value || "");
  const [competitorsText, setCompetitorsText] = useState(
    (task.competitors || []).map((item) => item.value).join("、"),
  );
  const [analysisProduct, setAnalysisProduct] = useState(task.analysis_product?.value || "");
  const [analysisGoal, setAnalysisGoal] = useState(task.analysis_goal?.value || "");

  const competitorChips = useMemo(
    () => task.competitors || [],
    [task.competitors],
  );

  const handleConfirm = async () => {
    if (submitting || locked) return;
    setSubmitting(true);
    setError(null);
    try {
      const competitors = competitorsText
        .split(/[、,，]/)
        .map((item) => item.trim())
        .filter(Boolean);
      const turn = await confirmResearchTask(conversationId, task.id, {
        collection_targets: collectionTargets.trim() || null,
        collection_topics: collectionTopics.trim() || null,
        research_scope: researchScope.trim() || null,
        analysis_subject: analysisSubject.trim() || null,
        competitors,
        analysis_product: analysisProduct.trim() || null,
        analysis_goal: analysisGoal.trim() || null,
        analysis_mode: task.analysis_mode,
      });
      onConfirmed(turn);
    } catch (err) {
      setError(extractApiErrorMessage(err, "确认失败，请稍后重试"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ml-1 rounded-xl border bg-background p-4 text-sm shadow-sm">
      <div className="font-medium">请确认研究任务</div>
      <p className="mt-1 text-xs text-muted-foreground">
        确认后才会启动
        {task.routed_workflow === "intelligence_collection" ? "信息收集" : "竞品分析"}
        ，在此之前不会产生检索或深度研究调用。
      </p>

      <div className="mt-4 space-y-3">
        <section>
          <h3 className="text-xs font-semibold text-foreground">信息采集任务</h3>
          <FieldRow
            label="采集对象"
            value={collectionTargets}
            source={task.collection_targets?.source}
            editing={editing}
            onChange={setCollectionTargets}
          />
          <FieldRow
            label="采集主题"
            value={collectionTopics}
            source={task.collection_topics?.source}
            editing={editing}
            onChange={setCollectionTopics}
            multiline
          />
          <FieldRow
            label="研究范围"
            value={researchScope}
            source={task.research_scope?.source}
            editing={editing}
            onChange={setResearchScope}
          />
        </section>
        <section>
          <h3 className="text-xs font-semibold text-foreground">竞品分析任务</h3>
          <FieldRow
            label="分析对象"
            value={analysisSubject}
            source={task.analysis_subject?.source}
            editing={editing}
            onChange={setAnalysisSubject}
          />
          {editing ? (
            <FieldRow
              label="竞品对象"
              value={competitorsText}
              source="user_input"
              editing
              onChange={setCompetitorsText}
            />
          ) : (
            <div className="mt-2">
              <div className="text-[11px] text-muted-foreground">竞品对象</div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {competitorChips.length ? (
                  competitorChips.map((item) => (
                    <span
                      key={`${item.value}-${item.source}`}
                      className="rounded-md border border-border/80 bg-muted/40 px-2 py-0.5 text-xs"
                    >
                      {item.value}
                      {sourceHint(item.source) ? (
                        <span className="ml-1 text-[10px] text-muted-foreground">
                          {sourceHint(item.source)}
                        </span>
                      ) : null}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-muted-foreground">未指定</span>
                )}
              </div>
            </div>
          )}
          <FieldRow
            label="分析产品"
            value={analysisProduct}
            source={task.analysis_product?.source}
            editing={editing}
            onChange={setAnalysisProduct}
          />
          <FieldRow
            label="分析目标"
            value={analysisGoal}
            source={task.analysis_goal?.source}
            editing={editing}
            onChange={setAnalysisGoal}
            multiline
          />
        </section>
      </div>

      {error ? <p className="mt-3 text-xs text-destructive">{error}</p> : null}

      {locked ? (
        <p className="mt-3 text-xs text-muted-foreground">
          {task.status === "confirmed" ? "任务已确认并启动。" : "该确认单已失效。"}
        </p>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={submitting}
            onClick={() => setEditing((value) => !value)}
          >
            {editing ? "完成修改" : "修改任务"}
          </Button>
          <Button type="button" size="sm" disabled={submitting} onClick={() => void handleConfirm()}>
            {submitting ? "启动中…" : "确认并开始"}
          </Button>
        </div>
      )}
    </div>
  );
}

function FieldRow({
  label,
  value,
  source,
  editing,
  onChange,
  multiline = false,
}: {
  label: string;
  value: string;
  source?: ResearchFieldSource;
  editing: boolean;
  onChange: (value: string) => void;
  multiline?: boolean;
}) {
  const hint = sourceHint(source);
  return (
    <div className="mt-2">
      <div className="text-[11px] text-muted-foreground">
        {label}
        {hint ? <span className="ml-1">（{hint}）</span> : null}
      </div>
      {editing ? (
        multiline ? (
          <textarea
            value={value}
            onChange={(event) => onChange(event.target.value)}
            rows={3}
            className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1.5 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        ) : (
          <input
            value={value}
            onChange={(event) => onChange(event.target.value)}
            className="mt-1 w-full rounded-md border border-border/60 bg-background px-2 py-1.5 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        )
      ) : (
        <div className="mt-0.5 text-sm text-foreground">{value || "未指定"}</div>
      )}
    </div>
  );
}
