import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { Activity, Bot, CheckCircle2, DatabaseZap, FlaskConical, Network, Play, RefreshCw, Search, XCircle } from "lucide-react";
import { type Session } from "../api/auth";
import { ApiError } from "../api/client";
import { getIntegrationStatus, testIntegration, type IntegrationResult, type IntegrationStatus, type IntegrationTarget } from "../api/integrations";

const checks: Array<{
  id: IntegrationTarget;
  title: string;
  description: string;
  icon: typeof Activity;
  consent?: "model" | "chembl";
  unavailable?: boolean;
}> = [
  { id: "qwen", title: "Qwen / 本机模型", description: "发送一条不含研究数据的短文本，验证当前配置的模型连接。", icon: Bot, consent: "model" },
  { id: "disease", title: "疾病证据检索", description: "使用 Pulmonary fibrosis 检查疾病目录与别名查询。", icon: Search },
  { id: "herb", title: "中药证据检索", description: "使用粳米检查本地中药—成分—靶点证据。", icon: DatabaseZap },
  { id: "component", title: "成分靶点检索", description: "使用 quercetin 检查本地成分证据查询。", icon: Activity },
  { id: "chembl", title: "ChEMBL 官方接口", description: "查询 quercetin；只发送测试词，不发送用户研究数据。", icon: FlaskConical, consent: "chembl" },
  { id: "intersection", title: "靶点交集", description: "计算本地目录中的中药与疾病候选交集，不保存分析任务。", icon: Network },
  { id: "compare", title: "成分比对", description: "比较页面内置的合成测试名称，不读取用户上传数据。", icon: CheckCircle2 },
];

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="integration-json">{JSON.stringify(value, null, 2)}</pre>;
}

function summarize(value: unknown) {
  if (!value || typeof value !== "object") return "暂无返回数据";
  const data = value as Record<string, unknown>;
  if (typeof data.candidateTargetCount === "number") return `候选靶点 ${data.candidateTargetCount} 个`;
  if (typeof data.totalCount === "number") return `返回 ${data.totalCount} 条记录`;
  if (typeof data.count === "number") return `匹配 ${data.count} 条记录`;
  if (Array.isArray(data.results)) return `返回 ${data.results.length} 条记录`;
  if (typeof data.matchRate === "number") return `匹配率 ${data.matchRate}%`;
  return "已返回结构化数据";
}

