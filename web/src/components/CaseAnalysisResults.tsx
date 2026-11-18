import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import type { CaseStatisticsTask } from "../api/caseStatistics";
import { RAnalysisGallery } from "./RAnalysisGallery";
import { downloadText, encodeCsv } from "../utils/downloads";

export type CaseAnalysisModule = "distribution" | "medication" | "association" | "clustering" | "relations";
const statistics = [["sex", "性别"], ["age_group", "年龄分组"], ["visit_count", "诊次数"], ["western_diagnosis", "西医病名"], ["tcm_diagnosis", "中医病名"], ["syndrome", "证型"], ["treatment", "治法治则"], ["tongue", "舌象"], ["pulse", "脉象"]];

export function CaseAnalysisResults({ task, module, onClusterMethod }: { task: CaseStatisticsTask; module: CaseAnalysisModule; onClusterMethod: (method: string) => void }) {
  const [metric, setMetric] = useState("sex");
  const [shape, setShape] = useState("bar");
  const [medication, setMedication] = useState("herbs");
  const [association, setAssociation] = useState("network");
  const [cluster, setCluster] = useState("dendrogram");
  const [k, setK] = useState("4");
  useEffect(() => {
    if (module === "clustering") onClusterMethod(cluster === "dendrogram" ? "层次聚类" : "K-Means");
  }, [module, cluster, onClusterMethod]);
  const result = task.result;
  let key = "";
  if (module === "distribution") key = `case_${metric}_${shape}`;
  if (module === "medication") key = medication === "pairs" ? "case_herb_pairs_heatmap" : medication === "attributes" ? "" : `case_${medication}_bar`;
  if (module === "association") key = `case_association_${association}`;
  if (module === "clustering") key = cluster === "kmeans" ? `case_cluster_kmeans_${k}` : `case_cluster_${cluster}`;
  if (module === "relations") key = "case_relations_network";
  const selectedMetric = module === "distribution" ? result.metrics[metric] : module === "medication" ? result.metrics[medication] : undefined;
  const figure = result.figures?.[key];
  const canDraw = key && (figure || (selectedMetric && selectedMetric.rows.length > 0));
  const headers = figure?.table.headers ?? ["类别", "出现数", "占统计单位比例", "分母"];
  const rows = figure?.table.rows ?? selectedMetric?.rows.map(row => [row.label, row.count, `${(100 * row.count / selectedMetric.denominator).toFixed(2)}%`, selectedMetric.denominator]) ?? [];
  const tableTitle = module === "clustering" ? "聚类输入药物" : module === "association" ? "关联规则明细" : "图表对应明细";

  return <>
    <section className="case-visualization-config" aria-label="分析配置">
      <div className="case-visualization-fields">
        {module === "distribution" && <>
          <label className="form-label">统计字段<select className="field" value={metric} onChange={e => setMetric(e.target.value)}>{statistics.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label className="form-label">图像类型<select className="field" value={shape} onChange={e => setShape(e.target.value)}><option value="bar">频数条形图</option><option value="donut">构成环形图</option></select></label>
        </>}
        {module === "medication" && <label className="form-label">用药分析<select className="field" value={medication} onChange={e => setMedication(e.target.value)}>
          <option value="herbs">药物频次 · 条形图</option><option value="formulas">方剂名称提及 · 条形图</option><option value="pairs">药对共现 · 热图</option><option value="attributes">四气、五味、归经 · 属性分布</option>
        </select></label>}
        {module === "association" && <label className="form-label">规则展示<select className="field" value={association} onChange={e => setAssociation(e.target.value)}><option value="network">关联规则网络</option><option value="bubble">支持度—置信度气泡图</option></select><small>前项：药物；后项：药物。支持度 ≥ 0.05，置信度 ≥ 0.50。</small></label>}
        {module === "clustering" && <>
          <label className="form-label">聚类方法与图型<select className="field" value={cluster} onChange={e => { setCluster(e.target.value); onClusterMethod(e.target.value === "dendrogram" ? "层次聚类" : "K-Means"); }}><option value="dendrogram">层次聚类 · 树状图</option><option value="kmeans">K-Means · PCA 分组图</option><option value="elbow">K-Means · 肘部图</option></select><small>对象：前 20 味高频药物。层次聚类使用 Jaccard 距离与平均连接；K-Means 使用原二元特征。</small></label>
          {cluster === "kmeans" && <label className="form-label">类别数 K<select className="field" value={k} onChange={e => setK(e.target.value)}>{[3,4,5].map(n => <option key={n} value={n}>{n}</option>)}</select></label>}
        </>}
        {module === "relations" && <p className="section-help">疾病—证型—药物共现图。连线来自所选统计单位的同次记录；经核验知识图谱将在实体和来源关系整理后接入。</p>}
      </div>
      {module === "medication" && result.medicationSummary && <p className="section-help">{result.medicationSummary.prescriptionCount} 个统计单位含可识别的完整方药条目，{result.medicationSummary.herbCount} 个原文药名；同一单位内同药去重，保留炮制名称。</p>}
    </section>
    {canDraw ? <>
      <RAnalysisGallery key={`${task.id}-${key}`} taskId={task.id} chartKeys={[key]} taskOnly sectionTitle="分析图像" />
      <details className="case-analysis-details"><summary>{tableTitle} · {rows.length} 条</summary>
        <div className="source-record-actions"><button className="btn btn-secondary" onClick={() => downloadText(`case-analysis-${task.id}-${key}.csv`, encodeCsv(headers, rows), "text/csv;charset=utf-8")}><Download size={15} />下载明细 CSV</button></div>
        {module === "clustering" && <p className="section-help">下表为聚类输入；计算后的分组标签见交互图的“查看图表对应数据表”，并随 HTML 文件保存。</p>}
        <div className="table-scroll"><table className="data-table"><thead><tr>{headers.map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, col) => <td key={col}>{typeof cell === "number" && cell % 1 !== 0 ? cell.toFixed(4) : cell}</td>)}</tr>)}</tbody></table></div>
      </details>
    </> : <div className="case-visualization-empty"><strong>{medication === "attributes" && module === "medication" ? "等待药物属性对应数据" : "当前数据还不能生成此图"}</strong><p>{medication === "attributes" && module === "medication" ? "四气、五味、归经和功效需要有来源的药名—属性对应表。补齐后，此处展示属性条形图或雷达图。" : "请选用包含对应字段的医案数据；本栏目使用自身的分析结果。"}</p></div>}
  </>;
}
