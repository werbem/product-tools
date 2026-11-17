"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState, KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";

export type AnalysisMode = "fast" | "full";

export type ConversationComposerHandle = {
  focus: () => void;
};

const MODE_OPTIONS: Array<{
  value: AnalysisMode;
  label: string;
  description: string;
}> = [
  {
    value: "fast",
    label: "快速洞察",
    description: "快速完成调研与成稿",
  },
  {
    value: "full",
    label: "完整尽调",
    description: "增加对比、洞察、策略与质量复核",
  },
];

const DEFAULT_MISSION_PLACEHOLDER = "描述你想分析的问题，或点击上方示例快速填入…";

/** Soft hints only — fill the draft; do not change Router / backend. */
const MISSION_HINTS: Array<{ id: string; label: string; example: string }> = [
  {
    id: "compare",
    label: "竞品对比",
    example: "为什么飞猪酒旅增长放缓？请对比美团与携程，并给出产品策略",
  },
  {
    id: "collect",
    label: "公开信息收集",
    example: "帮我收集字节跳动抖音近期商业发展信息",
  },
  {
    id: "qa",
    label: "快速问答",
    example: "飞猪酒店都有哪些竞品？",
  },
];

export const ConversationComposer = forwardRef<
  ConversationComposerHandle,
  {
    onSubmit: (content: string, analysisMode: AnalysisMode) => Promise<void> | void;
    disabled?: boolean;
    placeholder?: string;
    value?: string;
    onValueChange?: (value: string) => void;
    analysisMode?: AnalysisMode;
    onAnalysisModeChange?: (mode: AnalysisMode) => void;
    sectionId?: string;
    /** Homepage mission console vs in-thread reply (Phase 1). */
    variant?: "mission" | "reply";
  }
>(function ConversationComposer(
  {
    onSubmit,
    disabled,
    placeholder = DEFAULT_MISSION_PLACEHOLDER,
    value: controlledValue,
    onValueChange,
    analysisMode: controlledMode,
    onAnalysisModeChange,
    sectionId,
    variant = "mission",
  },
  ref,
) {
  const [uncontrolledValue, setUncontrolledValue] = useState("");
  const [uncontrolledMode, setUncontrolledMode] = useState<AnalysisMode>("fast");
  const [submitting, setSubmitting] = useState(false);
  const [activeHintId, setActiveHintId] = useState<string | null>(null);
  const composing = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => ({
    focus: () => {
      textareaRef.current?.focus();
    },
  }));

  const isControlled = controlledValue !== undefined;
  const value = isControlled ? controlledValue : uncontrolledValue;
  const analysisMode = controlledMode ?? uncontrolledMode;

  const setValue = (next: string) => {
    if (!isControlled) setUncontrolledValue(next);
    onValueChange?.(next);
  };

  const setMode = (next: AnalysisMode) => {
    if (controlledMode === undefined) setUncontrolledMode(next);
    onAnalysisModeChange?.(next);
  };

  const fillExample = (hint: (typeof MISSION_HINTS)[number]) => {
    setValue(hint.example);
    setActiveHintId(hint.id);
    // Defer focus/select so controlled parent state has committed.
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(0, hint.example.length);
    });
  };

  useEffect(() => {
    if (!value.trim()) {
      setActiveHintId(null);
      return;
    }
    const matched = MISSION_HINTS.find((hint) => hint.example === value);
    setActiveHintId(matched?.id ?? null);
  }, [value]);

  const handleSubmit = async () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || submitting) return;
    setSubmitting(true);
    setValue("");
    setActiveHintId(null);
    try {
      await onSubmit(trimmed, analysisMode);
    } catch {
      setValue(trimmed);
    } finally {
      setSubmitting(false);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !composing.current) {
      e.preventDefault();
      void handleSubmit();
    }
  };

  const isMission = variant === "mission";
  const replyPlaceholder =
    placeholder === DEFAULT_MISSION_PLACEHOLDER ||
    placeholder.startsWith("例如：为什么飞猪")
      ? "继续追问，或提出新的分析问题…"
      : placeholder;

  return (
    <div
      id={sectionId}
      className="scroll-mt-24 rounded-lg border border-border bg-card"
    >
      {isMission ? (
        <>
          <div className="border-b border-border/80 px-4 py-3 sm:px-5">
            <div>
              <h2 className="text-sm font-semibold text-foreground">提出一个分析问题</h2>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                告诉 Agent 你想解决的商业问题，系统会自动判断任务类型并规划执行路径。
              </p>
            </div>
          </div>

          <div className="px-4 pt-3 sm:px-5">
            <p className="text-[11px] text-muted-foreground">示例（可选，点击填入）</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {MISSION_HINTS.map((hint) => {
                const active = activeHintId === hint.id;
                return (
                  <button
                    key={hint.id}
                    type="button"
                    disabled={disabled || submitting}
                    aria-pressed={active}
                    onClick={() => fillExample(hint)}
                    className={`rounded-md border px-2.5 py-1 text-xs transition-colors disabled:opacity-50 ${
                      active
                        ? "border-foreground/30 bg-muted/60 text-foreground"
                        : "border-border/80 bg-background text-muted-foreground hover:border-foreground/20 hover:text-foreground"
                    }`}
                  >
                    {hint.label}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              不确定也没关系，发送后会自动判断。
            </p>
          </div>
        </>
      ) : null}

      <div className={`px-4 sm:px-5 ${isMission ? "pt-3" : "pt-4"}`}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          onCompositionStart={() => {
            composing.current = true;
          }}
          onCompositionEnd={() => {
            composing.current = false;
          }}
          disabled={disabled || submitting}
          placeholder={isMission ? placeholder : replyPlaceholder}
          rows={isMission ? 3 : 3}
          className="w-full resize-none rounded-md border border-border/60 bg-background px-3 py-2 text-sm leading-relaxed outline-none placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        />
      </div>

      <div className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-end sm:justify-between sm:px-5">
        <div className="min-w-0 space-y-2">
          <p className="text-[11px] text-muted-foreground">
            {isMission ? "分析深度（可选）" : "分析深度"}
          </p>
          <div className="flex flex-wrap gap-2">
            {MODE_OPTIONS.map((option) => {
              const active = analysisMode === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  disabled={disabled || submitting}
                  onClick={() => setMode(option.value)}
                  className={`max-w-[14rem] rounded-md border px-3 py-2 text-left transition-colors disabled:opacity-50 ${
                    active
                      ? "border-foreground/30 bg-muted/60"
                      : "border-border/80 bg-background hover:bg-muted/40"
                  }`}
                >
                  <span className="block text-xs font-medium text-foreground">{option.label}</span>
                  <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
                    {option.description}
                  </span>
                </button>
              );
            })}
          </div>
          {isMission ? (
            <p className="text-[11px] text-muted-foreground">不确定选哪种？直接发送即可。</p>
          ) : null}
        </div>

        <Button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={disabled || submitting || !value.trim()}
          className="shrink-0 self-end"
        >
          {submitting || disabled ? "提交中…" : "交给 Agent"}
        </Button>
      </div>
    </div>
  );
});

ConversationComposer.displayName = "ConversationComposer";
