"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AnalysisForm } from "@/components/analysis-form";
import { ReportHistory } from "@/components/report-history";
import { Button } from "@/components/ui/button";
import { getDemoStatus } from "@/lib/api";

type SystemMode = "loading" | "demo" | "real" | "error";

const DEMO_VALUES = {
  our_company: "抖音",
  competitor_company: "快手",
  product: "抖音",
  objective: "product_improvement",
};

const CAPABILITIES = [
  {
    title: "企业实体识别",
    desc: "自动识别并关联企业信息、品牌名称和产品线，构建竞品关系图谱",
    icon: (
      <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    ),
  },
  {
    title: "多 Agent 任务拆解",
    desc: "Strategy → Research → Insight → Compare → Report → Review 六步协作管线",
    icon: (
      <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
        <rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" />
      </svg>
    ),
  },
  {
    title: "多渠道 Web 检索",
    desc: "集成 Tavily 搜索引擎，覆盖 App Store、新闻、社区、GitHub 等多源数据",
    icon: (
      <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
      </svg>
    ),
  },
  {
    title: "Evidence 证据校验",
    desc: "每条分析结论标注置信度（Verified/Likely/Estimated），事实审计确保报告可信",
    icon: (
      <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M9 12l2 2 4-4" /><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" />
      </svg>
    ),
  },
  {
    title: "自动生成分析报告",
    desc: "支持 Markdown / HTML / DOCX 多格式导出，包含 SWOT 分析和战略建议",
    icon: (
      <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
      </svg>
    ),
  },
];

