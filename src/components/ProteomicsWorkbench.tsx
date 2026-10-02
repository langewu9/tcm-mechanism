"use client";

import { Activity, Database, Network, ShieldCheck, Upload } from "lucide-react";
import { useState } from "react";

import { NetworkGraph, type NetworkData } from "@/components/NetworkGraph";

type ProteomicsResult = {
  summary: {
    selectedRowCount: number;
    uniqueLabelCount: number;
    normalizedCount: number;
    unmappedCount: number;
    localAnnotatedCount: number;
    referenceCount: number;
    candidateOverlapCount: number;
    pathwayCount: number;
    enrichmentMode: string;
    enrichmentNote: string;
  };
  rows: Array<{ index: number; originalLabel: string; symbol: string | null; geneName: string | null; log2FoldChange: number | null; fdr: number | null; direction: string | null }>;
  unmapped: string[];
  topNodes: Array<{ symbol: string; degree: number; log2FoldChange: number | null; fdr: number | null; direction: string | null; pathways: string[] }>;
  pathways: Array<{ name: string; stableId: string }>;
  validation: { referenceTargets: string[]; overlap: string[]; proteomicsOnly: string[]; referenceOnly: string[] };
  network: NetworkData;
};

function compact(value: number | null | undefined) {
  return value == null ? "-" : Number(value).toPrecision(4);
}

