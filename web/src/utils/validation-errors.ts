import { ApiError } from "../api/client";

/** Only surface the upload serializer's public 400 field errors, never raw diagnostics. */
export function datasetUploadErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "请求未完成，请稍后重试。";
  if (error.status !== 400 || error.code !== "VALIDATION_ERROR" || !error.details || typeof error.details !== "object" || Array.isArray(error.details)) return error.message;
  const details = error.details as Record<string, unknown>;
  const messages: string[] = [];
  for (const [field, label] of [["file", "文件"], ["name", "数据集名称"], ["description", "数据说明"]]) {
    const values = Array.isArray(details[field]) ? details[field] : [details[field]];
    for (const value of values.slice(0, 3)) {
      if (typeof value === "string" && value.trim()) messages.push(`${label}：${value.trim().slice(0, 300)}`);
    }
  }
  return [...new Set(messages)].slice(0, 3).join("；").slice(0, 900) || error.message;
}
