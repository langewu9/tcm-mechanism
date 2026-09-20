"use client";

import { Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function DatasetUploader() {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(formData: FormData) {
    setLoading(true);
    setMessage("");
    const response = await fetch("/api/datasets", { method: "POST", body: formData });
    const data = await response.json();
    setLoading(false);
    if (!response.ok) {
      setMessage(data.error || "上传失败");
      return;
    }
    setMessage(`已导入 ${data.item.rowCount} 行数据`);
    router.refresh();
  }

  return (
    <form action={submit} className="panel space-y-3 p-5">
      <div>
        <h2 className="text-lg font-black">上传数据集</h2>
        <p className="mt-1 text-sm text-ink/58">支持 CSV、XLS、XLSX，入库后可检索、预览和删除。</p>
      </div>
      <label className="form-label">数据集名称<input className="field mt-2" name="name" placeholder="例如：麦门冬汤六味中药成分靶点数据" required /></label>
      <label className="form-label">数据说明<textarea className="field mt-2 min-h-20" name="description" placeholder="描述来源、字段含义与使用范围" /></label>
      <label className="form-label">选择文件<input className="field mt-2" name="file" type="file" accept=".csv,.xls,.xlsx" required /></label>
      {message ? <p className={message.includes("失败") ? "notice-error" : "notice-success"} aria-live="polite">{message}</p> : null}
      <button className="btn btn-primary" disabled={loading}>
        <Upload size={17} />
        {loading ? "导入中..." : "导入数据"}
      </button>
    </form>
  );
}
