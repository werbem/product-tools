import { ApiError } from "@/lib/api";

export function isNotFoundError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export function extractApiErrorMessage(error: unknown, fallback = "请求失败，请稍后重试"): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return "接口不存在，请重启后端后再试";
    }
    const detail = error.detail;
    if (typeof detail === "string") {
      if (detail === "Not Found" || detail.toLowerCase() === "not found") {
        return "接口不存在，请重启后端后再试";
      }
      return detail;
    }
    if (detail && typeof detail === "object" && "detail" in detail) {
      const inner = (detail as { detail: unknown }).detail;
      if (typeof inner === "string") {
        if (inner === "Not Found" || inner.toLowerCase() === "not found") {
          return "接口不存在，请重启后端后再试";
        }
        return inner;
      }
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return fallback;
}
