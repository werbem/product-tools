"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Conversation, ConversationMessage } from "@/types/copilot";
import { ConversationComposer } from "./conversation-composer";
import { ConversationMessageList } from "./conversation-message-list";
import { WorkspacePageHeader } from "./workspace-page-header";
import type { TaskPhaseState } from "./analysis-started-card";
import {
  getConversation,
  getTaskProgress,
  listConversationMessages,
  sendConversationMessage,
} from "@/lib/copilot-api";
import { extractApiErrorMessage } from "@/lib/copilot-errors";
import { subscribeToConversation } from "@/lib/conversation-sse";
import {
  ensurePendingMessageSent,
  getDisplayPendingMessage,
  mergeConversationMessages,
  optimisticThinkingMessage,
  optimisticUserMessage,
} from "@/lib/conversation-pending";

function phaseFromProgress(progress: {
  status: string;
  current_agent: string;
  progress: number;
  stage_hint?: string | null;
  total_elapsed_s?: number | null;
}): TaskPhaseState {
  const status = progress.status;
  const base = {
    stage_hint: progress.stage_hint ?? undefined,
    total_elapsed_s: progress.total_elapsed_s ?? undefined,
    updated_at: Date.now(),
  };
  if (status === "completed" || status === "failed") {
    return {
      phase: status,
      progress: status === "completed" ? 100 : progress.progress,
      status,
      ...base,
    };
  }
  return {
    phase: progress.current_agent || status,
    progress: progress.progress,
    status: "running",
    ...base,
  };
}

