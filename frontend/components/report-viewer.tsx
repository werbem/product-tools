"use client";

import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";

interface EvidenceSource {
  source_id?: string;
  url?: string;
  title?: string;
  summary?: string;
  source_type?: string;
  date?: string;
  domain?: string;
}

interface ReportViewerProps {
  markdown: string | null;
  html: string | null;
  wordUrl: string | null;
  evidenceSources?: EvidenceSource[];
}


// ── Evidence link preprocessing ──
// 将报告中的 [E001]、[E016] 等引用标记替换为：
//   - 可点击的超链接（新窗口打开原始来源）
//   - 悬浮时展示 名称/来源渠道/日期/摘要 详情
// 关联证据行额外直接展示证据标题（渠道 · 日期）。

function escapeAttr(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// 构建 E 编号 → 证据来源 的映射（兼容新旧数据格式与 0/1 基编号）
function buildEvidenceMap(sources?: EvidenceSource[]): Map<number, EvidenceSource> {
  const map = new Map<number, EvidenceSource>();
  if (!sources) return map;
  sources.forEach((s, idx) => {
    const id = s.source_id || "";
    let eNum = /^E(\d+)/i.exec(id)?.[1];
    let srcNum = /^src_(\d+)/i.exec(id)?.[1];
    // E001 → 1（1-based）；src_000 → 1（兼容旧格式，0-based 补 +1）
    const key = eNum
      ? parseInt(eNum, 10)
      : srcNum
        ? parseInt(srcNum, 10) + 1
        : idx + 1;
    if (!map.has(key)) map.set(key, s);
    // 旧格式 src_000 同时也注册 0-based 编号 0，兼容 LLM 输出的 [E000]
    if (srcNum && !map.has(parseInt(srcNum, 10))) {
      map.set(parseInt(srcNum, 10), s);
    }
  });
  return map;
}

function findEvidence(map: Map<number, EvidenceSource>, num: number): EvidenceSource | undefined {
  // 1-based 精确匹配
  const exact = map.get(num);
  if (exact) return exact;
  // 0-based 容错：报告 [E000] 实际指向第一条证据（E001）
  return map.get(num + 1);
}

function evidenceChannel(s: EvidenceSource): string {
  return s.domain || s.source_type || "";
}

// 构建悬浮详情文本（标题 / 来源 / 摘要）
function evidenceTooltip(s: EvidenceSource): string {
  const meta = [evidenceChannel(s), s.date].filter(Boolean).join(" · ");
  return [
    s.title ? `📄 标题：${s.title}` : "",
    meta ? `🔗 来源：${meta}` : "",
    s.summary ? `📝 摘要：${s.summary.slice(0, 180)}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

// Markdown 链接内的文本转义（防止 ] [ 破坏链接语法）
function escapeLinkText(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/\[/g, "\\[").replace(/\]/g, "\\]");
}

// Markdown 链接 title 转义（避免双引号破坏 title 语法）
function escapeTitle(s: string): string {
  return s.replace(/"/g, "'");
}

function preprocessEvidence(
  md: string,
  sources?: EvidenceSource[],
  _mode?: string,
): string {
  if (!md || !sources || sources.length === 0) return md;
  const map = buildEvidenceMap(sources);

  // Step 1: Strip any existing markdown links from evidence refs
  md = md.replace(/\[E(\d{3})\]\([^)]*\)/g, (_m: string, num: string) => `[E${num}]`);

  // Step 2: Replace [E001] with clean markdown links
  // Uses short E001 text to avoid table-layout issues
  return md.replace(/\[E(\d{3})\]/g, (_m: string, num: string) => {
    const s = findEvidence(map, parseInt(num, 10));
    if (!s) return `[E${num}]`;
    const url = escapeAttr(s.url || "#");
    return `[E${num}](${url})`;
  });
}

function buildEvidenceAppendixMd(sources?: EvidenceSource[]): string {
  if (!sources || sources.length === 0) return "";
  const rows = sources
    .filter((s) => s.source_id)
    .map((s) => {
      const title = (s.title || "").replace(/\|/g, "｜").replace(/\n/g, " ");
      const date = s.date || "-";
      const domain = s.domain || s.source_type || "-";
      return `| ${s.source_id} | ${title} | ${date} | ${domain} |`;
    })
    .join("\n");
  if (!rows) return "";
  return `\n\n## 附录：证据来源\n\n| 编号 | 标题 | 日期 | 来源 |\n|------|------|------|------|\n${rows}\n`;
}

export function ReportViewer({ markdown, html, wordUrl, evidenceSources }: ReportViewerProps) {
  const [useHtml, setUseHtml] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!markdown) return;
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
      const ta = document.createElement("textarea");
      ta.value = markdown;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleDownloadWord = () => {
    if (!wordUrl) return;
    const a = document.createElement("a");
    a.href = wordUrl;
    a.download = "竞品分析报告.docx";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleDownloadMarkdown = () => {
    if (!markdown) return;
    const fullMarkdown = markdown + buildEvidenceAppendixMd(evidenceSources);
    const blob = new Blob([fullMarkdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "竞品分析报告.md";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const displayMarkdown = preprocessEvidence(markdown || "", evidenceSources);
  const content = useHtml && html ? html : (displayMarkdown || markdown);
  const displayHtml = useHtml && html ? preprocessEvidence(html, evidenceSources, "html") : null;

  if (!content) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        暂无报告内容
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Action bar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">报告视图：</span>
          <div className="flex rounded-md border overflow-hidden">
            <button
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                !useHtml ? "bg-primary text-primary-foreground" : "bg-background hover:bg-muted"
              }`}
              onClick={() => setUseHtml(false)}
            >
              Markdown
            </button>
            {html && (
              <button
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  useHtml ? "bg-primary text-primary-foreground" : "bg-background hover:bg-muted"
                }`}
                onClick={() => setUseHtml(true)}
              >
                HTML
              </button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {wordUrl && (
            <Button variant="outline" size="sm" onClick={handleDownloadWord}>
              <svg className="h-4 w-4 mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              下载 Word
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={handleDownloadMarkdown} disabled={!markdown}>
            <svg className="h-4 w-4 mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            下载 Markdown
          </Button>
          <Button variant="outline" size="sm" onClick={handleCopy} disabled={!markdown}>
            {copied ? "已复制" : "复制 Markdown"}
          </Button>
        </div>
      </div>

      {/* Report content */}
      <div className="border rounded-lg bg-white p-6 sm:p-8 shadow-sm">
        {useHtml && html ? (
          <div className="report-content" dangerouslySetInnerHTML={{ __html: displayHtml || "" }} />
        ) : (
          <div className="report-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {displayMarkdown}
            </ReactMarkdown>
          </div>
        )}
      </div>

      {/* ═══════════════ 附录：证据来源清单 ═══════════════ */}
      {evidenceSources && evidenceSources.length > 0 && (
        <div className="border rounded-lg bg-white p-6 sm:p-8 shadow-sm">
          <h2 className="text-xl font-bold mb-4">附录：证据来源</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left py-2 px-3 font-medium w-16">编号</th>
                  <th className="text-left py-2 px-3 font-medium">标题</th>
                  <th className="text-left py-2 px-3 font-medium w-28">日期</th>
                  <th className="text-left py-2 px-3 font-medium w-32">来源</th>
                </tr>
              </thead>
              <tbody>
                {evidenceSources.filter(s => s.source_id).map((s, i) => (
                  <tr key={s.source_id || i} className="border-b hover:bg-muted/30 transition-colors">
                    <td className="py-2 px-3 text-muted-foreground font-mono text-xs">{s.source_id}</td>
                    <td className="py-2 px-3">
                      {s.url ? (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline"
                          title={s.summary || s.title || ""}
                        >
                          {s.title || s.source_id || ""}
                        </a>
                      ) : (
                        <span>{s.title || s.source_id || ""}</span>
                      )}
                      {s.summary && (
                        <span className="block text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          {s.summary}
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-muted-foreground text-xs whitespace-nowrap">{s.date || "-"}</td>
                    <td className="py-2 px-3 text-muted-foreground text-xs">{s.domain || s.source_type || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
