import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Activity, ArrowLeft, Download, Play, RefreshCw } from "lucide-react";
import {
  getAnalysisTask,
  getAnalysisTasks,
  getDatasets,
  getProteomicsRows,
  exportProteomicsResults,
  runProteomicsAnalysis,
  type AnalysisTask,
  type ProteomicsResult,
  type ProteomicsRowPage,
  type ResearchDataset,
} from "../api/datasets";
import { ApiError } from "../api/client";
import { createVisualization } from "../api/network";
import { StringNetworkResult } from "../components/StringNetworkResult";
import { RAnalysisGallery } from "../components/RAnalysisGallery";
import { RDemoGallery } from "../components/RDemoGallery";

const initialMapping = {
  geneColumn: "",
  proteinColumn: "",
  log2FcColumn: "",
  fdrColumn: "",
  pValueColumn: "",
  directionColumn: "",
};

function splitColumnNames(value: string) {
  return [...new Set(value.split(/[,，、;；|\n\r]+/).map((item) => item.trim()).filter(Boolean))];
}

function parseSamplePairs(value: string) {
  const lines = value.split(/[\n\r]+/).map((line) => line.trim()).filter(Boolean);
  const samplePairs: { pairId: string; controlSample: string; treatmentSample: string }[] = [];
  let invalidLineCount = 0;
  lines.forEach((line) => {
    const columns = line.split(/[,，\t;；]+/).map((item) => item.trim());
    if (columns.length !== 3 || columns.some((item) => !item)) {
      invalidLineCount += 1;
      return;
    }
    samplePairs.push({ pairId: columns[0], controlSample: columns[1], treatmentSample: columns[2] });
  });
  return { samplePairs, invalidLineCount };
}

