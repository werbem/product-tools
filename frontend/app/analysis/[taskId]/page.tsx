"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ProgressTracker } from "@/components/progress-tracker";
import { createReport, getProgress, subscribeProgress, ApiError } from "@/lib/api";
import { saveToHistory } from "@/lib/utils";
import type { AnalysisInput, PhaseRecord, StreamEvent, DiagnosisInfo } from "@/types";

const POLL_INTERVAL = 800;
const MAX_WAIT_SECONDS = 600;

type PageState =
  | { type: "loading"; taskId: string }
  | { type: "creating"; taskId: string; payload: AnalysisInput }
  | { type: "polling"; taskId: string; serverTaskId: string }
  | { type: "completed"; taskId: string }
  | { type: "error"; message: string; diagnosis?: any }
  | { type: "timeout" };

// ── Phase step order (for progress tracker) ──
const PHASE_STEP_ORDER = ["validated", "planned", "researched", "compared", "strategized", "reported", "reviewed"] as const;
type StepKey = (typeof PHASE_STEP_ORDER)[number];

const PHASE_STEP_PROGRESS: Record<StepKey, number> = {
  validated: 5,
  planned: 15,
  researched: 40,
  compared: 55,
  strategized: 65,
  reported: 85,
  reviewed: 95,
};

// Agent name → completed step key (when status === "completed")
const AGENT_TO_COMPLETED: Record<string, StepKey> = {
  gate: "validated",
  planner: "planned",
  research: "researched",
  compare: "compared",
  strategy: "strategized",
  report: "reported",
  review: "reviewed",
};

// ── Session storage keys for refresh resilience ──
const SS_START_TIME = (tid: string) => `analysis_start_${tid}`;
const SS_COMPLETED_STEPS = (tid: string) => `analysis_steps_${tid}`;

