"use client";

import { useEffect, useRef } from "react";
import type { ConversationMessage } from "@/types/copilot";
import { ConversationMessageItem } from "./conversation-message-item";
import { AnalysisStartedCard, type TaskPhaseState } from "./analysis-started-card";

export function ConversationMessageList({
  messages,
  taskPhases,
}: {
  messages: ConversationMessage[];
  taskPhases: Record<string, TaskPhaseState>;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, taskPhases]);

  return (
    <div className="space-y-4" aria-live="polite">
      {messages.map((message) => (
        <div key={message.id} className="space-y-3">
          <ConversationMessageItem message={message} />
          {message.task_id
          && message.metadata?.message_type !== "query_answered"
          && message.metadata?.message_type !== "follow_up_answered"
          && message.metadata?.message_type !== "question_answered" ? (
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
            />
          ) : null}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