function parseSampleFactors(value: string) {
  const lines = value.split(/[\n\r]+/).map((line) => line.trim()).filter(Boolean);
  const sampleFactors: { sampleColumn: string; factors: Record<string, string> }[] = [];
  let invalidLineCount = 0;
  lines.forEach((line) => {
    const [sampleColumn, ...entries] = line.split(/[,，\t;；]+/).map((item) => item.trim());
    const factors: Record<string, string> = {};
    let invalid = !sampleColumn || entries.length < 2;
    entries.forEach((entry) => {
      const separator = entry.indexOf("=");
      const name = separator < 0 ? "" : entry.slice(0, separator).trim();
      const level = separator < 0 ? "" : entry.slice(separator + 1).trim();
      if (!name || !level || Object.hasOwn(factors, name)) invalid = true;
      else factors[name] = level;
    });
    if (invalid) invalidLineCount += 1;
    else sampleFactors.push({ sampleColumn, factors });
  });
  return { sampleFactors, invalidLineCount };
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function formatNumber(value: number | null | undefined) {
  return value == null ? "—" : Number(value).toPrecision(4);
}

function formatExternalIdentifiers(identifiers: Array<{ namespace: string; identifier: string; source: string; sourceVersion: string | null }> | undefined) {
  if (!identifiers?.length) return "—";
  return identifiers.map((item) =>
    `${item.namespace}:${item.identifier} · ${item.source}${item.sourceVersion ? `@${item.sourceVersion}` : ""}`,
  ).join("；");
}

function taskStatusLabel(status: AnalysisTask["status"]) {
  return ({ queued: "排队中", running: "分析中", succeeded: "已完成", failed: "失败", cancelled: "已取消" })[status];
}

function mappingStatusLabel(status: string) {
  return ({
    database: "本地核实",
    external: "外部映射",
    unverified: "未核实候选",
    ambiguous: "标识歧义",
    unmapped: "未映射",
    missing: "缺少标识",
  } as Record<string, string>)[status] ?? status;
}

function qualityReasonLabel(reason: string) {
  return ({
    missing_identifier: "缺少基因/蛋白标识",
    invalid_sample_values: "样本数值非法",
    missing_sample_values: "样本值缺失",
    incomplete_samples: "部分样本缺失，整行未检验",
    insufficient_valid_replicates: "有效重复数不足",
    insufficient_valid_pairs: "有效配对数不足",
    insufficient_model_degrees_of_freedom: "样本不足以估计模型",
    rank_deficient_sample_design: "缺失值导致模型因素共线，无法估计",
    test_not_estimable: "当前重复值无法估计统计检验",
    invalid_log2fc: "log2FC 数值非法",
    missing_log2fc: "缺少 log2FC",
    log2fc_below_threshold: "log2FC 未达到阈值",
    missing_significance: "缺少显著性数值",
    invalid_significance: "显著性数值非法",
    fdr_above_threshold: "FDR 超过阈值",
    p_value_above_threshold: "P 值超过阈值",
    local_target_name_only: "旧库仅有靶点名称，规范基因标识待核对",
    local_target_symbol_unverified: "旧库符号候选尚未核实",
  } as Record<string, string>)[reason] ?? reason;
}

function downloadJson(filename: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ProteomicsPage() {
  const [datasets, setDatasets] = useState<ResearchDataset[]>([]);
  const [datasetId, setDatasetId] = useState<number | "">("");
  const [task, setTask] = useState<AnalysisTask | null>(null);
  const [visualizationTask, setVisualizationTask] = useState<AnalysisTask | null>(null);
  const [volcanoVisualizationTask, setVolcanoVisualizationTask] = useState<AnalysisTask | null>(null);
  const [analysisMode, setAnalysisMode] = useState<"differential_table" | "raw_matrix">("differential_table");
  const [matrixDesignType, setMatrixDesignType] = useState<"unpaired" | "paired" | "multifactor">("unpaired");
  const [mapping, setMapping] = useState(initialMapping);
  const [matrixIdentifierColumn, setMatrixIdentifierColumn] = useState("");
  const [controlSampleColumns, setControlSampleColumns] = useState("");
  const [treatmentSampleColumns, setTreatmentSampleColumns] = useState("");
  const [pairedSampleColumns, setPairedSampleColumns] = useState("");
  const [factorSampleColumns, setFactorSampleColumns] = useState("");
  const [contrastFactor, setContrastFactor] = useState("");
  const [referenceLevel, setReferenceLevel] = useState("");
  const [treatmentLevel, setTreatmentLevel] = useState("");
  const [matrixValueScale, setMatrixValueScale] = useState("");
  const [matrixNormalization, setMatrixNormalization] = useState("");
  const [matrixMissingPolicy, setMatrixMissingPolicy] = useState("");
  const [thresholds, setThresholds] = useState({ log2FcMin: "1", fdrMax: "0.05", pValueMax: "0.05" });
  const [referenceTargets, setReferenceTargets] = useState("");
  const [externalReactome, setExternalReactome] = useState(false);
  const [externalString, setExternalString] = useState(false);
  const [externalGProfiler, setExternalGProfiler] = useState(false);
  const [stringRequiredScore, setStringRequiredScore] = useState("700");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [visualizationSubmitting, setVisualizationSubmitting] = useState(false);
  const [showRows, setShowRows] = useState(false);
  const [rowPageNumber, setRowPageNumber] = useState(1);
  const [rowPage, setRowPage] = useState<ProteomicsRowPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([getDatasets(), getAnalysisTasks()])
      .then(([datasetResponse, taskResponse]) => {
        if (!active) return;
        setDatasets(datasetResponse.results);
        if (datasetResponse.results.length) setDatasetId(datasetResponse.results[0].id);
        const latestTask = taskResponse.results.find((item) => item.task_type === "proteomics");
        if (latestTask) {
          setTask(latestTask);
          if (latestTask.dataset) setDatasetId(latestTask.dataset);
          const latestVisualization = taskResponse.results.find((item) =>
            item.task_type === "visualization"
            && item.input_parameters.analysisKind === "r_visualization"
            && item.input_parameters.chartKey === "proteomics_go_kegg_enrichment"
            && Number(item.input_parameters.parentTaskId) === latestTask.id,
          );
          if (latestVisualization) setVisualizationTask(latestVisualization);
          const latestVolcanoVisualization = taskResponse.results.find((item) =>
            item.task_type === "visualization"
            && item.input_parameters.analysisKind === "r_visualization"
            && item.input_parameters.chartKey === "proteomics_volcano"
            && Number(item.input_parameters.parentTaskId) === latestTask.id,
          );
          if (latestVolcanoVisualization) setVolcanoVisualizationTask(latestVolcanoVisualization);
        }
      })
      .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!task || !["queued", "running"].includes(task.status)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      getAnalysisTask(task.id)
        .then((latest) => { if (active) setTask(latest); })
        .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); });
    }, 1400);
    return () => { active = false; window.clearTimeout(timer); };
  }, [task]);

  useEffect(() => {
    if (!visualizationTask || !["queued", "running"].includes(visualizationTask.status)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      getAnalysisTask(visualizationTask.id)
        .then((latest) => { if (active) setVisualizationTask(latest); })
        .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); });
    }, 1400);
    return () => { active = false; window.clearTimeout(timer); };
  }, [visualizationTask]);

  useEffect(() => {
    if (!volcanoVisualizationTask || !["queued", "running"].includes(volcanoVisualizationTask.status)) return;
    let active = true;
    const timer = window.setTimeout(() => {
      getAnalysisTask(volcanoVisualizationTask.id)
        .then((latest) => { if (active) setVolcanoVisualizationTask(latest); })
        .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); });
    }, 1400);
    return () => { active = false; window.clearTimeout(timer); };
  }, [volcanoVisualizationTask]);

  useEffect(() => {
    if (!showRows || !task || task.status !== "succeeded") return;
    let active = true;
    getProteomicsRows(task.id, rowPageNumber)
      .then((value) => { if (active) setRowPage(value); })
      .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); });
    return () => { active = false; };
  }, [showRows, task, rowPageNumber]);

  const selectedDataset = useMemo(
    () => datasets.find((item) => item.id === datasetId) ?? null,
    [datasets, datasetId],
  );
  const taskDataset = useMemo(
    () => datasets.find((item) => item.id === task?.dataset) ?? null,
    [datasets, task?.dataset],
  );
  const result = task?.status === "succeeded" && task.task_type === "proteomics"
    ? task.result as ProteomicsResult
    : null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDataset) return;
    const parsedPairs = parseSamplePairs(pairedSampleColumns);
    const parsedFactors = parseSampleFactors(factorSampleColumns);
    const controlColumns = matrixDesignType === "paired"
      ? parsedPairs.samplePairs.map((pair) => pair.controlSample)
      : matrixDesignType === "multifactor" ? [] : splitColumnNames(controlSampleColumns);
    const treatmentColumns = matrixDesignType === "paired"
      ? parsedPairs.samplePairs.map((pair) => pair.treatmentSample)
      : matrixDesignType === "multifactor" ? [] : splitColumnNames(treatmentSampleColumns);
    const allSampleColumns = matrixDesignType === "multifactor"
      ? parsedFactors.sampleFactors.map((assignment) => assignment.sampleColumn)
      : [...controlColumns, ...treatmentColumns];
    const factorNames = Object.keys(parsedFactors.sampleFactors[0]?.factors ?? {});
    const hasConsistentFactorNames = parsedFactors.sampleFactors.every(
      (assignment) => Object.keys(assignment.factors).sort().join("\u0000") === [...factorNames].sort().join("\u0000"),
    );
    const contrastLevels = parsedFactors.sampleFactors
      .map((assignment) => assignment.factors[contrastFactor.trim()])
      .filter((level): level is string => Boolean(level));
    const contrastHasReplicates = [referenceLevel.trim(), treatmentLevel.trim()].every(
      (level) => contrastLevels.filter((value) => value === level).length >= 2,
    );
    if (analysisMode === "raw_matrix" && (
      !matrixIdentifierColumn.trim()
      || (matrixDesignType === "unpaired" && (controlColumns.length < 2 || treatmentColumns.length < 2))
      || (matrixDesignType === "paired" && (parsedPairs.invalidLineCount > 0 || parsedPairs.samplePairs.length < 2))
      || (matrixDesignType === "multifactor" && (
        parsedFactors.invalidLineCount > 0 || parsedFactors.sampleFactors.length < 4
        || factorNames.length < 2 || !hasConsistentFactorNames
        || !contrastFactor.trim() || !referenceLevel.trim() || !treatmentLevel.trim()
        || !contrastHasReplicates || referenceLevel.trim() === treatmentLevel.trim()
      ))
      || !matrixValueScale || !matrixNormalization || !matrixMissingPolicy
    )) {
      setError("请完整填写原始矩阵实验设计、样本分组、主要对比，以及数值尺度、归一化和缺失值策略。");
      return;
    }
    if (analysisMode === "raw_matrix" && matrixDesignType === "paired" && new Set(parsedPairs.samplePairs.map((pair) => pair.pairId)).size !== parsedPairs.samplePairs.length) {
      setError("每一对样本必须使用唯一的配对编号。");
      return;
    }
    if (analysisMode === "raw_matrix" && matrixDesignType !== "unpaired" && new Set(allSampleColumns).size !== allSampleColumns.length) {
      setError("每个样本列只能出现在设计中一次。");
      return;
    }
    if (analysisMode === "raw_matrix" && new Set(allSampleColumns).size > 100) {
      setError("原始矩阵每次最多选择 100 个样本列。");
      return;
    }
    setSubmitting(true);
    setError(null);
    setNotice(null);
    setShowRows(false);
    setRowPage(null);
    setVisualizationTask(null);
    try {
      const taskResponse = await runProteomicsAnalysis(selectedDataset.id, {
        analysisMode,
        ...(analysisMode === "raw_matrix" ? {
          matrixDesign: {
            identifierColumn: matrixIdentifierColumn.trim(),
            sampleColumns: [...new Set(allSampleColumns)],
            designType: matrixDesignType,
            ...(matrixDesignType !== "multifactor" ? {
              controlSamples: controlColumns,
              treatmentSamples: treatmentColumns,
            } : {}),
            ...(matrixDesignType === "paired" ? { samplePairs: parsedPairs.samplePairs } : {}),
            ...(matrixDesignType === "multifactor" ? {
              sampleFactors: parsedFactors.sampleFactors,
              contrastFactor: contrastFactor.trim(),
              referenceLevel: referenceLevel.trim(),
              treatmentLevel: treatmentLevel.trim(),
            } : {}),
            valuesAreLog2: matrixValueScale === "log2",
            normalization: matrixNormalization as "none" | "median_center",
            missingPolicy: matrixMissingPolicy as "complete_rows" | "available_replicates",
          },
        } : { mapping }),
        thresholds: {
          log2FcMin: Number(thresholds.log2FcMin),
          fdrMax: Number(thresholds.fdrMax),
          pValueMax: Number(thresholds.pValueMax),
        },
        referenceTargets: referenceTargets.split(/[\s,，、;；|/]+/).filter(Boolean),
        externalReactome,
        externalString,
        externalGProfiler,
        stringRequiredScore: Number(stringRequiredScore),
      });
      setTask(taskResponse);
      setNotice(`分析任务 #${taskResponse.id} 已进入后台队列。`);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  }

  async function exportRows(format: "csv" | "xlsx" | "pdf") {
    if (!task) return;
    setError(null);
    try {
      const blob = await exportProteomicsResults(task.id, format);
      downloadBlob(`proteomics-task-${task.id}.${format}`, blob);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  async function requestGoKeggVisualization() {
    if (!task || task.status !== "succeeded") return;
    setError(null);
    setVisualizationSubmitting(true);
    try {
      setVisualizationTask(await createVisualization(task.id, "proteomics_go_kegg_enrichment"));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setVisualizationSubmitting(false);
    }
  }

  async function requestVolcanoVisualization() {
    if (!task || task.status !== "succeeded") return;
    setError(null);
    setVisualizationSubmitting(true);
    try {
      setVolcanoVisualizationTask(await createVisualization(task.id, "proteomics_volcano"));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setVisualizationSubmitting(false);
    }
  }

  return <>
    <RDemoGallery />

      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Proteomics analysis</p><h1 className="page-title">差异蛋白组学分析</h1>
        <p className="page-description">复用 main 分支的差异蛋白筛选和本地网络逻辑；逐行保留筛选、映射和排除原因，未验证的符号会明确标出。</p></div>
        <Link to="/datasets" className="btn btn-secondary"><ArrowLeft size={16} />数据集管理</Link>
      </div>

      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {notice && <div className="notice-success workspace-notice" role="status">{notice}</div>}

      <div className="case-workspace-grid proteomics-workspace-grid">
        <form className="panel case-form" onSubmit={(event) => void submit(event)} aria-label="启动差异蛋白分析">
          <div className="panel-header"><div><h2 className="section-title-sm">分析设置</h2><p className="section-help">数据集原始文件不会发送到外部服务。</p></div><span className="page-heading-icon"><Activity size={19} /></span></div>
          <div className="case-form-fields">
            {loading ? <p className="section-help" role="status">正在读取你的数据集…</p> : datasets.length ? <label className="form-label" htmlFor="proteomics-dataset">选择已上传数据集
              <select className="field" id="proteomics-dataset" value={datasetId} onChange={(event) => setDatasetId(Number(event.target.value))}>
                {datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.original_filename}</option>)}
              </select></label> : <div className="empty-state"><strong>还没有可分析的数据集</strong><p>先上传差异蛋白 CSV、TSV 或 Excel 文件。</p><Link className="btn btn-secondary" to="/datasets">上传数据集</Link></div>}

            {datasets.length > 0 && <>
              <label className="form-label" htmlFor="proteomics-analysis-mode">输入数据类型<select className="field" id="proteomics-analysis-mode" value={analysisMode} onChange={(event) => setAnalysisMode(event.target.value as "differential_table" | "raw_matrix")}><option value="differential_table">已计算的差异蛋白表</option><option value="raw_matrix">原始定量矩阵</option></select></label>
              {analysisMode === "differential_table" ? <>
                <p className="section-help">常见表头会自动识别。若使用了特殊表头，请填写文件中的确切列名；基因列和蛋白列至少能识别一个。</p>
                <div className="proteomics-column-grid">
                {([
                  ["geneColumn", "基因列", "Gene Symbol / 基因符号"],
                  ["proteinColumn", "蛋白列", "Protein / UniProt"],
                  ["log2FcColumn", "log2FC 列", "log2FC"],
                  ["fdrColumn", "FDR 列", "FDR / padj"],
                  ["pValueColumn", "P 值列", "pvalue"],
                  ["directionColumn", "变化方向列", "direction"],
                ] as const).map(([key, label, placeholder]) => <label className="form-label" key={key}>{label}
                  <input className="field" value={mapping[key]} placeholder={placeholder} onChange={(event) => setMapping((value) => ({ ...value, [key]: event.target.value }))} />
                </label>)}
                </div>
              </> : <section className="raw-matrix-design">
                <label className="form-label">实验设计<select className="field" value={matrixDesignType} onChange={(event) => setMatrixDesignType(event.target.value as "unpaired" | "paired" | "multifactor")}><option value="unpaired">独立样本（非配对）</option><option value="paired">配对样本</option><option value="multifactor">多因素（分类因素加性模型）</option></select></label>
                <p className="section-help">请按实验记录明确指定样本分组，不会根据列名、顺序或数值猜测设计。多因素首版只拟合各因素主效应，不含交互项。</p>
                <label className="form-label">蛋白/基因标识列<input className="field" value={matrixIdentifierColumn} onChange={(event) => setMatrixIdentifierColumn(event.target.value)} placeholder="例如：Gene Symbol、UniProt" required /></label>
                {matrixDesignType === "unpaired" ? <>
                  <label className="form-label">对照组样本列<textarea className="field case-textarea case-textarea-short" value={controlSampleColumns} onChange={(event) => setControlSampleColumns(event.target.value)} placeholder="例如：Control_1, Control_2, Control_3" required /></label>
                  <label className="form-label">实验组样本列<textarea className="field case-textarea case-textarea-short" value={treatmentSampleColumns} onChange={(event) => setTreatmentSampleColumns(event.target.value)} placeholder="例如：Treatment_1, Treatment_2, Treatment_3" required /></label>
                </> : matrixDesignType === "paired" ? <label className="form-label">配对样本关系<textarea className="field case-textarea" value={pairedSampleColumns} onChange={(event) => setPairedSampleColumns(event.target.value)} placeholder={"每行填写：配对编号，对照列，实验列\n受试者 1, Control_1, Treatment_1\n受试者 2, Control_2, Treatment_2"} required /><span className="field-help">至少填写 2 对。每行用逗号或制表符分隔，配对编号要唯一，样本列不能重复。</span></label> : <>
                  <label className="form-label">样本列与因素水平<textarea className="field case-textarea" value={factorSampleColumns} onChange={(event) => setFactorSampleColumns(event.target.value)} placeholder={"每行填写：样本列, 因素名=水平, 因素名=水平\nControl_B1_1, treatment=control, batch=B1\nControl_B2_1, treatment=control, batch=B2\nDrug_B1_1, treatment=drug, batch=B1\nDrug_B2_1, treatment=drug, batch=B2"} required /><span className="field-help">每个样本一行；每行至少写 2 个分类因素，因素名在所有行保持一致。每个主要对比水平至少 2 个样本，且因素组合须能估计所选模型。</span></label>
                  <div className="proteomics-column-grid">
                    <label className="form-label">主要对比因素<input className="field" value={contrastFactor} onChange={(event) => setContrastFactor(event.target.value)} placeholder="例如：treatment" required /></label>
                    <label className="form-label">参考水平<input className="field" value={referenceLevel} onChange={(event) => setReferenceLevel(event.target.value)} placeholder="例如：control" required /></label>
                    <label className="form-label">实验水平<input className="field" value={treatmentLevel} onChange={(event) => setTreatmentLevel(event.target.value)} placeholder="例如：drug" required /></label>
                  </div>
                </>}
                <div className="proteomics-column-grid">
                  <label className="form-label">样本数值尺度<select className="field" value={matrixValueScale} onChange={(event) => setMatrixValueScale(event.target.value)} required><option value="">请选择</option><option value="linear">原始正值强度（执行 log2 转换）</option><option value="log2">文件中已经是 log2 值</option></select></label>
                  <label className="form-label">样本归一化<select className="field" value={matrixNormalization} onChange={(event) => setMatrixNormalization(event.target.value)} required><option value="">请选择</option><option value="median_center">按样本中位数中心化</option><option value="none">不再归一化（数据已处理）</option></select></label>
                  <label className="form-label">缺失值策略<select className="field" value={matrixMissingPolicy} onChange={(event) => setMatrixMissingPolicy(event.target.value)} required><option value="">请选择</option><option value="complete_rows">任一样本缺失则排除整行</option><option value="available_replicates">按可用重复计算（每组至少 2 个）</option></select></label>
                </div>
              </section>}
              <div className="proteomics-threshold-grid">
                <label className="form-label">|log2FC| ≥<input className="field" type="number" min="0" max="100" step="0.1" value={thresholds.log2FcMin} onChange={(event) => setThresholds((value) => ({ ...value, log2FcMin: event.target.value }))} /></label>
                <label className="form-label">FDR ≤<input className="field" type="number" min="0" max="1" step="0.01" value={thresholds.fdrMax} onChange={(event) => setThresholds((value) => ({ ...value, fdrMax: event.target.value }))} /></label>
                <label className="form-label">P 值 ≤<input className="field" type="number" min="0" max="1" step="0.01" value={thresholds.pValueMax} onChange={(event) => setThresholds((value) => ({ ...value, pValueMax: event.target.value }))} /></label>
              </div>
              <label className="form-label" htmlFor="proteomics-reference">候选靶点（可选）
                <textarea className="field case-textarea case-textarea-short" id="proteomics-reference" value={referenceTargets} onChange={(event) => setReferenceTargets(event.target.value)} placeholder="TP53, IL6, MAPK1" />
              </label>
              <label className="proteomics-consent">
                <input type="checkbox" checked={externalReactome} onChange={(event) => setExternalReactome(event.target.checked)} />
                <span><strong>启用 MyGene.info 标识映射与 Reactome 富集</strong><small>仅发送通过筛选的基因/蛋白标识（最多 500 个），不会发送完整文件、未通过行、账号或医案。当前外部分析仅支持人类标识；不勾选时所有分析留在本地。</small></span>
              </label>
              <label className="proteomics-consent">
                <input type="checkbox" checked={externalGProfiler} onChange={(event) => setExternalGProfiler(event.target.checked)} />
                <span><strong>单独同意提交 g:Profiler 进行 GO/KEGG 富集</strong><small>将发送最多 500 个通过筛选的规范化符号作为查询集，并发送最多 25,000 个所有输入行中可识别的规范化符号作为自定义背景；只发送这些基因标识，不发送原始文件、账号或医案。服务按人类数据分析；使用 FDR 校正，默认关闭。</small></span>
              </label>
              <label className="proteomics-consent">
                <input type="checkbox" checked={externalString} onChange={(event) => setExternalString(event.target.checked)} />
                <span><strong>另行同意查询 STRING 物理互作（PPI）</strong><small>最多发送筛选后 200 个基因/蛋白标识，只查询人类物理互作；不会发送原始文件或其他行。STRING 分数表示数据库互作证据，不证明因果关系。</small></span>
              </label>
              {externalString && <label className="form-label">STRING 最低置信度（0–1000）
                <input className="field" type="number" min="0" max="1000" step="50" value={stringRequiredScore} onChange={(event) => setStringRequiredScore(event.target.value)} />
              </label>}
            </>}
          </div>
          <div className="case-form-footer"><p>阈值筛选不会把缺失或非法统计值默认为显著。</p>
            <button className="btn btn-primary" type="submit" disabled={!selectedDataset || submitting || task?.status === "queued" || task?.status === "running"}>
              {submitting ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}{submitting ? "正在提交…" : "提交后台分析"}
            </button></div>
        </form>

        <section className="case-list" aria-labelledby="proteomics-results-heading">
          <div className="case-list-heading"><div><p className="page-kicker">Reproducible analysis</p><h2 id="proteomics-results-heading" className="section-title-sm">分析结果</h2></div>
            {task && <span className={`status-badge ${task.status === "failed" ? "status-error" : task.status === "succeeded" ? "status-success" : "status-warning"}`}>{taskStatusLabel(task.status)}</span>}
          </div>
          {!task ? <div className="panel empty-state"><Activity size={27} /><strong>等待分析任务</strong><p>选择一个已上传的数据集并提交分析设置。</p></div>
            : <article className="panel proteomics-result-panel">
              <div className="case-record-top"><div><h3>任务 #{task.id} · {taskDataset?.name ?? `数据集 ${task.dataset ?? "已移除"}`}</h3><time dateTime={task.created_at}>创建于 {new Date(task.created_at).toLocaleString("zh-CN")}</time></div>
                {result && <div className="proteomics-export-actions">
                  <button type="button" className="btn btn-secondary" onClick={() => void exportRows("csv")}><Download size={15} />CSV</button>
                  <button type="button" className="btn btn-secondary" onClick={() => void exportRows("xlsx")}><Download size={15} />XLSX</button>
                  <button type="button" className="btn btn-secondary" onClick={() => void exportRows("pdf")}><Download size={15} />PDF 报告</button>
                  <button type="button" className="btn btn-secondary" onClick={() => downloadJson(`proteomics-task-${task.id}.json`, result)}><Download size={15} />JSON</button>
                </div>}</div>
              {(task.status === "queued" || task.status === "running") && <div className="analysis-progress" role="status"><span>任务已排队，分析过程在后台运行。</span><progress max={100} value={task.progress} /></div>}
              {task.status === "failed" && <div className="notice-error" role="alert">{task.error_summary || "分析失败，请检查文件和列映射。"}</div>}
              {result && <ProteomicsResultView result={result} task={task} showRows={showRows} rowPage={rowPage} rowPageNumber={rowPageNumber}
                visualizationTask={visualizationTask} volcanoVisualizationTask={volcanoVisualizationTask} visualizationSubmitting={visualizationSubmitting}
                onCreateVolcanoVisualization={() => void requestVolcanoVisualization()}
                onCreateGoKeggVisualization={() => void requestGoKeggVisualization()}
                onToggleRows={() => { setShowRows((value) => !value); setRowPageNumber(1); }}
                onRowPageChange={setRowPageNumber} />}
            </article>}
        </section>
      </div>

  </>;
}

