export function WorkspaceAsyncState({
  loading,
  error,
  empty,
  children,
}: {
  loading?: boolean;
  error?: string | null;
  empty?: boolean;
  children: React.ReactNode;
}) {
  if (loading) {
    return <div className="text-sm text-muted-foreground">加载中…</div>;
  }
  if (error) {
    return <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>;
  }
  if (empty) {
    return null;
  }
  return <>{children}</>;
}
