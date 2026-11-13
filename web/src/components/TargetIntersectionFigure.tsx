import type { NetworkPharmacologyResult } from "../api/network";
import { TargetIdentityResults } from "./TargetIdentityResults";

type IntersectionKind = "unmatched" | "missing_evidence" | "invalid" | "disjoint" | "overlap";
const number = (value: number) => value.toLocaleString("zh-CN");

export function intersectionState(result: NetworkPharmacologyResult) {
  const s = result.summary;
  const stages = result.rawLimits?.inputRelationsTruncated ?? {};
  const partial = Boolean(s.unmatchedHerbs?.length || s.unresolvedFormulas?.length ||
    s.diseaseResolution?.entitiesTruncated || stages.formulaHerbs || stages.herbCompounds ||
    stages.compoundTargets || stages.diseaseTargets);
  let kind: IntersectionKind;
  let message: string;
  if (s.unmatchedDiseases?.length || s.matchedDiseases?.length === 0 ||
      (s.matchedHerbs?.length === 0 && !s.matchedFormulas?.length)) {
    kind = "unmatched";
    message = "查询名称尚未完整匹配，无法判断靶点交集；未匹配不等于靶点数量为零。";
  } else if (![s.herbTargetCount, s.diseaseTargetCount, s.strictIntersectionCount].every(value =>
      Number.isSafeInteger(value) && value >= 0) || s.strictIntersectionCount > Math.min(s.herbTargetCount, s.diseaseTargetCount)) {
    kind = "invalid";
    message = "靶点计数不一致，暂不绘制集合图；请重新查询或核对任务来源。";
  } else if (!s.herbTargetCount || !s.diseaseTargetCount) {
    kind = "missing_evidence";
    message = `名称已匹配，但${!s.herbTargetCount && !s.diseaseTargetCount ? "两侧" : !s.herbTargetCount ? "中药侧" : "疾病侧"}未返回有效靶点证据，暂不能判断生物学关联。`;
  } else {
    kind = s.strictIntersectionCount ? "overlap" : "disjoint";
    message = s.strictIntersectionCount ? "交集仅按相同实体标识计算，不以同名靶点自动合并。" :
      "当前已返回、按实体标识核验的靶点中未发现严格交集；未完成跨库标识统一的同名记录不计入，不能据此判断没有生物学关联。";
  }
  const comparable = kind === "disjoint" || kind === "overlap";
  let badge = kind === "unmatched" ? "名称待确认" : kind === "missing_evidence" ? "证据不足" :
    kind === "invalid" ? "统计待核验" : partial ? "部分结果" : kind === "disjoint" ? "当前交集为 0" : "交集已计算";
  if (result.targetIdentity?.available && comparable) {
    const identity = result.targetIdentity;
    badge = identity.verifiedGeneIntersectionCount ? "标准靶点已对齐" :
      (identity.herb?.pendingRecords || identity.disease?.pendingRecords) ? "部分靶点待核验" : "已核验交集为 0";
    message = `原始实体记录比较：${message}`;
  }
  return { kind, message, partial, comparable, badge };
}