function Metric({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return <div className="proteomics-metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

function ProteomicsResultView({
  result, task, showRows, rowPage, rowPageNumber, visualizationTask, volcanoVisualizationTask, visualizationSubmitting,
  onCreateVolcanoVisualization, onCreateGoKeggVisualization, onToggleRows, onRowPageChange,
}: {
  result: ProteomicsResult;
  task: AnalysisTask;
  showRows: boolean;
  rowPage: ProteomicsRowPage | null;
  rowPageNumber: number;
  visualizationTask: AnalysisTask | null;
  volcanoVisualizationTask: AnalysisTask | null;
  visualizationSubmitting: boolean;
  onCreateVolcanoVisualization: () => void;
  onCreateGoKeggVisualization: () => void;
  onToggleRows: () => void;
  onRowPageChange: (page: number) => void;
}) {
  return <div className="proteomics-result-content">
    <p className="section-help">原始文件 SHA-256：<code>{result.dataset.sha256}</code> · 算法版本：{result.algorithmVersion} · 来源版本数：{task.source_releases.length}</p>
    <div className="proteomics-metrics">
      <Metric label="通过筛选" value={result.summary.selectedRowCount} />
      <Metric label="唯一标识" value={result.summary.uniqueLabelCount} />
      <Metric label="本地映射" value={result.summary.databaseMappedCount} note={`外部映射 ${result.summary.externalMappedCount ?? 0} · 格式推测 ${result.summary.unverifiedSymbolCount}`} />
      <Metric label="未映射" value={result.summary.unmappedCount} />
      <Metric label="本地通路" value={result.summary.pathwayCount} />
      <Metric label="候选交集" value={result.summary.candidateOverlapCount} />
    </div>

    {result.differentialAnalysis && <section className="panel raw-matrix-method">
      <h3 className="section-title-sm">原始矩阵统计设计</h3>
      <dl className="dataset-provenance"><div><dt>统计检验</dt><dd>{result.differentialAnalysis.designType === "paired" ? "配对 t 检验" : result.differentialAnalysis.designType === "multifactor" ? "多因素加性线性模型对比 t 检验" : "非配对 Welch t 检验"}</dd></div><div><dt>效应量</dt><dd>{result.differentialAnalysis.designType === "paired" ? "每对样本实验组减对照组的 log2 差值均值" : result.differentialAnalysis.designType === "multifactor" ? "控制模型中其他因素后的 log2 均值差" : "实验组减对照组的平均 log2 强度"}</dd></div><div><dt>多重校正</dt><dd>{result.differentialAnalysis.pValueAdjustment}</dd></div><div><dt>变换 / 归一化</dt><dd>{result.differentialAnalysis.inputScaleTransform === "log2" ? "log2 转换" : "不转换"} / {{ none: "不再归一化", median_center: "样本中位数中心化" }[result.differentialAnalysis.normalization] ?? result.differentialAnalysis.normalization}</dd></div><div><dt>缺失策略</dt><dd>{{ complete_rows: "仅完整样本行", available_replicates: "使用可用重复值" }[result.differentialAnalysis.missingPolicy] ?? result.differentialAnalysis.missingPolicy}</dd></div>{result.differentialAnalysis.designType === "paired" ? <div><dt>配对样本</dt><dd>{result.differentialAnalysis.samplePairs.map((pair) => `${pair.pairId}：${pair.controlSample} ↔ ${pair.treatmentSample}`).join("；")}</dd></div> : result.differentialAnalysis.designType === "multifactor" ? <><div><dt>主要对比</dt><dd>{result.differentialAnalysis.contrast?.factor}：{result.differentialAnalysis.contrast?.treatmentLevel} − {result.differentialAnalysis.contrast?.referenceLevel}</dd></div><div><dt>模型因素</dt><dd>{result.differentialAnalysis.factorNames?.map((name) => `${name}（${result.differentialAnalysis?.factorLevels?.[name]?.join("、")}）`).join("；")}</dd></div><div><dt>设计模型</dt><dd>{result.differentialAnalysis.model}</dd></div></> : <><div><dt>对照组样本</dt><dd>{result.differentialAnalysis.controlSamples?.join("、")}</dd></div><div><dt>实验组样本</dt><dd>{result.differentialAnalysis.treatmentSamples?.join("、")}</dd></div></>}</dl>
      <p className="notice-warning">统计模型只适用于所选实验设计；未做数值插补，统计结果应按实验设计和领域规范复核。多因素首版假设样本相互独立、误差方差相同且残差近似正态，只估计主效应，不拟合交互项或随机效应。</p>
    </section>}

    <section className="proteomics-qc panel">
      <div className="panel-header"><div><h3 className="section-title-sm">输入质量检查</h3><p className="section-help">所有输入行都保留了筛选结果和排除原因。</p></div></div>
      <div className="proteomics-qc-grid">
        <Metric label="输入行" value={result.qc.inputRowCount} />
        <Metric label="缺少标识" value={result.qc.missingIdentifierCount} />
        <Metric label="重复标识" value={result.qc.duplicateIdentifierCount} />
        <Metric label="非法数值行" value={result.qc.invalidNumericValueRowCount} />
        <Metric label="排除行" value={result.qc.excludedRowCount} />
        {result.qc.rawMatrix && <Metric label="完成检验" value={result.qc.rawMatrix.rowsTested} note={`缺失单元格 ${result.qc.rawMatrix.missingSampleValueCount} · 非法数值单元格 ${result.qc.rawMatrix.invalidSampleValueCount}`} />}
      </div>
      {Object.keys(result.qc.excludedReasonCounts).length > 0 && <p className="section-help">排除原因：{Object.entries(result.qc.excludedReasonCounts).map(([reason, count]) => `${qualityReasonLabel(reason)} ${count}`).join(" · ")}</p>}
    </section>

    {result.warnings.map((warning) => <p className="notice-warning" key={warning}>{warning}</p>)}
    <div className="notice-info"><Activity size={17} /><span>{result.summary.enrichmentNote}</span></div>

    <section className="proteomics-result-section">
      <div className="case-list-heading"><div><h3 className="section-title-sm">差异蛋白火山图</h3><p className="section-help">根据本任务已保存的 log2FC、P 值和筛选状态生成，最多绘制 5,000 行；不发送原始文件或医案。</p></div>
        <button className="btn btn-secondary" type="button" disabled={visualizationSubmitting || Boolean(volcanoVisualizationTask && ["queued", "running", "succeeded"].includes(volcanoVisualizationTask.status))} onClick={onCreateVolcanoVisualization}>{visualizationSubmitting ? "正在创建图表…" : volcanoVisualizationTask?.status === "succeeded" ? "R 火山图已生成" : volcanoVisualizationTask?.status === "failed" ? "重试生成 R 火山图" : "生成 R 火山图"}</button></div>
      {volcanoVisualizationTask && <ProteomicsVisualizationResult task={volcanoVisualizationTask} title="差异蛋白火山图" alt="差异蛋白火山图；横轴为 log2 Fold Change，纵轴为负对数 P 值，颜色区分阈值筛选结果" />}
    </section>

    {result.externalReactome && <section className="proteomics-result-section">
      <div className="case-list-heading"><div><h3 className="section-title-sm">MyGene.info / Reactome 外部结果</h3><p className="section-help">{result.externalReactome.organism} · {result.externalReactome.source}{result.externalReactome.sourceVersion ? ` ${result.externalReactome.sourceVersion}` : " · 版本未返回"}</p></div>
        <span className="status-badge">{{ succeeded: "有显著通路", no_significant_pathways: "无显著通路", no_mapped_identifiers: "没有可映射标识", unavailable: "服务不可用", disabled: "服务已停用" }[result.externalReactome.status] ?? result.externalReactome.status}</span>
      </div>
      <p className="section-help">映射 {result.externalReactome.mappings.length} 个标识；发送到 Reactome {result.externalReactome.submittedIdentifierCount ?? 0} 个。歧义 {result.externalReactome.ambiguousIdentifiers.length} 个，未映射 {result.externalReactome.unmappedIdentifiers.length} 个。</p>
      {result.externalReactome.pathways.length > 0 ? <div className="table-scroll"><table className="data-table"><thead><tr><th>通路</th><th>Reactome ID</th><th>命中实体</th><th>覆盖率</th><th>P 值</th><th>FDR</th></tr></thead><tbody>
        {result.externalReactome.pathways.map((pathway) => <tr key={pathway.stableId}><td>{pathway.name}</td><td>{pathway.stableId}</td><td>{pathway.matchedEntities}/{pathway.totalEntities ?? "—"}</td><td>{pathway.coverage == null ? "—" : formatNumber(pathway.coverage)}</td><td>{formatNumber(pathway.pValue)}</td><td>{formatNumber(pathway.fdr)}</td></tr>)}
      </tbody></table></div> : <p className="section-help">本次没有可展示的显著 Reactome 通路，或外部服务不可用。</p>}
      {result.externalReactome.ambiguousIdentifiers.length > 0 && <details className="case-notes"><summary>存在歧义的标识</summary><p>{result.externalReactome.ambiguousIdentifiers.join("、")}</p></details>}
    </section>}

    {result.externalGProfiler && <section className="proteomics-result-section">
      <div className="case-list-heading"><div><h3 className="section-title-sm">GO / KEGG 功能富集</h3><p className="section-help">{result.externalGProfiler.organism} · {result.externalGProfiler.source}{result.externalGProfiler.sourceVersion ? ` ${result.externalGProfiler.sourceVersion}` : " · 版本未返回"} · FDR ≤ {result.externalGProfiler.threshold}</p></div>
        <span className={`status-badge ${result.externalGProfiler.status === "succeeded" ? "status-success" : result.externalGProfiler.status === "unavailable" || result.externalGProfiler.status === "disabled" ? "status-warning" : ""}`}>{{ succeeded: "有显著条目", no_significant_terms: "无显著条目", insufficient_identifiers: "可用标识不足", input_limit_exceeded: "超出分析限制", unavailable: "服务不可用", disabled: "服务已停用" }[result.externalGProfiler.status] ?? result.externalGProfiler.status}</span>
      </div>
      <p className="section-help">查询集 {result.externalGProfiler.queryCount} 个{result.externalGProfiler.queryTruncatedCount > 0 ? `（另有 ${result.externalGProfiler.queryTruncatedCount} 个未发送）` : ""} · 自定义背景 {result.externalGProfiler.backgroundCount} 个规范化标识 · 数据库：{result.externalGProfiler.sources.join("、")}</p>
      <p className="section-help">服务返回的是多重检验校正后的 p 值（FDR），未单独返回未校正 p 值；命中标识来自 g:Profiler 输出。</p>
      <details className="case-notes"><summary>查看数据源版本</summary><pre>{JSON.stringify(result.externalGProfiler.dataVersions, null, 2)}</pre></details>
      {result.externalGProfiler.terms.length > 0 ? <div className="table-scroll"><table className="data-table"><thead><tr><th>类别</th><th>功能条目</th><th>条目 ID</th><th>命中数</th><th>查询数</th><th>GeneRatio</th><th>条目基因数</th><th>有效背景数</th><th>FDR</th></tr></thead><tbody>
        {result.externalGProfiler.terms.map((term) => <tr key={`${term.source}:${term.termId}`}><td>{term.source}</td><td>{term.name}</td><td>{term.termId}</td><td>{term.intersectionSize ?? "—"}</td><td>{term.querySize ?? "—"}</td><td>{formatNumber(term.geneRatio)}</td><td>{term.termSize ?? "—"}</td><td>{term.effectiveDomainSize ?? "—"}</td><td>{formatNumber(term.adjustedPValue)}</td></tr>)}
      </tbody></table></div> : <p className="section-help">本次没有可展示的 GO/KEGG 显著条目。</p>}
      {result.externalGProfiler.terms.length > 0 && <>
        <div className="source-record-actions"><button className="btn btn-secondary" type="button" disabled={visualizationSubmitting || Boolean(visualizationTask && ["queued", "running", "succeeded"].includes(visualizationTask.status))} onClick={onCreateGoKeggVisualization}>{visualizationSubmitting ? "正在创建图表…" : visualizationTask?.status === "succeeded" ? "R 气泡图已生成" : visualizationTask?.status === "failed" ? "重试生成 R 气泡图" : "生成 R 富集气泡图"}</button><span className="section-help">只把最多 100 条富集结果的名称、类别、GeneRatio、FDR 和命中数交给 R 绘图；不发送原始文件或医案。</span></div>
        {visualizationTask && <ProteomicsVisualizationResult task={visualizationTask} title="GO / KEGG 富集气泡图" alt="GO / KEGG 富集气泡图；横轴为 GeneRatio，点大小为命中数，颜色表示 FDR 显著性" />}
      </>}
      {result.externalGProfiler.terms.some((term) => term.matchedIdentifiers.length > 0) && <details className="case-notes"><summary>查看命中标识</summary>{result.externalGProfiler.terms.filter((term) => term.matchedIdentifiers.length > 0).slice(0, 30).map((term) => <p key={`${term.source}:${term.termId}`}><strong>{term.name}</strong>：{term.matchedIdentifiers.join("、")}</p>)}</details>}
    </section>}

    <RAnalysisGallery key={task.id} taskId={task.id} />
    {result.externalString && <StringNetworkResult result={result.externalString} task={task} />}

    <section className="proteomics-result-section">
      <div className="case-list-heading"><h3 className="section-title-sm">Top degree 候选蛋白</h3><span className="section-help">degree 表示本地已登记通路关联数，不代表因果结论。</span></div>
      {result.topNodes.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>基因/蛋白</th><th>映射状态</th><th>degree</th><th>log2FC</th><th>FDR</th><th>方向</th><th>通路</th></tr></thead><tbody>
        {result.topNodes.map((row) => <tr key={row.symbol}><td>{row.symbol}</td><td>{mappingStatusLabel(row.mappingStatus)}</td><td>{row.degree}</td><td>{formatNumber(row.log2FoldChange)}</td><td>{formatNumber(row.fdr)}</td><td>{row.direction || "—"}</td><td title={row.pathways.join("、")}>{row.pathways.slice(0, 2).join("、") || "—"}</td></tr>)}
      </tbody></table></div> : <div className="empty-state">当前本地知识库没有可展示的基因—通路关系。</div>}
    </section>

    <section className="proteomics-result-section">
      <h3 className="section-title-sm">与候选靶点交叉验证</h3>
      {result.validation.referenceTargets.length ? <div className="proteomics-validation-grid">
        <div><span>共同靶点</span><p>{result.validation.overlap.join("、") || "无"}</p></div>
        <div><span>组学特有</span><p>{result.validation.proteomicsOnly.slice(0, 30).join("、") || "无"}</p></div>
        <div><span>候选未检出</span><p>{result.validation.referenceOnly.slice(0, 30).join("、") || "无"}</p></div>
      </div> : <p className="section-help">本次未输入候选靶点，只生成蛋白组学内部结果。</p>}
    </section>

    <section className="proteomics-result-section">
      <div className="case-list-heading"><h3 className="section-title-sm">来源可追溯的本地通路</h3><span className="section-help">{result.pathways.length} 条</span></div>
      {result.pathways.length ? <ul className="proteomics-pathways">{result.pathways.slice(0, 100).map((pathway) => <li key={pathway.stableId}><strong>{pathway.name}</strong><span>{pathway.stableId} · {pathway.source} {pathway.version}</span></li>)}</ul> : <p className="section-help">没有命中当前本地通路目录。</p>}
    </section>

    {result.unmapped.length > 0 && <details className="case-notes"><summary>未映射标识（{result.summary.unmappedCount} 个）</summary>
      <p>{result.unmapped.join("、")}{result.unmappedTruncated ? "……（其余可在逐行 QC 中查看）" : ""}</p></details>}

    <section className="proteomics-result-section">
      <div className="case-list-heading"><div><h3 className="section-title-sm">逐行筛选结果</h3><p className="section-help">任务共处理 {result.qc.inputRowCount} 行；当前预览 {result.rows.length} 行。</p></div>
        <button className="btn btn-secondary" type="button" onClick={onToggleRows}>{showRows ? "收起完整结果" : "查看逐行 QC"}</button></div>
      {!showRows && <div className="table-scroll"><table className="data-table"><thead><tr><th>原始标识</th><th>规范标识</th><th>稳定 ID</th><th>映射状态</th><th>log2FC</th><th>FDR</th><th>方向</th></tr></thead><tbody>
        {result.rows.slice(0, 20).map((row) => <tr key={row.index}><td>{row.originalLabel}</td><td>{row.symbol || "—"}</td><td>{formatExternalIdentifiers(row.externalIdentifiers)}</td><td>{mappingStatusLabel(row.mappingStatus)}</td><td>{formatNumber(row.log2FoldChange)}</td><td>{formatNumber(row.fdr)}</td><td>{row.direction || "—"}</td></tr>)}
      </tbody></table></div>}
      {result.previewTruncated && !showRows && <p className="section-help">预览超过 500 行；打开逐行 QC 可分页读取完整结果。</p>}
      {showRows && <>
        {rowPage ? <div className="table-scroll"><table className="data-table"><thead><tr><th>行</th><th>原始标识</th><th>规范标识</th><th>稳定 ID</th><th>映射状态</th><th>log2FC</th><th>FDR</th><th>筛选</th><th>排除/警告</th></tr></thead><tbody>
          {rowPage.results.map((row) => <tr key={row.row_index}><td>{row.row_index + 1}</td><td>{row.original_label || "—"}</td><td>{row.normalized_symbol || "—"}</td><td>{formatExternalIdentifiers(row.external_identifiers)}</td><td>{mappingStatusLabel(row.mapping_status)}</td><td>{formatNumber(row.log2_fold_change)}</td><td>{formatNumber(row.fdr)}</td><td>{row.selected ? "通过" : "排除"}</td><td>{[...row.exclusion_reasons, ...row.qc_warnings].map(qualityReasonLabel).join("、") || "—"}</td></tr>)}
        </tbody></table></div> : <p className="section-help">正在读取逐行结果…</p>}
        {rowPage && <div className="case-pagination"><button className="btn btn-secondary" type="button" disabled={!rowPage.previous} onClick={() => onRowPageChange(Math.max(1, rowPageNumber - 1))}>上一页</button>
          <span>第 {rowPageNumber} 页 / 共 {rowPage.count} 行</span><button className="btn btn-secondary" type="button" disabled={!rowPage.next} onClick={() => onRowPageChange(rowPageNumber + 1)}>下一页</button></div>}
      </>}
    </section>
  </div>;
}

function ProteomicsVisualizationResult({ task, title, alt }: { task: AnalysisTask; title: string; alt: string }) {
  if (["queued", "running"].includes(task.status)) return <p className="section-help" role="status">R 富集图表任务 #{task.id} 正在后台执行（{task.progress}%）。</p>;
  if (task.status === "failed") return <div className="notice-error" role="alert">R 图表生成失败：{task.error_summary}</div>;
  const value = task.result as { rendererVersion?: string; artifacts?: Array<{ id: number; format: string; downloadUrl: string }> };
  const artifacts = value.artifacts ?? [];
  const svg = artifacts.find((artifact) => artifact.format === "svg");
  return <div className="panel source-record"><h3>{title} · {String(value.rendererVersion ?? "")}</h3>
    {svg && <img className="visualization-preview" src={`${svg.downloadUrl}?inline=1`} alt={alt} />}
    <div className="source-record-actions">{artifacts.map((artifact) => <a className="btn btn-secondary" key={artifact.id} href={artifact.downloadUrl}>下载 {artifact.format.toUpperCase()}</a>)}</div>
  </div>;
}
