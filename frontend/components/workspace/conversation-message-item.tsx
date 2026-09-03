import type { ConversationMessage } from "@/types/copilot";
import { formatDateTime } from "@/lib/utils";

export function ConversationMessageItem({ message }: { message: ConversationMessage }) {
  const isUser = message.role === "user";
  const showFollowUpHint =
    !isUser &&
    message.metadata?.message_type === "follow_up_answered" &&
    (message.metadata?.follow_up_mode === "short_answer" ||
      Boolean(message.metadata?.prior_task_id));

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
          isUser ? "bg-primary text-primary-foreground" : "bg-muted"
        } ${message.metadata?.message_type === "thinking" ? "animate-pulse" : ""}`}
      >
        {showFollowUpHint ? (
          <div className="mb-1 text-[10px] text-muted-foreground">基于上次分析追问</div>
        ) : null}
        <div>{message.content}</div>
        <div className={`mt-1 text-[10px] ${isUser ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
          {formatDateTime(message.created_at)}
        </div>
      </div>
    </div>
  );
}
