import type { ConversationEvent, ConversationEventType } from "@/types/copilot";
import { API_PREFIX } from "@/lib/api";

export interface ConversationSSEHandlers {
  onConnected?: (event: ConversationEvent) => void;
  onAnalysisStarted?: (event: ConversationEvent) => void;
  onPhaseUpdate?: (event: ConversationEvent) => void;
  onArtifactCreated?: (event: ConversationEvent) => void;
  onAnalysisCompleted?: (event: ConversationEvent) => void;
  onAnalysisFailed?: (event: ConversationEvent) => void;
  onHeartbeat?: (event: ConversationEvent) => void;
  onError?: (error: unknown) => void;
}

const EVENT_TYPES: ConversationEventType[] = [
  "connected",
  "analysis_started",
  "phase_update",
  "artifact_created",
  "analysis_completed",
  "analysis_failed",
  "heartbeat",
];

export function parseConversationEvent(raw: unknown): ConversationEvent | null {
  if (!raw || typeof raw !== "object") return null;
  const data = raw as Record<string, unknown>;
  if (typeof data.event !== "string" || !EVENT_TYPES.includes(data.event as ConversationEventType)) {
    return null;
  }
  if (typeof data.conversation_id !== "string" || typeof data.timestamp !== "string") {
    return null;
  }
  return {
    event: data.event as ConversationEventType,
    conversation_id: data.conversation_id,
    task_id: typeof data.task_id === "string" ? data.task_id : null,
    timestamp: data.timestamp,
    data: (data.data as Record<string, unknown>) ?? {},
  };
}

export function subscribeToConversation(
  conversationId: string,
  handlers: ConversationSSEHandlers,
): () => void {
  const url = `${API_PREFIX}/conversations/${encodeURIComponent(conversationId)}/stream`;
  const es = new EventSource(url);

  const dispatch = (eventName: string, e: MessageEvent) => {
    try {
      const parsed = parseConversationEvent(JSON.parse(e.data));
      if (!parsed) {
        handlers.onError?.(new Error(`Invalid SSE payload for ${eventName}`));
        return;
      }
      switch (parsed.event) {
        case "connected":
          handlers.onConnected?.(parsed);
          break;
        case "analysis_started":
          handlers.onAnalysisStarted?.(parsed);
          break;
        case "phase_update":
          handlers.onPhaseUpdate?.(parsed);
          break;
        case "artifact_created":
          handlers.onArtifactCreated?.(parsed);
          break;
        case "analysis_completed":
          handlers.onAnalysisCompleted?.(parsed);
          break;
        case "analysis_failed":
          handlers.onAnalysisFailed?.(parsed);
          break;
        case "heartbeat":
          handlers.onHeartbeat?.(parsed);
          break;
      }
    } catch (err) {
      handlers.onError?.(err);
    }
  };

  for (const eventName of EVENT_TYPES) {
    es.addEventListener(eventName, (e) => dispatch(eventName, e as MessageEvent));
  }

  es.onerror = (err) => handlers.onError?.(err);

  return () => es.close();
}
