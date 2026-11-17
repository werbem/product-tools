"use client";

export type WorkspaceUseCaseKind = "collection" | "analysis";

export type WorkspaceUseCase = {
  id: string;
  kind: WorkspaceUseCaseKind;
  title: string;
  description: string;
  example: string;
};

export const WORKSPACE_USE_CASES: WorkspaceUseCase[] = [
  {
    id: "intel",
    kind: "collection",
    title: "了解市场动态",
    description: "公开信息收集",
    example: "收集字节跳动近期酒旅业务发展信息",
  },
  {
    id: "growth",
    kind: "analysis",
    title: "增长变慢时",
    description: "竞品分析",
    example: "为什么飞猪酒店业务增长放缓？请对比美团与携程",
  },
  {
    id: "launch",
    kind: "analysis",
    title: "新品上线前",
    description: "竞品分析",
    example: "对比分析方与竞品在会员体系上的差异",
  },
  {
    id: "review",
    kind: "analysis",
    title: "周报 / 评审前",
    description: "竞品分析",
    example: "分析携程酒店业务的竞争优势，并给出产品建议",
  },
];

const KIND_LABEL: Record<WorkspaceUseCaseKind, string> = {
  collection: "公开信息收集",
  analysis: "竞品分析",
};

export function WorkspaceUseCases({
  onSelectExample,
}: {
  onSelectExample: (example: string) => void;
}) {
  return (
    <section className="space-y-2.5 opacity-80">
      <div>
        <h2 className="text-xs font-semibold tracking-tight text-muted-foreground">常见任务</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          从一个真实问题开始 — 点击后填入输入框，不会直接创建任务。
        </p>
      </div>
      <ul className="divide-y divide-border/70 rounded-lg border border-border/80 bg-background">
        {WORKSPACE_USE_CASES.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelectExample(item.example)}
              className="flex w-full flex-col gap-0.5 px-3 py-2.5 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex-row sm:items-baseline sm:gap-3"
            >
              <span className="shrink-0 text-sm font-medium text-foreground">{item.title}</span>
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                {KIND_LABEL[item.kind]}
              </span>
              <span className="min-w-0 flex-1 text-xs leading-relaxed text-muted-foreground sm:text-right">
                {item.example}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
