import { useId, useRef, useState } from "react";
import { BarChart3, Download, Table2 } from "lucide-react";
import { downloadText, encodeCsv } from "../utils/downloads";

export type CaseCountSeries = { name: string; value: number };

const COLORS = ["#9c2b22", "#c89b3c", "#66736a", "#b7682f", "#8b5a2b"];
const count = (value: number) => value.toLocaleString("zh-CN");
const percent = (value: number, total: number) => total ? `${(value / total * 100).toFixed(1)}%` : "—";

/** Draws only supplied counts; callers must provide an explicit scope and denominator. */
export function CaseCountFigure({ title, data, scope, version, filename }: {
  title: string;
  data: CaseCountSeries[];
  scope: string;
  version?: string | null;
  filename: string;
}) {
  const id = useId();
  const svg = useRef<SVGSVGElement>(null);
  const [chart, setChart] = useState("bar");
  const [table, setTable] = useState(false);
  const total = data.reduce((sum, row) => sum + row.value, 0);
  const maximum = Math.max(1, ...data.map(row => row.value));
  const height = Math.max(170, data.length * 54 + 45);
  const radius = 68;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  function saveSvg() {
    if (!svg.current) return;
    const copy = svg.current.cloneNode(true) as SVGSVGElement;
    copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const description = document.createElementNS("http://www.w3.org/2000/svg", "desc");
    description.textContent = `${title}；${scope}；显示分类合计 ${total} 条${version ? `；版本 ${version}` : ""}`;
    copy.prepend(description);
    downloadText(`${filename}.svg`, new XMLSerializer().serializeToString(copy), "image/svg+xml;charset=utf-8");
  }

  return <section className="case-count-figure" aria-labelledby={`${id}-title`}>
    <div className="case-count-heading"><div><h3 id={`${id}-title`} className="section-title-sm">{title}</h3><p className="section-help">{scope}</p></div><span className="status-badge">分类合计 {count(total)} 条</span></div>
    <div className="case-count-toolbar">
      <label className="form-label" htmlFor={`${id}-chart`}>图像类型<select id={`${id}-chart`} className="field" value={chart} onChange={event => setChart(event.target.value)}><option value="bar">条形图</option><option value="donut">环形图</option></select></label>
      <div className="source-record-actions"><button type="button" className="btn btn-secondary" onClick={() => setTable(value => !value)} aria-expanded={table} aria-controls={`${id}-table`}><Table2 size={15} />{table ? "收起明细" : "查看明细表"}</button><button type="button" className="btn btn-secondary" disabled={!total} onClick={saveSvg}><Download size={15} />下载 SVG</button><button type="button" className="btn btn-secondary" disabled={!total} onClick={() => downloadText(`${filename}.csv`, encodeCsv(["类别", "记录数", "占比", "分母", "统计范围", "来源版本"], data.map(row => [row.name, row.value, percent(row.value, total), total, scope, version ?? ""])), "text/csv;charset=utf-8")}><Download size={15} />下载 CSV</button></div>
    </div>
    {total > 0 ? <div className="case-count-canvas"><svg ref={svg} viewBox={`0 0 620 ${chart === "donut" ? 235 : height}`} role="img" aria-label={`${title}：${data.map(row => `${row.name} ${row.value} 条`).join("，")}；${scope}`}>
      <title>{title}</title><rect width="100%" height="100%" fill="#fffdf8" />
      {chart === "bar" ? data.map((row, index) => <g key={row.name}>
        <title>{`${row.name}：${row.value} 条（${percent(row.value, total)}）`}</title>
        <text x={24} y={index * 54 + 25} fill="#2c1810" fontSize={14}>{row.name}</text>
        <rect x={150} y={index * 54 + 10} width={350} height={24} rx={3} fill="#eee5d7" />
        <rect x={150} y={index * 54 + 10} width={350 * row.value / maximum} height={24} rx={3} fill={COLORS[index % COLORS.length]} />
        <text x={518} y={index * 54 + 27} fill="#2c1810" fontSize={14}>{count(row.value)} 条</text>
        <text x={150} y={index * 54 + 48} fill="#6b5344" fontSize={11}>{percent(row.value, total)}</text>
      </g>) : <>
        {data.map((row, index) => {
          const fraction = row.value / total;
          const dashOffset = -offset * circumference;
          offset += fraction;
          return <circle key={row.name} cx={124} cy={105} r={radius} fill="none" stroke={COLORS[index % COLORS.length]} strokeWidth={29} strokeDasharray={`${fraction * circumference} ${circumference}`} strokeDashoffset={dashOffset} transform="rotate(-90 124 105)"><title>{`${row.name}：${row.value} 条（${percent(row.value, total)}）`}</title></circle>;
        })}
        <text x={124} y={104} textAnchor="middle" fontSize={26} fontWeight={700} fill="#2c1810">{count(total)}</text><text x={124} y={126} textAnchor="middle" fontSize={12} fill="#6b5344">记录数</text>
        {data.map((row, index) => <g key={row.name}><rect x={264} y={27 + index * 32} width={12} height={12} rx={2} fill={COLORS[index % COLORS.length]} /><text x={288} y={39 + index * 32} fill="#2c1810" fontSize={14}>{row.name} · {count(row.value)} 条 · {percent(row.value, total)}</text></g>)}
      </>}
      <text x={24} y={chart === "donut" ? 218 : height - 8} fill="#6b5344" fontSize={11}>{scope} · 占比分母 {count(total)} 条</text>
    </svg></div> : <div className="empty-state"><BarChart3 size={24} /><p>当前范围没有可绘制的记录。</p></div>}
    <div id={`${id}-table`} hidden={!table} className="table-scroll"><table className="data-table case-visualization-table"><caption className="section-help">{title} · 占比分母 {count(total)} 条</caption><thead><tr><th>类别</th><th>记录数</th><th>占比</th></tr></thead><tbody>{data.map(row => <tr key={row.name}><td>{row.name}</td><td>{count(row.value)}</td><td>{percent(row.value, total)}</td></tr>)}</tbody></table></div>
    {version && <p className="section-help case-count-source">来源版本：{version}</p>}
  </section>;
}
