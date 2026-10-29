import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Activity, ArrowLeft, Download, Play, RefreshCw } from "lucide-react";
import {
  getAnalysisTask,
  getDatasets,
  getProteomicsRows,
  exportProteomicsResults,
  runProteomicsAnalysis,
  type AnalysisTask,
  type ProteomicsResult,
  type ProteomicsRowPage,
  type ResearchDataset,
  type DatasetPage,
} from "../api/datasets";
import { restoreProteomicsTasks } from "../api/task-restoration";
import { ApiError } from "../api/client";
import { createVisualization } from "../api/network";
import { StringNetworkResult } from "../components/StringNetworkResult";
import { RAnalysisGallery } from "../components/RAnalysisGallery";
import { RDemoGallery } from "../components/RDemoGallery";
import { SubviewTabs } from "../components/SubviewTabs";
import { RChartSource } from "../components/RChartSource";
import { RChartViewer, hasInteractiveRenderer } from "../components/RChartViewer";

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
  const sampleFormatPrefix = "ambiguous_sample_numeric_format:";
  if (reason.startsWith(sampleFormatPrefix)) {
    return `样本列 ${reason.slice(sampleFormatPrefix.length)} 含逗号数值格式，含义不明确，未转换`;
  }
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
    invalid_p_value: "P 值非法，应为 0 至 1 的数值",
    invalid_fdr: "FDR 非法，应为 0 至 1 的数值",
    missing_log2fc: "缺少 log2FC",
    log2fc_below_threshold: "log2FC 未达到阈值",
    missing_significance: "缺少显著性数值",
    invalid_significance: "显著性数值非法",
    invalid_numeric_value: "包含非法统计数值",
    ambiguous_numeric_format: "含逗号数值格式，含义不明确，未转换",
    ambiguous_log2fc_numeric_format: "log2FC 含逗号数值格式，含义不明确，未转换",
    ambiguous_p_value_numeric_format: "P 值含逗号数值格式，含义不明确，未转换",
    ambiguous_fdr_numeric_format: "FDR 含逗号数值格式，含义不明确，未转换",
    ambiguous_sample_numeric_format: "样本值含逗号数值格式，含义不明确，未转换",
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
  const [searchParams, setSearchParams] = useSearchParams();
  const savedTaskId = searchParams.get("proteomicsTask");
  const [workspaceSubview, setWorkspaceSubview] = useState(savedTaskId === null ? "settings" : "results");
  const adoptedTaskId = useRef<string | null>(null);
  const mounted = useRef(false);
  const generation = useRef(0);
  const submissionInFlight = useRef(false);
  const visualizationInFlight = useRef(false);
  const exportInFlight = useRef<number | null>(null);
  const datasetPaging = useRef(false);
  const [datasets, setDatasets] = useState<ResearchDataset[]>([]);
  const [datasetPage, setDatasetPage] = useState<DatasetPage | null>(null);
  const [datasetPageNumber, setDatasetPageNumber] = useState(1);
  const [datasetReload, setDatasetReload] = useState(0);
  const [datasetError, setDatasetError] = useState<string | null>(null);
  const [datasetId, setDatasetId] = useState<number | "">("");
  const [storedTask, setTask] = useState<AnalysisTask | null>(null);
  // Match the URL during render so a newly selected history entry cannot show
  // the preceding task before its restoration effect clears state.
  const task = savedTaskId === null || savedTaskId === String(storedTask?.id) ? storedTask : null;
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
  const [restoring, setRestoring] = useState(true);
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [pollFailures, setPollFailures] = useState(0);
  const [pollError, setPollError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const [rowReload, setRowReload] = useState(0);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; generation.current += 1; };
  }, []);

  useEffect(() => {
    let active = true;
    datasetPaging.current = true;
    setLoading(true); setDatasetError(null); setDatasetPage(null); setDatasets([]);
    getDatasets(datasetPageNumber)
      .then((datasetResponse) => {
        if (!active) return;
        setDatasets(datasetResponse.results);
        setDatasetPage(datasetResponse);
        setDatasetId(current => datasetResponse.results.some(item => item.id === current)
          ? current : datasetResponse.results[0]?.id ?? "");
      })
      .catch((cause: unknown) => { if (active) setDatasetError(errorMessage(cause)); })
      .finally(() => { if (active) { datasetPaging.current = false; setLoading(false); } });
    return () => { active = false; };
  }, [datasetPageNumber, datasetReload]);

  useEffect(() => {
    // The just-created response is already verified. Updating its URL must not
    // discard it or create a competing restoration request.
    if (savedTaskId !== null && adoptedTaskId.current === savedTaskId) {
      adoptedTaskId.current = null;
      return;
    }
    adoptedTaskId.current = null;
    const current = ++generation.current;
    let active = true;
    exportInFlight.current = null;
    setTask(null); setVisualizationTask(null); setVolcanoVisualizationTask(null);
    setShowRows(false); setRowPage(null); setRowPageNumber(1); setRowError(null);
    setError(null); setNotice(null); setPollError(null); setPollFailures(0);
    setSubmitting(false); setVisualizationSubmitting(false);
    setRestoring(true); setRestoreError(null);
    if (savedTaskId !== null && (!/^[1-9]\d*$/.test(savedTaskId) || !Number.isSafeInteger(Number(savedTaskId)))) {
      setRestoreError("蛋白组学任务编号无效。"); setRestoring(false);
      return () => { active = false; };
    }
    restoreProteomicsTasks(savedTaskId === null ? undefined : Number(savedTaskId))
      .then((restored) => {
        if (!active || !mounted.current || generation.current !== current) return;
        const latestTask = restored.task;
        if (latestTask) {
          setTask(latestTask);
          setWorkspaceSubview("results");
          setVisualizationTask(restored.visualizationTask);
          setVolcanoVisualizationTask(restored.volcanoVisualizationTask);
        }
        setRestoreError(restored.figureError ?? null);
      })
      .catch((cause: unknown) => { if (active && mounted.current && generation.current === current) setRestoreError(errorMessage(cause)); })
      .finally(() => { if (active && mounted.current && generation.current === current) setRestoring(false); });
    return () => { active = false; };
  }, [restoreAttempt, savedTaskId]);

  useEffect(() => {
    const current = generation.current;
    let active = true;
    const pending = [
      { saved: task, update: setTask },
      { saved: visualizationTask, update: setVisualizationTask },
      { saved: volcanoVisualizationTask, update: setVolcanoVisualizationTask },
    ].filter(({ saved }) => saved && ["queued", "running"].includes(saved.status));
    if (!pending.length) { setPollError(null); return; }
    const timer = window.setTimeout(() => {
      void Promise.all(pending.map(async ({ saved, update }) => {
        if (!saved) return true;
        try {
          const latest = await getAnalysisTask(saved.id);
          if (!active || !mounted.current || generation.current !== current) return true;
          if (latest.id !== saved.id || latest.task_type !== saved.task_type || latest.parent_task !== saved.parent_task) {
            throw new Error("Task identity mismatch");
          }
          return { saved, update, latest };
        } catch (cause) {
          return { cause };
        }
      })).then(reads => {
        if (!active || !mounted.current || generation.current !== current) return;
        let failed = false;
        for (const read of reads) {
          if (typeof read === "object" && "cause" in read) {
            failed = true;
            setPollError(`${errorMessage(read.cause)} 正在重试读取已有任务，不会重新提交。`);
          } else if (typeof read === "object" && "latest" in read) {
            read.update(previous => previous?.id === read.saved.id ? read.latest : previous);
          }
        }
        if (!failed) { setPollFailures(0); setPollError(null); }
        else setPollFailures(value => value + 1);
      });
    }, Math.min(1400 * 2 ** Math.min(pollFailures, 4), 12000));
    return () => { active = false; window.clearTimeout(timer); };
  }, [task, visualizationTask, volcanoVisualizationTask, pollFailures]);

  useEffect(() => {
    if (!showRows || !task || task.status !== "succeeded") return;
    let active = true;
    setRowPage(null); setRowError(null);
    getProteomicsRows(task.id, rowPageNumber)
      .then((value) => { if (active) setRowPage(value); })
      .catch((cause: unknown) => { if (active) setRowError(errorMessage(cause)); });
    return () => { active = false; };
  }, [showRows, task, rowPageNumber, rowReload]);

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

  function changeDatasetPage(next: number) {
    if (datasetPaging.current || submissionInFlight.current) return;
    datasetPaging.current = true;
    setLoading(true); setDatasetPage(null); setDatasets([]);
    setDatasetPageNumber(Math.max(1, next));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDataset || loading || restoring || submissionInFlight.current || visualizationInFlight.current
      || (task && ["queued", "running"].includes(task.status))) return;
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
    submissionInFlight.current = true;
    const current = ++generation.current;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    setShowRows(false);
    setRowPage(null);
    setRowPageNumber(1);
    setRowError(null);
    setPollError(null); setPollFailures(0);
    setVisualizationTask(null);
    setVolcanoVisualizationTask(null);
    setTask(null);
    setExternalReactome(false); setExternalString(false); setExternalGProfiler(false);
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
      if (!mounted.current || generation.current !== current) return;
      if (!Number.isSafeInteger(taskResponse.id) || taskResponse.id < 1
        || taskResponse.task_type !== "proteomics" || taskResponse.dataset !== selectedDataset.id) {
        throw new ApiError("返回的任务与本次数据集不一致，请重新读取任务记录。", "TASK_SOURCE_MISMATCH", null, null, 502);
      }
      setTask(taskResponse);
      setWorkspaceSubview("results");
      adoptedTaskId.current = String(taskResponse.id);
      setSearchParams(previous => {
        const next = new URLSearchParams(previous);
        next.set("proteomicsTask", String(taskResponse.id));
        return next;
      }, { replace: true });
      setNotice(`分析任务 #${taskResponse.id} 已进入后台队列。`);
    } catch (cause) {
      if (mounted.current && generation.current === current) setError(errorMessage(cause));
    } finally {
      submissionInFlight.current = false;
      if (mounted.current && generation.current === current) setSubmitting(false);
    }
  }

  async function exportRows(format: "csv" | "xlsx" | "pdf") {
    if (!task || task.status !== "succeeded" || exportInFlight.current !== null) return;
    const current = generation.current;
    exportInFlight.current = current;
    setError(null);
    try {
      const blob = await exportProteomicsResults(task.id, format);
      if (mounted.current && generation.current === current) downloadBlob(`proteomics-task-${task.id}.${format}`, blob);
    } catch (cause) {
      if (mounted.current && generation.current === current) setError(errorMessage(cause));
    } finally {
      if (exportInFlight.current === current) exportInFlight.current = null;
    }
  }

  async function requestGoKeggVisualization() {
    await requestVisualization("proteomics_go_kegg_enrichment", visualizationTask, setVisualizationTask);
  }

  async function requestVolcanoVisualization() {
    await requestVisualization("proteomics_volcano", volcanoVisualizationTask, setVolcanoVisualizationTask);
  }

  async function requestVisualization(key: "proteomics_volcano" | "proteomics_go_kegg_enrichment", existing: AnalysisTask | null, update: (value: AnalysisTask) => void) {
    if (!task || task.status !== "succeeded" || submissionInFlight.current || visualizationInFlight.current
      || (existing && ["queued", "running", "succeeded"].includes(existing.status))) return;
    visualizationInFlight.current = true;
    const current = generation.current;
    setError(null);
    setVisualizationSubmitting(true);
    try {
      const job = await createVisualization(task.id, key);
      if (!mounted.current || generation.current !== current) return;
      if (job.task_type !== "visualization" || job.parent_task !== task.id
        || job.input_parameters.analysisKind !== "r_visualization" || job.input_parameters.chartKey !== key) {
        throw new Error("Visualization does not belong to this analysis");
      }
      update(job);
    } catch (cause) {
      if (mounted.current && generation.current === current) setError(errorMessage(cause));
    } finally {
      visualizationInFlight.current = false;
      if (mounted.current && generation.current === current) setVisualizationSubmitting(false);
    }
  }

  return <>
      <div className="page-heading"><div className="page-heading-copy"><h1 className="page-title">差异蛋白组学分析</h1>
        <p className="page-description">分析差异蛋白、关联靶点与通路，查看图表并追溯每行数据的筛选和映射结果。</p></div>
        <Link to="/datasets" className="btn btn-secondary"><ArrowLeft size={16} />数据库</Link>
      </div>

      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      {notice && <div className="notice-success workspace-notice" role="status">{notice}</div>}
      {pollError && <p className="notice-error workspace-notice" role="alert">{pollError}</p>}
      {restoreError && <div className="notice-error workspace-notice" role="alert"><p>{restoreError}</p><button type="button" className="btn btn-secondary" disabled={restoring || submitting || visualizationSubmitting || Boolean(task && ["queued", "running"].includes(task.status))} onClick={() => setRestoreAttempt(value => value + 1)}>重新读取历史任务</button></div>}

      <SubviewTabs label="蛋白组学工作区" value={workspaceSubview} onChange={setWorkspaceSubview} keepMounted views={[
        { key: "settings", label: "分析设置", content:
        <form className="panel case-form" onSubmit={(event) => void submit(event)} aria-label="启动差异蛋白分析">
          <div className="panel-header"><div><h2 className="section-title-sm">分析设置</h2><p className="section-help">数据集原始文件不会发送到外部服务。</p></div><span className="page-heading-icon"><Activity size={19} /></span></div>
          <div className="case-form-fields">
            {loading ? <p className="section-help" role="status">正在读取你的数据集…</p> : datasetError ? <div className="notice-error" role="alert"><p>{datasetError}</p><button className="btn btn-secondary" type="button" onClick={() => setDatasetReload(value => value + 1)}>重新读取数据集</button>{datasetPageNumber > 1 && <button className="btn btn-secondary" type="button" onClick={() => changeDatasetPage(datasetPageNumber - 1)}>返回上一页数据集</button>}</div> : datasets.length ? <label className="form-label" htmlFor="proteomics-dataset">选择已上传数据集
              <select className="field" id="proteomics-dataset" value={datasetId} onChange={(event) => setDatasetId(Number(event.target.value))}>
                {datasets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.original_filename}</option>)}
              </select></label> : <div className="empty-state"><strong>还没有可分析的数据集</strong><p>先上传差异蛋白 CSV、TSV 或 Excel 文件。</p><Link className="btn btn-secondary" to="/datasets">上传数据集</Link></div>}
            {datasetPage && (datasetPage.next || datasetPage.previous) && <nav className="case-pagination" aria-label="可分析数据集分页"><button className="btn btn-secondary" type="button" aria-label="上一页数据集" disabled={!datasetPage.previous || submitting} onClick={() => changeDatasetPage(datasetPageNumber - 1)}>上一页</button><span>第 {datasetPageNumber} 页 · {datasetPage.count} 个数据集</span><button className="btn btn-secondary" type="button" aria-label="下一页数据集" disabled={!datasetPage.next || submitting} onClick={() => changeDatasetPage(datasetPageNumber + 1)}>下一页</button></nav>}

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
                <p className="section-help">请按实验记录明确指定样本分组，不会根据列名、顺序或数值猜测设计。多因素模型只拟合各因素主效应，不含交互项。</p>
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
              <label className="form-label" htmlFor="proteomics-reference">参考符号（可选，用于名称对照）
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
            <button className="btn btn-primary" type="submit" disabled={!selectedDataset || loading || restoring || submitting || visualizationSubmitting || task?.status === "queued" || task?.status === "running"}>
              {submitting ? <RefreshCw size={16} className="spin" /> : <Play size={16} />}{submitting ? "正在提交…" : "提交后台分析"}
            </button></div>
        </form> },
        { key: "results", label: "分析结果", content:
        <section className="case-list" aria-labelledby="proteomics-results-heading">
          <div className="case-list-heading"><div><h2 id="proteomics-results-heading" className="section-title-sm">分析结果</h2></div>
            {task && <span className={`status-badge ${task.status === "failed" ? "status-error" : task.status === "succeeded" ? "status-success" : "status-warning"}`}>{taskStatusLabel(task.status)}</span>}
          </div>
          {!task ? restoring ? <div className="panel empty-state" role="status">正在读取蛋白组学任务…</div> : !restoreError && <div className="panel empty-state"><Activity size={27} /><strong>等待分析任务</strong><p>选择一个已上传的数据集并提交分析设置。</p></div>
            : <article className="panel proteomics-result-panel">
              <div className="case-record-top"><div><h3>任务 #{task.id} · {taskDataset?.name ?? String(task.input_parameters.name || `数据集 ${task.dataset ?? "已移除"}`)}</h3><time dateTime={task.created_at}>创建于 {new Date(task.created_at).toLocaleString("zh-CN")}</time></div>
                {result && <div className="proteomics-export-actions">
                  <button type="button" className="btn btn-secondary" onClick={() => void exportRows("csv")}><Download size={15} />CSV</button>
                  <button type="button" className="btn btn-secondary" onClick={() => void exportRows("xlsx")}><Download size={15} />XLSX</button>
                  <button type="button" className="btn btn-secondary" onClick={() => void exportRows("pdf")}><Download size={15} />PDF 报告</button>
                  <button type="button" className="btn btn-secondary" onClick={() => downloadJson(`proteomics-task-${task.id}.json`, result)}><Download size={15} />JSON</button>
                </div>}</div>
              {(task.status === "queued" || task.status === "running") && <div className="analysis-progress" role="status"><span>任务已排队，分析过程在后台运行。</span><progress max={100} value={task.progress} /></div>}
              {task.status === "failed" && <div className="notice-error" role="alert">{task.error_summary || "分析失败，请检查文件和列映射。"}</div>}
              {result && <ProteomicsResultView key={task.id} result={result} task={task} showRows={showRows} rowPage={rowPage} rowPageNumber={rowPageNumber} rowReadFailed={Boolean(rowError)}
                visualizationTask={visualizationTask} volcanoVisualizationTask={volcanoVisualizationTask} visualizationSubmitting={visualizationSubmitting}
                onCreateVolcanoVisualization={() => void requestVolcanoVisualization()}
                onCreateGoKeggVisualization={() => void requestGoKeggVisualization()}
                onToggleRows={() => { setShowRows((value) => !value); setRowPageNumber(1); }}
                onRowPageChange={setRowPageNumber} />}
              {showRows && rowError && <div className="notice-error" role="alert"><p>逐行结果读取失败：{rowError}</p><button type="button" className="btn btn-secondary" onClick={() => setRowReload(value => value + 1)}>重新读取逐行结果</button></div>}
            </article>}
        </section> },
        { key: "demo", label: "演示图库", content: <RDemoGallery defaultOpen /> },
      ]} />

  </>;
}

