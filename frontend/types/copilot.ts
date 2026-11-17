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
  | "awaiting_confirmation"
  | "out_of_scope"
  | "unsupported_workflow"
  | "query_answered"
  | "follow_up_answered"
  | "question_answered"
  | "workflow_busy";

export type ResearchFieldSource =
  | "user_input"
  | "system_inferred"
  | "system_default"
  | "unresolved";

export interface SourcedText {
  value: string | null;
  source: ResearchFieldSource;
}

export interface SourcedItem {
  value: string;
  source: ResearchFieldSource;
}

export interface ResearchTask {
  id: string;
  status: "pending" | "confirmed" | "cancelled";
  conversation_id: string;
  project_id: string;
  analysis_mode: "fast" | "full";
  routed_workflow: "deep_analysis" | "intelligence_collection";
  raw_message: string;
  collection_targets: SourcedText;
  collection_topics: SourcedText;
  research_scope: SourcedText;
  analysis_subject: SourcedText;
  competitors: SourcedItem[];
  analysis_product: SourcedText;
  analysis_goal: SourcedText;
  launched_task_id?: string | null;
  launched_report_id?: string | null;
}

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

/** GET /api/projects/{id}/memory — Project Memory (not Evidence). */
export interface ProjectMemoryEntities {
  our_company: string | null;
  competitors: string[];
  product: string | null;
  industry: string | null;
}

export interface MemoryFinding {
  text: string;
  source_task_id: string | null;
  source_type: "report" | "collection" | "manual";
  updated_at: string;
}

export interface ProjectMemory {
  project_id: string;
  entities: ProjectMemoryEntities;
  last_objectives: string[];
  key_findings: MemoryFinding[];
  open_questions: string[];
  last_report_id: string | null;
  last_collection_id: string | null;
  last_task_id: string | null;
  last_workflow_type: string | null;
  conversation_summaries: Record<string, unknown>;
  schema_version: number;
  updated_at: string;
}

/** GET /api/projects/{id}/knowledge/notes */
export interface KnowledgeNote {
  id: string;
  project_id: string;
  title: string;
  body: string;
  tags: string[];
  created_at: string;
  updated_at: string;
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
