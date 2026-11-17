import { useEffect, useState } from "react";
import { BarChart3, GitBranch, Layers, Network, Pill } from "lucide-react";
import { ApiError } from "../api/client";
import { getCaseCorpusSummary, type CaseCorpusSummary } from "../api/caseCorpus";
import { getMedicalCases } from "../api/cases";
import { CaseCountFigure, type CaseCountSeries } from "./CaseStatistics";
import "../styles/case-visualization.css";

type Source = "mine" | "reference";
type Analysis = "distribution" | "medication" | "association" | "clustering" | "relations";

type MethodGuide = {
  method: string;
  introduction: string;
  principle: string;
  steps: string[];
  interpretation: string;
  projectState: string;
};

const modules: Array<{ key: Analysis; label: string; icon: typeof BarChart3; summary: string; output: string; requirement: string }> = [
  { key: "distribution", label: "医案统计", icon: BarChart3, summary: "按疾病类别、证型、症状、四诊和方药查看分布。", output: "条形图 / 环形图 / 明细表", requirement: "需要当前数据范围内可计数的结构化字段。" },
  { key: "medication", label: "用药特征", icon: Pill, summary: "查看方剂与药物构成，以及四气、五味、归经、功效分布。", output: "药物频次图 / 属性分布图 / 雷达图", requirement: "需要可核对的方药记录，以及药物与属性的规范对应。" },
  { key: "association", label: "关联分析", icon: GitBranch, summary: "配置症状、证候、治法、方剂或药物之间的关联规则。", output: "关联网络 / 规则结果表", requirement: "需要明确的记录或诊次边界、关系字段和来源证据。" },
  { key: "clustering", label: "聚类分析", icon: Layers, summary: "按病例特征或方药组合分组，查看组间相似性。", output: "树状图 / 聚类分布图 / 分组表", requirement: "需要统一编码的病例特征矩阵，并确认距离与聚类方法。" },
  { key: "relations", label: "医案关系", icon: Network, summary: "展示经核对的症状—证候—治法—方剂—药物关系。", output: "可交互关系图 / 来源明细", requirement: "需要整理后的实体、诊次、关系和可追溯来源。" },
];

const initialError = (cause: unknown) => cause instanceof ApiError ? cause.message : "数据范围读取失败，请重试。";

