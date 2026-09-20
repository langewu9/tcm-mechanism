"use client";

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis
} from "recharts";

const palette = ["#9c2b22", "#c89b3c", "#b7682f", "#e0bd67", "#7a3326", "#d99b3d", "#ad4c36", "#8b5a2b"];

export type OverviewDatum = {
  name: string;
  value: number;
  note: string;
};

export type RankedDatum = {
  name: string;
  value: number;
  secondary?: number;
  category?: string;
};

export type PathwayDatum = {
  name: string;
  targets: number;
  compounds: number;
  evidence: number;
};

export type MatrixDatum = {
  herb: string;
  compound: string;
  value: number;
};

export type VisualizationAtlasProps = {
  overview: OverviewDatum[];
  topHerbs: RankedDatum[];
  topCompounds: RankedDatum[];
  topTargets: RankedDatum[];
  pathways: PathwayDatum[];
  matrix: MatrixDatum[];
  latestSummary?: string | null;
};

type RankingMode = "herb" | "compound" | "target";

function ChartFrame({
  panel,
  title,
  caption,
  children,
  className = ""
}: {
  panel: string;
  title: string;
  caption: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`figure-card ${className}`}>
      <div className="figure-heading">
        <span>{panel}</span>
        <div>
          <h2>{title}</h2>
          <p>{caption}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function compactNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function downloadCsv(filename: string, rows: Array<Record<string, string | number | undefined>>) {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const body = rows.map((row) =>
    headers
      .map((header) => {
        const value = String(row[header] ?? "");
        return `"${value.replaceAll('"', '""')}"`;
      })
      .join(",")
  );
  const blob = new Blob([[headers.join(","), ...body].join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function rankData(mode: RankingMode, props: VisualizationAtlasProps) {
  if (mode === "herb") return { title: "高连接中药", data: props.topHerbs, valueLabel: "成分数", secondaryLabel: "方剂数" };
  if (mode === "compound") return { title: "高覆盖成分", data: props.topCompounds, valueLabel: "靶点数", secondaryLabel: "来源中药" };
  return { title: "核心靶点", data: props.topTargets, valueLabel: "关联度", secondaryLabel: "通路/基因" };
}

export function VisualizationAtlas(props: VisualizationAtlasProps) {
  const [mode, setMode] = useState<RankingMode>("herb");
  const ranking = rankData(mode, props);
  const radarData = useMemo(
    () =>
      props.topTargets.slice(0, 6).map((target) => ({
        target: target.name,
        compounds: target.value,
        pathways: target.secondary ?? 0
      })),
    [props.topTargets]
  );
  const matrixMax = Math.max(...props.matrix.map((item) => item.value), 1);
  const visibleMatrix = props.matrix.slice(0, 56);

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
        <ChartFrame
          panel="Figure A"
          title="知识库规模"
          caption="以当前本地数据库为准，展示药物、成分、靶点和通路四类核心实体。"
        >
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={props.overview} margin={{ top: 12, right: 18, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="#ded3c2" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tickLine={false} axisLine={{ stroke: "#b9ad9c" }} />
                <YAxis tickLine={false} axisLine={false} tickFormatter={compactNumber} width={56} />
                <Tooltip formatter={(value) => compactNumber(Number(value))} labelStyle={{ color: "#2b1711" }} />
                <Bar dataKey="value" radius={[5, 5, 0, 0]}>
                  {props.overview.map((entry, index) => (
                    <Cell key={entry.name} fill={palette[index % palette.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartFrame>

        <ChartFrame panel="Figure B" title="实体组成" caption="环形图用于快速判断当前知识库的数据重心和模块占比。">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={props.overview}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={58}
                  outerRadius={108}
                  paddingAngle={2}
                >
                  {props.overview.map((entry, index) => (
                    <Cell key={entry.name} fill={palette[index % palette.length]} />
                  ))}
                </Pie>
                <Legend verticalAlign="bottom" height={32} />
                <Tooltip formatter={(value) => compactNumber(Number(value))} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </ChartFrame>
      </div>

      <ChartFrame
        panel="Figure C"
        title={ranking.title}
        caption="排序图支持在中药、成分和靶点三个层级间切换，优先暴露高证据连接节点。"
      >
        <div className="chart-toolbar">
          <button className={mode === "herb" ? "is-active" : ""} onClick={() => setMode("herb")} type="button">
            中药
          </button>
          <button className={mode === "compound" ? "is-active" : ""} onClick={() => setMode("compound")} type="button">
            成分
          </button>
          <button className={mode === "target" ? "is-active" : ""} onClick={() => setMode("target")} type="button">
            靶点
          </button>
          <button className="ml-auto" onClick={() => downloadCsv(`qihuang-${mode}-ranking.csv`, ranking.data)} type="button">
            导出 CSV
          </button>
        </div>
        <div className="h-[390px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={ranking.data.slice(0, 12)} layout="vertical" margin={{ top: 12, right: 34, bottom: 8, left: 20 }}>
              <CartesianGrid stroke="#ded3c2" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tickLine={false} axisLine={false} />
              <YAxis dataKey="name" type="category" width={112} tickLine={false} axisLine={false} />
              <Tooltip
                formatter={(value, name) => [
                  compactNumber(Number(value)),
                  name === "value" ? ranking.valueLabel : ranking.secondaryLabel
                ]}
              />
              <Legend />
              <Bar dataKey="value" name={ranking.valueLabel} fill="#9c2b22" radius={[0, 4, 4, 0]} />
              <Bar dataKey="secondary" name={ranking.secondaryLabel} fill="#c89b3c" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </ChartFrame>

      <div className="grid gap-5 xl:grid-cols-2">
        <ChartFrame panel="Figure D" title="核心靶点雷达" caption="比较高频靶点在成分覆盖和通路覆盖上的相对强度。">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData} outerRadius="70%">
                <PolarGrid stroke="#d8ccb9" />
                <PolarAngleAxis dataKey="target" />
                <PolarRadiusAxis tick={false} axisLine={false} />
                <Radar dataKey="compounds" name="成分覆盖" fill="#9c2b22" fillOpacity={0.22} stroke="#9c2b22" strokeWidth={2} />
                <Radar dataKey="pathways" name="通路覆盖" fill="#c89b3c" fillOpacity={0.18} stroke="#c89b3c" strokeWidth={2} />
                <Legend />
                <Tooltip />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </ChartFrame>

        <ChartFrame panel="Figure E" title="通路富集代理图" caption="气泡大小表示证据连接强度，横纵轴分别表示靶点与成分覆盖。">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 16, right: 22, bottom: 16, left: 0 }}>
                <CartesianGrid stroke="#ded3c2" strokeDasharray="3 3" />
                <XAxis dataKey="targets" name="靶点" tickLine={false} axisLine={{ stroke: "#b9ad9c" }} />
                <YAxis dataKey="compounds" name="成分" tickLine={false} axisLine={{ stroke: "#b9ad9c" }} />
                <ZAxis dataKey="evidence" range={[80, 720]} name="证据" />
                <Tooltip
                  cursor={{ strokeDasharray: "3 3" }}
                  formatter={(value, name) => [compactNumber(Number(value)), name]}
                  labelFormatter={(_, payload) => payload?.[0]?.payload?.name ?? ""}
                />
                <Scatter data={props.pathways.slice(0, 18)} name="通路" fill="#9b6b34" />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </ChartFrame>
      </div>

      <ChartFrame
        panel="Figure F"
        title="中药-成分-靶点证据矩阵"
        caption="每个单元格表示某一中药来源成分所覆盖的靶点数量，颜色越深说明证据连接越密集。"
      >
        <div className="evidence-matrix" role="table" aria-label="中药成分靶点证据矩阵">
          {visibleMatrix.map((item) => (
            <div
              className="matrix-cell"
              key={`${item.herb}-${item.compound}`}
              style={{ ["--strength" as string]: Math.max(0.12, item.value / matrixMax).toFixed(3) }}
              title={`${item.herb} / ${item.compound}: ${item.value} 个靶点`}
            >
              <strong>{item.herb}</strong>
              <span>{item.compound}</span>
              <em>{item.value}</em>
            </div>
          ))}
          {!visibleMatrix.length ? <div className="empty-state">暂无可绘制的成分-靶点证据矩阵。</div> : null}
        </div>
      </ChartFrame>

      {props.latestSummary ? (
        <section className="panel p-5">
          <p className="page-kicker">LATEST ANALYSIS NOTE</p>
          <p className="mt-2 text-sm leading-7 text-ink/68">{props.latestSummary}</p>
        </section>
      ) : null}
    </div>
  );
}

export function SummaryCharts({ data }: { data: { name: string; value: number }[] }) {
  const overview = data.map((item) => ({ ...item, note: "" }));
  return <VisualizationAtlas overview={overview} topHerbs={[]} topCompounds={[]} topTargets={[]} pathways={[]} matrix={[]} />;
}
