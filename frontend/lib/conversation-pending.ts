import type { ConversationMessage } from "@/types/copilot";

export type PendingConversationMessage = {
  content: string;
  analysis_mode: "fast" | "full";
};

/** Survives React Strict Mode remounts so the first send runs once. */
const pendingSendPromises = new Map<string, Promise<void>>();

function pendingKey(conversationId: string) {
  return `copilot-pending:${conversationId}`;
}

function inflightKey(conversationId: string) {
  return `copilot-inflight:${conversationId}`;
}

function readStored(
  conversationId: string,
  keyFn: (id: string) => string,
): PendingConversationMessage | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(keyFn(conversationId));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PendingConversationMessage;
  } catch {
    return null;
  }
}

export function peekPendingMessage(
  conversationId: string,
): PendingConversationMessage | null {
  return readStored(conversationId, pendingKey);
}

export function peekInflightMessage(
  conversationId: string,
): PendingConversationMessage | null {
  return readStored(conversationId, inflightKey);
}

/** Pending or in-flight first message — used for optimistic UI across remounts. */
export function getDisplayPendingMessage(
  conversationId: string,
): PendingConversationMessage | null {
  return peekPendingMessage(conversationId) ?? peekInflightMessage(conversationId);
}

export function stashPendingMessage(
  conversationId: string,
  payload: PendingConversationMessage,
): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(pendingKey(conversationId), JSON.stringify(payload));
}

/** Claim pending message for send; prevents duplicate sends across Strict Mode remounts. */
export function claimPendingMessage(
  conversationId: string,
): PendingConversationMessage | null {
  if (typeof window === "undefined") return null;
  if (sessionStorage.getItem(inflightKey(conversationId))) return null;
  const pending = peekPendingMessage(conversationId);
  if (!pending) return null;
  sessionStorage.removeItem(pendingKey(conversationId));
  sessionStorage.setItem(inflightKey(conversationId), JSON.stringify(pending));
  return pending;
}

export function releaseInflightSend(conversationId: string): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(inflightKey(conversationId));
}

/**
 * Send the stashed first message exactly once across remounts.
 * Concurrent callers await the same promise, then refresh UI from the server.
 */
export async function ensurePendingMessageSent(
  conversationId: string,
  sender: (pending: PendingConversationMessage) => Promise<void>,
): Promise<"sent" | "skipped"> {
  const existing = pendingSendPromises.get(conversationId);
  if (existing) {
    await existing;
    return "sent";
  }

  const pending = claimPendingMessage(conversationId);
  if (!pending) {
    return "skipped";
  }

  const promise = (async () => {
    try {
      await sender(pending);
    } finally {
      releaseInflightSend(conversationId);
      pendingSendPromises.delete(conversationId);
    }
  })();

  pendingSendPromises.set(conversationId, promise);
  await promise;
  return "sent";
}

export function optimisticUserMessage(
  conversationId: string,
  content: string,
): ConversationMessage {
  return {
    id: `optimistic-user-${conversationId}`,
    conversation_id: conversationId,
    role: "user",
    content,
    created_at: new Date().toISOString(),
    task_id: null,
    metadata: { optimistic: true },
  };
}

export function optimisticThinkingMessage(conversationId: string): ConversationMessage {
  return {
    id: `optimistic-thinking-${conversationId}`,
    conversation_id: conversationId,
    role: "assistant",
    content: "正在理解您的意图…",
    created_at: new Date().toISOString(),
    task_id: null,
    metadata: { message_type: "thinking", optimistic: true },
  };
}

export function mergeConversationMessages(
  prev: ConversationMessage[],
  incoming: ConversationMessage[],
): ConversationMessage[] {
  const withoutOptimistic = prev.filter((m) => !m.metadata?.optimistic);
  const map = new Map<string, ConversationMessage>();
  for (const message of withoutOptimistic) {
    map.set(message.id, message);
  }
  for (const message of incoming) {
    map.set(message.id, message);
  }
  return [...map.values()].sort((a, b) => a.created_at.localeCompare(b.created_at));
}
