import Link from "next/link";
import { WorkspaceNav } from "./workspace-nav";

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-background/95 backdrop-blur sticky top-0 z-50">
        <div className="container max-w-6xl flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
          <Link href="/workspace" className="flex items-center gap-2 font-semibold text-lg">
            <svg className="h-6 w-6 text-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
            竞品分析助手
          </Link>
          <WorkspaceNav />
        </div>
      </header>
      <main className="container max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
