"use client";

import { usePathname } from "next/navigation";

export function RootChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isWorkspace = pathname?.startsWith("/workspace");

  if (isWorkspace) {
    return <>{children}</>;
  }

  return (
    <>
      <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 sticky top-0 z-50">
        <div className="container flex h-14 items-center">
          <a href="/workspace" className="flex items-center gap-2 font-semibold text-lg">
            <svg className="h-6 w-6 text-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
            竞品分析助手
          </a>
        </div>
      </header>
      <main>{children}</main>
    </>
  );
}
