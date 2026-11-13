import type { NetworkPharmacologyResult, TargetIdentityOverlap, TargetIdentityRecord } from "../api/network";
import { downloadText, encodeCsv } from "../utils/downloads";

type IdentitySide = NonNullable<NonNullable<NetworkPharmacologyResult["targetIdentity"]>["herb"]>;

function sideCounts(side: IdentitySide) {
  const entries = Object.entries(side.statuses ?? {});
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  const verified = side.statuses?.verified ?? side.verifiedRecords;
  const pending = entries.length
    ? entries.reduce((sum, [status, count]) => sum + (status === "verified" ? 0 : count), 0)
    : side.pendingRecords;
  return {
    records: entries.length ? total : side.records,
    verified,
    pending,
    candidate: side.statuses?.candidate ?? 0,
    needsReview: (side.statuses?.ambiguous ?? 0) + (side.statuses?.conflict ?? 0) + (side.statuses?.unmapped ?? 0),
    breakdown: entries.filter(([status]) => status !== "verified"),
    summaryMismatch: entries.length > 0 && (
      total !== side.records || verified !== side.verifiedRecords || pending !== side.pendingRecords || total !== verified + pending
    ),
  };
}

function records(items: TargetIdentityRecord[]) {
  return items.map(item => {
    const taxon = item.taxonEvidence?.taxon === "9606"
      ? `物种 Homo sapiens${item.taxonEvidence.basis === "user_confirmed_all_records_human" ? "（来源范围由用户确认）" : "（来源字段）"}`
      : `原始物种 ${item.originalTaxon === "unknown" ? "未提供" : item.originalTaxon}`;
    return `${item.label} · ${item.source} #${item.entityId} · ${item.status === "verified" ? "已确证" : "待核验"} · ${taxon}`;
  }).join("；");
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
  const entityIdComparison = identity.entityIdComparison;
  const referenceCatalogNames = Object.keys(identity.referenceCatalogs ?? {}).map(key => ({
    uniprotReviewedHuman: "UniProt 人类人工审阅条目",
    ncbiGeneHuman: "NCBI Gene 人类基因符号、名称与别名",
  }[key] ?? key));
  const sourceSpeciesAssertions = Object.entries(identity.sourceSpeciesAssertions ?? {});
  const sourceLabels: Record<string, string> = {
    "disease-herb": "疾病—中药工作簿",
    "disease-targets": "疾病靶点工作簿",
  };
  const herbCounts = sideCounts(herb), diseaseCounts = sideCounts(disease);
  const verifiedGeneOverlap = identity.verifiedGeneIntersectionCount ?? 0;
  const candidateGeneOverlap = identity.pendingGeneOverlapCount ?? 0;
  const diseaseEvidence = identity.diseaseTargetEvidence;
  const reviewedScope = diseaseEvidence?.scope === "reviewed_direct_disease_targets_v1";
  const statusRows = [["中药侧", herbCounts], ["疾病侧", diseaseCounts]] as const;
  return <section className="figure-card target-identity-results" aria-label="标准靶点核验">
    <h3 className="section-title-sm">标准靶点核验</h3>
    <p className="section-help">按人类标准基因编号和蛋白编号分别统计。只有身份与物种证据满足核验规则的记录才计入确证交集；单一候选和未匹配记录不并入确证数。</p>
    {reviewedScope && diseaseEvidence.candidateEntityCount > 0 ? <div className="notice-warning">
      <p>疾病侧仅纳入经过关联来源审核的直接疾病—靶点关系。本次另有 {diseaseEvidence.candidateEntityCount.toLocaleString()} 个来源候选实体、{diseaseEvidence.candidateRelationCount.toLocaleString()} 条关系暂不计入疾病靶点集合和交集。靶点编号映射到人类只确认身份，不代表疾病关联已经核实。</p>
      <details><summary>候选关系来源与数量</summary><div className="table-wrap"><table className="data-table"><thead><tr><th>来源</th><th>关系类型</th><th>来源实体</th><th>关系记录</th><th>处理</th></tr></thead><tbody>{diseaseEvidence.candidateSources.map((source, index) => <tr key={`${source.sourceSlug}-${source.sourceVersion}-${source.relationType}-${index}`}><td>{sourceLabels[source.sourceSlug] ?? source.sourceSlug} · {source.sourceVersion}</td><td>{source.relationType}</td><td>{source.entityCount.toLocaleString()}</td><td>{source.relationCount.toLocaleString()}</td><td>{source.scope === "analysis" ? "纳入分析" : source.relationType === "disease_herb_target" ? "药材上下文候选" : "关联来源待审核"}</td></tr>)}</tbody></table></div><p className="section-help">原始来源行与关系仍保留在数据库及完整证据导出中。</p></details>
    </div> : !reviewedScope ? <p className="notice-warning">这是按旧统计口径保存的分析快照，疾病侧可能混入未审核的汇总表或药材上下文关系。请重新提交分析后查看新口径结果。</p> : null}
    <div className="np-metrics"><div><span>确证基因交集</span><strong>{verifiedGeneOverlap.toLocaleString()}</strong></div><div><span>确证蛋白交集</span><strong>{(identity.verifiedProteinIntersectionCount ?? 0).toLocaleString()}</strong></div><div><span>候选基因交集（待核验）</span><strong>{candidateGeneOverlap.toLocaleString()}</strong></div></div>
    <div className="table-wrap"><table className="data-table"><thead><tr><th>集合</th><th>靶点实体（去重）</th><th>身份已确证</th><th>单一映射待核验</th><th>需补录或消歧</th><th>标准基因</th><th>标准蛋白</th></tr></thead><tbody>{[["中药侧", herb, herbCounts], ["疾病侧", disease, diseaseCounts]].map(([name, side, counts]) => {
      const s = side as typeof herb;
      const summary = counts as typeof herbCounts;
      return <tr key={name as string}><td>{name as string}</td><td>{summary.records.toLocaleString()}</td><td>{summary.verified.toLocaleString()}</td><td>{summary.candidate.toLocaleString()}</td><td>{summary.needsReview.toLocaleString()}</td><td>{s.genes.toLocaleString()}</td><td>{s.proteins.toLocaleString()}</td></tr>;
    })}</tbody></table></div>
    <p className="section-help">表中 0 表示该身份状态没有记录，不代表该侧没有靶点。“单一映射待核验”表示当前只定位到一个参考条目，但编号或其他身份依据不足以确证；“需补录或消歧”包括多重匹配、标识冲突和无匹配。</p>
    {sourceSpeciesAssertions.length > 0 && <details className="raw-details"><summary>来源物种确认</summary><p className="section-help">{sourceSpeciesAssertions.map(([source, assertion]) => `${sourceLabels[source] ?? source}：${assertion.organism}（确认于 ${assertion.confirmedAt}）`).join("；")}。原始工作簿未带物种列，此处记录项目范围确认。</p></details>}
    {statusRows.some(([, counts]) => counts.pending > 0) && <details className="raw-details">
      <summary>身份解析明细</summary>
      <div className="table-wrap"><table className="data-table"><thead><tr><th>集合</th><th>单一映射待核验</th><th>多重匹配</th><th>标识冲突</th><th>无匹配</th></tr></thead><tbody>{statusRows.map(([name, counts]) => <tr key={name}><td>{name}</td>{["candidate", "ambiguous", "conflict", "unmapped"].map(status => <td key={status}>{(Object.fromEntries(counts.breakdown)[status] ?? 0).toLocaleString()}</td>)}</tr>)}</tbody></table></div>
      <p className="section-help">这些是来源靶点记录的身份状态数，不是基因交集数。物种范围已确认后，仍可能因编号缺失、冲突或名称无法唯一匹配而待核验。</p>
    </details>}
    {entityIdComparison && <details className="raw-details">
      <summary>原始实体 ID 明细（本库诊断：{entityIdComparison.intersectionCount.toLocaleString()}）</summary>
      <p className="section-help">内部实体 ID 是本项目数据库的记录编号，不是跨库标准靶点编号。此处仅比较药材侧全部靶点与按当前疾病来源审核口径纳入的直接疾病靶点；药材上下文和待审核汇总记录不计入。跨库靶点比较请看上方标准基因与蛋白交集。</p>
      {entityIdComparison.intersectionEntities.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>实体 ID</th><th>名称</th><th>类型</th><th>稳定标识</th></tr></thead><tbody>{entityIdComparison.intersectionEntities.map(item => <tr key={item.id}><td>{item.id}</td><td>{item.label}</td><td>{item.entity_type}</td><td>{item.stable_id}</td></tr>)}</tbody></table></div> : <p className="section-help">完整有效关系集合中没有相同实体 ID。</p>}
      {entityIdComparison.rowsTruncated && <p className="section-help">交集实体超过100个，页面表格只显示前100项。</p>}
      <div className="download-panel"><button type="button" disabled={!entityIdComparison.intersectionEntities.length} onClick={() => downloadText("complete-entity-id-intersection.csv", encodeCsv(["entityId", "label", "entityType", "stableId"], entityIdComparison.intersectionEntities.map(item => [item.id, item.label, item.entity_type, item.stable_id])), "text/csv;charset=utf-8")}>导出完整关系集实体 ID 交集</button></div>
    </details>}
    {!entityIdComparison && <p className="notice-warning">该历史任务没有保存完整关系集的原始实体 ID 交集；图中的旧交集数只代表当时返回的结果子集。重新执行检索即可生成完整统计。</p>}
    {(herbCounts.summaryMismatch || diseaseCounts.summaryMismatch) && <p className="notice-warning">返回汇总与各核验状态数量不一致；页面已按状态明细合计显示，请核查此任务保存的映射版本。</p>}
    {(herbCounts.pending > 0 || diseaseCounts.pending > 0) && <p className="notice-warning">另有 {candidateGeneOverlap.toLocaleString()} 个可能重叠的基因候选尚未确证；它们不计入上方交集。其余未核验记录需要补充编号或消歧。</p>}
    {Boolean(herb.geneUnresolvedRecords || disease.geneUnresolvedRecords) && <p className="section-help">部分已核验蛋白没有唯一的基因对照，只计入蛋白层级。</p>}
    {identity.coverage?.scope === "all_active_relations_for_matched_entities" ? <p className="section-help">标准主键比较覆盖匹配实体的全部已启用靶点关系；原始证据表和网络图仍有展示上限。</p> : Object.values(result.rawLimits?.inputRelationsTruncated ?? {}).some(Boolean) && <p className="section-help">本次源关系读取存在上限；上述统计仅覆盖当前返回子集。</p>}
    <details className="raw-details" open={genes.length > 0}><summary>已核验基因交集（{identity.verifiedGeneIntersectionCount ?? 0}）</summary><Rows rows={genes} /></details>
    <details className="raw-details"><summary>已核验蛋白交集（{identity.verifiedProteinIntersectionCount ?? 0}）</summary><Rows rows={proteins} /></details>
    <details className="raw-details"><summary>尚未确证的候选基因重叠（{candidateGeneOverlap.toLocaleString()}）</summary><p className="section-help">这里列出两侧可能对应同一标准基因、但现有身份依据不足以纳入确证交集的记录。</p><Rows rows={identity.pendingCandidates ?? []} pending />{identity.pendingRowsTruncated && <p className="section-help">候选超过100项，接口已截断。</p>}</details>
    <div className="download-panel"><button type="button" disabled={!genes.length} onClick={() => downloadText("verified-gene-intersection.csv", encodeCsv(["standardKey", "label", "taxon", "herbRecords", "diseaseRecords", "referenceVersion"], genes.map(row => [row.key, row.label, row.taxon, records(row.herbRecords), records(row.diseaseRecords), identity.referenceVersion ?? ""])), "text/csv;charset=utf-8")}>导出已核验基因交集</button><button type="button" onClick={() => downloadText("target-identity-audit.json", JSON.stringify(identity, null, 2), "application/json;charset=utf-8")}>导出靶点核验记录</button></div>
    <details className="raw-details"><summary>映射版本与追溯</summary><p className="section-help">参考目录：{referenceCatalogNames.length ? referenceCatalogNames.join("；") : "当前版本未记录目录详情"}。新版本优先采用 NCBI Gene 标准符号与全名，再匹配别名；同名冲突保留多候选。来源物种缺失时，仍保留未知物种。映射版本：{identity.referenceVersion}；比较规则：{identity.comparisonVersion ?? "历史规则"}；校验和：{identity.referenceSha256}。原始实体编号、关系及历史任务保持可追溯。</p></details>
  </section>;
}
