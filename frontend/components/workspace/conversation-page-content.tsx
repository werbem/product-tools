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
  ensureThinkingWhilePending,
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
    setError(null);
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

  const handleTaskCancelled = useCallback((taskId: string) => {
    setTaskPhases((prev) => ({
      ...prev,
      [taskId]: {
        phase: "failed",
        progress: prev[taskId]?.progress ?? 0,
        status: "failed",
        stage_hint: "任务已终止",
        updated_at: Date.now(),
      },
    }));
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
    setMessages((prev) => {
      const merged = mergeConversationMessages(prev, msgs);
      return ensureThinkingWhilePending(
        merged,
        conversationId,
        getDisplayPendingMessage(conversationId),
      );
    });
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
      // Proxy/timeout may fail while backend still finishes — recover from store.
      const recovered = await (async () => {
        for (const waitMs of [800, 2500, 5000]) {
          await new Promise((r) => setTimeout(r, waitMs));
          try {
            const msgs = await refreshMessages();
            const trimmed = content.trim();
            for (let i = msgs.length - 1; i >= 0; i -= 1) {
              const m = msgs[i];
              if (m.role === "user" && (m.content || "").trim() === trimmed) {
                const next = msgs[i + 1];
                if (next && next.role === "assistant" && !next.metadata?.optimistic) {
                  return true;
                }
                break;
              }
            }
          } catch {
            // keep trying
          }
        }
        return false;
      })();
      if (recovered) {
        setError(null);
        return;
      }
      setMessages((prev) => prev.filter((m) => !m.metadata?.optimistic));
      setError(extractApiErrorMessage(err, "发送消息失败"));
      throw err;
    }
  }, [applyTurn, conversationId, refreshMessages, showOptimisticPair]);

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
        const pending = getDisplayPendingMessage(conversationId);
        if (msgs.length === 0 && (optimistic.length > 0 || pending)) {
          const base = optimistic.length > 0 ? optimistic : prev;
          return ensureThinkingWhilePending(base, conversationId, pending);
        }
        const merged = optimistic.length > 0
          ? mergeConversationMessages(optimistic, msgs)
          : mergeConversationMessages(prev, msgs);
        return ensureThinkingWhilePending(merged, conversationId, pending);
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
          // Keep status visible for the whole Intent LLM wait (often ~10–20s).
          if (!cancelled) {
            showOptimisticPair(pending.content);
          }
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
          // Same recovery as in-conversation send: proxy may time out first.
          let recovered = false;
          for (const waitMs of [800, 2500, 5000]) {
            if (cancelled) break;
            await new Promise((r) => setTimeout(r, waitMs));
            try {
              const msgs = await refreshMessages();
              if (msgs.some((m) => m.role === "assistant" && !m.metadata?.optimistic)) {
                recovered = true;
                break;
              }
            } catch {
              // keep trying
            }
          }
          if (!recovered) {
            setMessages((prev) => prev.filter((m) => !m.metadata?.optimistic));
            setError(extractApiErrorMessage(err, "发送消息失败"));
          } else {
            setError(null);
          }
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [loading, conversationId, applyTurn, refreshMessages, showOptimisticPair]);

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
    let cancelled = false;
    let hintTimer: ReturnType<typeof setTimeout> | null = null;
    const close = subscribeToConversation(conversationId, {
      onConnected: () => {
        if (hintTimer) {
          clearTimeout(hintTimer);
          hintTimer = null;
        }
        if (!cancelled) setConnectionHint(null);
      },
      onAnalysisStarted: (event) => {
        const taskId = event.task_id;
        if (!taskId) return;
        setTaskPhases((prev) => ({
          ...prev,
          [taskId]: prev[taskId] ?? { phase: "", progress: 0, status: "running" },
        }));
      },
      onPhaseUpdate: (event) => {
        const hint =
          typeof event.data.stage_hint === "string" ? event.data.stage_hint.trim() : "";
        // Pre-task turn progress (Intent LLM): keep / refresh「正在识别意图…」
        if (!event.task_id) {
          if (hint) {
            setMessages((prev) => {
              if (prev.some((m) => m.role === "assistant" && !m.metadata?.optimistic)) {
                return prev;
              }
              const thinkingId = `optimistic-thinking-${conversationId}`;
              const existing = prev.find((m) => m.id === thinkingId);
              if (existing) {
                return prev.map((m) =>
                  m.id === thinkingId ? { ...m, content: hint } : m,
                );
              }
              return mergeConversationMessages(prev, [
                {
                  ...optimisticThinkingMessage(conversationId),
                  content: hint,
                },
              ]);
            });
          }
          return;
        }
        const taskId = event.task_id;
        setTaskPhases((prev) => ({
          ...prev,
          [taskId]: {
            phase: String(event.data.phase ?? ""),
            progress: Number(event.data.progress ?? 0),
            status: "running",
            stage_hint: hint || undefined,
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
        // Debounce: only show hint if reconnect does not succeed quickly
        if (hintTimer) return;
        hintTimer = setTimeout(() => {
          if (!cancelled) {
            setConnectionHint("实时连接不稳定，已改用轮询更新进度");
          }
        }, 4000);
      },
    });
    return () => {
      cancelled = true;
      if (hintTimer) clearTimeout(hintTimer);
      close();
    };
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
        <ConversationMessageList
          messages={messages}
          conversationId={conversationId}
          taskPhases={taskPhases}
          onTaskCancelled={handleTaskCancelled}
          onResearchTaskConfirmed={applyTurn}
        />
      </div>
      <ConversationComposer variant="reply" onSubmit={handleSend} />
    </div>
  );
}