export default function AnalysisProgressPage({
  params,
}: {
  params: Promise<{ taskId: string }>;
}) {
  const router = useRouter();
  const [state, setState] = useState<PageState>({ type: "loading", taskId: "" });
  const [demoMode, setDemoMode] = useState(false);
  const [activeStep, setActiveStep] = useState<StepKey | "">("");
  const [completedSteps, setCompletedSteps] = useState<StepKey[]>([]);
  const [progress, setProgress] = useState(0);
  const [phaseHistory, setPhaseHistory] = useState<PhaseRecord[]>([]);
  const [eta, setEta] = useState<string>("");
  const [diagnosis, setDiagnosis] = useState<any>(null);

  // Smoothed ETA tracking
  const etaDeltas = useRef<number[]>([]);
  const payloadRef = useRef<AnalysisInput | null>(null);
  const lastEtaPhase = useRef<number>(0);
  const lastEtaTime = useRef<number>(0);

  // ── ETA calculation with moving average ──
  const updateETA = useCallback((status: string, sid: string) => {
    if (status === "completed") return;
    const now = Date.now();
    const startMs = parseInt(sessionStorage.getItem(SS_START_TIME(sid)) || String(now));

    setCompletedSteps((steps) => {
      const count = Math.max(steps.length, 1);
      if (count < 2) {
        setEta("待确认...");
        return steps;
      }
      const elapsed = Math.max(1, (now - startMs) / 1000);
      const totalSteps = PHASE_STEP_ORDER.length;

      // Track delta for moving average between phase completions
      if (count !== lastEtaPhase.current && lastEtaPhase.current > 0) {
        const deltaPerPhase = (now - lastEtaTime.current) / 1000 / (count - lastEtaPhase.current);
        etaDeltas.current.push(Math.max(1, deltaPerPhase));
        if (etaDeltas.current.length > 4) etaDeltas.current.shift();
      }
      lastEtaPhase.current = count;
      lastEtaTime.current = now;

      // Use moving average if we have enough data, otherwise simple average
      let avgPerPhase: number;
      if (etaDeltas.current.length >= 2) {
        avgPerPhase = etaDeltas.current.reduce((a, b) => a + b, 0) / etaDeltas.current.length;
      } else {
        avgPerPhase = elapsed / count;
      }

      const phasesLeft = totalSteps - count;
      const remaining = Math.round(avgPerPhase * phasesLeft);

      if (remaining <= 0) {
        setEta("即将完成");
      } else if (remaining < 60) {
        setEta(`大约还需 ${remaining} 秒`);
      } else {
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        setEta(`大约还需 ${mins} 分 ${secs} 秒`);
      }
      return steps;
    });
  }, []);

  // Resolve taskId from params and check for pending task
  useEffect(() => {
    params.then((p) => {
      const taskId = p.taskId;
      // Restore state from sessionStorage (for page refresh)
      const savedSteps = sessionStorage.getItem(SS_COMPLETED_STEPS(taskId));
      if (savedSteps) {
        try {
          const parsed: StepKey[] = JSON.parse(savedSteps);
          setCompletedSteps(parsed);
          // Calculate progress from completed steps
          if (parsed.length > 0) {
            const last = parsed[parsed.length - 1];
            setProgress(PHASE_STEP_PROGRESS[last] || 0);
            // Set active step to the next one
            const idx = PHASE_STEP_ORDER.indexOf(last);
            if (idx >= 0 && idx + 1 < PHASE_STEP_ORDER.length) {
              setActiveStep(PHASE_STEP_ORDER[idx + 1]);
            }
          }
        } catch {}
      }

      // Check sessionStorage for a pending task created by the form
      const raw = sessionStorage.getItem("pending_analysis");
      if (raw) {
        try {
          const pending = JSON.parse(raw);
          if (pending.clientTaskId === taskId && pending.payload) {
            setState({ type: "creating", taskId, payload: pending.payload });
            return;
          }
        } catch {
          // ignore invalid JSON
        }
      }
      // Normal flow: task already exists in backend
      setState({ type: "polling", taskId, serverTaskId: taskId });
    }).catch(() => router.push("/"));
  }, [params, router]);

  // Handle the "creating" phase — POST to backend, then start polling
  // Save payload when entering "creating" state
  useEffect(() => {
    if (state.type === "creating" && state.payload) {
      payloadRef.current = state.payload;
    }
  }, [state]);

  useEffect(() => {
    if (state.type !== "creating") return;

    const doCreate = async () => {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);
        let result;
        try {
          result = await createReport(state.payload, controller.signal);
        } catch (err: any) {
          if (err.name === "AbortError") {
            setState({ type: "polling", taskId: state.taskId, serverTaskId: state.taskId });
            return;
          }
          throw err;
        } finally {
          clearTimeout(timeoutId);
        }
        // Init session storage for the server task
        sessionStorage.setItem(SS_START_TIME(result.task_id), String(Date.now()));
        sessionStorage.setItem(SS_COMPLETED_STEPS(result.task_id), JSON.stringify([]));
        // Clear pending data
        sessionStorage.removeItem("pending_analysis");
        // Start polling with server task_id
        setState({ type: "polling", taskId: state.taskId, serverTaskId: result.task_id });
      } catch (err: any) {
        if (err instanceof ApiError) {
          const detail = err.detail;
          const diag = detail?.diagnosis;
          setState({
            type: "error",
            message: typeof detail === "string" ? detail : (detail?.detail || detail?.message || "创建分析任务失败"),
            diagnosis: diag || (detail && typeof detail === "object" ? {
              error_type: `HTTP_${err.status}`,
              root_cause: detail?.detail || String(err.detail || ""),
              suggestion: err.status >= 500 ? "请检查后端日志排查问题" : "请检查输入参数或联系管理员",
              retry_available: err.status >= 500,
            } : undefined),
          });
        } else {
          const msg = err instanceof Error ? err.message : "创建分析任务失败";
          setState({ type: "error", message: msg, diagnosis: {
            error_type: "NETWORK_ERROR",
            root_cause: msg.includes("Failed to fetch") ? "后端服务可能未运行或端口被占用" : "创建任务时发生异常",
            suggestion: "请确认后端已启动: bash start.sh",
            retry_available: true,
          } });
        }
      }
    };
    doCreate();
  }, [state, router]);

  // Initialize start time once serverTaskId is known
  useEffect(() => {
    if (state.type === "polling" && !sessionStorage.getItem(SS_START_TIME(state.serverTaskId))) {
      sessionStorage.setItem(SS_START_TIME(state.serverTaskId), String(Date.now()));
    }
  }, [state]);

  // ── SSE Streaming (parallel to polling) ──
  useEffect(() => {
    if (state.type !== "polling") return;

    const es = subscribeProgress(
      state.serverTaskId,
      (event: StreamEvent) => {
        if (event.event_type === "phase_update") {
          const agentKey = event.agent || "";
          if (event.status === "running") {
            // Agent started — set as active step
            setActiveStep(AGENT_TO_COMPLETED[agentKey] || "");
          } else if (event.status === "completed") {
            // Agent completed — add to completed steps
            const completedKey = AGENT_TO_COMPLETED[agentKey];
            if (completedKey) {
              setCompletedSteps((prev) => {
                if (!prev.includes(completedKey)) {
                  const next = [...prev, completedKey];
                  sessionStorage.setItem(SS_COMPLETED_STEPS(state.serverTaskId), JSON.stringify(next));
                  return next;
                }
                return prev;
              });
              // Move active to next step
              const idx = PHASE_STEP_ORDER.indexOf(completedKey);
              if (idx >= 0 && idx + 1 < PHASE_STEP_ORDER.length) {
                setActiveStep(PHASE_STEP_ORDER[idx + 1]);
              } else {
                setActiveStep("");
              }
              // Use phase-based progress (stable, no jumping)
              setProgress(PHASE_STEP_PROGRESS[completedKey] || progress);
            }
          }
          updateETA(event.status || "", state.serverTaskId);
        }
      },
      (status: string) => {
        // onDone — workflow complete
        // NOTE: Do NOT navigate immediately. Let polling detect completion
        // and display intermediate progress steps first.
        // Save to history and mark complete, polling handles navigation.
        if (status === "completed") {
          const p = payloadRef.current;
          saveToHistory({
            taskId: state.serverTaskId,
            ourCompany: p?.our_company || "",
            competitorCompany: p?.competitor_company || "",
            product: p?.product || "",
            objective: p?.objective || "",
          });
        } else if (status === "need_more_research") {
          setState({ type: "error", message: "证据不足，需要补充更多信息后重新分析" });
        }
      },
      (err: Event) => {
        // Silently handle SSE errors — polling is the fallback
      }
    );

    return () => { es.close(); };
  }, [state, router, updateETA]);

  // ── Polling (fallback + result detection) ──
  useEffect(() => {
    if (state.type !== "polling") return;

    const timeout = setTimeout(() => {
      setState({ type: "timeout" });
    }, MAX_WAIT_SECONDS * 1000);

    const interval = setInterval(async () => {
      try {
        const now = Date.now();
        const startMs = parseInt(sessionStorage.getItem(SS_START_TIME(state.serverTaskId)) || String(now));
        const data = await getProgress(state.serverTaskId);

        // ── Update progress from polling data ──
        const ph = (data.phase_history || []) as PhaseRecord[];
        const completed = ph
          .filter((p) => p.status === "completed")
          .map((p) => p.phase) as StepKey[];
        if (completed.length > 0) {
          setCompletedSteps((prev) => [...new Set([...prev, ...completed])]);
        }
        if (typeof data.progress === "number") {
          setProgress(data.progress);
        }
        setPhaseHistory(ph);

        // Detect completion states
        const status = data.status;
        if (status === "completed" || status === "reviewed") {
          clearInterval(interval);
          clearTimeout(timeout);
          setProgress(100);
          setEta("");
          // Save to history on completion
          const p = payloadRef.current;
          saveToHistory({
            taskId: state.serverTaskId,
            ourCompany: p?.our_company || "",
            competitorCompany: p?.competitor_company || "",
            product: p?.product || "",
            objective: p?.objective || "",
          });
          setState({ type: "completed", taskId: state.serverTaskId });
          router.push(`/report/${state.serverTaskId}`);
        } else if (status === "failed" || status === "review_failed" || status === "validation_failed") {
          clearInterval(interval);
          clearTimeout(timeout);
          // Try to fetch diagnosis
          try {
            const diagRes = await fetch(`/api/traces/${state.serverTaskId}/diagnosis`);
            if (diagRes.ok) {
              const diag = await diagRes.json();
              setState({ type: "error", message: data.error_info || "分析任务失败", diagnosis: diag });
              return;
            }
          } catch {}
          setState({ type: "error", message: data.error_info || "分析任务失败" });
        } else if (data.status === "need_more_research") {
          clearInterval(interval);
          clearTimeout(timeout);
          setState({ type: "error", message: "证据不足，需要补充更多信息后重新分析" });
        } else if (data.status !== "pending" && data.status !== "unknown") {
          // Echo progress from backend
          updateETA(data.status, state.serverTaskId);
        }
      } catch (err: any) {
        // Check error type for better diagnosis
        if (err instanceof ApiError) {
          clearInterval(interval);
          clearTimeout(timeout);
          const detail = err.detail;
          const diag = detail?.diagnosis;
          let errMsg = typeof detail === "string" ? detail : (detail?.detail || detail?.message || "分析失败");
          if (err.status === 404) {
            errMsg = "分析任务已丢失（后台服务可能已重启），请返回首页重新创建";
          }
          setState({
            type: "error",
            message: errMsg,
            diagnosis: diag || (detail && typeof detail === "object" ? {
              error_type: `HTTP_${err.status}`,
              root_cause: detail?.detail || String(err.detail || "服务器返回错误"),
              suggestion: err.status === 404 ? "返回首页重新创建分析任务" : "请检查后端日志排查问题",
              retry_available: err.status >= 500 || err.status === 404,
            } : undefined),
          });
        } else {
          // Task may not be ready yet — keep polling
          const elapsed = (Date.now() - startTime()) / 1000;
          if (elapsed > 10 && (err?.message?.includes("404") || err?.message?.includes("Failed to fetch"))) {
            clearInterval(interval);
            clearTimeout(timeout);
            const isFetch = err?.message?.includes("Failed to fetch");
            const reason = isFetch
              ? "无法连接后端服务 — 后台服务可能已崩溃或未启动"
              : "任务未找到 (HTTP 404) — 后台服务可能已重启";
            setState({ type: "error", message: reason, diagnosis: {
              error_type: isFetch ? "NETWORK_ERROR" : "TASK_NOT_FOUND",
              root_cause: "后台服务在分析过程中重启或不可达，内存中的任务数据已丢失",
              suggestion: "请返回首页重新创建分析任务。如持续失败，请关闭所有进程后执行 bash start.sh 重启",
              retry_available: true,
            } });
          }
        }
      }
    }, POLL_INTERVAL);

    return () => {
      clearInterval(interval);
      clearTimeout(timeout);
    };
  }, [state, router, updateETA]);

  const handleCancel = useCallback(() => {
    if (state.type === "polling") {
      // Clean up session storage for cancelled tasks
      sessionStorage.removeItem("pending_analysis");
      sessionStorage.removeItem(SS_START_TIME(state.serverTaskId));
      sessionStorage.removeItem(SS_COMPLETED_STEPS(state.serverTaskId));
    }
    router.push("/");
  }, [router, state]);

  // ── Helper for start time ──
  const startTime = (): number => {
    if (state.type === "polling") {
      return parseInt(sessionStorage.getItem(SS_START_TIME(state.serverTaskId)) || String(Date.now()));
    }
    return Date.now();
  };

  // ── Render ──

  if (state.type === "loading") {
    return (
      <div className="flex justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  if (state.type === "creating") {
    return (
      <div className="max-w-2xl mx-auto space-y-8 py-4">
        <div className="text-center space-y-4">
          <div className="flex justify-center gap-1.5">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-3 w-3 rounded-full bg-primary animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </div>
          <h1 className="text-2xl font-bold">正在创建分析任务</h1>
          <p className="text-muted-foreground">
            AI 正在准备分析引擎，即将开始情报收集...
          </p>
        </div>

        <Card className="p-8">
          <div className="space-y-4">
            <div className="flex items-center gap-3 text-sm">
              <div className="h-2 w-2 rounded-full bg-primary animate-pulse" />
              <span>验证输入参数</span>
            </div>
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <div className="h-2 w-2 rounded-full bg-muted-foreground/30" />
              <span>制定研究计划</span>
            </div>
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <div className="h-2 w-2 rounded-full bg-muted-foreground/30" />
              <span>跨源证据采集</span>
            </div>
          </div>
        </Card>

        <div className="text-center">
          <Button variant="ghost" onClick={handleCancel}>
            取消返回首页
          </Button>
        </div>
      </div>
    );
  }

  if (state.type === "timeout") {
    return (
      <div className="max-w-lg mx-auto text-center space-y-4 py-12">
        <div className="text-4xl">⏰</div>
        <h2 className="text-xl font-semibold">分析超时</h2>
        <p className="text-muted-foreground">分析超过 5 分钟仍未完成，请稍后重试</p>
        <div className="flex justify-center gap-3">
          <Button variant="outline" onClick={handleCancel}>返回首页</Button>
          <Button onClick={() => window.location.reload()}>重试</Button>
        </div>
      </div>
    );
  }

  if (state.type === "error") {
    return (
      <div className="max-w-lg mx-auto space-y-4 py-12">
        <div className="text-center space-y-4">
          <div className="text-4xl">❌</div>
          <h2 className="text-xl font-semibold">分析失败</h2>
          <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-3 text-left">
            <p className="text-sm font-mono break-all text-destructive">{state.message}</p>
          </div>
        </div>
        {state.diagnosis && (
          <Card className="p-4 space-y-2 bg-destructive/5 border-destructive/20">
            <h3 className="font-medium text-sm">故障诊断</h3>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
              <div className="text-muted-foreground">失败环节</div>
              <div>{state.diagnosis.failed_stage || state.diagnosis.failed_agent || "—"}</div>
              <div className="text-muted-foreground">错误类型</div>
              <div className="font-mono text-xs">{state.diagnosis.error_type || "—"}</div>
              <div className="text-muted-foreground">根因分析</div>
              <div className="text-xs">{state.diagnosis.root_cause || "—"}</div>
              <div className="text-muted-foreground">建议</div>
              <div className="text-xs">{state.diagnosis.suggestion || "—"}</div>
              <div className="text-muted-foreground">可重试</div>
              <div>{state.diagnosis.retry_available ? "✅ 可以" : "❌ 不可"}</div>
            </div>
          </Card>
        )}
        <div className="text-center">
          <Button variant="outline" onClick={handleCancel}>返回首页</Button>
        </div>
      </div>
    );
  }

  // state.type === "polling" — progress tracking
  return (
    <div className="max-w-2xl mx-auto space-y-8 py-4">
      <div className="text-center space-y-2">
        <h1 className="text-2xl font-bold">
          {completedSteps.length === 0 ? "正在启动分析引擎" : "正在分析中"}
        </h1>
        <p className="text-muted-foreground text-sm">
          {completedSteps.length === 0
            ? "AI 正在准备分析引擎，即将开始情报收集..."
            : "AI 正在收集情报并进行深度分析，请稍候..."}
        </p>
        {eta ? (
          <p className={`text-sm font-medium ${eta === "待确认..." ? "text-muted-foreground" : "text-primary animate-pulse"}`}>
            ⏱️ {eta}
          </p>
        ) : (
          <p className="text-sm font-medium text-muted-foreground animate-pulse">
            ⏱️ 待确认...
          </p>
        )}
      </div>
      <Card className="p-6">
        <ProgressTracker
          activeStep={activeStep}
          completedSteps={completedSteps}
          phaseHistory={phaseHistory}
          progress={progress}
          demoMode={demoMode}
        />
      </Card>
      <div className="text-center">
        <Button variant="ghost" onClick={handleCancel}>取消返回首页</Button>
      </div>
    </div>
  );
}
