import type { NetworkPharmacologyResult, TargetIdentityOverlap, TargetIdentityRecord } from "../api/network";
import { downloadText, encodeCsv } from "../utils/downloads";

function records(items: TargetIdentityRecord[]) {
  return items.map(item => `${item.label} · ${item.source} #${item.entityId} · ${item.status === "verified" ? "已核验" : "待核验"} · 原物种 ${item.originalTaxon === "unknown" ? "未提供" : item.originalTaxon}`).join("；");
}

function Rows({ rows, pending = false }: { rows: TargetIdentityOverlap[]; pending?: boolean }) {
  if (!rows.length) return <p className="section-help">{pending ? "当前返回记录中没有可列出的共同名称候选。" : "当前返回、已完成编号核验的记录中未取得共同标准靶点。"}</p>;
  return <><div className="table-wrap"><table className="data-table"><thead><tr><th>{pending ? "人类参考候选" : "标准靶点"}</th><th>标准主键</th><th>中药侧来源记录</th><th>疾病侧来源记录</th></tr></thead><tbody>{rows.slice(0, 20).map(row => <tr key={row.key}><td>{row.label}</td><td>{row.key}</td><td>{records(row.herbRecords)}</td><td>{records(row.diseaseRecords)}</td></tr>)}</tbody></table></div>{rows.length > 20 && <p className="section-help">页面显示前20项；完整返回列表包含在JSON中。</p>}</>;
}

export function TargetIdentityResults({ result }: { result: NetworkPharmacologyResult }) {
  const identity = result.targetIdentity;
  if (!identity) return <p className="section-help">此历史任务没有标准靶点映射快照；重新检索可按当前版本核验。</p>;
  if (!identity.available || !identity.herb || !identity.disease) return <p className="notice-info">{identity.reason || "标准靶点映射暂不可用。"}</p>;
  const { herb, disease } = identity;
  const genes = identity.geneIntersections ?? [], proteins = identity.proteinIntersections ?? [];
  return <section className="figure-card target-identity-results" aria-label="标准靶点核验">
    <h3 className="section-title-sm">标准靶点核验</h3>
    <p className="section-help">按物种和标准编号计算交集，基因与蛋白分别计数。名称候选不计入已核验交集。</p>
    <div className="np-metrics"><div><span>已核验基因交集</span><strong>{identity.verifiedGeneIntersectionCount ?? 0}</strong></div><div><span>已核验蛋白交集</span><strong>{identity.verifiedProteinIntersectionCount ?? 0}</strong></div><div><span>待核验共同候选</span><strong>{identity.pendingGeneOverlapCount ?? 0}</strong></div></div>
    <div className="table-wrap"><table className="data-table"><thead><tr><th>集合</th><th>原始记录</th><th>已核验记录</th><th>待核验记录</th><th>标准基因</th><th>标准蛋白</th></tr></thead><tbody>{[["中药侧", herb], ["疾病侧", disease]].map(([name, side]) => {
      const s = side as typeof herb;
      return <tr key={name as string}><td>{name as string}</td><td>{s.records}</td><td>{s.verifiedRecords}</td><td>{s.pendingRecords}</td><td>{s.genes}</td><td>{s.proteins}</td></tr>;
    })}</tbody></table></div>
    {(herb.pendingRecords > 0 || disease.pendingRecords > 0) && <p className="notice-warning">仍有记录缺少可核验编号或物种，或存在标识冲突。已核验交集为0不代表没有生物学关联；待核验候选也不代表已证实的共同靶点。</p>}
    {Boolean(herb.geneUnresolvedRecords || disease.geneUnresolvedRecords) && <p className="section-help">部分已核验蛋白没有唯一的基因对照，只计入蛋白层级。</p>}
    {identity.coverage?.scope === "all_active_relations_for_matched_entities" ? <p className="section-help">标准主键比较覆盖匹配实体的全部已启用靶点关系；原始证据表和网络图仍有展示上限。</p> : Object.values(result.rawLimits?.inputRelationsTruncated ?? {}).some(Boolean) && <p className="section-help">本次源关系读取存在上限；上述统计仅覆盖当前返回子集。</p>}
    <details className="raw-details" open={genes.length > 0}><summary>已核验基因交集（{identity.verifiedGeneIntersectionCount ?? 0}）</summary><Rows rows={genes} /></details>
    <details className="raw-details"><summary>已核验蛋白交集（{identity.verifiedProteinIntersectionCount ?? 0}）</summary><Rows rows={proteins} /></details>
    <details className="raw-details"><summary>待核验共同候选（{identity.pendingGeneOverlapCount ?? 0}，不计入交集）</summary><p className="section-help">仅列出在参考目录中具有唯一基因对应的候选；多义名称和截断候选集不计入此数。原记录的未知物种保持未知。</p><Rows rows={identity.pendingCandidates ?? []} pending />{identity.pendingRowsTruncated && <p className="section-help">候选超过100项，接口已截断。</p>}</details>
    <div className="download-panel"><button type="button" disabled={!genes.length} onClick={() => downloadText("verified-gene-intersection.csv", encodeCsv(["standardKey", "label", "taxon", "herbRecords", "diseaseRecords", "referenceVersion"], genes.map(row => [row.key, row.label, row.taxon, records(row.herbRecords), records(row.diseaseRecords), identity.referenceVersion ?? ""])), "text/csv;charset=utf-8")}>导出已核验基因交集</button><button type="button" onClick={() => downloadText("target-identity-audit.json", JSON.stringify(identity, null, 2), "application/json;charset=utf-8")}>导出靶点核验记录</button></div>
    <details className="raw-details"><summary>映射版本与追溯</summary><p className="section-help">参考物种：人类（9606）；源记录物种未被覆盖。映射版本：{identity.referenceVersion}；比较规则：{identity.comparisonVersion ?? "历史规则"}；校验和：{identity.referenceSha256}。原始实体编号、关系及历史任务保持可追溯。</p></details>
  </section>;
}
