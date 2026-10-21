import { useState } from "react";
import type { NetworkPharmacologyResult, ReactomeEnrichmentResult } from "../api/network";

type CountDatum = { name: string; value: number; fdr?: number; stableId?: string };
const COLORS = ["#9c2b22", "#c89b3c", "#b7682f", "#9b6b34"];

function count(value: number) {
  return value.toLocaleString("zh-CN");
}

function shortened(label: string) {
  return label.length > 22 ? `${label.slice(0, 21)}…` : label;
}

// Adapted from main's query-scoped overview and component/pathway bar charts.
function CountChart({ panel, title, caption, data, unit = "靶点", emptyMessage = "本次查询暂无可展示的数据。" }: {
  panel: string;
  title: string;
  caption: string;
  data: CountDatum[];
  unit?: string;
  emptyMessage?: string;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const maximum = Math.max(...data.map((row) => row.value), 1);
  const width = 720;
  const labelWidth = 230;
  const plotWidth = 420;
  const rowHeight = 36;
  const height = Math.max(data.length * rowHeight + 50, 140);
  const selectedRow = selected === null ? null : data[selected];
  const ticks = [...new Set([0, 0.25, 0.5, 0.75, 1].map((position) => Math.round(maximum * position)))];
  const hasFdr = data.some((row) => row.fdr !== undefined);
  const describe = (row: CountDatum) => `${row.name}：${count(row.value)} 个${unit}${row.fdr === undefined ? "" : ` · FDR ${row.fdr.toExponential(2)}`}${row.stableId ? ` · ${row.stableId}` : ""}`;

  return <section className="figure-card" style={{ marginTop: "1rem" }}>
    <div className="figure-heading"><span>{panel}</span><div><h2>{title}</h2><p>{caption}</p></div></div>
    {!data.length ? <div className="empty-state" style={{ minHeight: "9rem" }}>{emptyMessage}</div> : <>
      <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label={title} style={{ display: "block", width: "100%" }}>
        {ticks.map((value) => <g key={value}>
          <line x1={labelWidth + plotWidth * value / maximum} x2={labelWidth + plotWidth * value / maximum} y1={8} y2={height - 31} stroke="#ded3c2" strokeDasharray="3 3" />
          <text x={labelWidth + plotWidth * value / maximum} y={height - 10} textAnchor="middle" fontSize={12} fill="#6b5344">{count(value)}</text>
        </g>)}
        {data.map((row, index) => {
          const y = 12 + index * rowHeight;
          return <g key={`${row.name}-${index}`} tabIndex={0} role="button" aria-label={describe(row)} aria-pressed={selected === index}
            onMouseEnter={() => setSelected(index)} onFocus={() => setSelected(index)} onClick={() => setSelected(index)}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelected(index); } }}>
            <title>{describe(row)}</title>
            <rect x={0} y={y - 4} width={width} height={rowHeight} rx={4} fill={selected === index ? "rgba(139,37,0,.06)" : "transparent"} />
            <text x={labelWidth - 12} y={y + 18} textAnchor="end" fontSize={13} fill="#2c1810">{shortened(row.name)}</text>
            <rect x={labelWidth} y={y} width={plotWidth * row.value / maximum} height={24} rx={4} fill={COLORS[index % COLORS.length]} />
            <text x={labelWidth + plotWidth * row.value / maximum + 8} y={y + 17} fontSize={13} fill="#2c1810">{count(row.value)}</text>
          </g>;
        })}
      </svg>
      <p className="section-help" aria-live="polite" style={{ minHeight: "1.5rem", overflowWrap: "anywhere" }}>{selectedRow ? describe(selectedRow) : "指向、点击或用键盘选择条形，可查看完整名称与计数。"}</p>
      <details style={{ marginTop: ".4rem" }}><summary className="section-help">查看图表数据表</summary><div className="table-scroll"><table className="data-table"><thead><tr><th>名称</th><th>{unit}数</th>{hasFdr && <th>FDR</th>}</tr></thead><tbody>{data.map((row, index) => <tr key={`${row.name}-${index}`}><td>{row.name}</td><td>{count(row.value)}</td>{hasFdr && <td>{row.fdr?.toExponential(2) ?? "—"}</td>}</tr>)}</tbody></table></div></details>
    </>}
  </section>;
}

export function candidateComposition(result: NetworkPharmacologyResult) {
  const { strictIntersectionCount: strict, directAssociationTargetCount: direct, candidateTargetCount: total } = result.summary;
  if (result.limits?.targetsTruncated || ![strict, direct, total].every((value) => Number.isSafeInteger(value) && value >= 0)
    || Object.values(result.rawLimits?.inputRelationsTruncated ?? {}).some(Boolean)
    || strict > total || direct > total || strict + direct < total) return null;
  return { strict, directOnly: total - strict, overlap: strict + direct - total, total };
}

