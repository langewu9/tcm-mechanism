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
  return <div className="target-intersection-notices" role="status">
    {s.unmatchedDiseases?.length ? <p className="notice-warning">未匹配疾病：{s.unmatchedDiseases.join("、")}。请确认规范名称；下方 0 仅表示本次未取得数据。</p> : null}
    {s.unmatchedHerbs?.length ? <p className="notice-warning">未匹配中药或方剂：{s.unmatchedHerbs.join("、")}。其证据未纳入，本次不是完整处方的交集。</p> : null}
    {s.unresolvedFormulas?.length ? <p className="notice-warning">方剂 {s.unresolvedFormulas.join("、")} 已匹配，但缺少可追溯组成关系，无法完整展开。</p> : null}
    {s.matchedDiseases?.length ? <p className="section-help">{resolution?.status === "alias" ? "疾病名称对应" : "已匹配疾病"}：{s.disease} → {[...new Set(s.matchedDiseases)].join("、")}。{resolution?.aliasVersion ? `名称规则 ${resolution.aliasVersion}；` : ""}不同来源实体及原始证据保持独立。</p> : null}
    {resolution?.candidates?.length ? <div className="target-intersection-candidates"><p>以下是相关检索候选，不一定与原疾病等价；请选择确切名称后重新检索：</p>{resolution.candidates.map(item =>
      onDiseaseSelect ? <button className="btn btn-secondary" type="button" key={item.label} onClick={() => onDiseaseSelect(item.label)}>使用名称：{item.label}<small>{item.sourceSlugs.join(" / ")}</small></button> : <p key={item.label}>{item.label} · {item.sourceSlugs.join(" / ")}</p>
    )}</div> : null}
    <p className={state.comparable ? "section-help" : "notice-warning"}>{state.message}</p>
    {state.partial && <p className="notice-warning">{result.targetIdentity?.coverage?.scope === "all_active_relations_for_matched_entities" ? "原始证据表与网络图按返回子集展示；标准主键比较另按已匹配实体的全部有效靶点关系计算。未匹配名称不参与统计。" : "查询名称、实体匹配或源关系读取不完整；图和计数只描述当前返回子集，不是全库总量。请缩小查询范围或补齐来源与标识映射。"}</p>}
  </div>;
}

function OriginalTargetIntersectionFigure({ result }: { result: NetworkPharmacologyResult }) {
  const s = result.summary, state = intersectionState(result);
  const a = s.herbTargetCount, b = s.diseaseTargetCount, common = s.strictIntersectionCount;
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
  return <section className="figure-card target-intersection" aria-label="中药与疾病靶点集合">
    <div className="figure-heading"><span>原始记录</span><div><h2>中药靶点 ∩ 疾病靶点</h2><p>此图仅比较原始实体标识；标准靶点核验在上方分别展示。</p></div></div>
    <div className="target-intersection-legend">
      <div className="target-intersection-herb"><span>中药侧</span><strong>{s.herb}</strong></div>
      <div className="target-intersection-disease"><span>疾病侧</span><strong>{s.disease}</strong></div>
    </div>
    {!state.comparable ? <div className="target-intersection-empty"><strong>{state.badge}</strong><p>{state.message}</p><p>数据不完整时不绘制重叠圆，也不据零值作交集结论。</p></div> : <>
      <div className="target-intersection-canvas"><svg className="target-intersection-svg" viewBox="0 0 640 360" role="img" aria-label={`靶点集合${state.partial ? "当前返回子集" : "示意"}：中药侧 ${number(a)}，疾病侧 ${number(b)}，严格交集 ${number(common)}。圆面积不代表数量。`}>
        <title>{`中药侧 ${number(a)}；疾病侧 ${number(b)}；严格交集 ${number(common)}。${mode === "disjoint" ? "两个集合互不重叠。" : ""}`}</title>
        {circles.map((circle, i) => <circle key={i} cx={circle.x} cy="180" r={circle.r} fill={circle.color} fillOpacity="0.12" stroke={circle.color} strokeWidth="2.5" strokeDasharray={mode === "identical" && i === 1 ? "8 5" : undefined} />)}
        {zones.map(zone => <g key={zone.label}><text x={zone.x} y="165" textAnchor="middle" fill={zone.color} fontSize="14">{zone.label}</text><text x={zone.x} y="205" textAnchor="middle" fill={ink} fontSize={number(zone.value).length > 5 ? 24 : 30}>{number(zone.value)}</text></g>)}
        {mode === "disjoint" && <text x="320" y="184" textAnchor="middle" fill={ink} fontSize="14">∩ = 0</text>}
      </svg></div>
      <p className="target-intersection-caption">{state.partial ? "当前返回子集" : "已返回靶点集合"}的示意图，圆面积不代表数量。中药侧 {number(a)} 个，疾病侧 {number(b)} 个，严格交集 {number(common)} 个。</p>
    </>}
  </section>;
}

export function TargetIntersectionFigure({ result }: { result: NetworkPharmacologyResult }) {
  return <>{result.targetIdentity && <TargetIdentityResults result={result} />}{result.targetIdentity?.available ? <details className="raw-details"><summary>查看原始实体记录交集</summary><OriginalTargetIntersectionFigure result={result} /></details> : <OriginalTargetIntersectionFigure result={result} />}</>;
}
