"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/workspace", label: "新对话", match: (p: string) => p === "/workspace" || p.startsWith("/workspace/conversations/") },
  { href: "/workspace/projects", label: "分析目录", match: (p: string) => p.startsWith("/workspace/projects") },
  { href: "/workspace/files", label: "分析文件", match: (p: string) => p === "/workspace/files" },
];

export function WorkspaceNav() {
  const pathname = usePathname() || "";

  return (
    <nav aria-label="Workspace 导航" className="flex flex-wrap gap-2">
      {NAV_ITEMS.map((item) => {
        const active = item.match(pathname);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
