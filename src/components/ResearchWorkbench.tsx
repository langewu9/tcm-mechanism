"use client";

import { Activity, Beaker, Database, Download, FileJson, GitCompareArrows, Leaf, Route, Search, Sparkles, Table2 } from "lucide-react";
import { PaginatedTable } from "@/components/ViewportPager";
import { useMemo, useState } from "react";

type Action = "disease" | "herb" | "component" | "chembl" | "intersection" | "pathway";

type TargetRow = {
  target: string;
  normalizedTarget: string;
  matchType: string;
  targetName: string;
  genes: string;
  pathways: string;
  components: string;
  herbs: string;
  diseaseNames: string;
  herbEvidenceCount: number;
  diseaseEvidenceCount: number;
  directEvidenceCount: number;
  sources: string;
};

type NetworkPharmacologyData = {
  ok: boolean;
  summary: {
    herb: string;
    herbs?: string[];
    disease: string;
    herbTargetCount: number;
    diseaseTargetCount: number;
    strictIntersectionCount: number;
    directAssociationTargetCount: number;
    candidateTargetCount: number;
    componentCount: number;
    pathwayCount: number;
    matchedDiseaseNames?: string[];
  };
  targets: TargetRow[];
  raw: Record<string, Record<string, unknown>[]>;
};

type HerbSearchData = {
  query: string;
  queries?: string[];
  herbs?: string[];
  components?: string[];
  targets?: string[];
  links?: Record<string, unknown>[];
  summaries?: Array<{ herb: string; matchedHerbs?: string; components: number; targets: number; links: number }>;
  counts?: { herbs?: number; components?: number; targets?: number; links?: number };
};

type NameMatch = {
  query: string;
  chinese: string;
  english: string;
  latin: string;
  matchedTerms: string;
  hitCount: number;
};

type ComponentSearchData = {
  query: string;
  queries?: string[];
  resolvedQueries?: string[];
  nameMatches?: NameMatch[];
  components?: string[];
  targets?: string[];
  links?: Record<string, unknown>[];
  counts?: { components?: number; targets?: number; links?: number; previewLinks?: number };
};

type ChemblSearchData = {
  available?: boolean;
  query: string;
  queries?: string[];
  resolvedQueries?: string[];
  nameMatches?: NameMatch[];
  items?: Record<string, unknown>[];
  counts?: { molecules?: number; queriedTerms?: number };
};

type CompareComponentRow = {
  side?: "detected" | "reference";
  input?: string;
  normalizedKey?: string;
  familyKey?: string;
  chinese?: string;
  english?: string;
  latin?: string;
  matchedTerms?: string;
  status?: string;
  group?: string;
  detectedInput?: string;
  referenceInput?: string;
  detectedEnglish?: string;
  referenceEnglish?: string;
  familyName?: string;
};

type CompareSearchData = {
  detected?: CompareComponentRow[];
  reference?: CompareComponentRow[];
  exactMatches?: CompareComponentRow[];
  detectedOnly?: CompareComponentRow[];
  referenceOnly?: CompareComponentRow[];
  familyMatches?: CompareComponentRow[];
  rows?: CompareComponentRow[];
  counts?: {
    detected?: number;
    reference?: number;
    matched?: number;
    detectedOnly?: number;
    referenceOnly?: number;
    familyMatches?: number;
    matchRate?: number;
  };
};

type PathwaySearchItem = {
  stableId: string;
  name: string;
  species: string | null;
  sourceUrl: string | null;
  lastSyncedAt: string | null;
  targetAnnotations: number;
  enrichmentRecords: number;
};

type PathwaySearchData = {
  query: string;
  catalogTotal: number;
  sourceVersion: string | null;
  items: PathwaySearchItem[];
};

const tools = [
  { id: "disease" as const, label: "疾病检索", hint: "疾病 -> 中药与靶点", icon: Search },
  { id: "herb" as const, label: "中药检索", hint: "中药 -> 成分与靶点", icon: Leaf },
  { id: "component" as const, label: "成分检索", hint: "成分 -> 来源与靶点", icon: Beaker },
  { id: "chembl" as const, label: "ChEMBL", hint: "分子、结构与活性", icon: Database },
  { id: "intersection" as const, label: "靶点交集", hint: "中药靶点 ∩ 疾病靶点", icon: Activity },
  { id: "pathway" as const, label: "通路检索", hint: "Reactome 人类通路目录", icon: Route }
];

const examples: Record<Action, string> = {
  disease: "肺纤维化",
  herb: "麦冬、半夏、人参、大枣、甘草、粳米",
  component: "甘草酸",
  chembl: "甘草酸",
  intersection: "麦冬、半夏、人参、大枣、甘草、粳米",
  pathway: "Interleukin"
};

function collectRows(data: unknown): Record<string, unknown>[] {
  if (!data || typeof data !== "object") return [];
  const record = data as Record<string, unknown>;
  const preferred = ["items", "records", "links", "molecules", "activities", "intersection", "matched", "herbs", "components", "targets"];
  for (const key of preferred) {
    if (Array.isArray(record[key])) {
      return record[key].map((item: unknown) =>
        typeof item === "object" && item !== null ? (item as Record<string, unknown>) : { value: item }
      );
    }
  }
  return [];
}

