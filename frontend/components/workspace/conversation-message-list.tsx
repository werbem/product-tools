"use client";

import { useEffect, useRef } from "react";
import type { ConversationMessage, ConversationTurnResponse } from "@/types/copilot";
import { ConversationMessageItem } from "./conversation-message-item";
import { AnalysisStartedCard, type TaskPhaseState } from "./analysis-started-card";
import { parseResearchTask, ResearchTaskConfirmCard } from "./research-task-confirm-card";

export function ConversationMessageList({
  messages,
  conversationId,
  taskPhases,
  onTaskCancelled,
  onResearchTaskConfirmed,
}: {
  messages: ConversationMessage[];
  conversationId: string;
  taskPhases: Record<string, TaskPhaseState>;
  onTaskCancelled?: (taskId: string) => void;
  onResearchTaskConfirmed?: (turn: ConversationTurnResponse) => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, taskPhases]);

  return (
    <div className="space-y-4" aria-live="polite">
      {messages.map((message) => {
        const researchTask = parseResearchTask(message.metadata?.research_task);
        const laterState = researchTask
          ? messages
              .map((item) => parseResearchTask(item.metadata?.research_task))
              .find((item) => item?.id === researchTask.id && item.status !== "pending")
          : null;
        const displayTask = laterState
          ? { ...researchTask!, status: laterState.status }
          : researchTask;
        return (
        <div key={message.id} className="space-y-3">
          <ConversationMessageItem message={message} />
          {message.metadata?.message_type === "research_task_confirmation" && displayTask ? (
            <ResearchTaskConfirmCard
              conversationId={conversationId}
              task={displayTask}
              onConfirmed={(turn) => onResearchTaskConfirmed?.(turn)}
            />
          ) : null}
          {message.task_id
          && message.metadata?.message_type !== "query_answered"
          && message.metadata?.message_type !== "follow_up_answered"
          && message.metadata?.message_type !== "question_answered"
          && message.metadata?.message_type !== "workflow_busy"
          && message.metadata?.message_type !== "research_task_confirmation" ? (
            <AnalysisStartedCard
              taskId={message.task_id}
              workflowType={
                typeof message.metadata?.workflow_type === "string"
                  ? message.metadata.workflow_type
                  : undefined
              }
              analysisMode={
                message.metadata?.analysis_mode === "full" ? "full" : "fast"
              }
              phase={taskPhases[message.task_id] ?? { phase: "", progress: 0, status: "running" }}
              onCancelled={onTaskCancelled}
            />
          ) : null}
        </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
