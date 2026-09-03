import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(iso: string): string {
  return formatDateTime(iso);
}

export function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function saveToHistory(entry: {
  taskId: string;
  ourCompany: string;
  competitorCompany: string;
  product: string;
  objective: string;
}) {
  const key = "analysis_history";
  const existing: string | null = localStorage.getItem(key);
  const history = existing ? JSON.parse(existing) : [];
  const newEntry = { ...entry, createdAt: new Date().toISOString() };
  // Deduplicate by taskId
  const filtered = history.filter((h: { taskId: string }) => h.taskId !== entry.taskId);
  filtered.unshift(newEntry);
  // Keep last 20
  localStorage.setItem(key, JSON.stringify(filtered.slice(0, 20)));
}

export function getHistory(): Array<{
  taskId: string;
  ourCompany: string;
  competitorCompany: string;
  product: string;
  objective: string;
  createdAt: string;
}> {
  if (typeof window === "undefined") return [];
  const key = "analysis_history";
  const existing = localStorage.getItem(key);
  return existing ? JSON.parse(existing) : [];
}

export function removeFromHistory(taskId: string) {
  if (typeof window === "undefined") return;
  const key = "analysis_history";
  const existing = localStorage.getItem(key);
  if (!existing) return;
  const history = JSON.parse(existing);
  const filtered = history.filter((h: { taskId: string }) => h.taskId !== taskId);
  localStorage.setItem(key, JSON.stringify(filtered));
}

export function generateUUID(): string {
  // Use native crypto.randomUUID if available (browser & Node 19+)
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback: UUID v4 using crypto.getRandomValues or Math.random
  const getRandomValues = (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function")
    ? () => crypto.getRandomValues(new Uint8Array(1))[0]
    : () => Math.floor(Math.random() * 256);
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (getRandomValues() & 0x0f) | (c === "x" ? 0 : 0x40);
    return (c === "x" ? r : (r & 0x3f) | 0x80).toString(16);
  });
}
