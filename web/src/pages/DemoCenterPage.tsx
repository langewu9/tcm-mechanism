import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Download, FlaskConical } from "lucide-react";
import { DEMO_WARNING, demoCase, demoModules, demoNetwork, demoProteinRows, evaluateDemo, type DemoModuleKey } from "../demo/catalog";
import { KnowledgeNetworkGraph } from "../components/KnowledgeNetworkGraph";
import { RDemoGallery } from "../components/RDemoGallery";

function downloadKey(key: string, value: unknown) {
  const blob = new Blob([JSON.stringify({ schemaVersion: "delivery-demo-1", synthetic: true, disclaimer: DEMO_WARNING, moduleKey: key, data: value }, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `synthetic-demo-${key}.json`;
  anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function Scenario({ moduleKey }: { moduleKey: DemoModuleKey }) {
  const module = demoModules.find(item => item.key === moduleKey)!;
  const [stage, setStage] = useState(0);
  const [query, setQuery] = useState("演示");
  const [fc, setFc] = useState(1);
  const [fdr, setFdr] = useState(0.05);
  const [review, setReview] = useState("pending");
  const [role, setRole] = useState("研究者");
  const result = evaluateDemo(moduleKey, query, fc, fdr);
  const selectedRows = demoProteinRows.filter(row => Math.abs(row.log2FoldChange) >= fc && row.fdr <= fdr);
  return <section className="panel source-record" aria-label={`${module.label} 演示场景`}>
    <h2 className="section-title-sm">{module.label} · 独立演示</h2>
    <p className="notice-warning">{DEMO_WARNING}。所有步骤只在当前页面运行，刷新后重置，不提交业务接口。</p>
    <ol className="demo-steps">{module.stages.map((label, index) => <li key={label} aria-current={stage === index ? "step" : undefined}><strong>{index+1}. {label}</strong>{stage === index && <span>当前步骤</span>}</li>)}</ol>
    <div className="source-record-actions"><button className="btn btn-primary" type="button" disabled={stage === 2} onClick={() => setStage(stage+1)}>下一步演示</button><button className="btn btn-secondary" type="button" onClick={() => { setStage(0); setQuery("演示"); setFc(1); setFdr(0.05); setReview("pending"); setRole("研究者"); }}>重置演示</button><button className="btn btn-secondary" type="button" onClick={() => downloadKey(module.key, { input: module.input, output: result, stage, review: module.key === "cases" ? review : undefined })}><Download size={16} />下载本模块 key</button></div>
    {moduleKey === "overview" && <div className="grid gap-3 sm:grid-cols-3">{[["演示数据集", 1], ["教学医案", 1], ["合成节点", 6]].map(([name, count]) => <div className="proteomics-metric" key={name}><span>{name}</span><strong>{count}</strong></div>)}</div>}
    {moduleKey === "research" && <label className="form-label">演示目录过滤<input className="field" value={query} onChange={event => setQuery(event.target.value)} placeholder="输入演示或 DEMO_GENE" /></label>}
    {moduleKey === "proteomics" && <><div className="grid gap-3 sm:grid-cols-2"><label className="form-label">演示 |log2FC| 阈值<input className="field" type="number" min={0} max={5} step={0.1} value={fc} onChange={event => setFc(Math.max(0, Math.min(5, Number(event.target.value) || 0)))} /></label><label className="form-label">演示 FDR 阈值<input className="field" type="number" min={0} max={1} step={0.01} value={fdr} onChange={event => setFdr(Math.max(0, Math.min(1, Number(event.target.value) || 0)))} /></label></div><p role="status">20 行合成输入，当前筛选 {selectedRows.length} 行；下方 R 图片使用固定 key，不随本页阈值重算。</p><RDemoGallery chartKey="proteomics_volcano" /></>}
    {moduleKey === "datasets" && <><p>演示输入包含 20 行，字段为 label、log2FoldChange、pValue、fdr。下载 key 不等于上传或入库。</p><div className="table-scroll"><table className="data-table"><thead><tr><th>合成标识</th><th>log2FC</th><th>FDR</th></tr></thead><tbody>{demoProteinRows.slice(0, 5).map(row => <tr key={row.label}><td>{row.label}</td><td>{row.log2FoldChange.toFixed(2)}</td><td>{row.fdr}</td></tr>)}</tbody></table></div></>}
    {moduleKey === "cases" && <><p>{demoCase.text}</p><ul>{demoCase.observations.map(item => <li key={item}>教学观察：{item}</li>)}</ul><p>{demoCase.warning}</p><label className="form-label">人工审核演示<select className="field" value={review} onChange={event => setReview(event.target.value)}><option value="pending">待确认</option><option value="accepted">确认教学候选（仅内存）</option><option value="rejected">驳回教学候选（仅内存）</option></select></label><p role="status">审核演示状态：{review}；未保存真实候选。</p></>}
    {moduleKey === "network" && <><p>模拟中药侧：DEMO:G1、DEMO:G2；疾病侧：DEMO:G1、DEMO:G3；唯一交集：DEMO:G1。</p><KnowledgeNetworkGraph network={demoNetwork} synthetic /><RDemoGallery chartKey="evidence_network" /><RDemoGallery chartKey="ppi_network" /></>}
    {moduleKey === "analysis" && <><p>教学规则链路：虚构症状 → 演示证候 → 演示方剂。下图展示另一个合成药理关系样例，两者不能作为临床证据相连。</p><KnowledgeNetworkGraph network={demoNetwork} synthetic /></>}
    {moduleKey === "sources" && <><p role="status">{stage === 0 ? "模拟预览：新增 2 项、变更 1 项、歧义 1 项。" : stage === 1 ? "模拟复核：DEMO_A:001 对应 DEMO:G1；DEMO_B:002 歧义，不自动合并。" : "模拟确认：仅复核映射可应用，歧义保持隔离；实际数据库没有发生变更。"}</p><p>主键统一记录稳定实体 ID、来源命名空间、来源 ID 与版本，不能仅凭同名自动合并。</p></>}
    {moduleKey === "accounts" && <><label className="form-label">模拟角色<select className="field" value={role} onChange={event => setRole(event.target.value)}><option>研究者</option><option>管理员</option></select></label><p role="status">{role === "研究者" ? "权限说明：只能操作自己有权访问的资料。" : "权限说明：真实管理页面仍需已授权管理员身份。"}此选择不登录、不修改权限、不创建账号。</p><Link className="btn btn-secondary" to="/login">真实登录页面</Link></>}
    <details open={stage === 2}><summary>查看当前演示结果与 key 字段</summary><pre className="integration-json">{JSON.stringify(result, null, 2)}</pre></details>
    <p className="notice-info"><strong>真实功能的交付前提：</strong>{module.gap}</p>
    <Link className="btn btn-secondary" to={module.route}>进入真实{module.label} <ArrowRight size={15} /></Link>
  </section>;
}
export function DemoCenterPage() {
  const [params, setParams] = useSearchParams();
  const selected = demoModules.find(module => module.key === params.get("module")) ?? demoModules[0];
  return <main className="site-home demo-center" id="main-content">
    <a className="skip-link" href="#demo-content">跳到演示内容</a>
    <header className="site-nav"><Link className="site-brand" to="/">远志 AI Scientist</Link><nav aria-label="演示导航"><Link to="/">返回首页</Link><Link to="/dashboard">真实工作区</Link><button type="button" className="btn btn-secondary" onClick={() => downloadKey("all-modules", demoModules)}>下载全部模块 key</button></nav></header>
    <div className="demo-content" id="demo-content"><div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Delivery demo workspace</p><h1 className="page-title">交付演示中心</h1><p className="page-description">11 个模块场景、14 种 R 图表；本页仅展示合成数据，不依赖业务数据库或模型服务。</p></div><FlaskConical size={28} /></div>
      <p className="notice-warning">演示完成不等于真实业务验收通过。数据源、模型和生产部署问题在各模块下方单独列明。</p>
      <nav className="demo-module-grid" aria-label="模块演示选择">{demoModules.map(module => <button type="button" className={`btn ${module.key === selected.key ? "btn-primary" : "btn-secondary"}`} key={module.key} aria-pressed={module.key === selected.key} onClick={() => setParams({ module: module.key })}>{module.label}</button>)}</nav>
      <Scenario key={selected.key} moduleKey={selected.key} />
      <RDemoGallery defaultOpen />
      <section className="panel source-record" aria-label="交付状态清单"><h2 className="section-title-sm">模块交付问题清单</h2><p>以下是实现/配置前提，不是实时健康检查。完整上线验收需要正式数据及生产环境测试。</p><div className="table-scroll"><table className="data-table"><thead><tr><th>模块</th><th>演示</th><th>正式交付前提</th></tr></thead><tbody>{demoModules.map(module => <tr key={module.key}><td>{module.label}</td><td>合成 key + 三步场景</td><td>{module.gap}</td></tr>)}</tbody></table></div></section>
    </div>
  </main>;
}
