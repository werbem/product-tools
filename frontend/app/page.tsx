import { redirect } from "next/navigation";

/** Copilot 默认入口：根路径进入 Workspace */
export default function HomePage() {
  redirect("/workspace");
}
