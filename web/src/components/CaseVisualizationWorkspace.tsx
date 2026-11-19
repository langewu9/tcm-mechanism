import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { BarChart3, GitBranch, Layers, Network, Pill } from "lucide-react";
import { ApiError } from "../api/client";
import { getCaseCorpusSummary, type CaseCorpusSummary } from "../api/caseCorpus";
import { getMedicalCases } from "../api/cases";
import { CaseCountFigure, type CaseCountSeries } from "./CaseStatistics";
import { CaseAnalysisResults } from "./CaseAnalysisResults";
import { getRecentCaseStatisticsTasks, getCaseStatisticsTask, uploadCaseStatisticsWorkbook, type CaseStatisticsTask } from "../api/caseStatistics";
import "../styles/case-visualization.css";

type Source = "mine" | "reference" | "dataset";
type Analysis = "distribution" | "medication" | "association" | "clustering" | "relations";

type MethodGuide = {
  method: string;
  introduction: string;
  principle: string;
  steps: string[];
  interpretation: string;
};

const modules: Array<{ key: Analysis; label: string; icon: typeof BarChart3; summary: string; output: string; requirement: string }> = [
  { key: "distribution", label: "医案统计", icon: BarChart3, summary: "查看性别、年龄、诊次数，以及病名、证型、四诊和治法的分布。", output: "条形图 / 环形图 / 明细表", requirement: "需要当前数据范围内可计数的结构化字段。" },
  { key: "medication", label: "用药特征", icon: Pill, summary: "查看药物、方剂频次和药对共现；药物属性按对应数据开放。", output: "药物频次图 / 属性分布图 / 雷达图", requirement: "需要可核对的方药记录，以及药物与属性的规范对应。" },
  { key: "association", label: "关联分析", icon: GitBranch, summary: "从同一统计单位的用药记录计算关联规则，查看支持度、置信度和提升度。", output: "关联网络 / 规则结果表", requirement: "需要明确的记录或诊次边界、关系字段和来源证据。" },
  { key: "clustering", label: "聚类分析", icon: Layers, summary: "按药物出现特征查看层次聚类、K-Means 分组和 K 值选择。", output: "树状图 / 聚类分布图 / 分组表", requirement: "需要统一编码的病例特征矩阵，并确认距离与聚类方法。" },
  { key: "relations", label: "医案关系", icon: Network, summary: "把病例、诊次、诊断、证型、治法、四诊记录和方药连成可追溯的知识图谱。", output: "知识图谱 / 共现网络 / 实体与来源明细", requirement: "从结构化字段生成实体关系，并为每条记录保留工作表行号。" },
];

const initialError = (cause: unknown) => cause instanceof ApiError ? cause.message : "数据范围读取失败，请重试。";