export function TargetIntersectionNotice({ result, onDiseaseSelect }: {
  result: NetworkPharmacologyResult; onDiseaseSelect?: (label: string) => void;
}) {
  const s = result.summary, state = intersectionState(result);
  const resolution = s.diseaseResolution;
  const identity = result.targetIdentity;
  const identityReady = Boolean(identity?.available && identity.herb && identity.disease);
  const verifiedHerbGenes = identity?.herb?.genes ?? 0;
  const verifiedDiseaseGenes = identity?.disease?.genes ?? 0;
  const verifiedGeneOverlap = identity?.verifiedGeneIntersectionCount ?? 0;
  const verifiedProteinOverlap = identity?.verifiedProteinIntersectionCount ?? 0;
  const candidateGeneOverlap = identity?.pendingGeneOverlapCount ?? 0;
  const standardComparable = identityReady && verifiedHerbGenes > 0 && verifiedDiseaseGenes > 0 &&
    Number.isSafeInteger(verifiedGeneOverlap) && verifiedGeneOverlap >= 0 &&
    verifiedGeneOverlap <= Math.min(verifiedHerbGenes, verifiedDiseaseGenes);
  const comparisonMessage = identityReady
    ? standardComparable
      ? `标准编号交集：基因 ${number(verifiedGeneOverlap)}、蛋白 ${number(verifiedProteinOverlap)}；另有 ${number(candidateGeneOverlap)} 个候选基因重叠尚未确证，不计入交集。`
      : `已核验标准基因集合不足以比较（中药侧 ${number(verifiedHerbGenes)}，疾病侧 ${number(verifiedDiseaseGenes)}）；未核验记录不计入标准交集。`
    : state.message;
  const diseaseEvidence = identity?.diseaseTargetEvidence;
  return <div className="target-intersection-notices" role="status">
    {s.unmatchedDiseases?.length ? <p className="notice-warning">未匹配疾病：{s.unmatchedDiseases.join("、")}。请确认规范名称；下方 0 仅表示本次未取得数据。</p> : null}
    {s.unmatchedHerbs?.length ? <p className="notice-warning">未匹配中药或方剂：{s.unmatchedHerbs.join("、")}。其证据未纳入，本次不是完整处方的交集。</p> : null}
    {s.unresolvedFormulas?.length ? <p className="notice-warning">方剂 {s.unresolvedFormulas.join("、")} 已匹配，但缺少可追溯组成关系，无法完整展开。</p> : null}
    {s.matchedDiseases?.length ? <p className="section-help">{resolution?.status === "alias" ? "疾病名称对应" : "已匹配疾病"}：{s.disease} → {[...new Set(s.matchedDiseases)].join("、")}。{resolution?.aliasVersion ? `名称规则 ${resolution.aliasVersion}；` : ""}不同来源实体及原始证据保持独立。</p> : null}
    {resolution?.candidates?.length ? <div className="target-intersection-candidates"><p>以下是相关检索候选，不一定与原疾病等价；请选择确切名称后重新检索：</p>{resolution.candidates.map(item =>
      onDiseaseSelect ? <button className="btn btn-secondary" type="button" key={item.label} onClick={() => onDiseaseSelect(item.label)}>使用名称：{item.label}<small>{item.sourceSlugs.join(" / ")}</small></button> : <p key={item.label}>{item.label} · {item.sourceSlugs.join(" / ")}</p>
    )}</div> : null}
    <p className={identityReady ? (standardComparable ? "section-help" : "notice-warning") : (state.comparable ? "section-help" : "notice-warning")}>{comparisonMessage}</p>
    {diseaseEvidence?.candidateEntityCount ? <p className="notice-warning">疾病侧另有 {number(diseaseEvidence.candidateEntityCount)} 个来源候选实体未纳入交集：汇总表关系尚缺独立疾病来源审核，疾病—中药靶点关系属于药材上下文。它们仍保留在来源证据中。</p> : null}
    {identityReady && !diseaseEvidence ? <p className="notice-warning">此为旧分析快照，疾病靶点沿用旧来源口径；请重新提交查询以排除未审核的疾病汇总候选和药材上下文关系。</p> : null}
    {state.partial && <p className="notice-warning">{result.targetIdentity?.coverage?.scope === "all_active_relations_for_matched_entities" ? "标准基因与蛋白交集按已匹配实体的全部有效关系计算；证据表和网络图受返回上限影响。未匹配名称不参与标准化统计。" : "查询名称、实体匹配或源关系读取不完整；图和计数只描述当前返回子集，不是全库总量。请缩小查询范围或补齐来源与标识映射。"}</p>}
  </div>;
}

