"use client";

import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";

interface ReportViewerProps {
  markdown: string | null;
  html: string | null;
  wordUrl: string | null;
}

export function ReportViewer({ markdown, html, wordUrl }: ReportViewerProps) {
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

  const handleExportWord = () => {
    if (wordUrl) {
      window.open(wordUrl, "_blank");
    }
  };

  const content = useHtml && html ? html : markdown;

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
          <Button variant="outline" size="sm" onClick={handleCopy} disabled={!markdown}>
            {copied ? "已复制" : "复制 Markdown"}
          </Button>
          {wordUrl && (
            <Button variant="outline" size="sm" onClick={handleExportWord}>
              导出 Word
            </Button>
          )}
        </div>
      </div>

      {/* Report content */}
      <div className="border rounded-lg bg-white p-6 sm:p-8 shadow-sm">
        {useHtml && html ? (
          <div className="report-content" dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <div className="report-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {markdown || ""}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