export default function ClassicAnalysisPage() {
  const [systemMode, setSystemMode] = useState<SystemMode>("loading");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getDemoStatus();
        if (cancelled) return;
        setSystemMode(res.demo_mode ? "demo" : "real");
      } catch {
        if (!cancelled) setSystemMode("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleStartClick = () => {
    setTimeout(() => {
      document.getElementById("analysis-form-section")?.scrollIntoView({ behavior: "smooth" });
    }, 100);
  };

  return (
    <div className="-mx-[calc((100vw-100%)/2)] w-screen">
      <div className="border-b bg-muted/40">
        <div className="container mx-auto flex flex-col gap-2 px-4 py-3 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <span>旧版表单分析入口 · 完整模式约 12 分钟</span>
          <Link href="/workspace" className="text-primary hover:underline">
            返回 Copilot 工作台 →
          </Link>
        </div>
      </div>

      {/* ═══════════════ Hero ═══════════════ */}
      <section className="relative overflow-hidden bg-gradient-to-br from-slate-900 via-primary/90 to-slate-900 text-white">
        <div className="absolute inset-0 opacity-10">
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle at 25% 25%, rgba(255,255,255,0.2) 1px, transparent 1px)", backgroundSize: "48px 48px" }} />
        </div>

        <div className="relative container mx-auto px-4 py-24 sm:py-32">
          <div className="max-w-3xl mx-auto text-center space-y-8">
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-white/10 text-sm text-white/80 backdrop-blur">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-400" />
              </span>
              基于 LLM Agent + RAG 架构
            </div>

            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-tight">
              AI 竞品情报
              <br />
              <span className="bg-gradient-to-r from-blue-300 to-cyan-200 bg-clip-text text-transparent">
                分析助手
              </span>
            </h1>

            <p className="text-lg sm:text-xl text-white/70 max-w-2xl mx-auto leading-relaxed">
              基于多 Agent 协作的智能竞品研究系统。
              输入目标公司和产品，AI 自动完成全网情报收集、
              多维对比分析和战略洞察报告生成。
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-4">
              <Button
                size="lg"
                onClick={handleStartClick}
                className="w-full sm:w-auto bg-white text-primary hover:bg-white/90 hover:text-primary/90 shadow-lg shadow-black/20 text-base px-8 py-6 h-auto"
              >
                开始分析
                <svg className="ml-2 w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14" /><path d="m12 5 7 7-7 7" /></svg>
              </Button>
            </div>

            {systemMode === "demo" && (
              <p className="text-sm text-white/40">
                当前为 Demo 模式，使用固定案例「抖音 vs 快手」展示完整分析流程，无需配置 API Key
              </p>
            )}
          </div>
        </div>

        <div className="absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-t from-background to-transparent" />
      </section>

      <section className="container mx-auto px-4 py-20">
        <div className="text-center mb-14">
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">产品能力</h2>
          <p className="mt-3 text-muted-foreground max-w-xl mx-auto">
            从企业识别到报告生成，全链路自动化竞品分析
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-5 max-w-6xl mx-auto">
          {CAPABILITIES.map((cap, i) => (
            <div
              key={i}
              className="group relative flex flex-col items-center text-center p-6 rounded-xl border bg-card hover:border-primary/30 hover:shadow-md transition-all duration-200"
            >
              <div className="w-12 h-12 flex items-center justify-center rounded-lg bg-primary/10 text-primary mb-4 group-hover:scale-110 transition-transform">
                {cap.icon}
              </div>
              <h3 className="font-semibold text-sm mb-2">{cap.title}</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">{cap.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-muted/40">
        <div className="container mx-auto px-4 py-20">
          <div className="text-center mb-14">
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">使用流程</h2>
            <p className="mt-3 text-muted-foreground">三步完成竞品分析，全程自动化</p>
          </div>

          <div className="flex flex-col md:hidden items-center gap-6 max-w-md mx-auto">
            {[
              { step: "1", title: "输入信息", desc: "填写目标公司、竞品公司和产品名称，选择分析目标" },
              { step: "2", title: "AI 研究", desc: "多 Agent 协作：策略规划 → 全网检索 → 多维对比 → 战略洞察" },
              { step: "3", title: "生成报告", desc: "自动输出深度分析报告，支持 Markdown / DOCX 导出" },
            ].map((item, i) => (
              <div key={i} className="flex items-start gap-4 w-full p-5 rounded-xl border bg-card">
                <div className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full bg-primary text-primary-foreground font-bold text-lg">
                  {item.step}
                </div>
                <div>
                  <h3 className="font-semibold">{item.title}</h3>
                  <p className="text-sm text-muted-foreground mt-1">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="hidden md:flex items-center justify-center gap-0 max-w-4xl mx-auto">
            {[
              { step: "1", title: "输入信息", desc: "填写目标公司、竞品公司和产品" },
              { step: "2", title: "AI 研究", desc: "多 Agent 协作分析与检索" },
              { step: "3", title: "生成报告", desc: "自动输出深度分析报告" },
            ].map((item, i) => (
              <div key={i} className="flex items-center">
                <div className="flex flex-col items-center text-center">
                  <div className="w-16 h-16 flex items-center justify-center rounded-2xl bg-primary text-primary-foreground font-bold text-2xl shadow-lg shadow-primary/20 mb-4">
                    {item.step}
                  </div>
                  <h3 className="font-semibold">{item.title}</h3>
                  <p className="text-sm text-muted-foreground mt-1 max-w-[200px]">{item.desc}</p>
                </div>
                {i < 2 && (
                  <div className="w-20 sm:w-32 flex items-center justify-center mx-1 sm:mx-2">
                    <svg className="w-12 h-6 text-muted-foreground/40" viewBox="0 0 48 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M0 12h40" /><polyline points="32 6 42 12 32 18" />
                    </svg>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="analysis-form-section" className="container mx-auto px-4 py-16 max-w-2xl">
        <div className="text-center mb-8">
          {systemMode === "loading" ? (
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border bg-muted text-muted-foreground border-border mb-4">
              正在检测系统模式…
            </span>
          ) : systemMode === "demo" ? (
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200 mb-4">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
              </span>
              当前系统配置为demo模式，Demo 使用固定案例「抖音 vs 快手」展示完整分析流程
            </span>
          ) : systemMode === "real" ? (
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 mb-4">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
              真实模式 · 使用真实数据源与 LLM 生成竞品分析报告
            </span>
          ) : (
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-muted text-muted-foreground border border-border mb-4">
              系统模式未知（后端服务不可达）
            </span>
          )}
          <h2 className="text-2xl font-bold tracking-tight">开始你的分析</h2>
          <p className="mt-2 text-muted-foreground">
            填写公司和产品信息，AI 将自动完成竞品分析（完整模式，约 12 分钟）
          </p>
        </div>

        <AnalysisForm
          initialValues={systemMode === "demo" ? DEMO_VALUES : undefined}
        />

        <div className="mt-16 pt-8 border-t">
          <ReportHistory />
        </div>
      </section>
    </div>
  );
}
