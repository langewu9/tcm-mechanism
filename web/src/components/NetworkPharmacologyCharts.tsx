import { useState } from "react";
import type { NetworkPharmacologyResult } from "../api/network";

type CountDatum = { name: string; value: number };
const COLORS = ["#9c2b22", "#c89b3c", "#b7682f", "#9b6b34"];

function count(value: number) {
  return value.toLocaleString("zh-CN");
}

function shortened(label: string) {
  return label.length > 22 ? `${label.slice(0, 21)}…` : label;
}

// Adapted from main's query-scoped overview and component/pathway bar charts.
function CountChart({ panel, title, caption, data }: {
  panel: string;
  title: string;
  caption: string;
  data: CountDatum[];
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

  return <section className="figure-card" style={{ marginTop: "1rem" }}>
    <div className="figure-heading"><span>{panel}</span><div><h2>{title}</h2><p>{caption}</p></div></div>
    {!data.length ? <div className="empty-state" style={{ minHeight: "9rem" }}>本次查询暂无可展示的数据。</div> : <>
      <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label={title} style={{ display: "block", width: "100%" }}>
        {ticks.map((value) => <g key={value}>
          <line x1={labelWidth + plotWidth * value / maximum} x2={labelWidth + plotWidth * value / maximum} y1={8} y2={height - 31} stroke="#ded3c2" strokeDasharray="3 3" />
          <text x={labelWidth + plotWidth * value / maximum} y={height - 10} textAnchor="middle" fontSize={12} fill="#6b5344">{count(value)}</text>
        </g>)}
        {data.map((row, index) => {
          const y = 12 + index * rowHeight;
          return <g key={`${row.name}-${index}`} tabIndex={0} role="button" aria-label={`${row.name}：${count(row.value)} 个靶点`} aria-pressed={selected === index}
            onMouseEnter={() => setSelected(index)} onFocus={() => setSelected(index)} onClick={() => setSelected(index)}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelected(index); } }}>
            <title>{`${row.name}：${count(row.value)} 个靶点`}</title>
            <rect x={0} y={y - 4} width={width} height={rowHeight} rx={4} fill={selected === index ? "rgba(139,37,0,.06)" : "transparent"} />
            <text x={labelWidth - 12} y={y + 18} textAnchor="end" fontSize={13} fill="#2c1810">{shortened(row.name)}</text>
            <rect x={labelWidth} y={y} width={plotWidth * row.value / maximum} height={24} rx={4} fill={COLORS[index % COLORS.length]} />
            <text x={labelWidth + plotWidth * row.value / maximum + 8} y={y + 17} fontSize={13} fill="#2c1810">{count(row.value)}</text>
          </g>;
        })}
      </svg>
      <p className="section-help" aria-live="polite" style={{ minHeight: "1.5rem", overflowWrap: "anywhere" }}>{selectedRow ? `${selectedRow.name}：${count(selectedRow.value)} 个靶点` : "指向、点击或用键盘选择条形，可查看完整名称与计数。"}</p>
      <details style={{ marginTop: ".4rem" }}><summary className="section-help">查看图表数据表</summary><div className="table-scroll"><table className="data-table"><thead><tr><th>名称</th><th>靶点数</th></tr></thead><tbody>{data.map((row, index) => <tr key={`${row.name}-${index}`}><td>{row.name}</td><td>{count(row.value)}</td></tr>)}</tbody></table></div></details>
    </>}
  </section>;
}

export function NetworkPharmacologyCharts({ result }: { result: NetworkPharmacologyResult }) {
  return <section aria-label="本次查询统计图">
    <CountChart panel="Prep A" title="靶点比对概览" caption="中药侧、疾病侧、严格交集和直接关联分别计数；各条形用于比较，不相加作为总数。" data={result.charts.overlap} />
    <CountChart panel="Prep C" title="关联成分 Top 20" caption="当前查询关联成分的靶点覆盖数，按覆盖数排序；同一靶点可被多个成分关联。" data={result.charts.components.slice(0, 20).map((row) => ({ name: row.name, value: row.targets }))} />
    <CountChart panel="Prep D" title="候选靶点的本地通路注释" caption="当前候选靶点在已导入目录中的通路覆盖数；这是本地注释统计，Reactome 外部富集结果另列于下方。" data={result.charts.pathways.slice(0, 20).map((row) => ({ name: row.name, value: row.targets }))} />
  </section>;
}
