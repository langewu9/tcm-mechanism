import { useEffect, useState } from "react";
import { apiRequest, ApiError } from "../api/client";

type Summary = { schemaVersion: string; entityCount: number; canonicalIdCount: number; identifierCount: number; mappingCount: number; rawRecordCount: number; relationCount: number; publishedRelationCount: number; quarantinedRecordCount: number; workbookReleases: {source: string; version?: string; active?: boolean; qualitySummary?: { targetReviewStatuses?: Record<string, number>; propertyConflictMolecules?: number }; state: string; counts: {rows?: number; relations?: number; quarantined?: number}}[]; mappingStatuses: Record<string, number>;
  targetIdentity?: { available: boolean; version: string; masterCount: number; statuses: Record<string, number>; sourceStatuses: Record<string, Record<string, number>> };
};
export function MasterTableStatus() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void apiRequest<Summary>("/api/v1/admin/master-table/").then(value => {
      if (active) setData(value);
    }).catch(cause => { if (active) setError(cause instanceof ApiError ? cause.message : "主表状态读取失败。"); });
    return () => { active = false; };
  }, []);
  return <section className="panel source-record" aria-label="多数据库统一主表">
    <h3 className="section-title-sm">多数据库统一主表</h3>
    <p className="section-help">查看实体主键、来源标识与关联证据。不同物种及同名异标识分别保留，支持追溯各数据库的原始记录。</p>
    {error ? <p className="notice-error" role="alert">{error}</p> : !data ? <p role="status">正在读取主表…</p> : <>
      <dl className="master-table-stats"><div><dt>来源实体记录</dt><dd>{data.entityCount.toLocaleString()}</dd></div><div><dt>实体全局 ID</dt><dd>{data.canonicalIdCount.toLocaleString()}</dd></div><div><dt>主标识映射</dt><dd>{data.identifierCount.toLocaleString()}</dd></div><div><dt>来源版本映射</dt><dd>{data.mappingCount.toLocaleString()}</dd></div><div><dt>原始来源行</dt><dd>{data.rawRecordCount.toLocaleString()}</dd></div><div><dt>证据关系</dt><dd>{data.relationCount.toLocaleString()}</dd></div></dl>
      <p className="section-help">已发布关系 {(data.publishedRelationCount ?? 0).toLocaleString()} · 待核查原始行 {data.quarantinedRecordCount ?? 0} · 标识冲突 {data.mappingStatuses.conflict ?? 0} · 歧义 {data.mappingStatuses.ambiguous ?? 0}。来源名称只用于检索，不自动合并同名实体。</p>
      {(data.workbookReleases ?? []).length > 0 && <div className="table-wrap master-source-table-wrap"><table className="master-source-table"><thead><tr><th>内部数据源</th><th>状态</th><th>原始行</th><th>关系</th><th>待核查</th></tr></thead><tbody>{data.workbookReleases.map((release, index) => <tr key={`${release.source}-${index}`}><td>{release.source}<details><summary>版本与质量</summary><p style={{overflowWrap:"anywhere"}}>{release.version ?? "历史版本"}</p>{release.qualitySummary?.targetReviewStatuses && <p>已核验靶点编号 {release.qualitySummary.targetReviewStatuses.verified ?? 0}；属性有冲突的化合物 {release.qualitySummary.propertyConflictMolecules ?? 0} 个。</p>}</details></td><td>{release.state !== "published" ? "暂存，未发布" : release.active === false ? "历史版本" : "已发布可用"}</td><td>{(release.counts.rows ?? 0).toLocaleString()}</td><td>{(release.counts.relations ?? 0).toLocaleString()}</td><td>{release.counts.quarantined ?? 0}</td></tr>)}</tbody></table><p className="section-help">授权范围：内部使用。原始工作簿与运行数据库不公开上传；定时同步仍未启用。</p></div>}
      {data.targetIdentity?.available && <section aria-label="标准靶点主表">
        <h4 className="section-title-sm">标准靶点主表</h4><p className="section-help">标准基因和蛋白共 {data.targetIdentity.masterCount.toLocaleString()} 项。仅凭可核验编号建立关联，未知物种的名称匹配保留为候选；基因和蛋白分别核算。</p>
        <div className="table-wrap"><table className="data-table"><thead><tr><th>实体来源</th><th>已核验</th><th>待核验候选</th><th>歧义</th><th>冲突</th><th>未映射</th></tr></thead><tbody>{Object.entries(data.targetIdentity.sourceStatuses).map(([source, counts]) => <tr key={source}><td>{source === "global" ? "跨来源标准编号实体" : source}</td>{["verified", "candidate", "ambiguous", "conflict", "unmapped"].map(status => <td key={status}>{(counts[status] ?? 0).toLocaleString()}</td>)}</tr>)}</tbody></table></div>
        <details className="raw-details"><summary>靶点映射版本</summary><p className="section-help">{data.targetIdentity.version}。发布新版本时原子切换，历史任务保留原版本；原始实体编号和关系不改写。</p></details>
        <a className="btn btn-secondary" href="/django-admin/core/targetidentitymapping/">查看靶点核验明细</a>
      </section>}
      <a className="btn btn-secondary" href="/django-admin/core/sourceentitymapping/">查看来源映射</a>
    </>}
  </section>;
}