function downloadJson(filename: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function ProteomicsWorkbench() {
  const [result, setResult] = useState<ProteomicsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function submit(formData: FormData) {
    setLoading(true);
    setError("");
    setMessage("");
    setResult(null);
    try {
      const response = await fetch("/api/proteomics", { method: "POST", body: formData });
      const data = await response.json();
      if (!response.ok) {
        setError(data.error || "蛋白组学分析失败");
        return;
      }
      setResult(data.analysis.result as ProteomicsResult);
      setMessage(`分析完成：筛选 ${data.analysis.selectedRowCount.toLocaleString()} 行，规范化 ${data.analysis.normalizedCount.toLocaleString()} 个标识。`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "网络请求失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[430px_minmax(0,1fr)]">
        <form action={submit} className="panel space-y-4 p-5">
          <div>
            <p className="page-kicker">PROTEOMICS EVIDENCE</p>
            <h2 className="text-lg font-black">差异蛋白批量分析</h2>
            <p className="mt-1 text-sm leading-6 text-ink/58">上传差异蛋白表，按阈值筛选后与本地基因、靶点、通路和候选靶点进行交叉验证。</p>
          </div>
          <label className="form-label">分析名称<input className="field mt-2" name="name" defaultValue="差异蛋白组学分析" /></label>
          <label className="form-label">数据说明<textarea className="field mt-2 min-h-20" name="description" placeholder="样本来源、疾病模型、实验组与对照组说明" /></label>
          <label className="form-label">差异蛋白文件<input className="field mt-2" name="file" type="file" accept=".csv,.xls,.xlsx" required /></label>
          <div className="rounded-md border border-pine/10 bg-cloud/60 p-3 text-xs leading-5 text-ink/60">
            自动识别常见字段；如果表头特殊，请手动填写实际列名。基因列和蛋白列至少填写或自动识别一个。
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="form-label">基因列<input className="field mt-2" name="geneColumn" placeholder="gene_symbol / 基因符号" /></label>
            <label className="form-label">蛋白列<input className="field mt-2" name="proteinColumn" placeholder="protein_name / 蛋白名称" /></label>
            <label className="form-label">log2FC 列<input className="field mt-2" name="log2FcColumn" placeholder="log2FC" /></label>
            <label className="form-label">FDR 列<input className="field mt-2" name="fdrColumn" placeholder="FDR / padj" /></label>
            <label className="form-label">P 值列<input className="field mt-2" name="pValueColumn" placeholder="pvalue" /></label>
            <label className="form-label">方向列<input className="field mt-2" name="directionColumn" placeholder="direction" /></label>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="form-label">|log2FC| ≥<input className="field mt-2" name="log2FcMin" type="number" min="0" step="0.1" defaultValue="1" /></label>
            <label className="form-label">FDR ≤<input className="field mt-2" name="fdrMax" type="number" min="0" max="1" step="0.01" defaultValue="0.05" /></label>
            <label className="form-label">P 值 ≤<input className="field mt-2" name="pValueMax" type="number" min="0" max="1" step="0.01" defaultValue="0.05" /></label>
          </div>
          <label className="form-label">候选靶点（可选）<textarea className="field mt-2 min-h-24" name="referenceTargets" placeholder="粘贴第 3 项网络药理学得到的候选靶点，例如 AKT1, IL6, MAPK1" /></label>
          <div className="rounded-md border border-amber-700/15 bg-amber-50/70 p-3 text-xs leading-5 text-amber-950/75">
            当前为本地安全模式：上传内容只在本项目数据库内处理，不会自动发送到 MyGene 或 Reactome。
          </div>
          {error ? <p className="notice-error" role="alert">{error}</p> : null}
          {message ? <p className="notice-success" role="status">{message}</p> : null}
          <button className="btn btn-primary" disabled={loading}>
            <Upload size={17} />
            {loading ? "分析中..." : "上传并分析"}
          </button>
        </form>

        <section className="panel min-h-[420px] p-5">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div><h2 className="text-lg font-black">分析结果</h2><p className="section-help">本地标识映射、靶点-通路网络、degree 排名和候选交集。</p></div>
            {result ? <button type="button" className="btn btn-secondary text-sm" onClick={() => downloadJson("proteomics_analysis.json", result)}>导出 JSON</button> : null}
          </div>
          {result ? <ProteomicsResultView result={result} /> : <div className="empty-state min-h-72"><Activity size={28} /><strong>等待蛋白组学数据</strong><p>上传 CSV、XLS 或 XLSX 后，系统会保存分析批次并生成可复核结果。</p></div>}
        </section>
      </div>
      {result?.network ? <NetworkGraph network={result.network} title="差异蛋白-通路证据网络" description="节点大小按本地已知通路关联 degree 展示；未在本地知识库中注释的蛋白仍保留在结果中。" /> : null}
    </div>
  );
}

function Metric({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return <div className="rounded-md border border-pine/10 bg-white/70 p-3"><span className="text-xs text-ink/55">{label}</span><strong className="mt-1 block text-xl font-black text-pine">{value}</strong>{note ? <small className="mt-1 block text-ink/50">{note}</small> : null}</div>;
}

function ProteomicsResultView({ result }: { result: ProteomicsResult }) {
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="通过筛选" value={result.summary.selectedRowCount} />
        <Metric label="唯一标识" value={result.summary.uniqueLabelCount} />
        <Metric label="本地规范化" value={result.summary.normalizedCount} />
        <Metric label="本地注释" value={result.summary.localAnnotatedCount} />
        <Metric label="通路" value={result.summary.pathwayCount} />
        <Metric label="候选交集" value={result.summary.candidateOverlapCount} />
      </div>
      <div className="flex items-start gap-3 rounded-md border border-pine/10 bg-cloud/60 p-3 text-sm leading-6">
        <ShieldCheck size={18} className="mt-1 shrink-0 text-pine" />
        <span>{result.summary.enrichmentNote}</span>
      </div>

      <section>
        <div className="mb-2 flex items-center gap-2"><Network size={17} className="text-pine" /><h3 className="font-black">Top degree 蛋白</h3></div>
        <div className="overflow-x-auto"><table className="data-table"><thead><tr><th>排名</th><th>基因符号</th><th>degree</th><th>log2FC</th><th>FDR</th><th>方向</th><th>本地通路</th></tr></thead><tbody>{result.topNodes.slice(0, 15).map((row, index) => <tr key={row.symbol}><td>{index + 1}</td><td className="font-bold">{row.symbol}</td><td>{row.degree}</td><td>{compact(row.log2FoldChange)}</td><td>{compact(row.fdr)}</td><td>{row.direction || "-"}</td><td title={row.pathways.join("、")}>{row.pathways.slice(0, 2).join("、") || "-"}</td></tr>)}</tbody></table></div>
      </section>

      <section>
        <div className="mb-2 flex items-center gap-2"><Database size={17} className="text-pine" /><h3 className="font-black">与候选靶点互相验证</h3></div>
        {result.summary.referenceCount ? <div className="grid gap-3 md:grid-cols-3"><div className="rounded-md border border-pine/10 p-3"><p className="text-xs text-ink/55">共同靶点</p><p className="mt-1 font-black text-pine">{result.validation.overlap.join("、") || "无"}</p></div><div className="rounded-md border border-pine/10 p-3"><p className="text-xs text-ink/55">蛋白组学特有</p><p className="mt-1 text-sm leading-6">{result.validation.proteomicsOnly.slice(0, 20).join("、") || "无"}</p></div><div className="rounded-md border border-pine/10 p-3"><p className="text-xs text-ink/55">候选靶点未检出</p><p className="mt-1 text-sm leading-6">{result.validation.referenceOnly.slice(0, 20).join("、") || "无"}</p></div></div> : <p className="rounded-md bg-cloud p-3 text-sm text-ink/60">本次未填写候选靶点，因此只输出蛋白组学内部结果；可将网络药理学候选靶点粘贴到左侧再次分析。</p>}
      </section>

      <section>
        <div className="mb-2 flex items-center gap-2"><Database size={17} className="text-pine" /><h3 className="font-black">本地通路注释</h3></div>
        {result.pathways.length ? <div className="flex flex-wrap gap-2">{result.pathways.slice(0, 30).map((pathway) => <span key={pathway.stableId} className="rounded-full border border-pine/15 bg-cloud px-3 py-1 text-xs">{pathway.name}</span>)}</div> : <p className="text-sm text-ink/55">当前蛋白未命中本地通路注释。</p>}
      </section>

      {result.unmapped.length ? <p className="text-xs leading-5 text-ink/50">未映射标识（前 30 个）：{result.unmapped.slice(0, 30).join("、")}</p> : null}
    </div>
  );
}
