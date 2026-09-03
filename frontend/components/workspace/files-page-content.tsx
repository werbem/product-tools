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

/** Keep the latest report artifact per project to avoid duplicate cards. */
function dedupeLatestByProject(artifacts: Artifact[]): Artifact[] {
  const byProject = new Map<string, Artifact>();
  for (const artifact of artifacts) {
    const key = artifact.project_id || artifact.id;
    const existing = byProject.get(key);
    if (!existing || new Date(artifact.created_at).getTime() > new Date(existing.created_at).getTime()) {
      byProject.set(key, artifact);
    }
  }
  return Array.from(byProject.values()).sort(
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

  const visibleArtifacts = useMemo(() => dedupeLatestByProject(artifacts), [artifacts]);
  const isEmpty = !loading && !error && visibleArtifacts.length === 0;

  return (
    <div>
      <WorkspacePageHeader title="分析文件" description="查看已生成的分析报告与产出物。" />
      {isEmpty ? (
        <WorkspaceEmptyState title="暂无分析文件" description="完成一次分析后，报告将出现在这里。" />
      ) : (
        <WorkspaceAsyncState loading={loading} error={error}>
          <div className="space-y-3">
            {visibleArtifacts.map((artifact) => {
              const reportPath = `/report/${artifact.task_id || artifact.report_id}`;
              return (
                <div key={artifact.id} className="rounded-xl border bg-card p-4">
                  <div className="font-medium">{artifact.title}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {formatDateTime(artifact.created_at)}
                  </div>
                  <div className="mt-3 flex gap-3 text-sm">
                    <Link href={reportPath} className="text-primary hover:underline">
                      查看报告
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
