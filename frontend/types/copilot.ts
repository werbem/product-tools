export type IntentType = "competitive_analysis" | "unsupported";

export interface IntentUnderstandingResult {
  type: IntentType;
  company: string | null;
  competitors: string[];
  product: string | null;
  objective: string | null;
  confidence: number;
  missing_fields: string[];
  needs_clarification: boolean;
  clarification_question: string | null;
  raw_message: string;
}

export interface Project {
  id: string;
  title: string;
  objective: string | null;
  status: "active" | "archived";
  analysis_status?: "idle" | "running" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface Conversation {
  id: string;
  project_id: string;
  title: string | null;
  status: "active" | "completed" | "archived";
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  task_id: string | null;
  metadata: Record<string, unknown>;
}

export type TurnStatus =
  | "needs_clarification"
  | "unsupported"
  | "analysis_started"
  | "out_of_scope"
  | "unsupported_workflow"
  | "query_answered"
  | "follow_up_answered"
  | "question_answered";

export interface RoutingDecision {
  workflow_type:
    | "competitive_analysis"
    | "research"
    | "information_query"
    | "simple_question"
    | "follow_up"
    | "out_of_scope";
  confidence: number;
  reason: string;
  legacy_workflow_kind?: "deep_analysis" | "intelligence_collection" | null;
}

export interface ConversationTurnResponse {
  conversation: Conversation;
  user_message: ConversationMessage;
  assistant_message: ConversationMessage;
  intent: IntentUnderstandingResult;
  status: TurnStatus;
  task_id: string | null;
  report_id: string | null;
  routing_decision?: RoutingDecision | null;
}

export interface Artifact {
  id: string;
  type: string;
  title: string;
  project_id: string;
  conversation_id: string | null;
  task_id: string;
  report_id: string | null;
  url: string;
  download_url: string | null;
  version: number;
  created_at: string;
  metadata: Record<string, unknown>;
}

export type ConversationEventType =
  | "connected"
  | "analysis_started"
  | "phase_update"
  | "artifact_created"
  | "analysis_completed"
  | "analysis_failed"
  | "heartbeat";

export interface ConversationEvent {
  event: ConversationEventType;
  conversation_id: string;
  task_id: string | null;
  timestamp: string;
  data: Record<string, unknown>;
}
