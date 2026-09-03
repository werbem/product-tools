const STEPS = [
  {
    step: "1",
    title: "用自然语言说出你的问题",
    description: "说明公司、产品，以及你想「收集信息」还是「做竞品对比」。",
  },
  {
    step: "2",
    title: "如果信息不完整，助手会追问补充",
    description: "像和同事聊天一样，把背景一点点说清楚。",
  },
  {
    step: "3",
    title: "完成后在目录和文件中查看结果",
    description: "信息收集会生成摘要条目；竞品分析会生成对比报告，均可在工作台找回。",
  },
];

export function WorkspaceHowItWorks() {
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">怎么使用</h2>
      <ol className="space-y-4">
        {STEPS.map((item) => (
          <li key={item.step} className="flex gap-3">
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border bg-muted text-xs font-semibold"
              aria-hidden
            >
              {item.step}
            </span>
            <div className="min-w-0">
              <div className="font-medium">{item.title}</div>
              <p className="mt-0.5 text-sm text-muted-foreground">{item.description}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
