import { Download } from "lucide-react";
import type { AnalysisTask } from "../api/datasets";
import { downloadText } from "../utils/downloads";

type StringStatus = "succeeded" | "no_interactions" | "insufficient_identifiers" | "unavailable" | "disabled";
type StringNode = { id: string; label: string; type: string; degree?: number; betweenness?: number };
type StringEdge = { source: string; target: string; score: number; scoreOutOf1000: number };
export type StringResult = {
  analysisKind?: "string_ppi";
  status?: StringStatus;
  organism: string;
  source: string;
  sourceVersion: string | null;
  sourceVersionKnown?: boolean;
  sourceEndpoint?: string;
  retrievedAt?: string;
  networkType: "physical";
  requiredScore: number;
  inputCount: number;
  submittedIdentifierCount?: number;
  truncatedIdentifierCount?: number;
  rejectedIdentifierCount?: number;
  interactionCount: number;
  nodes: StringNode[];
  edges: StringEdge[];
  centralityMethod?: string;
  consentRecorded?: boolean;
  failureStage?: string;
};

const statuses: Record<StringStatus, string> = {
  succeeded: "已返回互作",
  no_interactions: "没有满足阈值的互作",
  insufficient_identifiers: "可用标识不足",
  unavailable: "服务不可用",
  disabled: "服务已停用",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
function isScore(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}
function isNode(value: unknown): value is StringNode {
  return isRecord(value) && typeof value.id === "string" && Boolean(value.id)
    && typeof value.label === "string" && typeof value.type === "string"
    && (value.degree === undefined || isCount(value.degree))
    && (value.betweenness === undefined || isScore(value.betweenness));
}
function isEdge(value: unknown): value is StringEdge {
  return isRecord(value) && typeof value.source === "string" && typeof value.target === "string"
    && isScore(value.score) && isCount(value.scoreOutOf1000) && value.scoreOutOf1000 <= 1000;
}

// main@078d374 ProteomicsWorkbench uses a result table + JSON export and the
// local protein/pathway NetworkGraph. main has no separate STRING/PPI drawing;
// keep this adapter a result view, without inventing a new topology or evidence.
export function readStringNetwork(value: unknown): StringResult | null {
  if (!isRecord(value) || !(value.analysisKind === "string_ppi" || typeof value.status === "string")
    || !(value.analysisKind === undefined || value.analysisKind === "string_ppi")
    || !(value.status === undefined || Object.hasOwn(statuses, String(value.status)))
    || typeof value.organism !== "string" || typeof value.source !== "string"
    || !(value.sourceVersion === null || typeof value.sourceVersion === "string")
    || value.networkType !== "physical" || !isCount(value.requiredScore) || value.requiredScore > 1000
    || !isCount(value.inputCount) || !isCount(value.interactionCount)
    || !Array.isArray(value.nodes) || !value.nodes.every(isNode)
    || !Array.isArray(value.edges) || !value.edges.every(isEdge)
    || value.interactionCount !== value.edges.length) return null;
  if (["submittedIdentifierCount", "truncatedIdentifierCount", "rejectedIdentifierCount"]
    .some((field) => value[field] !== undefined && !isCount(value[field]))) return null;
  if (["sourceEndpoint", "retrievedAt", "centralityMethod", "failureStage"]
    .some((field) => value[field] !== undefined && typeof value[field] !== "string")) return null;
  const nodeIds = new Set(value.nodes.map((node) => node.id));
  if (nodeIds.size !== value.nodes.length || value.edges.some((edge) => !nodeIds.has(edge.source) || !nodeIds.has(edge.target))) return null;
  if (value.status !== undefined && value.status !== "succeeded" && value.edges.length > 0) return null;
  return value as StringResult;
}

export function stringResultJson(value: unknown, task?: AnalysisTask): string | null {
  if (!readStringNetwork(value) || (task && task.status !== "succeeded")) return null;
  return JSON.stringify({
    formatVersion: "string-network-export-v1",
    ...(task ? { task: {
      id: task.id, task_type: task.task_type, status: task.status,
      dataset: task.dataset, medical_case: task.medical_case,
      ...("parent_task" in task ? { parent_task: task.parent_task } : {}),
      input_parameters: task.input_parameters, source_releases: task.source_releases,
      created_at: task.created_at, started_at: task.started_at, finished_at: task.finished_at,
    } } : {}),
    result: value,
  }, null, 2);
}

export function StringNetworkResult({ result, task }: { result: unknown; task?: AnalysisTask }) {
  const value = readStringNetwork(result);
  if (!value) return <div className="notice-error" role="alert">STRING 结果格式不完整，暂不能展示互作或导出。</div>;
  const status = value.status ?? (value.edges.length ? "succeeded" : "no_interactions");
  const nodeLabels = new Map(value.nodes.map((node) => [node.id, node.label]));
  const rankedNodes = [...value.nodes].sort((left, right) => (right.betweenness ?? 0) - (left.betweenness ?? 0) || (right.degree ?? 0) - (left.degree ?? 0));
  function download() {
    const body = stringResultJson(result, task);
    if (body) downloadText(`string-network${task ? `-task-${task.id}` : ""}.json`, body, "application/json;charset=utf-8");
  }
  return <section className="proteomics-result-section">
    <div className="case-list-heading"><div><h3 className="section-title-sm">STRING 物理互作网络</h3>
      <p className="section-help">{value.organism} · {value.source}{value.sourceVersion ? ` ${value.sourceVersion}` : " · 来源版本未返回"} · 最低置信度 {value.requiredScore}/1000{task ? ` · 任务 #${task.id}` : ""}</p></div>
      <span className={`status-badge ${status === "succeeded" ? "status-success" : status === "unavailable" || status === "disabled" ? "status-warning" : ""}`}>{statuses[status]}</span></div>
    <div className="source-record-actions"><button className="btn btn-secondary" type="button" onClick={download} disabled={Boolean(task && task.status !== "succeeded")}><Download size={15} />导出 STRING 记录 JSON</button></div>
    <p className="section-help">本次识别 {value.inputCount} 个标识{value.submittedIdentifierCount !== undefined ? `，向 STRING 提交 ${value.submittedIdentifierCount} 个` : ""}；返回 {value.interactionCount} 条物理互作。分数是数据库证据，不代表因果结论。</p>
    {value.retrievedAt && <p className="section-help">检索时间 {value.retrievedAt}</p>}
    {status === "unavailable" && <p className="section-help">STRING 查询未完成，不能据此判断蛋白之间没有互作；本地分析结果仍可查看。</p>}
    {status === "disabled" && <p className="section-help">管理员已停用 STRING 服务，本次没有生成外部互作结果。</p>}
    {status === "insufficient_identifiers" && <p className="section-help">可用标识少于 2 个，本次未向 STRING 发送查询。</p>}
    {value.edges.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>蛋白 A</th><th>蛋白 B</th><th>STRING 评分</th></tr></thead><tbody>
      {value.edges.slice(0, 200).map((edge, index) => <tr key={`${edge.source}:${edge.target}:${index}`}><td title={edge.source}>{nodeLabels.get(edge.source) || edge.source}</td><td title={edge.target}>{nodeLabels.get(edge.target) || edge.target}</td><td>{edge.scoreOutOf1000}/1000</td></tr>)}
    </tbody></table></div> : status === "no_interactions" || status === "succeeded" ? <p className="section-help">本次查询已完成，当前标识和置信度下没有返回物理互作边。</p> : null}
    {value.edges.length > 200 && <p className="section-help">页面预览前 200 条互作；JSON 保留实际返回的全部 {value.edges.length} 条及蛋白稳定 ID。</p>}
    {rankedNodes.length > 0 && <>
      <h4 className="section-title-sm">STRING 网络中心性</h4>
      <p className="section-help">degree 为互作邻居数；betweenness 是当前阈值网络中的无权最短路径中介中心性（归一化）。这些指标只描述网络结构，不代表因果作用。</p>
      <div className="table-scroll"><table className="data-table"><thead><tr><th>蛋白</th><th>degree</th><th>betweenness</th></tr></thead><tbody>
        {rankedNodes.slice(0, 30).map((node) => <tr key={node.id}><td title={node.id}>{node.label || node.id}</td><td>{node.degree ?? "—"}</td><td>{node.betweenness == null ? "—" : node.betweenness.toPrecision(4)}</td></tr>)}
      </tbody></table></div>
      {rankedNodes.length > 30 && <p className="section-help">页面展示前 30 个中心性节点；JSON 包含全部 {rankedNodes.length} 个返回节点。中心性按本次返回的互作图计算。</p>}
    </>}
    {(value.truncatedIdentifierCount ?? 0) > 0 && <p className="section-help">单次最多提交 200 个标识，另有 {value.truncatedIdentifierCount} 个未发送；当前网络仅覆盖已提交标识。</p>}
    {(value.rejectedIdentifierCount ?? 0) > 0 && <p className="section-help">有 {value.rejectedIdentifierCount} 个无效或过长标识未发送。</p>}
  </section>;
}

export function StringTaskResult({ task, sourceTaskId }: { task: AnalysisTask; sourceTaskId?: number }) {
  if (["queued", "running"].includes(task.status)) return <p className="section-help" role="status">STRING 任务 #{task.id} 正在后台执行（{task.progress}%）。</p>;
  if (task.status === "failed") return <div className="notice-error" role="alert">STRING 任务 #{task.id} 失败：{task.error_summary || "外部分析未完成。"}</div>;
  if (task.status === "cancelled") return <p className="section-help" role="status">STRING 任务 #{task.id} 已取消。</p>;
  const parentId = "parent_task" in task ? task.parent_task : undefined;
  if (task.input_parameters.analysisKind !== "string_ppi" || (sourceTaskId !== undefined && typeof parentId === "number" && parentId !== sourceTaskId)) {
    return <div className="notice-error" role="alert">STRING 任务 #{task.id} 与当前查询的来源不一致，暂不展示或导出。</div>;
  }
  return <div className="panel source-record"><StringNetworkResult result={task.result} task={task} />
    {sourceTaskId !== undefined && <p className="section-help">{typeof parentId === "number" ? `来源查询任务 #${parentId} 已保存在服务端。` : `来源查询任务 #${sourceTaskId} 仅为当前页面关联；此历史任务尚未保存来源绑定。`}</p>}
  </div>;
}
