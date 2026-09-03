import type { Metadata } from "next";
import "./globals.css";
import { RootChrome } from "@/components/root-chrome";

export const metadata: Metadata = {
  title: "AI 竞品分析助手",
  description: "自动生成互联网产品竞品分析报告",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <RootChrome>{children}</RootChrome>
      </body>
    </html>
  );
}
