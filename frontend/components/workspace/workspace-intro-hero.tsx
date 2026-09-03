"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";

export function WorkspaceIntroHero({ onStartInput }: { onStartInput: () => void }) {
  return (
    <section className="border-b pb-8">
      <p className="text-sm font-medium text-primary">竞品分析助手</p>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
        支持两类需求：<strong className="font-medium text-foreground">信息收集</strong>
        （整理公开资料与近期动态）和
        <strong className="font-medium text-foreground">竞品分析</strong>
        （对比差异并给出可执行建议）。直接说出公司、产品和你的问题即可。
      </p>
      <div className="mt-6 flex flex-wrap gap-3">
        <Button type="button" onClick={onStartInput}>
          开始输入问题
        </Button>
        <Button variant="outline" asChild>
          <Link href="/workspace/projects">查看分析目录</Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href="/workspace/files">查看分析文件</Link>
        </Button>
      </div>
    </section>
  );
}