function methodGuide(analysis: Analysis, source: Source, referenceAvailable: boolean, clusterMethod: string): MethodGuide {
  if (analysis === "distribution" && source === "reference") return {
    method: "描述性统计 · 频数与构成比",
    introduction: "描述性统计用于概括医案资料中各类别的数量与构成，便于观察当前语料的类别分布。",
    principle: "本项目按当前启用语料版本中登记的疾病类别计数。类别频数记为 nᵢ；构成比 = nᵢ ÷ 当前图表类别频数之和 × 100%。",
    steps: [
      "读取当前启用的参考医案版本，按登记类别分组并统计每类医案记录数。",
      "条形图以频数比较类别；环形图按各类别频数占当前显示类别总频数的比例绘制。",
    ],
    interpretation: "选择前 5 类或前 10 类时，分母随显示类别变化，因此表示这些显示类别内部的构成，不代表整库占比；类别来自登记字段，不是从医案原文推断。",
    projectState: referenceAvailable ? "参考库类别计数已实现；图表使用接口返回的计数和语料版本。" : "类别计数算法已实现，但当前没有可用的参考语料版本，因此尚未产生图表结果。",
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
    projectState: "当前页面能读取当前账号范围内的医案总数，但还没有对个人医案字段做全量分组统计。",
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
    interpretation: "频次反映所选数据范围内的记录情况，不等同于剂量、疗效或临床推荐；药名和属性必须有依据，原文不会按逗号等标点自动拆分。",
    projectState: "本页尚未对医案处方运行用药频次或属性分布计算。",
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
    projectState: "当前支持度和置信度只是界面参数，尚未执行统计关联规则；已有的单案模型候选审核不是这类算法。",
  };

  if (analysis === "clustering" && clusterMethod === "K-Means") return {
    method: "K-Means 聚类算法",
    introduction: "聚类的基本思想是“物以类聚、人以群分”，根据特征相似性把没有预先类别标签的样本分成若干组。K-Means 是常用的划分式聚类方法。",
    principle: "K-Means 迭代寻找 K 个簇的划分，使每个样本到所属簇中心的误差平方和尽量小。",
    steps: [
      "将每条医案或诊次整理为特征向量，并设定类别数 K，选取 K 个初始聚类中心。",
      "计算每个样本到各聚类中心的距离，把样本分配给最近的中心。",
      "根据每个簇当前包含的样本重新计算簇中心。",
      "重复分配样本和更新中心，直到分组不再变化或达到停止条件。",
    ],
    interpretation: "聚类结果是探索性分组，不自动等于中医证型或疾病分类；更改特征、距离或 K 值会改变结果。",
    projectState: "当前页面尚未构建病例特征矩阵，也没有运行 K-Means 任务；此处只展示算法说明和配置位置。",
  };

  if (analysis === "clustering") return {
    method: "层次聚类算法",
    introduction: "层次聚类根据样本或簇之间的距离，逐步合并相近对象，形成由细到粗的层级结构，常用树状图展示。",
    principle: "先把每个样本视为一个簇，再依据距离度量和连接方法计算簇间距离；每一步合并距离最近的两个簇，直到达到停止条件。",
    steps: [
      "将每条医案或诊次整理为特征向量，并把每个样本分别作为一个初始簇。",
      "按选定的距离度量和连接方法，计算当前各簇之间的距离。",
      "合并距离最近的两个簇，并更新新簇与其他簇之间的距离。",
      "重复计算和合并，直到达到目标类别数或其他停止条件，再通过树状图查看层级关系。",
    ],
    interpretation: "树状图表示样本合并的层级与距离；切分层级不同会得到不同分组。结果不自动代表证型或临床分类。",
    projectState: "当前页面尚未构建病例特征矩阵，也没有运行层次聚类任务；此处只展示算法说明和配置位置。",
  };

  return {
    method: "证据关系图 · 按已核验关系逐层展开",
    introduction: "关系图把已核验的实体作为节点、来源明确的关系作为连线，帮助查看单案候选与中药、成分、靶点及通路之间的证据链。",
    principle: "本项目的单案链路以研究者确认的证候或方剂实体为起点，沿启用且带来源版本的关系逐层查询。",
    steps: [
      "模型根据医案资料提出证候/方剂候选，并提供可回到原文核对的证据。",
      "研究者逐条确认候选；仅将可唯一对应的规范实体作为链路起点。",
      "逐层查询证候→方剂→中药→成分→靶点→通路关系，保留节点身份、关系类型、来源记录和版本。",
    ],
    interpretation: "图中的连线表示数据库中有来源的关系，不等同于疾病因果或已经证实的药理作用。",
    projectState: "单案确认候选后的版本化证据链计算已存在；当前医案可视化页还没有把它展示为通用关系图。",
  };
}

