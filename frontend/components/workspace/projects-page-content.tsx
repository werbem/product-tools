"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { Project } from "@/types/copilot";
import { deleteProject, listConversations, listProjects } from "@/lib/copilot-api";
import { extractApiErrorMessage, isNotFoundError } from "@/lib/copilot-errors";
import { formatDateTime } from "@/lib/utils";
import { WorkspaceAsyncState } from "./workspace-async-state";
import { WorkspaceEmptyState } from "./workspace-empty-state";
import { WorkspacePageHeader } from "./workspace-page-header";

export function ProjectsPageContent() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch((err) => {
        if (isNotFoundError(err)) {
          setProjects([]);
          setError(null);
          return;
        }
        setError(extractApiErrorMessage(err));
      })
      .finally(() => setLoading(false));
  }, []);

  const openProjectConversation = async (project: Project) => {
    if (openingId || deletingId) return;
    setOpeningId(project.id);
    setError(null);
    try {
      const conversations = await listConversations(project.id);
      const latest = conversations[0];
      if (!latest) {
        setError("该项目暂无会话，请从「新对话」重新开始。");
        return;
      }
      router.push(`/workspace/conversations/${latest.id}`);
    } catch (err) {
      setError(extractApiErrorMessage(err, "打开会话失败，请稍后重试"));
    } finally {
      setOpeningId(null);
    }
  };

  const handleDelete = async (project: Project) => {
    if (deletingId || openingId) return;
    const confirmed = window.confirm(
      `确认删除「${project.title}」？\n将同时删除关联的会话与分析文件。`,
    );
    if (!confirmed) return;

    setDeletingId(project.id);
    setError(null);
    try {
      await deleteProject(project.id);
      setProjects((prev) => prev.filter((p) => p.id !== project.id));
    } catch (err) {
      setError(extractApiErrorMessage(err, "删除失败，请稍后重试"));
    } finally {
      setDeletingId(null);
    }
  };

  const isEmpty = !loading && !error && projects.length === 0;

  return (
    <div>
      <WorkspacePageHeader title="分析目录" description="点击项目直接进入对应分析会话。" />
      {isEmpty ? (
        <WorkspaceEmptyState title="暂无分析目录" description="从「新对话」开始你的第一次竞品分析。" />
      ) : (
        <WorkspaceAsyncState loading={loading} error={error}>
          <div className="grid gap-4 sm:grid-cols-2">
            {projects.map((project) => (
              <div
                key={project.id}
                className="rounded-xl border bg-card p-4 transition hover:border-primary/40 hover:shadow-sm"
              >
                <button
                  type="button"
                  disabled={openingId === project.id || deletingId === project.id}
                  onClick={() => void openProjectConversation(project)}
                  className="w-full text-left disabled:opacity-60"
                >
                  <div className="font-semibold">{project.title}</div>
                  {project.objective ? (
                    <div className="mt-1 text-xs text-muted-foreground">{project.objective}</div>
                  ) : null}
                  <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                    <span>
                      {openingId === project.id
                        ? "进入会话中…"
                        : project.status === "archived"
                          ? "已归档"
                          : project.analysis_status === "completed"
                            ? "已完成"
                            : project.analysis_status === "running"
                              ? "分析中"
                              : project.analysis_status === "failed"
                                ? "分析失败"
                                : "未开始"}
                    </span>
                    <span>{formatDateTime(project.updated_at)}</span>
                  </div>
                </button>
                <div className="mt-3 flex justify-end border-t pt-3">
                  <button
                    type="button"
                    disabled={deletingId === project.id || openingId === project.id}
                    onClick={() => void handleDelete(project)}
                    className="text-xs text-destructive hover:underline disabled:opacity-50"
                  >
                    {deletingId === project.id ? "删除中…" : "删除"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </WorkspaceAsyncState>
      )}
    </div>
  );
}
