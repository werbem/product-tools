"use client";

export default function WorkspaceError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6">
      <h2 className="font-semibold text-destructive">页面加载失败</h2>
      <p className="mt-2 text-sm text-muted-foreground">{error.message}</p>
      <button type="button" onClick={reset} className="mt-4 text-sm text-primary hover:underline">
        重试
      </button>
    </div>
  );
}
