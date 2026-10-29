import { useEffect, useRef, useState } from "react";
import { getSnapshotPage, snapshotDownloadUrl, type EvidenceSnapshot, type SnapshotPage } from "../api/complete-evidence";

const labels: Record<string, string> = { evidenceRecords: "来源关系", entities: "实体身份", queries: "查询归属", diseaseLinks: "疾病—中药—靶点关联", targets: "全部候选靶点", targetSources: "候选来源",
  herbLinks: "中药侧原始表", diseaseTargets: "疾病侧原始表", diseaseHerbLinks: "疾病—中药—靶点表", directDiseaseHerbLinks: "直接关联表", reportSections: "研究计划报告章节", herbSummaries: "方药逐来源汇总" };

export function SnapshotEvidence({ taskId, snapshot }: { taskId: number; snapshot: EvidenceSnapshot }) {
  const [open, setOpen] = useState(false), [table, setTable] = useState("evidenceRecords"), [page, setPage] = useState(1);
  const [data, setData] = useState<SnapshotPage | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [retry, setRetry] = useState(0);
  const [dataScope, setDataScope] = useState("");
  const scope = `${taskId}:${snapshot.sha256}:${table}:${page}`;
  const visible = dataScope === scope ? data : null;
  const generation = useRef(0);
  useEffect(() => { setData(null); setPage(1); setTable("evidenceRecords"); setError(""); }, [taskId, snapshot.sha256]);
  useEffect(() => {
    const current = ++generation.current;
    setData(null); setError("");
    if (!open) return;
    setBusy(true);
    getSnapshotPage(taskId, table, page).then(result => {
      if (generation.current !== current) return;
      if (result.taskId !== taskId || result.table !== table || result.snapshotSha256 !== snapshot.sha256
        || result.tableSha256 !== snapshot.tables[table]?.sha256 || result.count !== snapshot.tables[table]?.count || result.complete !== true) throw new Error("返回证据与当前任务快照不一致。");
      setData(result); setDataScope(scope);
    }).catch(cause => { if (generation.current === current) setError(cause instanceof Error ? cause.message : "证据读取失败。"); })
      .finally(() => { if (generation.current === current) setBusy(false); });
    return () => { generation.current++; };
  }, [open, taskId, snapshot.sha256, table, page, retry]);
  return <details className="raw-details" style={{ minWidth: 0, maxWidth: "100%" }} open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>完整证据快照与分页查看</summary>
    <p className="section-help">后台输入已读全；图和页面表格仍可只显示部分。下载只读取任务 #{taskId} 的冻结记录，目录更新不会改变本次证据。</p>
    <div className="source-record-actions">
      <a className="btn btn-secondary" href={snapshotDownloadUrl(taskId)} download>下载完整快照 JSONL</a>
      <a className="btn btn-secondary" href={snapshotDownloadUrl(taskId, table, "csv")} download>下载当前完整表 CSV</a>
      <label>证据表 <select value={table} onChange={event => { setTable(event.target.value); setPage(1); }}>{Object.entries(snapshot.tables).map(([key, value]) => <option key={key} value={key}>{labels[key] ?? key}（{value.count}）</option>)}</select></label>
    </div>
    {busy && <p role="status">正在读取冻结证据…</p>}
    {error && <p role="alert" className="notice-error">{error} <button className="btn btn-secondary" type="button" onClick={() => setRetry(value => value + 1)}>重试读取</button></p>}
    {visible && <>
      <div className="table-scroll"><table className="data-table" aria-label="完整快照证据"><thead><tr><th>序号</th><th>冻结记录</th></tr></thead><tbody>{visible.results.map(row => <tr key={row.ordinal}><td>{row.ordinal}</td><td><details><summary>{String(row.payload.subject ?? row.payload.target ?? row.payload.label ?? row.payload.query ?? row.payload.herb ?? row.ordinal)}{row.payload.object ? ` → ${String(row.payload.object)}` : ""} {String(row.payload.sourceRecordId ?? "")}</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(row.payload, null, 2)}</pre></details></td></tr>)}</tbody></table></div>
      <nav className="table-pager" aria-label="完整快照分页"><span>第 {page} 页，共 {visible.count} 行</span><div><button type="button" disabled={page === 1 || busy} onClick={() => setPage(value => value - 1)}>上一页</button><button type="button" disabled={!visible.next || busy} onClick={() => setPage(value => value + 1)}>下一页</button></div></nav>
    </>}
    <p className="section-help" style={{ overflowWrap: "anywhere" }}>快照 SHA-256：{snapshot.sha256}</p>
  </details>;
}