// main's Prep B donut is retained with mutually exclusive slices: a direct
// association that is also a strict intersection must not be counted twice.
function CandidateComposition({ result }: { result: NetworkPharmacologyResult }) {
  const value = candidateComposition(result);
  const radius = 74;
  const circumference = 2 * Math.PI * radius;
  return <section className="figure-card" style={{ marginTop: "1rem" }}>
    <div className="figure-heading"><span>Prep B</span><div><h2>候选靶点构成</h2><p>区分严格交集与仅直接关联候选；同时具有两类证据的靶点归入严格交集，避免重复计数。</p></div></div>
    {!value ? <div className="empty-state">候选集已截断或统计不完整，暂不绘制构成比例；原始计数仍保留在概览和导出中。</div>
      : !value.total ? <div className="empty-state">本次查询没有候选靶点。</div> : <>
        <svg viewBox="0 0 360 245" role="img" aria-label={`候选靶点 ${value.total} 个，严格交集 ${value.strict} 个，仅直接关联 ${value.directOnly} 个`} style={{ display: "block", width: "100%", maxHeight: "18rem" }}>
          <title>{`候选靶点构成：严格交集 ${value.strict}，仅直接关联 ${value.directOnly}；重叠 ${value.overlap} 已归入严格交集。`}</title>
          <circle cx={180} cy={115} r={radius} fill="none" stroke="#b94232" strokeWidth={36} />
          <circle cx={180} cy={115} r={radius} fill="none" stroke="#9c2b22" strokeWidth={36}
            strokeDasharray={`${circumference * value.strict / value.total} ${circumference}`} transform="rotate(-90 180 115)" />
          <text x={180} y={113} textAnchor="middle" fill="#2c1810" fontSize={30} fontWeight={700}>{count(value.total)}</text>
          <text x={180} y={135} textAnchor="middle" fill="#6b5344" fontSize={13}>去重候选靶点</text>
          <rect x={52} y={221} width={11} height={11} fill="#9c2b22" /><text x={70} y={231} fill="#2c1810" fontSize={13}>严格交集 {count(value.strict)}</text>
          <rect x={193} y={221} width={11} height={11} fill="#b94232" /><text x={211} y={231} fill="#2c1810" fontSize={13}>仅直接关联 {count(value.directOnly)}</text>
        </svg>
        <p className="section-help">直接关联共有 {count(result.summary.directAssociationTargetCount)} 个，其中 {count(value.overlap)} 个也属于严格交集。图中两部分合计 {count(value.total)} 个去重候选。</p>
      </>}
  </section>;
}

export function NetworkPharmacologyCharts({ result, reactome = null }: { result: NetworkPharmacologyResult; reactome?: ReactomeEnrichmentResult | null }) {
  return <section aria-label="本次查询统计图">
    <CountChart panel="Prep A" title="靶点比对概览" caption="中药侧、疾病侧、严格交集和直接关联分别计数；各条形用于比较，不相加作为总数。" data={result.charts.overlap} />
    <CandidateComposition result={result} />
    <CountChart panel="Prep C" title="关联成分 Top 20" caption="当前查询关联成分的靶点覆盖数，按覆盖数排序；同一靶点可被多个成分关联。" data={result.charts.components.slice(0, 20).map((row) => ({ name: row.name, value: row.targets }))} />
    {reactome ? <CountChart key={`reactome-${reactome.retrievedAt}`} panel="Prep D" title="Reactome 富集通路" caption="按 FDR 升序展示前 12 条查询级统计富集结果，条形表示 Reactome 返回的命中实体数；本地目录图统计的是已登记通路的靶点覆盖数，全部富集结果可在下方导出。"
      unit="命中实体" emptyMessage="本次 Reactome 分析已完成，没有返回符合当前筛选阈值的显著通路。"
      data={[...reactome.pathways].sort((left, right) => left.fdr - right.fdr).slice(0, 12).map((row) => ({ name: row.name, value: row.matchedEntities, fdr: row.fdr, stableId: row.stableId }))} />
      : <CountChart key="local-pathways" panel="Prep D" title="候选靶点的本地通路注释" caption="当前候选靶点在已导入目录中的通路覆盖数；这是本地目录注释统计，Reactome 成功完成后的统计富集结果将在此展示。" data={result.charts.pathways.slice(0, 20).map((row) => ({ name: row.name, value: row.targets }))} />}
  </section>;
}