function methodGuide(analysis: Analysis, source: Source, clusterMethod: string): MethodGuide {
  if (analysis === "distribution" && source === "reference") return {
    method: "描述性统计 · 频数与构成比",
    introduction: "描述性统计用于概括医案资料中各类别的数量与构成，便于观察当前语料的类别分布。",
    principle: "本项目按当前启用语料版本中登记的疾病类别计数。类别频数记为 nᵢ；构成比 = nᵢ ÷ 当前图表类别频数之和 × 100%。",
    steps: [
      "读取当前启用的参考医案版本，按登记类别分组并统计每类医案记录数。",
      "条形图以频数比较类别；环形图按各类别频数占当前显示类别总频数的比例绘制。",
    ],
    interpretation: "选择前 5 类或前 10 类时，分母随显示类别变化，因此表示这些显示类别内部的构成，不代表整库占比；类别来自登记字段，不是从医案原文推断。",
  };

  if (analysis === "distribution") return {
    method: "描述性统计 · 频数与构成比",
    introduction: "描述性统计可用于比较个人医案中疾病、证型、症状、四诊等结构化字段的类别分布。",
    principle: "先确定统计单位是医案还是诊次。若选定范围有 N 个有效单位，某类别出现 nᵢ 次，则该类别频数为 nᵢ，构成比为 nᵢ ÷ N × 100%。",
    steps: [
      "按选定范围和统计单位读取结构化字段的已登记值。",
      "对相同类别计数，得到各类别频数。",
      "用各类别频数除以有效单位总数，计算构成比并生成图表。",
    ],
    interpretation: "分布描述的是数据中记录到的类别比例，不代表疾病患病率，也不应把自由文本切词后当作规范类别。",
  };

  if (analysis === "medication") return {
    method: "频数统计 · 药物属性分布",
    introduction: "用药频数分析用于观察选定医案或处方中哪些药物记录较多；属性分布用于概括已核实药物在四气、五味、归经或功效类别中的构成。",
    principle: "以来源明确、身份已核实的药物条目作为计数对象，再按研究问题汇总药物频次或药物属性类别频次。",
    steps: [
      "确定统计单位，并读取其中明确列出的药物条目。",
      "按药物身份汇总出现频次；若分析四气、五味等属性，则按有来源的属性值归类并计数。",
      "按所选图型展示频数或类别分布；雷达图仅在各轴口径可比较时用于并列观察。",
    ],
    interpretation: "频次反映所选数据范围内的记录情况，不等同于剂量、疗效或临床推荐；药名和属性必须有依据，药名从完整方药列的明确药名与剂量片段识别；保留炮制原名，不从叙述处方推断药物。",
  };

  if (analysis === "association") return {
    method: "关联规则 · 共现统计",
    introduction: "关联规则用于从共同出现记录中寻找项目之间的统计关系，例如某症状与某证候是否经常记录在同一分析单元中。",
    principle: "把一条医案、一次诊次或一张处方定义为一个事务。支持度衡量 A、B 同时出现的比例；置信度衡量出现 A 时同时出现 B 的比例；提升度将该比例与 B 的总体出现率比较。",
    steps: [
      "在每个事务中记录有明确依据的项目，并统计 A、B 同时出现的事务数。",
      "支持度 = 同时含 A、B 的事务数 ÷ 全部有效事务数；置信度 A→B = 同时含 A、B 的事务数 ÷ 含 A 的事务数。",
      "提升度 = 置信度 A→B ÷ B 的总体出现率；再按设定阈值筛选规则。",
    ],
    interpretation: "规则表示共现模式或条件比例，不证明因果。一个分析单元的定义会改变分母和结果，必须与研究问题一致。",
  };

  if (analysis === "clustering" && clusterMethod === "K-Means") return {
    method: "K-Means 聚类算法",
    introduction: "聚类的基本思想是“物以类聚、人以群分”，根据特征相似性把没有预先类别标签的样本分成若干组。K-Means 是常用的划分式聚类方法。",
    principle: "K-Means 迭代寻找 K 个簇的划分，使每个样本到所属簇中心的误差平方和尽量小。",
    steps: [
      "将每味高频药物在各医案或诊次中的出现情况整理为二元特征向量，并设定类别数 K，选取 K 个初始聚类中心。",
      "计算每个样本到各聚类中心的距离，把样本分配给最近的中心。",
      "根据每个簇当前包含的样本重新计算簇中心。",
      "重复分配样本和更新中心，直到分组不再变化或达到停止条件。",
    ],
    interpretation: "聚类结果是探索性分组，不自动等于中医证型或疾病分类；更改特征、距离或 K 值会改变结果。",
  };

  if (analysis === "clustering") return {
    method: "层次聚类算法",
    introduction: "层次聚类根据样本或簇之间的距离，逐步合并相近对象，形成由细到粗的层级结构，常用树状图展示。",
    principle: "先把每个样本视为一个簇，再依据距离度量和连接方法计算簇间距离；每一步合并距离最近的两个簇，直到达到停止条件。",
    steps: [
      "将每味高频药物在各医案或诊次中的出现情况整理为二元特征向量，并把每个样本分别作为一个初始簇。",
      "按选定的距离度量和连接方法，计算当前各簇之间的距离。",
      "合并距离最近的两个簇，并更新新簇与其他簇之间的距离。",
      "重复计算和合并，直到达到目标类别数或其他停止条件，再通过树状图查看层级关系。",
    ],
    interpretation: "树状图表示样本合并的层级与距离；切分层级不同会得到不同分组。结果不自动代表证型或临床分类。",
  };

  return {
    method: "医案知识图谱 · 实体与关系建模",
    introduction: "知识图谱把病例中的对象表示为实体，把原始记录明确写出的联系表示为关系，并为实体和关系保留可回查的字段来源。",
    principle: "本项目以匿名病例和诊次作为记录骨架；西医病名、中医病名、证型、治法治则、舌象、脉象、方剂和药物按原表字段建立实体。方药剂量属于某次处方与药物之间的关系属性。",
    steps: [
      "按病例编号在内存中归并诊次，并生成不含原始编号的匿名病例与诊次标识。",
      "读取每次诊次中明确填写的病名、证型、治法、舌象和脉象字段，按实体类型与记录名称建立节点。",
      "将病例连接到诊次，再将诊次连接到其记录的临床字段；存在明确处方时，建立方药记录，并连接原文明确提及的方剂和可识别药物。",
      "把剂量等信息保存在处方—药物关系上，并为每个实体关系记录工作表、行号和字段，供查看与导出。",
    ],
    interpretation: "图中关系表示原表如何记录，不表示疾病与药物之间的疗效、因果或推荐。当前只按现有结构字段建图，不从主诉、病史、医嘱等叙述文字自动抽取症状实体。",
  };
}

