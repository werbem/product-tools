import type {
  Artifact,
  Conversation,
  ConversationMessage,
  ConversationTurnResponse,
  IntentUnderstandingResult,
  Project,
} from "@/types/copilot";
import { API_PREFIX, request, resolveApiUrl } from "@/lib/api";

export class CopilotClientError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CopilotClientError";
  }
}

export function resolveArtifactUrl(path: string): string {
  return resolveApiUrl(path);
}

export async function createProject(input: {
  title: string;
  objective?: string | null;
  metadata?: Record<string, unknown>;
}): Promise<Project> {
  return request<Project>(`${API_PREFIX}/projects`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listProjects(): Promise<Project[]> {
  return request<Project[]>(`${API_PREFIX}/projects`);
}

export async function getProject(projectId: string): Promise<Project> {
  return request<Project>(`${API_PREFIX}/projects/${encodeURIComponent(projectId)}`);
}

export async function archiveProject(projectId: string): Promise<Project> {
  return request<Project>(`${API_PREFIX}/projects/${encodeURIComponent(projectId)}/archive`, {
    method: "POST",
  });
}

export async function deleteProject(projectId: string): Promise<{
  project_id: string;
  deleted_conversations: number;
  deleted_tasks: number;
}> {
  return request(`${API_PREFIX}/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
  });
}

export async function createConversation(
  projectId: string,
  input?: { title?: string | null; metadata?: Record<string, unknown> },
): Promise<Conversation> {
  return request<Conversation>(
    `${API_PREFIX}/projects/${encodeURIComponent(projectId)}/conversations`,
    { method: "POST", body: JSON.stringify(input ?? {}) },
  );
}

export async function listConversations(projectId: string): Promise<Conversation[]> {
  return request<Conversation[]>(
    `${API_PREFIX}/projects/${encodeURIComponent(projectId)}/conversations`,
  );
}

export async function getConversation(conversationId: string): Promise<Conversation> {
  return request<Conversation>(
    `${API_PREFIX}/conversations/${encodeURIComponent(conversationId)}`,
  );
}

export async function listConversationMessages(
  conversationId: string,
): Promise<ConversationMessage[]> {
  return request<ConversationMessage[]>(
    `${API_PREFIX}/conversations/${encodeURIComponent(conversationId)}/messages`,
  );
}

export async function sendConversationMessage(
  conversationId: string,
  input: { content: string; analysis_mode?: "fast" | "full" },
): Promise<ConversationTurnResponse> {
  return request<ConversationTurnResponse>(
    `${API_PREFIX}/conversations/${encodeURIComponent(conversationId)}/messages`,
    {
      method: "POST",
      body: JSON.stringify({
        content: input.content,
        analysis_mode: input.analysis_mode ?? "fast",
      }),
    },
  );
}

export async function listArtifacts(filters?: {
  projectId?: string;
  conversationId?: string;
  taskId?: string;
}): Promise<Artifact[]> {
  const keys = filters
    ? [filters.projectId, filters.conversationId, filters.taskId].filter(Boolean)
    : [];
  if (keys.length > 1) {
    throw new CopilotClientError("只能指定一个过滤参数");
  }
  const params = new URLSearchParams();
  if (filters?.projectId) params.set("project_id", filters.projectId);
  if (filters?.conversationId) params.set("conversation_id", filters.conversationId);
  if (filters?.taskId) params.set("task_id", filters.taskId);
  const qs = params.toString();
  return request<Artifact[]>(`${API_PREFIX}/artifacts${qs ? `?${qs}` : ""}`);
}

export async function getArtifact(artifactId: string): Promise<Artifact> {
  return request<Artifact>(`${API_PREFIX}/artifacts/${encodeURIComponent(artifactId)}`);
}

export async function understandIntent(input: {
  message: string;
  partial?: IntentUnderstandingResult | null;
  conversation_id?: string | null;
}): Promise<IntentUnderstandingResult> {
  return request<IntentUnderstandingResult>(`${API_PREFIX}/intent/understand`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getTaskProgress(taskId: string) {
  return request<import("@/types").TaskProgressResponse>(
    `${API_PREFIX}/tasks/${encodeURIComponent(taskId)}/progress`,
  );
}

export async function getTaskCollection(taskId: string) {
  return request<import("@/types").CollectionDetailResponse>(
    `${API_PREFIX}/tasks/${encodeURIComponent(taskId)}/collection`,
  );
}