export function ConversationPageContent({ conversationId }: { conversationId: string }) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [taskPhases, setTaskPhases] = useState<Record<string, TaskPhaseState>>({});
  const [connectionHint, setConnectionHint] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const showOptimisticPair = useCallback((content: string) => {
    setMessages((prev) =>
      mergeConversationMessages(prev, [
        optimisticUserMessage(conversationId, content),
        optimisticThinkingMessage(conversationId),
      ]),
    );
  }, [conversationId]);

  const applyTurn = useCallback((turn: Awaited<ReturnType<typeof sendConversationMessage>>) => {
    setConversation(turn.conversation);
    setMessages((prev) =>
      mergeConversationMessages(prev, [turn.user_message, turn.assistant_message]),
    );
    if (turn.task_id) {
      setTaskPhases((prev) => ({
        ...prev,
        [turn.task_id!]: { phase: "", progress: 0, status: "running" },
      }));
      void getTaskProgress(turn.task_id)
        .then((progress) => {
          setTaskPhases((prev) => ({
            ...prev,
            [turn.task_id!]: phaseFromProgress(progress),
          }));
        })
        .catch(() => undefined);
    }
  }, []);

  const hydrateTaskPhases = useCallback(async (msgs: ConversationMessage[]) => {
    const taskIds = Array.from(
      new Set(msgs.map((m) => m.task_id).filter((id): id is string => Boolean(id))),
    );
    if (taskIds.length === 0) return;

    const results = await Promise.allSettled(taskIds.map((id) => getTaskProgress(id)));
    setTaskPhases((prev) => {
      const next = { ...prev };
      results.forEach((result, index) => {
        const taskId = taskIds[index];
        if (result.status === "fulfilled") {
          next[taskId] = phaseFromProgress(result.value);
        } else if (!next[taskId]) {
          next[taskId] = { phase: "", progress: 0, status: "running" };
        }
      });
      return next;
    });
  }, []);

  const refreshMessages = useCallback(async () => {
    const [conv, msgs] = await Promise.all([
      getConversation(conversationId),
      listConversationMessages(conversationId),
    ]);
    setConversation(conv);
    setMessages(msgs);
    await hydrateTaskPhases(msgs);
    return msgs;
  }, [conversationId, hydrateTaskPhases]);

  const sendMessage = useCallback(async (
    content: string,
    analysisMode: "fast" | "full",
    options?: { skipOptimistic?: boolean },
  ) => {
    if (!options?.skipOptimistic) {
      showOptimisticPair(content);
    }
    try {
      const turn = await sendConversationMessage(conversationId, {
        content,
        analysis_mode: analysisMode,
      });
      applyTurn(turn);
    } catch (err) {
      setMessages((prev) => prev.filter((m) => !m.metadata?.optimistic));
      setError(extractApiErrorMessage(err, "发送消息失败"));
      throw err;
    }
  }, [applyTurn, conversationId, showOptimisticPair]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [conv, msgs] = await Promise.all([
        getConversation(conversationId),
        listConversationMessages(conversationId),
      ]);
      setConversation(conv);
      setMessages((prev) => {
        const optimistic = prev.filter((m) => m.metadata?.optimistic);
        if (msgs.length === 0 && (optimistic.length > 0 || getDisplayPendingMessage(conversationId))) {
          return optimistic.length > 0 ? optimistic : prev;
        }
        if (optimistic.length > 0) {
          return mergeConversationMessages(optimistic, msgs);
        }
        return msgs;
      });
      if (msgs.length > 0) {
        await hydrateTaskPhases(msgs);
      }
    } catch (err) {
      setError(extractApiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [conversationId, hydrateTaskPhases]);

  // Show user message + thinking immediately while page loads / remounts.
  useEffect(() => {
    const pending = getDisplayPendingMessage(conversationId);
    if (!pending) return;
    showOptimisticPair(pending.content);
  }, [conversationId, showOptimisticPair]);

  useEffect(() => {
    void load();
  }, [load]);

  // First message from new-conversation page: navigate first, send once across remounts.
  useEffect(() => {
    if (loading) return;
    let cancelled = false;

    void (async () => {
      const hadDisplayPending = Boolean(getDisplayPendingMessage(conversationId));
      try {
        const result = await ensurePendingMessageSent(conversationId, async (pending) => {
          const turn = await sendConversationMessage(conversationId, {
            content: pending.content,
            analysis_mode: pending.analysis_mode,
          });
          if (!cancelled) {
            applyTurn(turn);
          }
        });
        if (cancelled) return;

        // Remounted mount may have missed applyTurn; always refresh from server.
        if (result === "sent" || hadDisplayPending) {
          const msgs = await refreshMessages();
          if (!cancelled && msgs.length === 0) {
            // Brief retry — JSON store is sync, but cover slow networks.
            await new Promise((r) => setTimeout(r, 300));
            if (!cancelled) {
              await refreshMessages();
            }
          }
        }
      } catch (err) {
        if (!cancelled) {
          setMessages((prev) => prev.filter((m) => !m.metadata?.optimistic));
          setError(extractApiErrorMessage(err, "发送消息失败"));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [loading, conversationId, applyTurn, refreshMessages]);

  useEffect(() => {
    const ids = Array.from(
      new Set(messages.map((m) => m.task_id).filter((id): id is string => Boolean(id))),
    );
    if (ids.length === 0) return;

    let cancelled = false;

    const tick = () => {
      void Promise.allSettled(ids.map((id) => getTaskProgress(id))).then((results) => {
        if (cancelled) return;
        setTaskPhases((prev) => {
          const next = { ...prev };
          let changed = false;
          let allDone = true;
          results.forEach((result, index) => {
            const taskId = ids[index];
            if (result.status !== "fulfilled") {
              allDone = false;
              return;
            }
            const mapped = phaseFromProgress(result.value);
            if (mapped.status !== "completed" && mapped.status !== "failed") {
              allDone = false;
            }
            const prevPhase = prev[taskId];
            if (
              !prevPhase
              || prevPhase.phase !== mapped.phase
              || prevPhase.progress !== mapped.progress
              || prevPhase.status !== mapped.status
              || prevPhase.stage_hint !== mapped.stage_hint
            ) {
              next[taskId] = mapped;
              changed = true;
            }
          });
          if (allDone && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          return changed ? next : prev;
        });
      });
    };

    tick();
    pollRef.current = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [messages]);

  useEffect(() => {
    const close = subscribeToConversation(conversationId, {
      onConnected: () => setConnectionHint(null),
      onAnalysisStarted: (event) => {
        const taskId = event.task_id;
        if (!taskId) return;
        setTaskPhases((prev) => ({
          ...prev,
          [taskId]: prev[taskId] ?? { phase: "", progress: 0, status: "running" },
        }));
      },
      onPhaseUpdate: (event) => {
        const taskId = event.task_id;
        if (!taskId) return;
        setTaskPhases((prev) => ({
          ...prev,
          [taskId]: {
            phase: String(event.data.phase ?? ""),
            progress: Number(event.data.progress ?? 0),
            status: "running",
            stage_hint: typeof event.data.stage_hint === "string" ? event.data.stage_hint : undefined,
            total_elapsed_s:
              typeof event.data.total_elapsed_s === "number"
                ? event.data.total_elapsed_s
                : undefined,
            updated_at: Date.now(),
          },
        }));
      },
      onAnalysisCompleted: (event) => {
        const taskId = event.task_id;
        if (!taskId) return;
        setTaskPhases((prev) => ({
          ...prev,
          [taskId]: { phase: "completed", progress: 100, status: "completed" },
        }));
        void load();
      },
      onAnalysisFailed: (event) => {
        const taskId = event.task_id;
        if (!taskId) return;
        setTaskPhases((prev) => ({
          ...prev,
          [taskId]: { phase: "failed", progress: 0, status: "failed" },
        }));
      },
      onError: () => {
        setConnectionHint("实时连接不稳定，已改用轮询更新进度");
      },
    });
    return close;
  }, [conversationId, load]);

  const handleSend = async (content: string, analysisMode: "fast" | "full") => {
    setError(null);
    await sendMessage(content, analysisMode);
  };

  const hasOptimistic = messages.some((m) => m.metadata?.optimistic);
  const hasDisplayPending = typeof window !== "undefined"
    && Boolean(getDisplayPendingMessage(conversationId));
  if (loading && messages.length === 0 && !hasOptimistic && !hasDisplayPending) {
    return <div className="text-sm text-muted-foreground">加载会话中…</div>;
  }
  if (error && messages.length === 0) {
    return <div className="text-sm text-destructive">{error}</div>;
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <WorkspacePageHeader title={conversation?.title || "会话"} />
      {connectionHint ? (
        <div className="text-xs text-muted-foreground">{connectionHint}</div>
      ) : null}
      {error ? <div className="text-sm text-destructive">{error}</div> : null}
      <div className="min-h-[360px] rounded-xl border bg-card p-4">
        <ConversationMessageList messages={messages} taskPhases={taskPhases} />
      </div>
      <ConversationComposer onSubmit={handleSend} />
    </div>
  );
}