function displayValue(value: unknown) {
  if (Array.isArray(value)) return value.slice(0, 5).join("、");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "-");
}

function csvValue(value: unknown) {
  const text = Array.isArray(value) ? value.join("; ") : String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const body = rows.map((row) => headers.map((header) => csvValue(row[header])).join(","));
  const blob = new Blob([`\ufeff${[headers.join(","), ...body].join("\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function metricNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function VennDiagram({ herbCount, diseaseCount, intersectionCount, herbLabel, diseaseLabel }: { herbCount: number; diseaseCount: number; intersectionCount: number; herbLabel: string; diseaseLabel: string }) {
  const herbOnly = Math.max(herbCount - intersectionCount, 0);
  const diseaseOnly = Math.max(diseaseCount - intersectionCount, 0);

  return (
    <svg viewBox="0 0 640 320" className="h-80 w-full" role="img" aria-label="中药靶点与疾病靶点韦恩图">
      <rect width="640" height="320" rx="8" fill="rgba(255,250,241,0.62)" />
      <circle cx="260" cy="165" r="116" fill="#14533d" fillOpacity="0.24" stroke="#14533d" strokeWidth="3" />
      <circle cx="380" cy="165" r="116" fill="#b94232" fillOpacity="0.22" stroke="#b94232" strokeWidth="3" />
      <text x="212" y="78" textAnchor="middle" fill="#14533d" fontSize="15" fontWeight="800">{herbLabel}</text>
      <text x="428" y="78" textAnchor="middle" fill="#b94232" fontSize="15" fontWeight="800">{diseaseLabel}</text>
      <text x="224" y="164" textAnchor="middle" fill="#14533d" fontSize="13" fontWeight="800">中药特异</text>
      <text x="224" y="193" textAnchor="middle" fill="#2b1711" fontSize="28" fontWeight="900">{metricNumber(herbOnly)}</text>
      <text x="320" y="150" textAnchor="middle" fill="#7d1d04" fontSize="13" fontWeight="900">严格交集</text>
      <text x="320" y="186" textAnchor="middle" fill="#2b1711" fontSize="34" fontWeight="900">{metricNumber(intersectionCount)}</text>
      <text x="416" y="164" textAnchor="middle" fill="#b94232" fontSize="13" fontWeight="800">疾病特异</text>
      <text x="416" y="193" textAnchor="middle" fill="#2b1711" fontSize="28" fontWeight="900">{metricNumber(diseaseOnly)}</text>
      <text x="320" y="282" textAnchor="middle" fill="rgba(43,23,17,0.62)" fontSize="12">
        中药侧靶点 {metricNumber(herbCount)} 个，疾病侧靶点 {metricNumber(diseaseCount)} 个
      </text>
    </svg>
  );
}

function CompareVennDiagram({ detectedCount, referenceCount, matchedCount }: { detectedCount: number; referenceCount: number; matchedCount: number }) {
  const detectedOnly = Math.max(detectedCount - matchedCount, 0);
  const referenceOnly = Math.max(referenceCount - matchedCount, 0);

  return (
    <svg viewBox="0 0 640 300" className="h-72 w-full" role="img" aria-label="检测成分与参考成分韦恩图">
      <rect width="640" height="300" rx="8" fill="rgba(255,250,241,0.62)" />
      <circle cx="262" cy="152" r="108" fill="#14533d" fillOpacity="0.23" stroke="#14533d" strokeWidth="3" />
      <circle cx="378" cy="152" r="108" fill="#b94232" fillOpacity="0.22" stroke="#b94232" strokeWidth="3" />
      <text x="220" y="62" textAnchor="middle" fill="#14533d" fontSize="15" fontWeight="900">检测成分</text>
      <text x="420" y="62" textAnchor="middle" fill="#b94232" fontSize="15" fontWeight="900">参考库</text>
      <text x="220" y="150" textAnchor="middle" fill="#14533d" fontSize="13" fontWeight="900">仅检测</text>
      <text x="220" y="180" textAnchor="middle" fill="#2b1711" fontSize="30" fontWeight="900">{metricNumber(detectedOnly)}</text>
      <text x="320" y="136" textAnchor="middle" fill="#7d1d04" fontSize="13" fontWeight="900">交集</text>
      <text x="320" y="174" textAnchor="middle" fill="#2b1711" fontSize="36" fontWeight="900">{metricNumber(matchedCount)}</text>
      <text x="420" y="150" textAnchor="middle" fill="#b94232" fontSize="13" fontWeight="900">仅参考</text>
      <text x="420" y="180" textAnchor="middle" fill="#2b1711" fontSize="30" fontWeight="900">{metricNumber(referenceOnly)}</text>
      <text x="320" y="258" textAnchor="middle" fill="rgba(43,23,17,0.62)" fontSize="12">
        检测 {metricNumber(detectedCount)} 个，参考 {metricNumber(referenceCount)} 个
      </text>
    </svg>
  );
}

function HerbSearchResult({ result }: { result: { elapsedMs: number; data: HerbSearchData } }) {
  const data = result.data;
  const links = Array.isArray(data.links) ? data.links : [];
  const queryLabel = data.queries?.length ? data.queries.join("、") : data.query;
  const componentRows = (data.components ?? []).map((component) => ({ component }));
  const targetRows = (data.targets ?? []).map((target) => ({ target }));

  return (
    <div>
      <div className="panel-header">
        <div>
          <h3 className="section-title-sm">中药检索结果</h3>
          <p className="section-help">{result.elapsedMs} ms · {queryLabel}</p>
        </div>
        <span className="status-badge status-success">查询完成</span>
      </div>

      <div className="space-y-4 p-5">
        <div className="np-metrics">
          <div><span>匹配中药</span><strong>{metricNumber(data.counts?.herbs ?? data.herbs?.length ?? data.queries?.length ?? 0)}</strong></div>
          <div><span>关联成分</span><strong>{metricNumber(data.counts?.components ?? data.components?.length ?? 0)}</strong></div>
          <div><span>作用靶点</span><strong>{metricNumber(data.counts?.targets ?? data.targets?.length ?? 0)}</strong></div>
          <div><span>去重证据</span><strong>{metricNumber(data.counts?.links ?? links.length)}</strong></div>
        </div>

        {data.summaries?.length ? (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th>检索词</th><th>命中中药</th><th>成分数</th><th>靶点数</th><th>去重证据</th></tr></thead>
              <tbody>
                {data.summaries.map((item) => (
                  <tr key={item.herb}>
                    <td>{item.herb}</td>
                    <td title={item.matchedHerbs || item.herb}>{item.matchedHerbs || item.herb}</td>
                    <td>{item.components}</td>
                    <td>{item.targets}</td>
                    <td>{item.links}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <div className="download-panel">
          <button type="button" onClick={() => downloadCsv(`herb_links_${queryLabel}.csv`, links)}>
            <Table2 size={15} /> 导出成分-靶点表
          </button>
          <button type="button" onClick={() => downloadCsv(`herb_components_${queryLabel}.csv`, componentRows)}>
            <Download size={15} /> 导出成分清单
          </button>
          <button type="button" onClick={() => downloadCsv(`herb_targets_${queryLabel}.csv`, targetRows)}>
            <Download size={15} /> 导出靶点清单
          </button>
          <button type="button" onClick={() => downloadJson(`herb_search_${queryLabel}.json`, data)}>
            <FileJson size={15} /> 导出完整 JSON
          </button>
        </div>
      </div>

      {links.length ? <PaginatedTable rows={links} label="成分-靶点证据" headers={["检索词", "来源库", "中药", "成分", "靶点"]} rowKey={(row, index) => `${displayValue(row.sourceQuery)}-${displayValue(row.source)}-${displayValue(row.component)}-${index}`} renderCells={(row) => <><td title={displayValue(row.sourceQuery)}>{displayValue(row.sourceQuery)}</td><td title={displayValue(row.source)}>{displayValue(row.source)}</td><td title={displayValue(row.herb)}>{displayValue(row.herb)}</td><td title={displayValue(row.component)}>{displayValue(row.component)}</td><td title={displayValue(row.targets ?? row.target)}>{displayValue(row.targets ?? row.target)}</td></>} /> : null}
      {!links.length ? <div className="empty-state">当前中药名称没有检索到成分-靶点证据，请更换关键词或检查 FastAPI 数据服务。</div> : null}
    </div>
  );
}

function ComponentSearchResult({ result }: { result: { elapsedMs: number; data: ComponentSearchData } }) {
  const data = result.data;
  const links = Array.isArray(data.links) ? data.links : [];
  const matches = data.nameMatches ?? [];
  const queryLabel = data.queries?.length ? data.queries.join("、") : data.query;
  const targetRows = (data.targets ?? []).map((target) => ({ target }));

  return (
    <div>
      <div className="panel-header">
        <div>
          <h3 className="section-title-sm">成分检索结果</h3>
          <p className="section-help">{result.elapsedMs} ms · {queryLabel}</p>
        </div>
        <span className="status-badge status-success">查询完成</span>
      </div>

      <div className="space-y-4 p-5">
        <div className="np-metrics">
          <div><span>命中成分</span><strong>{metricNumber(data.counts?.components ?? data.components?.length ?? 0)}</strong></div>
          <div><span>作用靶点</span><strong>{metricNumber(data.counts?.targets ?? data.targets?.length ?? 0)}</strong></div>
          <div><span>去重证据</span><strong>{metricNumber(data.counts?.links ?? links.length)}</strong></div>
          <div><span>预览记录</span><strong>{metricNumber(data.counts?.previewLinks ?? links.length)}</strong></div>
        </div>

        <div className="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>检索词</th><th>中文名</th><th>英文名</th><th>拉丁/规范名</th><th>同义名</th></tr></thead>
            <tbody>
              {(matches.length ? matches : [{ query: queryLabel, chinese: "", english: queryLabel, latin: "", matchedTerms: queryLabel, hitCount: 0 }]).slice(0, 12).map((item) => (
                <tr key={`${item.query}-${item.english}`}>
                  <td>{item.query}</td>
                  <td>{item.chinese || "-"}</td>
                  <td>{item.english || "-"}</td>
                  <td>{item.latin || "-"}</td>
                  <td title={item.matchedTerms}>{item.matchedTerms || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="download-panel">
          <button type="button" onClick={() => downloadCsv(`component_links_${queryLabel}.csv`, links)}>
            <Table2 size={15} /> 导出成分-靶点表
          </button>
          <button type="button" onClick={() => downloadCsv(`component_targets_${queryLabel}.csv`, targetRows)}>
            <Download size={15} /> 导出靶点清单
          </button>
          <button type="button" onClick={() => downloadJson(`component_search_${queryLabel}.json`, data)}>
            <FileJson size={15} /> 导出完整 JSON
          </button>
        </div>
      </div>

      {links.length ? <PaginatedTable rows={links} label="成分检索证据" headers={["检索词", "成分中文", "成分英文", "拉丁/规范名", "来源中药", "来源库", "靶点"]} rowKey={(row, index) => `${displayValue(row.componentEnglish ?? row.component)}-${displayValue(row.herb)}-${index}`} renderCells={(row) => <><td title={displayValue(row.sourceQuery)}>{displayValue(row.sourceQuery)}</td><td title={displayValue(row.componentChinese)}>{displayValue(row.componentChinese) || "-"}</td><td title={displayValue(row.componentEnglish ?? row.component)}>{displayValue(row.componentEnglish ?? row.component)}</td><td title={displayValue(row.componentLatin)}>{displayValue(row.componentLatin) || "-"}</td><td title={displayValue(row.herb)}>{displayValue(row.herb)}</td><td title={displayValue(row.source)}>{displayValue(row.source)}</td><td title={displayValue(row.targets ?? row.target)}>{displayValue(row.targets ?? row.target)}</td></>} /> : null}
      {!links.length ? <div className="empty-state">当前成分名称没有检索到来源中药和靶点证据，请换用中文名、英文名或拉丁/规范名。</div> : null}
    </div>
  );
}

function ChemblSearchResult({ result }: { result: { elapsedMs: number; data: ChemblSearchData } }) {
  const data = result.data;
  const items = Array.isArray(data.items) ? data.items : [];
  const matches = data.nameMatches ?? [];
  const queryLabel = data.queries?.length ? data.queries.join("、") : data.query;
  const resolvedRows = (data.resolvedQueries ?? []).map((term) => ({ term }));
  const naturalProductCount = items.filter((row) => {
    const value = row.natural_product;
    return value === true || value === 1 || value === "1" || String(value).toLowerCase() === "true";
  }).length;

  return (
    <div>
      <div className="panel-header">
        <div>
          <h3 className="section-title-sm">ChEMBL 检索结果</h3>
          <p className="section-help">{result.elapsedMs} ms · {queryLabel}</p>
        </div>
        <span className="status-badge status-success">查询完成</span>
      </div>

      <div className="space-y-4 p-5">
        <div className="np-metrics">
          <div><span>命中分子</span><strong>{metricNumber(data.counts?.molecules ?? items.length)}</strong></div>
          <div><span>解析词数</span><strong>{metricNumber(data.counts?.queriedTerms ?? data.resolvedQueries?.length ?? 1)}</strong></div>
          <div><span>天然产物</span><strong>{metricNumber(naturalProductCount)}</strong></div>
          <div><span>预览记录</span><strong>{metricNumber(Math.min(items.length, 100))}</strong></div>
        </div>

        <div className="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>检索词</th><th>中文名</th><th>英文名</th><th>拉丁/规范名</th><th>同义名</th></tr></thead>
            <tbody>
              {(matches.length ? matches : [{ query: queryLabel, chinese: "", english: queryLabel, latin: "", matchedTerms: data.resolvedQueries?.join("、") || queryLabel, hitCount: items.length }]).slice(0, 12).map((item) => (
                <tr key={`${item.query}-${item.english}`}>
                  <td>{item.query}</td>
                  <td>{item.chinese || "-"}</td>
                  <td>{item.english || "-"}</td>
                  <td>{item.latin || "-"}</td>
                  <td title={item.matchedTerms}>{item.matchedTerms || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="download-panel">
          <button type="button" onClick={() => downloadCsv(`chembl_molecules_${queryLabel}.csv`, items)}>
            <Table2 size={15} /> 导出 ChEMBL 分子表
          </button>
          <button type="button" onClick={() => downloadCsv(`chembl_queries_${queryLabel}.csv`, resolvedRows)}>
            <Download size={15} /> 导出解析词
          </button>
          <button type="button" onClick={() => downloadJson(`chembl_search_${queryLabel}.json`, data)}>
            <FileJson size={15} /> 导出完整 JSON
          </button>
        </div>
      </div>

      {items.length ? <PaginatedTable rows={items} label="ChEMBL 分子" headers={["检索词", "中文名", "英文/规范名", "拉丁/规范名", "ChEMBL ID", "分子名称", "类型", "最高阶段", "天然产物", "SMILES"]} rowKey={(row, index) => `${displayValue(row.chembl_id ?? row.molregno)}-${index}`} renderCells={(row) => <><td title={displayValue(row.sourceQuery)}>{displayValue(row.sourceQuery)}</td><td title={displayValue(row.componentChinese)}>{displayValue(row.componentChinese) || "-"}</td><td title={displayValue(row.componentEnglish)}>{displayValue(row.componentEnglish) || "-"}</td><td title={displayValue(row.componentLatin)}>{displayValue(row.componentLatin) || "-"}</td><td title={displayValue(row.chembl_id)}>{displayValue(row.chembl_id)}</td><td title={displayValue(row.pref_name)}>{displayValue(row.pref_name)}</td><td title={displayValue(row.molecule_type)}>{displayValue(row.molecule_type)}</td><td title={displayValue(row.max_phase)}>{displayValue(row.max_phase)}</td><td title={displayValue(row.natural_product)}>{displayValue(row.natural_product)}</td><td title={displayValue(row.canonical_smiles)}>{displayValue(row.canonical_smiles)}</td></>} /> : null}
      {!items.length ? <div className="empty-state">当前名称没有检索到 ChEMBL 分子记录，请换用中文名、英文名、拉丁/规范名或更具体的分子名称。</div> : null}
    </div>
  );
}

function CompareSearchResult({ result }: { result: { elapsedMs: number; data: CompareSearchData } }) {
  const data = result.data;
  const detected = data.detected ?? [];
  const reference = data.reference ?? [];
  const exactMatches = data.exactMatches ?? [];
  const detectedOnly = data.detectedOnly ?? [];
  const referenceOnly = data.referenceOnly ?? [];
  const familyMatches = data.familyMatches ?? [];
  const rows = data.rows ?? [];
  const detectedCount = data.counts?.detected ?? detected.length;
  const referenceCount = data.counts?.reference ?? reference.length;
  const matchedCount = data.counts?.matched ?? exactMatches.length;
  const matchRate = data.counts?.matchRate ?? 0;
  const normalizedRows = [
    ...detected.map((row) => ({ ...row, sideLabel: "检测成分" })),
    ...reference.map((row) => ({ ...row, sideLabel: "参考成分" }))
  ];

  return (
    <div>
      <div className="panel-header">
        <div>
          <h3 className="section-title-sm">成分比对结果</h3>
          <p className="section-help">{result.elapsedMs} ms · 检测值 vs 参考库</p>
        </div>
        <span className="status-badge status-success">查询完成</span>
      </div>

      <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="figure-card">
          <div className="figure-heading">
            <span>Venn</span>
            <div>
              <h2>检测成分 ∩ 参考库</h2>
              <p>中文、英文、拉丁名会先规范化，再计算精确交集。</p>
            </div>
          </div>
          <CompareVennDiagram detectedCount={detectedCount} referenceCount={referenceCount} matchedCount={matchedCount} />
        </div>

        <div className="space-y-4">
          <div className="np-metrics">
            <div><span>检测成分</span><strong>{metricNumber(detectedCount)}</strong></div>
            <div><span>参考成分</span><strong>{metricNumber(referenceCount)}</strong></div>
            <div><span>精确交集</span><strong>{metricNumber(matchedCount)}</strong></div>
            <div><span>匹配率</span><strong>{matchRate}%</strong></div>
          </div>
          <div className="np-metrics">
            <div><span>仅检测</span><strong>{metricNumber(data.counts?.detectedOnly ?? detectedOnly.length)}</strong></div>
            <div><span>仅参考</span><strong>{metricNumber(data.counts?.referenceOnly ?? referenceOnly.length)}</strong></div>
            <div><span>同家族候选</span><strong>{metricNumber(data.counts?.familyMatches ?? familyMatches.length)}</strong></div>
            <div><span>规范化记录</span><strong>{metricNumber(normalizedRows.length)}</strong></div>
          </div>
          <div className="download-panel">
            <button type="button" onClick={() => downloadCsv("component_compare_matches.csv", exactMatches)}>
              <Table2 size={15} /> 导出交集表
            </button>
            <button type="button" onClick={() => downloadCsv("component_compare_all.csv", rows)}>
              <Download size={15} /> 导出完整比对表
            </button>
            <button type="button" onClick={() => downloadCsv("component_compare_normalized.csv", normalizedRows)}>
              <Download size={15} /> 导出规范化清单
            </button>
            <button type="button" onClick={() => downloadJson("component_compare.json", data)}>
              <FileJson size={15} /> 导出完整 JSON
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-5 p-5 pt-0">
        <PaginatedTable rows={normalizedRows} label="规范化成分" headers={["输入来源", "原始名称", "中文名", "英文/规范名", "拉丁/规范名", "同义名", "比对键"]} rowKey={(row, index) => `${row.sideLabel}-${row.normalizedKey}-${index}`} renderCells={(row) => <><td>{row.sideLabel}</td><td title={displayValue(row.input)}>{displayValue(row.input)}</td><td title={displayValue(row.chinese)}>{displayValue(row.chinese) || "-"}</td><td title={displayValue(row.english)}>{displayValue(row.english)}</td><td title={displayValue(row.latin)}>{displayValue(row.latin) || "-"}</td><td title={displayValue(row.matchedTerms)}>{displayValue(row.matchedTerms)}</td><td title={displayValue(row.normalizedKey)}>{displayValue(row.normalizedKey)}</td></>} />

        <PaginatedTable rows={rows} label="成分比对" headers={["分组", "检测输入", "参考输入", "原始名称", "中文名", "英文/规范名", "拉丁/规范名", "状态"]} rowKey={(row, index) => `${row.group}-${row.normalizedKey}-${index}`} renderCells={(row) => <><td>{row.group || "-"}</td><td title={displayValue(row.detectedInput)}>{displayValue(row.detectedInput)}</td><td title={displayValue(row.referenceInput)}>{displayValue(row.referenceInput)}</td><td title={displayValue(row.input)}>{displayValue(row.input)}</td><td title={displayValue(row.chinese)}>{displayValue(row.chinese) || "-"}</td><td title={displayValue(row.english)}>{displayValue(row.english)}</td><td title={displayValue(row.latin)}>{displayValue(row.latin) || "-"}</td><td>{row.status || "-"}</td></>} />

        {familyMatches.length ? <PaginatedTable rows={familyMatches} label="同家族候选" headers={["家族名称", "检测输入", "参考输入", "检测规范名", "参考规范名", "状态"]} rowKey={(row, index) => `${row.familyKey}-${index}`} renderCells={(row) => <><td>{row.familyName || row.familyKey}</td><td title={displayValue(row.detectedInput)}>{displayValue(row.detectedInput)}</td><td title={displayValue(row.referenceInput)}>{displayValue(row.referenceInput)}</td><td title={displayValue(row.detectedEnglish)}>{displayValue(row.detectedEnglish)}</td><td title={displayValue(row.referenceEnglish)}>{displayValue(row.referenceEnglish)}</td><td>{row.status || "同家族候选"}</td></>} /> : null}
      </div>
    </div>
  );
}

function PathwaySearchResult({ result }: { result: { elapsedMs: number; data: PathwaySearchData } }) {
  const data = result.data;
  const queryLabel = data.query || "全部人类通路";

  return (
    <div>
      <div className="panel-header">
        <div>
          <h3 className="section-title-sm">通路检索结果</h3>
          <p className="section-help">{result.elapsedMs} ms · Reactome v{data.sourceVersion || "未知"} · {queryLabel}</p>
        </div>
        <span className="status-badge status-success">目录已同步</span>
      </div>
      <div className="space-y-4 p-5">
        <div className="np-metrics">
          <div><span>人类通路目录</span><strong>{metricNumber(data.catalogTotal)}</strong></div>
          <div><span>本次命中</span><strong>{metricNumber(data.items.length)}</strong></div>
          <div><span>靶点注释</span><strong>{metricNumber(data.items.reduce((sum, item) => sum + item.targetAnnotations, 0))}</strong></div>
          <div><span>富集记录</span><strong>{metricNumber(data.items.reduce((sum, item) => sum + item.enrichmentRecords, 0))}</strong></div>
        </div>
        <div className="download-panel">
          <button type="button" onClick={() => downloadCsv(`reactome_pathways_${queryLabel}.csv`, data.items)}><Table2 size={15} /> 导出通路目录</button>
          <button type="button" onClick={() => downloadJson(`reactome_pathways_${queryLabel}.json`, data)}><FileJson size={15} /> 导出完整 JSON</button>
        </div>
      </div>
      {data.items.length ? <PaginatedTable rows={data.items} label="Reactome 人类通路" headers={["稳定 ID", "通路名称", "物种", "靶点注释", "富集记录", "最近同步", "Reactome"]} rowKey={(row) => row.stableId} renderCells={(row) => <><td>{row.stableId}</td><td title={row.name}>{row.name}</td><td>{row.species || "Homo sapiens"}</td><td>{row.targetAnnotations}</td><td>{row.enrichmentRecords}</td><td>{row.lastSyncedAt ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(new Date(row.lastSyncedAt)) : "-"}</td><td>{row.sourceUrl ? <a className="font-bold text-pine underline" href={row.sourceUrl} target="_blank" rel="noreferrer">打开</a> : "-"}</td></>} /> : <div className="empty-state">未找到匹配的 Reactome 人类通路，请尝试通路名称或稳定 ID，例如 R-HSA-449147。</div>}
    </div>
  );
}

function IntersectionResult({ result }: { result: { elapsedMs: number; data: NetworkPharmacologyData } }) {
  const data = result.data;
  const strictRows = data.targets.filter((row) => row.matchType.includes("交集"));
  const herbLabel = data.summary.herbs?.length ? data.summary.herbs.join("、") : data.summary.herb;
  const resolvedDiseases = data.summary.matchedDiseaseNames?.slice(0, 6) ?? [];

  return (
    <div>
      <div className="panel-header">
        <div>
          <h3 className="section-title-sm">靶点交集结果</h3>
          <p className="section-help">{result.elapsedMs} ms · {herbLabel} ∩ {data.summary.disease}</p>
        </div>
        <span className="status-badge status-success">查询完成</span>
      </div>

      <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="figure-card">
          <div className="figure-heading">
            <span>Venn</span>
            <div>
              <h2>中药靶点 ∩ 疾病靶点</h2>
              <p>严格交集只来自中药侧靶点集合与疾病侧靶点集合的相同靶点。</p>
            </div>
          </div>
          <VennDiagram
            herbCount={data.summary.herbTargetCount}
            diseaseCount={data.summary.diseaseTargetCount}
            intersectionCount={data.summary.strictIntersectionCount}
            herbLabel={herbLabel}
            diseaseLabel={data.summary.disease}
          />
        </div>

        <div className="space-y-4">
          <div className="np-metrics">
            <div><span>中药靶点</span><strong>{metricNumber(data.summary.herbTargetCount)}</strong></div>
            <div><span>疾病靶点</span><strong>{metricNumber(data.summary.diseaseTargetCount)}</strong></div>
            <div><span>严格交集</span><strong>{metricNumber(data.summary.strictIntersectionCount)}</strong></div>
            <div><span>关联成分</span><strong>{metricNumber(data.summary.componentCount)}</strong></div>
          </div>
          {resolvedDiseases.length ? <div className="notice-success">中文疾病名匹配到：{resolvedDiseases.join("、")}</div> : null}
          <div className="download-panel">
            <button type="button" onClick={() => downloadCsv(`strict_intersection_${herbLabel}_${data.summary.disease}.csv`, strictRows)}>
              <Table2 size={15} /> 导出严格交集表
            </button>
            <button type="button" onClick={() => downloadCsv(`all_candidates_${herbLabel}_${data.summary.disease}.csv`, data.targets)}>
              <Download size={15} /> 导出完整候选表
            </button>
            <button type="button" onClick={() => downloadJson(`intersection_${herbLabel}_${data.summary.disease}.json`, data)}>
              <FileJson size={15} /> 导出完整 JSON
            </button>
          </div>
        </div>
      </div>

      {strictRows.length ? <PaginatedTable rows={strictRows} label="严格交集靶点" headers={["交集靶点", "相关成分", "对应通路", "中药证据", "疾病证据", "来源"]} rowKey={(row) => row.normalizedTarget} renderCells={(row) => <><td title={row.target}>{row.target}</td><td title={row.components}>{row.components || "-"}</td><td title={row.pathways}>{row.pathways || "待富集"}</td><td>{row.herbEvidenceCount}</td><td>{row.diseaseEvidenceCount}</td><td title={row.sources}>{row.sources || "-"}</td></>} /> : null}
      {!strictRows.length ? <div className="empty-state">当前中药靶点和疾病靶点没有严格交集，请更换中药或疾病名称。</div> : null}
    </div>
  );
}

export function ResearchWorkbench() {
  const [active, setActive] = useState<Action>("herb");
  const [form, setForm] = useState<Record<string, string>>({
    query: "麦冬、半夏、人参、大枣、甘草、粳米",
    herbs: "麦冬、半夏、人参、大枣、甘草、粳米",
    disease: "肺纤维化",
    detected: "甘草酸、甘草苷、人参皂苷Rg1",
    reference: "Glycyrrhizic acid, Liquiritin, Ginsenoside Rg1"
  });
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const rows = useMemo(() => collectRows(result?.data), [result]);
  const columns = useMemo(() => {
    const keys = rows.flatMap((row) => Object.keys(row));
    return Array.from(new Set(keys)).slice(0, 6);
  }, [rows]);

  function changeTool(action: Action) {
    setActive(action);
    setResult(null);
    setError("");
    if (["disease", "herb", "component", "chembl", "pathway"].includes(action)) {
      setForm((current) => ({ ...current, query: examples[action] }));
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const startedAt = Date.now();
      const response = await fetch(active === "intersection" ? "/api/network-pharmacology" : "/api/research", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(active === "intersection" ? { herb: form.herbs, disease: form.disease } : { action: active, ...form })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "检索失败");
      setResult(active === "intersection" ? { ok: true, action: active, elapsedMs: Date.now() - startedAt, data } : data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "检索失败");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="page-kicker">PHARMACOLOGY SEARCH</p>
        <h2 className="page-title">中医药理检索</h2>
        <p className="page-description">统一检索本地中医药数据库与 ChEMBL，快速完成疾病、中药、成分和靶点关联查询。</p>
      </div>

      <div className="tool-tabs" role="tablist" aria-label="检索类型">
        {tools.map((tool) => {
          const Icon = tool.icon;
          return (
            <button key={tool.id} className={`tool-tab ${active === tool.id ? "is-active" : ""}`} onClick={() => changeTool(tool.id)} type="button">
              <Icon size={17} />
              <span><strong>{tool.label}</strong><small>{tool.hint}</small></span>
            </button>
          );
        })}
      </div>

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <form className="panel space-y-4 p-5" onSubmit={submit}>
          <div>
            <h3 className="section-title-sm">{tools.find((tool) => tool.id === active)?.label}</h3>
            <p className="section-help">{tools.find((tool) => tool.id === active)?.hint}</p>
          </div>
          {active === "herb" ? (
            <label className="form-label">中药名称（可输入多个）
              <textarea className="field mt-2 min-h-28" value={form.query || ""} onChange={(event) => setForm({ ...form, query: event.target.value })} placeholder="例如：麦冬、半夏、人参、大枣、甘草、粳米" />
            </label>
          ) : active === "component" ? (
            <label className="form-label">成分名称（中文 / 英文 / 拉丁）
              <input className="field mt-2" value={form.query || ""} onChange={(event) => setForm({ ...form, query: event.target.value })} placeholder="例如：甘草酸 / Glycyrrhizic acid" />
            </label>
          ) : active === "chembl" ? (
            <label className="form-label">分子名称（中文 / 英文 / 拉丁 / ChEMBL 规范名）
              <input className="field mt-2" value={form.query || ""} onChange={(event) => setForm({ ...form, query: event.target.value })} placeholder="例如：甘草酸 / Glycyrrhizic acid" />
            </label>
          ) : ["disease", "pathway"].includes(active) ? (
            <label className="form-label">检索词
              <input className="field mt-2" value={form.query || ""} onChange={(event) => setForm({ ...form, query: event.target.value })} placeholder={`例如：${examples[active]}`} />
            </label>
          ) : active === "intersection" ? (
            <>
              <label className="form-label">中药名称（可输入多个）
                <textarea className="field mt-2 min-h-28" value={form.herbs} onChange={(event) => setForm({ ...form, herbs: event.target.value })} placeholder="例如：麦冬、半夏、人参、大枣、甘草、粳米" />
              </label>
              <label className="form-label">疾病名称（支持中文）
                <input className="field mt-2" value={form.disease} onChange={(event) => setForm({ ...form, disease: event.target.value })} placeholder="例如：肺纤维化" />
              </label>
            </>
          ) : (
            <>
              <label className="form-label">检测成分（中文 / 英文 / 拉丁，可多个）
                <textarea className="field mt-2 min-h-28" value={form.detected} onChange={(event) => setForm({ ...form, detected: event.target.value })} placeholder="例如：甘草酸、甘草苷、人参皂苷Rg1" />
              </label>
              <label className="form-label">参考成分（中文 / 英文 / 拉丁，可多个）
                <textarea className="field mt-2 min-h-28" value={form.reference} onChange={(event) => setForm({ ...form, reference: event.target.value })} placeholder="例如：Glycyrrhizic acid, Liquiritin, Ginsenoside Rg1" />
              </label>
            </>
          )}
          {error ? <div className="notice-error">{error}</div> : null}
          <button className="btn btn-primary w-full" disabled={loading} type="submit">
            <Search size={17} />{loading ? "正在检索..." : "开始检索"}
          </button>
        </form>

        <section className="panel min-h-[460px] overflow-hidden">
          {active === "herb" && result ? (
            <HerbSearchResult result={result} />
          ) : active === "component" && result ? (
            <ComponentSearchResult result={result} />
          ) : active === "chembl" && result ? (
            <ChemblSearchResult result={result} />
          ) : active === "pathway" && result ? (
            <PathwaySearchResult result={result} />
          ) : active === "intersection" && result ? (
            <IntersectionResult result={result} />
          ) : (
            <>
              <div className="panel-header">
                <div><h3 className="section-title-sm">检索结果</h3><p className="section-help">{result ? `${result.elapsedMs} ms` : "等待检索"}</p></div>
                {result ? <span className="status-badge status-success">查询完成</span> : null}
              </div>
              {!result ? (
                <div className="empty-state"><Sparkles size={28} /><strong>从左侧开始检索</strong><p>结果会以摘要和表格呈现，便于快速筛选与后续分析。</p></div>
              ) : rows.length ? (
                <PaginatedTable rows={rows} label="检索结果" headers={columns} rowKey={(_, index) => String(index)} renderCells={(row) => <>{columns.map((column) => <td key={column} title={displayValue(row[column])}>{displayValue(row[column])}</td>)}</>} />
              ) : (
                <div className="p-5">
                  <div className="notice-success">查询已完成。结果为结构化汇总，详见下方数据详情。</div>
                  <dl className="result-summary">{Object.entries(result.data || {}).filter(([, value]) => typeof value !== "object").map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>)}</dl>
                </div>
              )}
              {result ? <details className="raw-details"><summary>查看完整返回数据</summary><pre>{JSON.stringify(result.data, null, 2)}</pre></details> : null}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
