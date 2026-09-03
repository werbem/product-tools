"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { CollectionDetailResponse } from "@/types";
import { getTaskCollection } from "@/lib/copilot-api";
import { extractApiErrorMessage } from "@/lib/copilot-errors";
import { WorkspacePageHeader } from "@/components/workspace/workspace-page-header";

export function CollectionPageContent({ taskId }: { taskId: string }) {
  const [data, setData] = useState<CollectionDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void getTaskCollection(taskId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(extractApiErrorMessage(err, "加载收集结果失败"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  if (loading) {
    return <div className="text-sm text-muted-foreground">加载收集结果中…</div>;
  }
  if (error || !data) {
    return <div className="text-sm text-destructive">{error || "未找到收集结果"}</div>;
  }

  const title = `${data.our_company} · ${data.product} 信息收集`;
  const topic = data.topic || data.objective || "";

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <WorkspacePageHeader
        title={title}
        description={
          topic
            ? `收集主题：${topic} · 共 ${data.evidence_count} 条信息 · 数据源 ${data.sources_succeeded}/${data.sources_attempted} 成功`
            : `共 ${data.evidence_count} 条信息 · 数据源 ${data.sources_succeeded}/${data.sources_attempted} 成功`
        }
      />
      <div className="text-xs text-muted-foreground">
        <Link href="/workspace/projects" className="hover:underline">
          返回项目
        </Link>
      </div>
      {data.warnings.length > 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          {data.warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>
      ) : null}
      {data.markdown ? (
        <article className="prose prose-sm max-w-none rounded-xl border bg-card p-6 whitespace-pre-wrap">
          {data.markdown}
        </article>
      ) : (
        <div className="text-sm text-muted-foreground">暂无摘要内容。</div>
      )}
      {data.evidence_items.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-base font-semibold">来源链接</h2>
          <ul className="space-y-2 text-sm">
            {data.evidence_items.map((item) => (
              <li key={item.id || item.url} className="rounded-lg border p-3">
                <div className="font-medium">{item.title || item.url}</div>
                {item.url ? (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 block truncate text-primary hover:underline"
                  >
                    {item.url}
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
