"use client";

import { Download, FlaskConical, FileText } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

type CaseOption = {
  id: string;
  title: string;
  symptoms: string;
};

export function AnalysisWorkbench({ cases }: { cases: CaseOption[] }) {
  const router = useRouter();
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(formData: FormData) {
    setLoading(true);
    setError("");
    setResult(null);
    const payload = Object.fromEntries(formData);
    const response = await fetch("/api/analysis/tasks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    setLoading(false);
    if (!response.ok) {
      setError(data.error || "分析失败");
      return;
    }
    setResult(data.item);
    router.refresh();
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
      <form action={submit} className="panel space-y-4 p-5">
        <div>
          <h2 className="text-lg font-black">证候-方药-靶点分析</h2>
          <p className="mt-1 text-sm text-ink/58">输入医案或选择已保存医案，自动生成分析链路。</p>
        </div>
        <label className="form-label">任务名称<input className="field mt-2" name="name" defaultValue="中风病医案网络药理分析" placeholder="任务名称" /></label>
        <label className="form-label">关联医案<select className="field mt-2" name="caseId" defaultValue="">
          <option value="">不绑定医案</option>
          {cases.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title}
            </option>
          ))}
        </select></label>
        <label className="form-label">分析问题<textarea className="field mt-2 min-h-44" name="query" placeholder="输入症状、证候、方药或希望验证的研究问题" required /></label>
        {error ? <p className="notice-error" role="alert">{error}</p> : null}
        <button className="btn btn-primary" disabled={loading}>
          <FlaskConical size={17} />
          {loading ? "分析中..." : "开始分析"}
        </button>
      </form>
      <section className="panel min-h-[360px] p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-black">最新分析结果</h2>
          {result?.result ? (
            <div className="flex gap-2">
              <a className="btn btn-secondary text-sm" href={`/api/analysis/results/${result.result.id}/export/csv`}>
                <Download size={15} />
                CSV
              </a>
              <a className="btn btn-secondary text-sm" href={`/api/analysis/results/${result.result.id}/export/pdf`}>
                <FileText size={15} />
                PDF
              </a>
            </div>
          ) : null}
        </div>
        {result?.result ? (
          <div className="space-y-4">
            <p className="rounded-md bg-cloud p-4 leading-7">{result.result.summary}</p>
            <Evidence evidenceJson={result.result.evidenceJson} />
          </div>
        ) : (
          <div className="empty-state min-h-64"><FlaskConical size={26} /><strong>等待分析任务</strong><p>提交研究问题后，系统会在这里展示摘要、证据条目和导出入口。</p></div>
        )}
      </section>
    </div>
  );
}

function Evidence({ evidenceJson }: { evidenceJson: string }) {
  const evidence = JSON.parse(evidenceJson) as Record<string, string[] | string>;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {Object.entries(evidence).map(([key, value]) => (
        <div key={key} className="rounded-md border border-pine/10 bg-white/65 p-3">
          <p className="text-xs font-bold uppercase text-pine">{key}</p>
          <p className="mt-1 text-sm leading-6">{Array.isArray(value) ? value.join("、") : value}</p>
        </div>
      ))}
    </div>
  );
}