export function ApiIntegrationPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [results, setResults] = useState<Partial<Record<IntegrationTarget, IntegrationResult>>>({});
  const [activeTarget, setActiveTarget] = useState<IntegrationTarget>("disease");
  const [loading, setLoading] = useState<string>("");
  const [modelConsent, setModelConsent] = useState(false);
  const [chemblConsent, setChemblConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshStatus() {
    setLoading("status");
    setError(null);
    try {
      setStatus(await getIntegrationStatus());
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading("");
    }
  }

  useEffect(() => { void refreshStatus(); }, []);

  async function runTest(target: IntegrationTarget) {
    const check = checks.find((item) => item.id === target);
    if (!check || check.unavailable) return;
    setActiveTarget(target);
    setLoading(target);
    setError(null);
    try {
      const consent = check.consent === "model" ? modelConsent : check.consent === "chembl" ? chemblConsent : false;
      const response = await testIntegration(target, consent);
      setResults((current) => ({ ...current, [target]: response.result }));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      if (check.consent === "model") setModelConsent(false);
      if (check.consent === "chembl") setChemblConsent(false);
      setLoading("");
    }
  }

  async function runLocalChecks() {
    for (const check of checks.filter((item) => !item.consent && !item.unavailable)) {
      await runTest(check.id);
    }
  }

  if (!user.isSuperuser) return <><section className="panel empty-state"><strong>仅平台管理员可查看此页面</strong><Link className="btn btn-secondary" to="/dashboard">返回研究总览</Link></section></>;

  const currentResult = results[activeTarget];

  return <>

      <div className="page-heading"><div className="page-heading-copy"><h1 className="page-title">API 接入监测</h1><p className="page-description">查看数据库与服务连接状态，检查本地检索及已配置的外部接口。</p></div><span className="status-badge status-success">管理员功能</span></div>
      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      <section className="panel integration-overview">
        <div><h2 className="section-title-sm">服务总览</h2><p className="section-help">数据库、数据源目录及模型服务的配置状态。</p></div>
        <div className="source-record-actions"><button className="btn btn-secondary" onClick={() => void refreshStatus()} disabled={Boolean(loading)}><RefreshCw size={15} />{loading === "status" ? "正在刷新…" : "刷新状态"}</button><button className="btn btn-primary" onClick={() => void runLocalChecks()} disabled={Boolean(loading)}><Play size={15} />一键测试本地接口</button></div>
        {status ? <><div className="integration-status-grid">{Object.entries(status.services).map(([key, service]) => <article className="integration-status-card" key={key}><span className={`status-badge ${service.ok ? "status-success" : "status-warning"}`}>{key.startsWith("qwen") ? service.ok ? "已配置" : "未配置" : service.ok ? "正常" : "不可用"}</span><strong>{key === "health" ? "Django 与数据库" : key === "sources" ? "本地数据源目录" : key === "qwenStatus" ? "本机模型配置" : "已配置的模型名称"}</strong><small>{service.url}</small></article>)}</div><details><summary>查看状态明细 · {new Date(status.checkedAt).toLocaleString("zh-CN")}</summary><JsonBlock value={status} /></details></> : <p className="section-help">正在读取服务状态…</p>}
      </section>
      <section className="panel integration-tests" aria-labelledby="integration-test-heading">
        <div className="integration-heading"><div><h2 id="integration-test-heading" className="section-title-sm">接口测试</h2><p className="section-help">每项使用固定的演示查询；靶点交集计算不会写入任务表。</p></div><span className="status-badge status-pending">已通过 {Object.values(results).filter((item) => item?.ok).length}/{checks.filter((item) => !item.unavailable).length} 项可执行测试</span></div>
        <div className="integration-grid">{checks.map((check) => {
          const Icon = check.icon;
          const result = results[check.id];
          return <article className="integration-card" key={check.id}>
            <div className="integration-card-title"><span className="integration-icon"><Icon size={17} /></span><div><h3>{check.title}</h3><p>{check.description}</p></div></div>
            {check.consent === "model" && <label className="integration-consent"><input type="checkbox" checked={modelConsent} onChange={(event) => setModelConsent(event.target.checked)} />同意向配置的本机/内网模型发送一条合成测试文本。</label>}
            {check.consent === "chembl" && <label className="integration-consent"><input type="checkbox" checked={chemblConsent} onChange={(event) => setChemblConsent(event.target.checked)} />同意将测试词 quercetin 发送到 ChEMBL 官方服务。</label>}
            {check.unavailable ? <span className="integration-pending">此接口暂不可用</span> : <button className="btn btn-secondary" type="button" disabled={Boolean(loading) || (check.consent === "model" && !modelConsent) || (check.consent === "chembl" && !chemblConsent)} onClick={() => void runTest(check.id)}>{loading === check.id ? <RefreshCw size={15} className="spin" /> : <Play size={15} />}{loading === check.id ? "测试中…" : "运行测试"}</button>}
            {result && <div className="integration-result"><strong className={result.ok ? "integration-pass" : "integration-fail"}>{result.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}{result.ok ? "通过" : `失败 · ${result.status}`} · {result.elapsedMs} ms</strong><span>{result.error || (result.data ? summarize(result.data) : "检查完成")}</span><small>{result.url}</small><details><summary>查看返回数据</summary><JsonBlock value={result} /></details></div>}
          </article>;
        })}</div>
      </section>
      {currentResult && <section className="panel integration-detail"><h2 className="section-title-sm">当前结果：{checks.find((item) => item.id === activeTarget)?.title}</h2><JsonBlock value={currentResult} /></section>}

  </>;
}