function IntersectionDiagram({ a, b, common, scopeLabel }: { a: number; b: number; common: number; scopeLabel: string }) {
  const mode = !common ? "disjoint" : a === b && common === a ? "identical" :
    common === a ? "herb_subset" : common === b ? "disease_subset" : "overlap";
  const blue = "#4E6D9C", red = "#B65A50", ink = "#32251F";
  const circles = mode === "disjoint" ? [{ x: 165, r: 112, color: blue }, { x: 475, r: 112, color: red }] :
    mode === "herb_subset" ? [{ x: 320, r: 140, color: red }, { x: 360, r: 90, color: blue }] :
    mode === "disease_subset" ? [{ x: 320, r: 140, color: blue }, { x: 360, r: 90, color: red }] :
    mode === "identical" ? [{ x: 320, r: 130, color: blue }, { x: 320, r: 130, color: red }] :
    [{ x: 245, r: 125, color: blue }, { x: 395, r: 125, color: red }];
  const zones = mode === "disjoint" ? [
    { x: 165, label: "中药侧", value: a, color: blue }, { x: 475, label: "疾病侧", value: b, color: red },
  ] : mode === "identical" ? [{ x: 320, label: "两侧集合完全重合", value: common, color: ink }] :
    mode === "herb_subset" ? [{ x: 220, label: "疾病特异", value: b - common, color: red }, { x: 360, label: "严格交集", value: common, color: ink }] :
    mode === "disease_subset" ? [{ x: 220, label: "中药特异", value: a - common, color: blue }, { x: 360, label: "严格交集", value: common, color: ink }] :
    [{ x: 185, label: "中药特异", value: a - common, color: blue }, { x: 320, label: "严格交集", value: common, color: ink }, { x: 455, label: "疾病特异", value: b - common, color: red }];
  return <div className="target-intersection-canvas"><svg className="target-intersection-svg" viewBox="0 0 640 360" role="img" aria-label={`${scopeLabel}：中药侧 ${number(a)}，疾病侧 ${number(b)}，交集 ${number(common)}。圆面积不代表数量。`}>
    <title>{`${scopeLabel}；中药侧 ${number(a)}；疾病侧 ${number(b)}；交集 ${number(common)}。${mode === "disjoint" ? "两个集合互不重叠。" : ""}`}</title>
    {circles.map((circle, i) => <circle key={i} cx={circle.x} cy="180" r={circle.r} fill={circle.color} fillOpacity="0.12" stroke={circle.color} strokeWidth="2.5" strokeDasharray={mode === "identical" && i === 1 ? "8 5" : undefined} />)}
    {zones.map(zone => <g key={zone.label}><text x={zone.x} y="165" textAnchor="middle" fill={zone.color} fontSize="14">{zone.label}</text><text x={zone.x} y="205" textAnchor="middle" fill={ink} fontSize={number(zone.value).length > 5 ? 24 : 30}>{number(zone.value)}</text></g>)}
    {mode === "disjoint" && <text x="320" y="184" textAnchor="middle" fill={ink} fontSize="14">∩ = 0</text>}
  </svg></div>;
}

function IntersectionFigureCard({ result, eyebrow, title, explanation, a, b, common, canCompare, emptyMessage, caption, scopeLabel, partial = false }: {
  result: NetworkPharmacologyResult; eyebrow: string; title: string; explanation: string;
  a: number; b: number; common: number; canCompare: boolean; emptyMessage: string;
  caption: string; scopeLabel: string; partial?: boolean;
}) {
  const s = result.summary;
  return <section className="figure-card target-intersection" aria-label={title}>
    <div className="figure-heading"><span>{eyebrow}</span><div><h2>{title}</h2><p>{explanation}</p></div></div>
    <div className="target-intersection-legend">
      <div className="target-intersection-herb"><span>中药侧</span><strong>{s.herb}</strong></div>
      <div className="target-intersection-disease"><span>疾病侧</span><strong>{s.disease}</strong></div>
    </div>
    {!canCompare ? <div className="target-intersection-empty"><strong>暂不能绘制交集</strong><p>{emptyMessage}</p><p>两侧可比较集合不足时，零值不代表没有生物学关联。</p></div> : <>
      <IntersectionDiagram a={a} b={b} common={common} scopeLabel={scopeLabel} />
      <p className="target-intersection-caption">{partial ? "当前返回子集" : "当前比较集合"}，圆面积不代表数量。中药侧 {number(a)} 个，疾病侧 {number(b)} 个，交集 {number(common)} 个。{caption}</p>
    </>}
  </section>;
}

