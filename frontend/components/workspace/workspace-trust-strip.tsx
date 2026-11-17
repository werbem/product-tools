"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getReport } from "@/lib/api";
import type { Artifact } from "@/types/copilot";
import type { ReportDetailResponse } from "@/types";

export type TrustEvidenceSnippet = {
  claim: string;
  evidenceId: string;
  sourceLabel: string;
  confidenceLabel: string | null;
  reportHref: string;
  taskId: string;
};

type EvidenceSource = {
  source_id?: string;
  url?: string;
  title?: string;
  summary?: string;
  source_type?: string;
  date?: string;
  domain?: string;
  confidence?: string | number | null;
};

function normalizeEvidenceId(raw: string): string | null {
  const id = raw.trim();
  if (!id) return null;
  const e = /^E(\d+)$/i.exec(id);
  if (e) return `E${e[1].padStart(3, "0")}`;
  const src = /^src_(\d+)$/i.exec(id);
  if (src) return `E${String(parseInt(src[1], 10) + 1).padStart(3, "0")}`;
  return id;
}

function formatConfidence(value: string | number | null | undefined): string | null {
  if (value == null || value === "") return null;
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  const raw = String(value).trim().toLowerCase();
  if (!raw) return null;
  if (raw === "high" || raw === "高") return "高";
  if (raw === "medium" || raw === "中" || raw === "med") return "中";
  if (raw === "low" || raw === "低") return "低";
  // Only surface explicit values from API — do not invent.
  return String(value).trim();
}

function sourceChannel(s: EvidenceSource): string {
  return (s.domain || s.source_type || "").trim();
}

function hasUsableSource(s: EvidenceSource): boolean {
  return Boolean(normalizeEvidenceId(s.source_id || "") && (s.title || "").trim() && (s.url || s.domain));
}

function scoreEvidence(s: EvidenceSource, citedIds: Set<string>): number {
  let score = 0;
  const id = normalizeEvidenceId(s.source_id || "");
  if (id) score += 2;
  if ((s.title || "").trim()) score += 2;
  if (s.url || s.domain) score += 2;
  if (formatConfidence(s.confidence) != null) score += 2;
  if (id && citedIds.has(id)) score += 3;
  return score;
}

/** Pull a short claim sentence that cites the evidence id from report markdown. */
export function extractClaimForEvidence(markdown: string, evidenceId: string): string | null {
  const id = normalizeEvidenceId(evidenceId);
  if (!id || !markdown) return null;
  const num = /^E(\d+)$/i.exec(id)?.[1];
  if (!num) return null;
  const refRe = new RegExp(`\\[E0*${parseInt(num, 10)}\\]`, "i");

  const blocks = markdown
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith("|"))
    .filter((line) => !/^#{1,6}\s*附录/.test(line))
    .filter((line) => !/内部笔记/.test(line));

  for (const block of blocks) {
    if (!refRe.test(block)) continue;
    const cleaned = block
      .replace(/^#{1,6}\s*/, "")
      .replace(/\*\*/g, "")
      .replace(/`+/g, "")
      .replace(/\[E\d{3}\]/gi, "")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/^[-*•]\s*/, "");
    if (cleaned.length < 8) continue;
    // Prefer first sentence-like chunk
    const sentence = cleaned.split(/(?<=[。！？.!?])\s*/)[0]?.trim() || cleaned;
    if (sentence.length < 8) continue;
    return sentence.length > 160 ? `${sentence.slice(0, 157)}…` : sentence;
  }
  return null;
}

function collectCitedIds(markdown: string): Set<string> {
  const set = new Set<string>();
  const re = /\[E(\d{1,4})\]/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(markdown)) !== null) {
    set.add(`E${m[1].padStart(3, "0")}`);
  }
  return set;
}

export function buildTrustSnippetFromReport(report: ReportDetailResponse): TrustEvidenceSnippet | null {
  const sources = (report.evidence_sources || []) as EvidenceSource[];
  if (!sources.length) return null;
  const markdown = report.markdown || "";
  const cited = collectCitedIds(markdown);
  const ranked = [...sources]
    .filter(hasUsableSource)
    .sort((a, b) => scoreEvidence(b, cited) - scoreEvidence(a, cited));

  for (const source of ranked) {
    const evidenceId = normalizeEvidenceId(source.source_id || "");
    if (!evidenceId) continue;
    const claim = extractClaimForEvidence(markdown, evidenceId);
    if (!claim) continue;
    const channel = sourceChannel(source);
    const title = (source.title || "").trim();
    const sourceLabel = channel ? `${title} / ${channel}` : title;
    const taskId = report.task_id;
    if (!taskId) continue;
    return {
      claim,
      evidenceId,
      sourceLabel,
      confidenceLabel: formatConfidence(source.confidence),
      reportHref: `/report/${taskId}`,
      taskId,
    };
  }
  return null;
}

export function WorkspaceTrustStrip({
  artifacts,
  overviewFailed = false,
}: {
  /** Preloaded artifacts from homepage overview (required when parent owns the fetch). */
  artifacts: Artifact[];
  overviewFailed?: boolean;
}) {
  const [snippet, setSnippet] = useState<TrustEvidenceSnippet | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(false);

    if (overviewFailed) {
      setSnippet(null);
      setFailed(true);
      setLoading(false);
      return;
    }

    const run = async () => {
      try {
        const reportArtifacts = artifacts
          .filter((a) => a.type !== "evidence_package" && a.task_id)
          .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        for (const artifact of reportArtifacts.slice(0, 5)) {
          try {
            const report = await getReport(artifact.task_id);
            const next = buildTrustSnippetFromReport(report);
            if (next) {
              if (!cancelled) setSnippet(next);
              return;
            }
          } catch {
            // Skip missing/in-progress reports; keep looking.
          }
        }
        if (!cancelled) setSnippet(null);
      } catch {
        if (!cancelled) {
          setSnippet(null);
          setFailed(true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [artifacts, overviewFailed]);

  return (
    <section className="border-y border-border/70 py-4" aria-label="结论可追溯">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">结论可追溯</h2>
        <p className="text-xs text-muted-foreground">
          关键判断尽量回指公开来源，并区分项目内部笔记。
        </p>
      </div>

      {loading ? (
        <p className="mt-3 text-xs text-muted-foreground">正在读取已有报告中的证据…</p>
      ) : snippet ? (
        <div className="mt-3 space-y-3">
          <div className="rounded-md border border-border/80 bg-background px-3 py-3 sm:px-4">
            <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              结论
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-foreground">{snippet.claim}</p>
            <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span className="font-mono text-foreground/80">[{snippet.evidenceId}]</span>
              <span>{snippet.sourceLabel}</span>
              {snippet.confidenceLabel ? (
                <span>置信度：{snippet.confidenceLabel}</span>
              ) : null}
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[11px] text-muted-foreground">
              公开检索证据 ≠ 项目内部笔记。内部笔记不会伪装成外部 Evidence。
            </p>
            <Link
              href={snippet.reportHref}
              className="shrink-0 text-xs font-medium text-foreground underline-offset-2 hover:underline"
            >
              打开完整报告查看证据 →
            </Link>
          </div>
        </div>
      ) : (
        <div className="mt-3 text-xs leading-relaxed text-muted-foreground">
          {failed ? (
            <p>暂时无法读取报告证据，请稍后再试。</p>
          ) : (
            <p>
              完成一次竞品分析后，这里会展示真实结论与对应 Evidence。
            </p>
          )}
          <p className="mt-1 text-[11px]">公开检索证据 ≠ 项目内部笔记。</p>
        </div>
      )}
    </section>
  );
}