export function CaseVisualizationWorkspace() {
  const [params, setParams] = useSearchParams();
  const initialMethod = params.get("caseMethod");
  const [analysis, setAnalysis] = useState<Analysis>(modules.some(m => m.key === initialMethod) ? initialMethod as Analysis : "distribution");
  const [source, setSource] = useState<Source>("dataset");
  const [datasets, setDatasets] = useState<CaseStatisticsTask[]>([]);
  const [task, setTask] = useState<CaseStatisticsTask | null>(null);
  const [referenceSummary, setReferenceSummary] = useState<CaseCorpusSummary | null>(null);
  const [myCaseCount, setMyCaseCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [unit, setUnit] = useState<"first_visit" | "all_visits">("first_visit");
  const [clusterMethod, setClusterMethod] = useState("层次聚类");
  const [referenceRun, setReferenceRun] = useState(false);

  useEffect(() => {
    let active = true;
    getRecentCaseStatisticsTasks().then(async page => {
      const id = Number(params.get("caseStatisticsTask"));
      const requested = id > 0 ? page.results.find(item => item.id === id) ?? await getCaseStatisticsTask(id) : null;
      // Prefer the latest analysis dataset; old aggregate-only snapshots remain accessible.
      const current = (requested && page.results.find(item => item.result.fileSha256 === requested.result.fileSha256 && item.result.unit === requested.result.unit)) ?? requested ?? page.results[0] ?? null;
      const distinct = page.results.filter((item, index, all) => all.findIndex(other => other.result.fileSha256 === item.result.fileSha256 && other.result.unit === item.result.unit) === index);
      if (active) {
        setDatasets(distinct); setTask(current); if (!current) setSource("mine");
        if (current && String(current.id) !== params.get("caseStatisticsTask")) {
          const next = new URLSearchParams(params); next.set("caseStatisticsTask", String(current.id)); setParams(next, {replace: true});
        }
      }
    }).catch(cause => { if (active) setError(initialError(cause)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (source === "dataset") return;
    let active = true;
    setLoading(true); setError(null); setReferenceRun(false);
    const request = source === "reference" ? getCaseCorpusSummary().then(value => { if (active) setReferenceSummary(value); })
      : getMedicalCases(1, false).then(value => { if (active) setMyCaseCount(value.count); });
    request.catch(cause => { if (active) setError(initialError(cause)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [source]);

  function changeAnalysis(value: Analysis) {
    setAnalysis(value); setClusterMethod("层次聚类");
    const next = new URLSearchParams(params); next.set("caseMethod", value); setParams(next, {replace: true});
  }
  function selectData(value: string) {
    setError(null); setClusterMethod("层次聚类");
    if (value === "mine" || value === "reference") { setSource(value); return; }
    const selected = datasets.find(item => item.id === Number(value));
    if (selected) {
      setTask(selected); setSource("dataset");
      const next = new URLSearchParams(params); next.set("caseStatisticsTask", String(selected.id)); setParams(next, {replace: true});
    }
  }
  async function importData(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    setBusy(true); setError(null);
    try {
      const saved = await uploadCaseStatisticsWorkbook(file, unit);
      setTask(saved); setDatasets(items => [saved, ...items.filter(item => item.id !== saved.id)]); setSource("dataset");
      const next = new URLSearchParams(params); next.set("caseStatisticsTask", String(saved.id)); setParams(next, {replace: true});
    } catch (cause) { setError(initialError(cause)); } finally { setBusy(false); }
  }
  const current = modules.find(item => item.key === analysis) ?? modules[0];
  const Icon = current.icon;
  const guide = methodGuide(analysis, source, clusterMethod);
  const categories: CaseCountSeries[] = (referenceSummary?.categories ?? []).map(row => ({name: row.label, value: row.count}));

  return <section className="case-visualization" aria-label="医案分析与图像生成">
    <header className="case-visualization-heading"><div><span className="case-visualization-eyebrow">医案数据分析</span><h2 className="section-title-sm">按研究问题配置图像</h2><p className="section-help">同一份医案数据，按统计、用药、关联与聚类分别查看结果。</p></div><span className="status-badge">图像由当前分析数据生成</span></header>
    <div className="case-visualization-workspace">
      <nav className="case-visualization-nav" aria-label="医案分析方法"><div className="case-visualization-nav-title">分析方法</div>
        {modules.map(item => { const ItemIcon = item.icon; return <button key={item.key} className="case-visualization-nav-item" type="button" aria-current={analysis === item.key ? "page" : undefined} onClick={() => changeAnalysis(item.key)}><ItemIcon size={18}/><span>{item.label}</span><span className="case-visualization-nav-chevron">›</span></button>; })}
        <div className="case-visualization-nav-note"><strong>按研究问题选择方法</strong><span>各栏目使用对应算法、图型和结果明细。</span></div>
      </nav>
      <div className="case-visualization-main">
        <div className="case-visualization-intro"><div className="case-visualization-module-icon"><Icon size={22}/></div><div><h3 className="section-title-sm">{current.label}</h3><p>{current.summary}</p></div></div>
        <section className="case-visualization-source" aria-label="数据范围">
          <div className="case-visualization-fields"><label className="form-label">分析数据<select className="field" aria-label="分析数据" value={source === "dataset" ? task?.id ?? "" : source} onChange={e => selectData(e.target.value)}>
            {!task && <option value="" disabled>选择医案数据</option>}
            {datasets.map(item => <option key={item.id} value={item.id}>医案数据 #{item.id} · {item.result.unitLabel} · {item.result.analysisCount} 个单位</option>)}
            <option value="mine">我的医案 · 使用中的记录</option><option value="reference">参考医案库 · 当前版本</option>
          </select></label></div>
          {source === "dataset" && task && <div className="case-workbook-summary" aria-label="统计范围"><span><strong>{task.result.caseGroupCount}</strong> 个病例组</span><span><strong>{task.result.recordCount}</strong> 条诊次</span><span>{task.result.unitLabel}</span>{task.result.testData && <span>当前使用示例医案数据</span>}</div>}
          <details className="case-analysis-import"><summary>导入 / 更换医案数据</summary><form className="case-analysis-import-form" onSubmit={importData}>
            <label className="form-label">医案表格<input className="field" type="file" accept=".xlsx" onChange={e => setFile(e.target.files?.[0] ?? null)}/></label>
            <label className="form-label">统计单位<select className="field" value={unit} onChange={e => setUnit(e.target.value as typeof unit)}><option value="first_visit">每组病例取首诊</option><option value="all_visits">全部诊次</option></select></label>
            <button className="btn btn-primary" disabled={busy || !file}>{busy ? "正在整理…" : "用于医案分析"}</button>
          </form></details>
        </section>
        <details className="case-visualization-method"><summary><span><strong>算法与用途</strong><span className="case-visualization-method-status">{guide.method}</span></span><span className="case-visualization-method-action">查看原理</span></summary><div className="case-visualization-method-body"><p>{guide.introduction}</p><p>{guide.principle}</p><p className="case-visualization-method-lead">其基本步骤是：</p><ol>{guide.steps.map((step, i) => <li key={i}>{step}</li>)}</ol><p>{guide.interpretation}</p></div></details>
        {error && <p className="notice-error" role="alert">{error}</p>}
        {loading ? <p role="status">正在读取医案数据…</p> : source === "dataset" && task ? <CaseAnalysisResults key={task.id} task={task} module={analysis} onClusterMethod={setClusterMethod}/> : source === "reference" && analysis === "distribution" && categories.length ? <>
          <button className="btn btn-primary" type="button" onClick={() => setReferenceRun(true)}>查看类别统计</button>
          {referenceRun && <CaseCountFigure title="参考医案类别分布" data={categories} scope="当前参考库" version={referenceSummary?.version} filename="case-categories"/>}
        </> : <div className="case-visualization-empty"><strong>{source === "mine" ? `当前有 ${myCaseCount ?? 0} 条个人医案` : "当前来源没有此项结构化结果"}</strong><p>选择已整理的医案数据后，可在对应栏目运行分析并查看图像。</p></div>}
      </div>
    </div>
  </section>;
}