function StandardTargetIntersectionFigure({ result }: { result: NetworkPharmacologyResult }) {
  const identity = result.targetIdentity!;
  const a = identity.herb!.genes, b = identity.disease!.genes;
  const common = identity.verifiedGeneIntersectionCount ?? 0;
  const valid = [a, b, common].every(value => Number.isSafeInteger(value) && value >= 0) && common <= Math.min(a, b);
  const pending = (identity.herb!.pendingRecords ?? 0) + (identity.disease!.pendingRecords ?? 0);
  const emptyMessage = !valid
    ? "标准基因集合计数不一致，请重新查询并核对映射版本。"
    : `当前可核验基因集合为中药侧 ${number(a)}、疾病侧 ${number(b)}；待核验实体共 ${number(pending)} 个，未计入交集。`;
  const candidateOverlap = identity.pendingGeneOverlapCount ?? 0;
  const caption = common > 0
    ? `身份确证基因交集 ${number(common)}；另有 ${number(candidateOverlap)} 个尚未确证的候选基因重叠，潜在合计 ${number(common + candidateOverlap)}。蛋白主键交集 ${number(identity.verifiedProteinIntersectionCount ?? 0)}。${pending ? `两侧仍有 ${number(pending)} 条靶点记录待核验。` : ""}`
    : `已确证基因集合中未发现共同主键。${candidateOverlap ? `另有 ${number(candidateOverlap)} 个尚未确证的候选基因重叠。` : ""}${pending ? `两侧仍有 ${number(pending)} 条靶点记录待核验，不能据此判断无关联。` : ""}`;
  return <IntersectionFigureCard result={result} eyebrow="标准基因编号" title="可核验标准基因交集"
    explanation="先按审核后的直接疾病关联确定疾病侧集合，再按人类标准基因主键比较；药材上下文关系与未核验实体不计入交集。蛋白编号交集在上方单独统计。"
    a={a} b={b} common={common} canCompare={valid && a > 0 && b > 0}
    emptyMessage={emptyMessage} caption={caption} scopeLabel="已核验标准基因集合" />;
}

function OriginalTargetIntersectionFigure({ result }: { result: NetworkPharmacologyResult }) {
  const s = result.summary, state = intersectionState(result);
  const comparison = result.targetIdentity?.entityIdComparison;
  const complete = comparison?.scope === "reviewed_direct_disease_targets_v1";
  const a = complete ? comparison.herbTargetCount : s.herbTargetCount;
  const b = complete ? comparison.diseaseTargetCount : s.diseaseTargetCount;
  const common = complete ? comparison.intersectionCount : s.strictIntersectionCount;
  const valid = [a, b, common].every(value => Number.isSafeInteger(value) && value >= 0) && common <= Math.min(a, b);
  const hasMatchedInputs = Boolean(s.matchedDiseases?.length && (s.matchedHerbs?.length || s.matchedFormulas?.length));
  const partial = complete
    ? Boolean(s.unmatchedHerbs?.length || s.unresolvedFormulas?.length || s.unmatchedDiseases?.length || s.diseaseResolution?.entitiesTruncated)
    : state.partial;
  const emptyMessage = !complete ? state.message : !valid ? "完整靶点集合计数不一致，请重新查询并核对来源版本。" :
    !hasMatchedInputs ? "中药或疾病名称尚未匹配，无法比较完整关系集。" :
    !a || !b ? `名称已匹配，但${!a && !b ? "两侧" : !a ? "中药侧" : "疾病侧"}没有有效靶点关系。` : state.message;
  return <IntersectionFigureCard result={result} eyebrow="原始实体 ID" title="来源实体主键交集"
    explanation={complete ? "比较药材侧完整靶点与通过疾病关联来源审核的直接疾病靶点；药材上下文关系和待审核汇总关系不进入交集。" : "仅比较当前返回的两侧原始实体 ID；同一标准靶点若来自不同实体记录，不会出现在此交集。"}
    a={a} b={b} common={common} canCompare={valid && a > 0 && b > 0 && (complete ? hasMatchedInputs : state.comparable)}
    emptyMessage={emptyMessage} caption={complete ? "已审核的完整分析集合；未纳入的来源候选仍保留在原始证据表。" : "此处统计的是当前返回结果中实体 ID 相同的记录。"}
    scopeLabel={complete ? "审核后疾病靶点集合中的原始实体 ID" : "当前返回结果中的原始实体 ID"} partial={partial} />;
}

export function TargetIntersectionFigure({ result }: { result: NetworkPharmacologyResult }) {
  const hasIdentity = Boolean(result.targetIdentity?.available && result.targetIdentity.herb && result.targetIdentity.disease);
  const hasCurrentEvidenceScope = result.targetIdentity?.diseaseTargetEvidence?.scope === "reviewed_direct_disease_targets_v1";
  return <>
    {hasIdentity && hasCurrentEvidenceScope && <StandardTargetIntersectionFigure result={result} />}
    {result.targetIdentity && <TargetIdentityResults result={result} />}
    {!result.targetIdentity && <OriginalTargetIntersectionFigure result={result} />}
  </>;
}