function Metric({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return <div className="proteomics-metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

function ProteomicsResultView({
  result, task, showRows, rowPage, rowPageNumber, rowReadFailed, visualizationTask, volcanoVisualizationTask, visualizationSubmitting,
  onCreateVolcanoVisualization, onCreateGoKeggVisualization, onToggleRows, onRowPageChange,
}: {
  result: ProteomicsResult;
  task: AnalysisTask;
  showRows: boolean;
  rowPage: ProteomicsRowPage | null;
  rowPageNumber: number;
  rowReadFailed: boolean;
  visualizationTask: AnalysisTask | null;
  volcanoVisualizationTask: AnalysisTask | null;
  visualizationSubmitting: boolean;
  onCreateVolcanoVisualization: () => void;
  onCreateGoKeggVisualization: () => void;
  onToggleRows: () => void;
  onRowPageChange: (page: number) => void;
}) {
  const [resultSubview, setResultSubview] = useState("overview");
  return <div className="proteomics-result-content">
    <SubviewTabs label="蛋白组学结果子页" value={resultSubview} onChange={setResultSubview} keepMounted views={[
      { key: "overview", label: "结果概览", content: <>
    <details className="raw-details"><summary>分析记录与来源版本</summary><p className="section-help">原始文件 SHA-256：<code>{result.dataset.sha256}</code> · 算法版本：{result.algorithmVersion} · 来源版本数：{task.source_releases.length}</p></details>
    <div className="proteomics-metrics">
      <Metric label="通过筛选" value={result.summary.selectedRowCount} />
      <Metric label="唯一标识" value={result.summary.uniqueLabelCount} />
      <Metric label="本地映射" value={result.summary.databaseMappedCount} note={`外部映射 ${result.summary.externalMappedCount ?? 0} · 格式推测 ${result.summary.unverifiedSymbolCount}`} />
      <Metric label="未映射" value={result.summary.unmappedCount} />
      <Metric label="本地通路" value={result.summary.pathwayCount} />
      <Metric label="入选符号重叠" value={result.summary.candidateOverlapCount} />
    </div>

    {result.differentialAnalysis && <section className="panel raw-matrix-method">
      <h3 className="section-title-sm">原始矩阵统计设计</h3>
      <dl className="dataset-provenance"><div><dt>统计检验</dt><dd>{result.differentialAnalysis.designType === "paired" ? "配对 t 检验" : result.differentialAnalysis.designType === "multifactor" ? "多因素加性线性模型对比 t 检验" : "非配对 Welch t 检验"}</dd></div><div><dt>效应量</dt><dd>{result.differentialAnalysis.designType === "paired" ? "每对样本实验组减对照组的 log2 差值均值" : result.differentialAnalysis.designType === "multifactor" ? "控制模型中其他因素后的 log2 均值差" : "实验组减对照组的平均 log2 强度"}</dd></div><div><dt>多重校正</dt><dd>{result.differentialAnalysis.pValueAdjustment}</dd></div><div><dt>变换 / 归一化</dt><dd>{result.differentialAnalysis.inputScaleTransform === "log2" ? "log2 转换" : "不转换"} / {{ none: "不再归一化", median_center: "样本中位数中心化" }[result.differentialAnalysis.normalization] ?? result.differentialAnalysis.normalization}</dd></div><div><dt>缺失策略</dt><dd>{{ complete_rows: "仅完整样本行", available_replicates: "使用可用重复值" }[result.differentialAnalysis.missingPolicy] ?? result.differentialAnalysis.missingPolicy}</dd></div>{result.differentialAnalysis.designType === "paired" ? <div><dt>配对样本</dt><dd>{result.differentialAnalysis.samplePairs.map((pair) => `${pair.pairId}：${pair.controlSample} ↔ ${pair.treatmentSample}`).join("；")}</dd></div> : result.differentialAnalysis.designType === "multifactor" ? <><div><dt>主要对比</dt><dd>{result.differentialAnalysis.contrast?.factor}：{result.differentialAnalysis.contrast?.treatmentLevel} − {result.differentialAnalysis.contrast?.referenceLevel}</dd></div><div><dt>模型因素</dt><dd>{result.differentialAnalysis.factorNames?.map((name) => `${name}（${result.differentialAnalysis?.factorLevels?.[name]?.join("、")}）`).join("；")}</dd></div><div><dt>设计模型</dt><dd>{result.differentialAnalysis.model}</dd></div></> : <><div><dt>对照组样本</dt><dd>{result.differentialAnalysis.controlSamples?.join("、")}</dd></div><div><dt>实验组样本</dt><dd>{result.differentialAnalysis.treatmentSamples?.join("、")}</dd></div></>}</dl>
      <p className="notice-warning">统计模型只适用于所选实验设计；未做数值插补，统计结果应按实验设计和领域规范复核。多因素模型假设样本相互独立、误差方差相同且残差近似正态，只估计主效应，不拟合交互项或随机效应。</p>
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
    <div className="notice-info"><Activity size={17} /><span>结果依据本任务保存的数据生成，筛选、映射和外部服务状态详见各结果页。</span></div>
      </> },
      { key: "charts", label: "R 图表", content: <RAnalysisGallery key={task.id} taskId={task.id} additionalCharts={[
        { key: "proteomics_volcano", label: "差异蛋白火山图", content: <RChartSource chartKey="proteomics_volcano"><section className="proteomics-result-section">
      <div className="case-list-heading"><div><h3 className="section-title-sm">差异蛋白火山图</h3><p className="section-help">根据本任务已保存的 log2FC、P 值和筛选状态生成，最多绘制 5,000 行；不发送原始文件或医案。</p></div>
        <button className="btn btn-secondary" type="button" disabled={visualizationSubmitting || Boolean(volcanoVisualizationTask && ["queued", "running", "succeeded"].includes(volcanoVisualizationTask.status))} onClick={onCreateVolcanoVisualization}>{visualizationSubmitting ? "正在创建图表…" : volcanoVisualizationTask?.status === "succeeded" ? "R 火山图已生成" : volcanoVisualizationTask?.status === "failed" ? "重试生成 R 火山图" : "生成 R 火山图"}</button></div>
      {volcanoVisualizationTask && <ProteomicsVisualizationResult task={volcanoVisualizationTask} title="差异蛋白火山图" alt="差异蛋白火山图；横轴为 log2 Fold Change，纵轴为负对数 P 值，颜色区分阈值筛选结果" />}
    </section></RChartSource> },
        { key: "proteomics_go_kegg_enrichment", label: "GO / KEGG 富集气泡图", content: <RChartSource chartKey="proteomics_go_kegg_enrichment"><section className="proteomics-result-section">
          <h3 className="section-title-sm">GO / KEGG 富集气泡图</h3>
          <p className="section-help">只使用当前任务保存的富集结果，不发送原始文件或医案。</p>
          <button className="btn btn-secondary" type="button" disabled={!result.externalGProfiler?.terms.length || visualizationSubmitting || Boolean(visualizationTask && ["queued", "running", "succeeded"].includes(visualizationTask.status))} onClick={onCreateGoKeggVisualization}>{!result.externalGProfiler?.terms.length ? "缺少所需分析数据" : visualizationSubmitting ? "正在创建图表…" : visualizationTask?.status === "succeeded" ? "R 气泡图已生成" : visualizationTask?.status === "failed" ? "重试生成 R 气泡图" : "生成 R 富集气泡图"}</button>
          {visualizationTask && <ProteomicsVisualizationResult task={visualizationTask} title="GO / KEGG 富集气泡图" alt="GO / KEGG 富集气泡图；横轴为 GeneRatio，点大小为命中数，颜色表示 FDR 显著性" />}
        </section></RChartSource> },
      ]} /> },
      { key: "enrichment", label: "富集数据", content: <>
    {!result.externalReactome && !result.externalGProfiler && <p className="section-help">本次任务未启用外部富集；可在图表页查看结果或打开演示图库。</p>}
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
      {result.externalGProfiler.terms.length > 0 && <button className="btn btn-secondary" type="button" onClick={() => setResultSubview("charts")}>前往 R 图表子页</button>}
      {result.externalGProfiler.terms.some((term) => term.matchedIdentifiers.length > 0) && <details className="case-notes"><summary>查看命中标识</summary>{result.externalGProfiler.terms.filter((term) => term.matchedIdentifiers.length > 0).slice(0, 30).map((term) => <p key={`${term.source}:${term.termId}`}><strong>{term.name}</strong>：{term.matchedIdentifiers.join("、")}</p>)}</details>}
    </section>}

      </> },
      { key: "ppi", label: "PPI 结果", content: result.externalString ? <StringNetworkResult result={result.externalString} task={task} /> : <p className="section-help">本次任务没有可用的 STRING PPI 结果。</p> },
      { key: "validation", label: "验证与通路", content: <>
    <section className="proteomics-result-section">
      <div className="case-list-heading"><h3 className="section-title-sm">Top degree 候选蛋白</h3><span className="section-help">degree 表示本地已登记通路关联数，不代表因果结论。</span></div>
      {result.topNodes.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>基因/蛋白</th><th>映射状态</th><th>degree</th><th>log2FC</th><th>FDR</th><th>方向</th><th>通路</th></tr></thead><tbody>
        {result.topNodes.map((row) => <tr key={row.symbol}><td>{row.symbol}</td><td>{mappingStatusLabel(row.mappingStatus)}</td><td>{row.degree}</td><td>{formatNumber(row.log2FoldChange)}</td><td>{formatNumber(row.fdr)}</td><td>{row.direction || "—"}</td><td title={row.pathways.join("、")}>{row.pathways.slice(0, 2).join("、") || "—"}</td></tr>)}
      </tbody></table></div> : <div className="empty-state">当前本地知识库没有可展示的基因—通路关系。</div>}
    </section>

    <section className="proteomics-result-section">
      <h3 className="section-title-sm">参考符号对照</h3>
      <p className="section-help">这里只比较通过筛选的符号与输入参考符号的名称集合，可能包含未核实项；名称重叠不代表同物种身份已确认或生物学交叉验证。“参考中未入选”不等于实验未测到。</p>
      {result.validation.referenceTargets.length ? <div className="proteomics-validation-grid">
        <div><span>入选符号重叠</span><p>{result.validation.overlap.join("、") || "无"}</p></div>
        <div><span>入选但不在参考集</span><p>{result.validation.proteomicsOnly.slice(0, 30).join("、") || "无"}</p></div>
        <div><span>参考中未入选</span><p>{result.validation.referenceOnly.slice(0, 30).join("、") || "无"}</p></div>
      </div> : <p className="section-help">本次未输入参考符号，只生成蛋白组学内部结果。</p>}
    </section>

    <section className="proteomics-result-section">
      <div className="case-list-heading"><h3 className="section-title-sm">来源可追溯的本地通路</h3><span className="section-help">{result.pathways.length} 条</span></div>
      {result.pathways.length ? <ul className="proteomics-pathways">{result.pathways.slice(0, 100).map((pathway) => <li key={pathway.stableId}><strong>{pathway.name}</strong><span>{pathway.stableId} · {pathway.source} {pathway.version}</span></li>)}</ul> : <p className="section-help">没有命中当前本地通路目录。</p>}
    </section>

      </> },
      { key: "qc", label: "逐行 QC", content: <>
    {result.unmapped.length > 0 && <details className="case-notes"><summary>未映射标识（{result.summary.unmappedCount} 个）</summary>
      <p>{result.unmapped.join("、")}{result.unmappedTruncated ? "……（其余可在逐行 QC 中查看）" : ""}</p></details>}

    <section className="proteomics-result-section">
      <div className="case-list-heading"><div><h3 className="section-title-sm">逐行筛选结果</h3><p className="section-help">任务共处理 {result.qc.inputRowCount} 行；{showRows && !rowPage ? rowReadFailed ? "逐行结果读取失败，可重新读取。" : "正在读取逐行结果…" : `当前显示 ${showRows ? rowPage?.results.length ?? 0 : Math.min(result.rows.length, 20)} 行。`}</p></div>
        <button className="btn btn-secondary" type="button" onClick={onToggleRows}>{showRows ? "收起完整结果" : "查看逐行 QC"}</button></div>
      {!showRows && <div className="table-scroll"><table className="data-table"><thead><tr><th>原始标识</th><th>规范标识</th><th>稳定 ID</th><th>映射状态</th><th>log2FC</th><th>FDR</th><th>方向</th></tr></thead><tbody>
        {result.rows.slice(0, 20).map((row) => <tr key={row.index}><td>{row.originalLabel}</td><td>{row.symbol || "—"}</td><td>{formatExternalIdentifiers(row.externalIdentifiers)}</td><td>{mappingStatusLabel(row.mappingStatus)}</td><td>{formatNumber(row.log2FoldChange)}</td><td>{formatNumber(row.fdr)}</td><td>{row.direction || "—"}</td></tr>)}
      </tbody></table></div>}
      {result.previewTruncated && !showRows && <p className="section-help">预览超过 500 行；打开逐行 QC 可分页读取完整结果。</p>}
      {showRows && <>
        {rowPage ? <div className="table-scroll"><table className="data-table"><thead><tr><th>行</th><th>原始标识</th><th>规范标识</th><th>稳定 ID</th><th>映射状态</th><th>log2FC</th><th>FDR</th><th>筛选</th><th>排除/警告</th></tr></thead><tbody>
          {rowPage.results.map((row) => <tr key={row.row_index}><td>{row.row_index + 1}</td><td>{row.original_label || "—"}</td><td>{row.normalized_symbol || "—"}</td><td>{formatExternalIdentifiers(row.external_identifiers)}</td><td>{mappingStatusLabel(row.mapping_status)}</td><td>{formatNumber(row.log2_fold_change)}</td><td>{formatNumber(row.fdr)}</td><td>{row.selected ? "通过" : "排除"}</td><td>{[...new Set([...row.exclusion_reasons, ...row.qc_warnings].map(qualityReasonLabel))].join("、") || "—"}</td></tr>)}
        </tbody></table></div> : !rowReadFailed && <p className="section-help">正在读取逐行结果…</p>}
        {rowPage && <div className="case-pagination"><button className="btn btn-secondary" type="button" disabled={!rowPage.previous} onClick={() => onRowPageChange(Math.max(1, rowPageNumber - 1))}>上一页</button>
          <span>第 {rowPageNumber} 页 / 共 {rowPage.count} 行</span><button className="btn btn-secondary" type="button" disabled={!rowPage.next} onClick={() => onRowPageChange(rowPageNumber + 1)}>下一页</button></div>}
      </>}
    </section>
      </> },
    ]} />
  </div>;
}

function ProteomicsVisualizationResult({ task, title, alt }: { task: AnalysisTask; title: string; alt: string }) {
  if (["queued", "running"].includes(task.status)) return <p className="section-help" role="status">R 绘图任务 #{task.id} 正在后台执行（{task.progress}%）。</p>;
  if (task.status === "failed") return <div className="notice-error" role="alert">R 图表生成失败：{task.error_summary}</div>;
  const value = task.result as { rendererVersion?: string; artifacts?: Array<{ id: number; format: string; downloadUrl: string }> };
  const artifacts = value.artifacts ?? [];
  const svg = artifacts.find((artifact) => artifact.format === "svg");
  const html = artifacts.find((artifact) => artifact.format === "html");
  return <div className="panel source-record"><h3>{title}</h3>
    {!hasInteractiveRenderer(value.rendererVersion) && <p className="notice-info">此任务提供静态图表，可查看或下载原始图片。</p>}
    <RChartViewer key={task.id} title={alt} interactive={hasInteractiveRenderer(value.rendererVersion)}
      svgUrl={svg && `${svg.downloadUrl}?inline=1`} htmlUrl={html && `${html.downloadUrl}?inline=1`} />
    <div className="source-record-actions">{artifacts.map((artifact) => <a className="btn btn-secondary" key={artifact.id} href={artifact.downloadUrl}>下载 {artifact.format.toUpperCase()}</a>)}</div>
  </div>;
}
