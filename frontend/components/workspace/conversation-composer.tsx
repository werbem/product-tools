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
  hint: string;
}> = [
  {
    value: "fast",
    label: "快速模式",
    hint: "约 6 分钟，跳过对比/洞察/战略/审阅，生成完整 13 章报告",
  },
  {
    value: "full",
    label: "完整模式",
    hint: "约 12 分钟，含对比、洞察、战略与审阅",
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
  }
>(function ConversationComposer(
  {
    onSubmit,
    disabled,
    placeholder = "描述你想分析的竞品问题…",
    value: controlledValue,
    onValueChange,
    analysisMode: controlledMode,
    onAnalysisModeChange,
    sectionId,
  },
  ref,
) {
  const [uncontrolledValue, setUncontrolledValue] = useState("");
  const [uncontrolledMode, setUncontrolledMode] = useState<AnalysisMode>("fast");
  const [submitting, setSubmitting] = useState(false);
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

  useEffect(() => {
    if (isControlled && controlledValue) {
      textareaRef.current?.focus();
    }
  }, [isControlled, controlledValue]);

  const handleSubmit = async () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || submitting) return;
    setSubmitting(true);
    try {
      await onSubmit(trimmed, analysisMode);
      setValue("");
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

  return (
    <div id={sectionId} className="rounded-xl border bg-card p-4 shadow-sm scroll-mt-24">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        onCompositionStart={() => { composing.current = true; }}
        onCompositionEnd={() => { composing.current = false; }}
        disabled={disabled || submitting}
        placeholder={placeholder}
        rows={3}
        className="w-full resize-none bg-transparent text-sm outline-none placeholder:text-muted-foreground"
      />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">模式</span>
          <div className="inline-flex rounded-lg border bg-background p-0.5">
            {MODE_OPTIONS.map((option) => {
              const active = analysisMode === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  title={option.hint}
                  disabled={disabled || submitting}
                  onClick={() => setMode(option.value)}
                  className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                    active
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  } disabled:opacity-50`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          <span className="hidden text-xs text-muted-foreground sm:inline" title={MODE_OPTIONS.find((o) => o.value === analysisMode)?.hint}>
            {analysisMode === "fast" ? "约 6 分钟" : "约 12 分钟"}
          </span>
        </div>
        <Button onClick={() => void handleSubmit()} disabled={disabled || submitting || !value.trim()}>
          {submitting ? "发送中…" : "发送"}
        </Button>
      </div>
    </div>
  );
});

ConversationComposer.displayName = "ConversationComposer";
