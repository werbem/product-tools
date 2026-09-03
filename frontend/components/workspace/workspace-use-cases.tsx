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
    title: "了解市场动态时",
    description: "收集某公司 / 产品的公开信息与近期动态（信息收集）",
    example: "帮我收集字节跳动抖音近期商业发展信息",
  },
  {
    id: "growth",
    kind: "analysis",
    title: "增长变慢时",
    description: "对比竞品，找出差距原因（竞品分析）",
    example: "为什么飞猪酒店最近增长下降？请对比美团和携程",
  },
  {
    id: "launch",
    kind: "analysis",
    title: "新品上线前",
    description: "快速对比核心能力与差异（竞品分析）",
    example: "对比我们和竞品在会员体系上的差异",
  },
  {
    id: "review",
    kind: "analysis",
    title: "周报 / 评审前",
    description: "生成有依据的完整竞品分析报告（竞品分析）",
    example: "分析携程酒店业务的竞争优势，并给出产品策略建议",
  },
];

const KIND_LABEL: Record<WorkspaceUseCaseKind, string> = {
  collection: "信息收集",
  analysis: "竞品分析",
};

export function WorkspaceUseCases({
  onSelectExample,
}: {
  onSelectExample: (example: string) => void;
}) {
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">它能帮你做什么</h2>
      <p className="text-sm text-muted-foreground">
        带「信息收集」的问题会整理公开资料摘要；带「竞品分析」的问题会生成对比结论或完整报告。
      </p>
      <div className="grid gap-3 sm:grid-cols-1">
        {WORKSPACE_USE_CASES.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelectExample(item.example)}
            className="rounded-xl border bg-card p-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{item.title}</span>
              <span className="rounded-full border bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                {KIND_LABEL[item.kind]}
              </span>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{item.description}</p>
            <p className="mt-3 break-words text-xs leading-relaxed text-foreground/80">
              示例：{item.example}
            </p>
          </button>
        ))}
      </div>
    </section>
  );
}
