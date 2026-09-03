export function buildInitialProjectTitle(message: string): string {
  const trimmed = message.trim();
  if (!trimmed) return "新分析项目";
  return trimmed.length > 40 ? `${trimmed.slice(0, 40)}…` : trimmed;
}
