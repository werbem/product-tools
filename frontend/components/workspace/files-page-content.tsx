"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { Artifact } from "@/types/copilot";
import { listArtifacts, resolveArtifactUrl } from "@/lib/copilot-api";
import { extractApiErrorMessage, isNotFoundError } from "@/lib/copilot-errors";
import { formatDateTime } from "@/lib/utils";
import { WorkspaceAsyncState } from "./workspace-async-state";
import { WorkspaceEmptyState } from "./workspace-empty-state";
import { WorkspacePageHeader } from "./workspace-page-header";

/** All persisted artifacts, newest first. Project delete hard-removes related files. */
function sortArtifactsNewestFirst(artifacts: Artifact[]): Artifact[] {
  return [...artifacts].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
}

export function FilesPageContent() {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listArtifacts()
      .then(setArtifacts)
      .catch((err) => {
        if (isNotFoundError(err)) {
          setArtifacts([]);
          setError(null);
          return;
        }
        setError(extractApiErrorMessage(err));
      })
      .finally(() => setLoading(false));
  }, []);

  const visibleArtifacts = useMemo(() => sortArtifactsNewestFirst(artifacts), [artifacts]);
  const isEmpty = !loading && !error && visibleArtifacts.length === 0;

  return (
    <div>
      <WorkspacePageHeader
        title="分析文件"
        description="展示全部已生成、未随项目删除的分析报告与产出物。"
      />
      {isEmpty ? (
        <WorkspaceEmptyState title="暂无分析文件" description="完成一次分析后，报告将出现在这里。" />
      ) : (
        <WorkspaceAsyncState loading={loading} error={error}>
          <div className="space-y-3">
            {visibleArtifacts.map((artifact) => {
              const isEvidence = artifact.type === "evidence_package";
              const href =
                (typeof artifact.metadata?.view_url === "string" && artifact.metadata.view_url)
                || (isEvidence
                  ? `/workspace/collections/${artifact.task_id}`
                  : `/report/${artifact.task_id || artifact.report_id}`);
              const linkLabel = isEvidence ? "查看收集结果" : "查看报告";
              return (
                <div key={artifact.id} className="rounded-xl border bg-card p-4">
                  <div className="font-medium">{artifact.title}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {formatDateTime(artifact.created_at)}
                  </div>
                  <div className="mt-3 flex gap-3 text-sm">
                    <Link href={href} className="text-primary hover:underline">
                      {linkLabel}
                    </Link>
                    {artifact.download_url ? (
                      <a
                        href={resolveArtifactUrl(artifact.download_url)}
                        className="text-primary hover:underline"
                      >
                        下载 Word
                      </a>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </WorkspaceAsyncState>
      )}
    </div>
  );
}
