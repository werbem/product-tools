import type { ConversationMessage } from "@/types/copilot";
import { formatDateTime } from "@/lib/utils";

function understandingLabel(message: ConversationMessage): string | null {
  const meta = message.metadata || {};
  if (typeof meta.understanding_summary === "string" && meta.understanding_summary.trim()) {
    return meta.understanding_summary.trim();
  }
  const intent = meta.intent as
    | { company?: string | null; product?: string | null }
    | undefined;
  if (!intent) return null;
  const bits: string[] = [];
  if (intent.company) bits.push(String(intent.company));
  if (intent.product) bits.push(String(intent.product));
  const wf = typeof meta.workflow_type === "string" ? meta.workflow_type : "";
  if (meta.message_type === "clarification") bits.push("待补充");
  if (meta.message_type === "research_task_confirmation") bits.push("待确认");
  else if (wf === "simple_question") bits.push("简答");
  else if (wf === "information_query") bits.push("信息查询");
  else if (wf === "competitive_analysis" || wf === "deep_analysis") bits.push("竞品分析");
  else if (wf === "intelligence_collection" || wf === "research") bits.push("信息收集");
  else if (wf === "follow_up") bits.push("追问");
  return bits.length ? bits.join(" · ") : null;
}

export function ConversationMessageItem({ message }: { message: ConversationMessage }) {
  const isUser = message.role === "user";
  const isThinking = message.metadata?.message_type === "thinking";
  const showFollowUpHint =
    !isUser &&
    message.metadata?.message_type === "follow_up_answered" &&
    (message.metadata?.follow_up_mode === "short_answer" ||
      Boolean(message.metadata?.prior_task_id));
  const understanding = !isUser && !isThinking ? understandingLabel(message) : null;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
          isUser ? "bg-primary text-primary-foreground" : "bg-muted"
        } ${isThinking ? "animate-pulse text-muted-foreground" : ""}`}
        aria-live={isThinking ? "polite" : undefined}
      >
        {understanding ? (
          <div className="mb-1 text-[10px] text-muted-foreground">已理解：{understanding}</div>
        ) : null}
        {showFollowUpHint ? (
          <div className="mb-1 text-[10px] text-muted-foreground">基于上次分析追问</div>
        ) : null}
        <div>{message.content}</div>
        {!isThinking ? (
          <div className={`mt-1 text-[10px] ${isUser ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
            {formatDateTime(message.created_at)}
          </div>
        ) : null}
      </div>
    </div>
  );
}
