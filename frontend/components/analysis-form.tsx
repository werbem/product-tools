"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { createReport } from "@/lib/api";
import { saveToHistory, generateUUID } from "@/lib/utils";
import { CUSTOM_OBJECTIVE, OBJECTIVE_OPTIONS } from "@/types";
import type { AnalysisInput } from "@/types";

interface AnalysisFormProps {
  initialValues?: Partial<AnalysisInput>;
}

export function AnalysisForm({ initialValues }: AnalysisFormProps = {}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<AnalysisInput & { customObjective?: string }>({
    our_company: initialValues?.our_company || "",
    competitor_company: initialValues?.competitor_company || "",
    product: initialValues?.product || "",
    objective: initialValues?.objective || "go_to_market",
  });

  useEffect(() => {
    if (initialValues) {
      setForm(prev => ({
        ...prev,
        our_company: initialValues.our_company || prev.our_company,
        competitor_company: initialValues.competitor_company || prev.competitor_company,
        product: initialValues.product || prev.product,
        objective: initialValues.objective || prev.objective,
      }));
    }
  }, [initialValues?.our_company, initialValues?.competitor_company, initialValues?.product, initialValues?.objective]);

  const isObjectiveCustom = form.objective === CUSTOM_OBJECTIVE;

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.our_company.trim() || !form.competitor_company.trim() || !form.product.trim()) {
      setError("请填写所有必填字段");
      return;
    }
    if (isObjectiveCustom && !form.customObjective?.trim()) {
      setError("请填写自定义分析目标");
      return;
    }
    setError(null);

    // Generate client-side task ID for immediate navigation
    const clientTaskId = generateUUID();

    // Build the actual API payload
    const payload: AnalysisInput = {
      our_company: form.our_company.trim(),
      competitor_company: form.competitor_company.trim(),
      product: form.product.trim(),
      objective: isObjectiveCustom ? "product_improvement" : form.objective,
      scene: isObjectiveCustom ? form.customObjective?.trim() : undefined,
    };

    // Save to sessionStorage so analysis page can pick it up
    const pendingTask = {
      clientTaskId,
      payload,
      createdAt: Date.now(),
    };
    sessionStorage.setItem("pending_analysis", JSON.stringify(pendingTask));

    // Navigate immediately — analysis page will create the report
    router.push(`/analysis/${clientTaskId}`);
  }, [form, isObjectiveCustom, router]);

  return (
    <Card className="max-w-2xl mx-auto">
      <CardHeader>
        <CardTitle className="text-2xl">开始竞品分析</CardTitle>
        <CardDescription>填写以下信息，AI 将自动生成深度竞品分析报告</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">分析公司 *</label>
              <input
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder="例：飞猪"
                value={form.our_company}
                onChange={(e) => setForm({ ...form, our_company: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">竞品公司 *</label>
              <input
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder="例：美团"
                value={form.competitor_company}
                onChange={(e) => setForm({ ...form, competitor_company: e.target.value })}
              />
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">分析产品 *</label>
            <input
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="例：酒店"
              value={form.product}
              onChange={(e) => setForm({ ...form, product: e.target.value })}
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">分析目标</label>
            <select
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={form.objective}
              onChange={(e) => setForm({ ...form, objective: e.target.value })}
            >
              {OBJECTIVE_OPTIONS.map(({ value, label }) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            {isObjectiveCustom && (
              <input
                className="mt-2 flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder="请输入自定义分析目标..."
                value={form.customObjective || ""}
                onChange={(e) => setForm({ ...form, customObjective: e.target.value })}
                autoFocus
              />
            )}
          </div>

          {error && (
            <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <Button type="submit" className="w-full h-10 text-base">
            开始分析
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