export function CaseVisualizationWorkspace() {
  const [analysis, setAnalysis] = useState<Analysis>("distribution");
  const [source, setSource] = useState<Source>("mine");
  const [referenceSummary, setReferenceSummary] = useState<CaseCorpusSummary | null>(null);
  const [myCaseCount, setMyCaseCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasRun, setHasRun] = useState(false);
  const [topN, setTopN] = useState("all");
  const [property, setProperty] = useState("四气");
  const [clusterMethod, setClusterMethod] = useState("层次聚类");
  const [clusterCount, setClusterCount] = useState("4");
  const [minimumSupport, setMinimumSupport] = useState("0.10");
  const [minimumConfidence, setMinimumConfidence] = useState("0.50");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setHasRun(false);
    if (source === "reference") setReferenceSummary(null);
    else setMyCaseCount(null);
    const request = source === "reference"
      ? getCaseCorpusSummary().then(result => { if (active) setReferenceSummary(result); })
      : getMedicalCases(1, false).then(result => { if (active) setMyCaseCount(result.count); });
    request.catch(cause => { if (active) setError(initialError(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [source]);

  const current = modules.find(item => item.key === analysis) ?? modules[0];
  const Icon = current.icon;
  const categories: CaseCountSeries[] = (referenceSummary?.categories ?? []).map(category => ({ name: category.label, value: category.count }));
  const categoryTotal = categories.reduce((sum, row) => sum + row.value, 0);
  const canDrawReferenceCategories = !loading && !error && source === "reference" && Boolean(referenceSummary?.available) && categoryTotal > 0;
  const sourceLabel = source === "mine" ? "我的医案 · 使用中的记录" : `参考医案库${referenceSummary?.version ? ` · ${referenceSummary.version}` : ""}`;
  const ready = analysis === "distribution" && source === "reference" && canDrawReferenceCategories;
  const guide = methodGuide(analysis, source, Boolean(referenceSummary?.available), clusterMethod);

  function changeAnalysis(next: Analysis) {
    setAnalysis(next);
    setHasRun(false);
  }

  return <section className="case-visualization" aria-label="医案分析与图像生成">
    <header className="case-visualization-heading">
      <div><span className="case-visualization-eyebrow">医案数据分析</span><h2 className="section-title-sm">按研究问题配置图像</h2><p className="section-help">先选择数据范围与分析类型，再查看图像、明细和来源说明。</p></div>
      <span className="status-badge">图像由当前分析数据生成</span>
    </header>

    <div className="case-visualization-workspace">
      <nav className="case-visualization-nav" aria-label="医案分析方法">
        <div className="case-visualization-nav-title">分析方法</div>
        {modules.map(item => {
          const ItemIcon = item.icon;
          return <button key={item.key} className="case-visualization-nav-item" type="button" aria-current={analysis === item.key ? "page" : undefined} onClick={() => changeAnalysis(item.key)}><ItemIcon size={18} /><span>{item.label}</span><span className="case-visualization-nav-chevron">›</span></button>;
        })}
        <div className="case-visualization-nav-note"><strong>按研究问题选择方法</strong><span>数据范围、配置项与可展示结果会随分析方法变化。</span></div>
      </nav>
      <div className="case-visualization-main">
        <div className="case-visualization-intro"><div className="case-visualization-module-icon"><Icon size={22} /></div><div><h3 className="section-title-sm">{current.label}</h3><p>{current.summary}</p></div></div>

        <details className="case-visualization-method">
          <summary><span><strong>算法与用途</strong><span className="case-visualization-method-status">{guide.method}</span></span><span className="case-visualization-method-action">查看原理</span></summary>
          <div className="case-visualization-method-body">
            <p>{guide.introduction}</p>
            <p>{guide.principle}</p>
            <p className="case-visualization-method-lead">其基本步骤是：</p>
            <ol>{guide.steps.map((step, index) => <li key={`method-${index}`}>{step}</li>)}</ol>
            <p>{guide.interpretation}</p>
            <p className="case-visualization-method-state"><strong>本项目实现情况：</strong>{guide.projectState}</p>
          </div>
        </details>

        <section className="case-visualization-source" aria-label="数据范围">
          <div className="case-visualization-section-heading"><div><h4>选择数据范围</h4><p>选择用于本次分析的医案来源。</p></div><span className="case-visualization-data-tag">{sourceLabel}</span></div>
          <div className="case-visualization-source-options" role="group" aria-label="选择数据来源">
            <button type="button" className={source === "mine" ? "is-selected" : ""} aria-pressed={source === "mine"} onClick={() => setSource("mine")}><strong>我的医案</strong><span>个人保存、未归档记录</span></button>
            <button type="button" className={source === "reference" ? "is-selected" : ""} aria-pressed={source === "reference"} onClick={() => setSource("reference")}><strong>参考医案库</strong><span>当前启用版本</span></button>
          </div>
          <div className="case-visualization-source-meta" aria-live="polite">
            {loading ? "正在读取所选数据范围…" : error ? error : source === "mine"
              ? `当前账号可见 ${myCaseCount ?? 0} 条使用中医案。${myCaseCount ? "现有接口只返回记录总数；完整字段分布需待分析汇总接口接入。" : "添加并整理医案后可继续分析。"}`
              : referenceSummary?.available
                ? `${referenceSummary.sourceName} · ${referenceSummary.recordCount.toLocaleString("zh-CN")} 条 · 版本 ${referenceSummary.version ?? "未登记"}`
                : "参考医案库当前不可用；恢复语料库连接后可读取分类统计。"}
          </div>
        </section>

        <section className="case-visualization-config" aria-label={`${current.label}分析配置`}>
          <div className="case-visualization-section-heading"><div><h4>分析配置</h4><p>{current.requirement}</p></div></div>
          {analysis === "distribution" && <div className="case-visualization-fields">
            <label className="form-label">统计字段<select className="field" value={source === "reference" ? "category" : "awaiting"} disabled><option value="category">疾病类别（参考库登记类别）</option><option value="awaiting">等待完整字段统计</option></select><small>疾病、证型、症状、四诊、治法、方剂和药物分布将在结构化数据就绪后逐项开放。</small></label>
            <label className="form-label">显示数量<select className="field" value={topN} onChange={event => { setTopN(event.target.value); setHasRun(false); }}><option value="all">全部类别</option>{categories.length > 5 && <option value="5">前 5 类</option>}{categories.length > 10 && <option value="10">前 10 类</option>}</select></label>
          </div>}
          {analysis === "medication" && <div className="case-visualization-fields">
            <label className="form-label">用药属性<select className="field" value={property} onChange={event => setProperty(event.target.value)}><option>四气</option><option>五味</option><option>归经</option><option>功效</option></select></label>
            <label className="form-label">图像类型<select className="field" disabled><option>频次条形图 / 雷达图</option></select></label>
          </div>}
          {analysis === "association" && <div className="case-visualization-fields">
            <label className="form-label">前项<select className="field" disabled><option>待结构化症状与证候</option></select></label>
            <label className="form-label">后项<select className="field" disabled><option>待结构化治法、方剂或药物</option></select></label>
            <label className="form-label">最小支持度<input className="field" type="number" min="0.01" max="1" step="0.01" value={minimumSupport} onChange={event => setMinimumSupport(event.target.value)} /></label>
            <label className="form-label">最小置信度<input className="field" type="number" min="0.01" max="1" step="0.01" value={minimumConfidence} onChange={event => setMinimumConfidence(event.target.value)} /></label>
          </div>}
          {analysis === "clustering" && <div className="case-visualization-fields">
            <label className="form-label">聚类方法<select className="field" value={clusterMethod} onChange={event => setClusterMethod(event.target.value)}><option>层次聚类</option><option>K-Means</option></select></label>
            <label className="form-label">目标类别数<input className="field" type="number" min="2" max="20" value={clusterCount} onChange={event => setClusterCount(event.target.value)} /></label>
            <label className="form-label">距离类型<select className="field" disabled><option>待病例特征编码后选择</option></select></label>
          </div>}
          {analysis === "relations" && <div className="case-visualization-fields">
            <label className="form-label">关系层级<select className="field" disabled><option>症状 → 证候 → 治法 → 方剂 → 药物</option></select></label>
            <label className="form-label">节点范围<select className="field" disabled><option>待整理实体和诊次编号</option></select></label>
          </div>}
          <p className="case-visualization-requirement"><strong>数据要求：</strong>{current.requirement}</p>
          {analysis === "relations" && <p className="notice-info case-visualization-boundary">知识图谱先保留位置。等医案数据处理并导入后，再按实体、诊次和证据生成关系图。</p>}
          {analysis === "association" && <p className="notice-info case-visualization-boundary">关联结果只表示当前数据中的共同出现或规则关系，不解释为因果。原文不会按逗号等标点自动拆成多个成分。</p>}
          <div className="case-visualization-actions"><button className="btn btn-primary" type="button" disabled={!ready || loading || Boolean(error)} onClick={() => setHasRun(true)}>开始分析</button><span className="section-help">{ready ? "可以按参考库类别生成当前支持的分布图。" : "所选范围或字段尚不足以生成真实图像。"}</span></div>
        </section>

        <section className="case-visualization-result" aria-label="分析图像与结果">
          <div className="case-visualization-section-heading"><div><h4>图像与结果</h4><p>{current.output} · 数据表与下载放在图像下方。</p></div><span className="status-badge">{hasRun && ready ? "已生成" : "等待分析"}</span></div>
          {hasRun && ready ? <CaseCountFigure title="参考医案疾病类别分布" data={topN === "all" ? categories : categories.slice(0, Number(topN))} scope={`当前启用参考库 · ${categories.length} 个登记类别`} version={referenceSummary?.version} filename="reference-case-category-distribution" /> : <div className="case-visualization-empty">
            <div className="case-visualization-empty-icon"><Icon size={27} /></div>
            <strong>{source === "reference" && !loading && !referenceSummary?.available ? "参考医案库尚未接通" : source === "mine" && !loading ? "待整理医案字段" : `${current.label}结果将在这里显示`}</strong>
            <p>{analysis === "distribution" && source === "mine"
              ? "个人医案目前只有分页读取接口，不能用当前一页冒充全部记录。接入完整范围统计后，这里按真实字段绘图。"
              : analysis === "distribution" && source === "reference"
                ? "恢复参考语料库后，可先按真实登记类别生成分布图，并查看同一批数据的明细表和 SVG / CSV 下载。"
                : current.requirement}</p>
            <span>{current.output}</span>
          </div>}
        </section>
      </div>
    </div>
    <footer className="case-visualization-footnote">当前只有“参考库登记类别分布”具备现成的数据汇总字段；其他图像在对应数据和算法接入前不会显示演示性结果。分析范围：{sourceLabel}。</footer>
  </section>;
}
