import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, BookOpenCheck, Database, Download, FileSearch, Network } from "lucide-react";
import { getHomeStats } from "../api/catalog";
import { HeroScroll } from "../components/HeroScroll";
import { HomeMetric } from "../components/HomeMetric";
type Metric = { label: string; value: number | null; kind: "herb" | "compound" | "target" | "pathway" };
const workflow = [
  { index: "01", title: "确认研究者身份", text: "研究记录关联登录账号，保留数据责任人。" },
  { index: "02", title: "整理知识目录", text: "按规范实体与来源版本组织可追溯数据。" },
  { index: "03", title: "创建研究记录", text: "数据集、医案与任务接口已建立个人访问边界。" },
  { index: "04", title: "逐步接入分析", text: "蛋白组学首版、证据约束的科研助手和医案分析已接通，更多链路仍在迁移。" },
  { index: "05", title: "补齐结果导出", text: "表格、图表和报告导出会在业务模块接通后加入。" },
];
export function HomePage() {
  const [metrics, setMetrics] = useState<Metric[]>([
    { label: "中药实体", value: null, kind: "herb" }, { label: "活性成分", value: null, kind: "compound" },
    { label: "作用靶点", value: null, kind: "target" }, { label: "生物通路", value: null, kind: "pathway" },
  ]);
  useEffect(() => {
    let active = true;
    getHomeStats().then(({ counts }) => {
      if (!active) return;
      setMetrics([
        { label: "中药实体", value: counts.herbs, kind: "herb" }, { label: "活性成分", value: counts.compounds, kind: "compound" },
        { label: "作用靶点", value: counts.targets, kind: "target" }, { label: "生物通路", value: counts.pathways, kind: "pathway" },
      ]);
    }).catch(() => { /* Keep unavailable counts visibly distinct from a verified zero. */ });
    return () => { active = false; };
  }, []);
  return <main className="site-home">
    <header className="site-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页"><img src="/images/yuanzhi-mark.png" alt="" width={48} height={48} className="brand-mark" /><span><strong>远志 AI Scientist</strong><small>中医药理研究平台</small></span></Link>
      <nav aria-label="首页导航"><a href="#workflow">研究流程</a><a href="#capabilities">核心能力</a><Link to="/research">知识检索</Link><Link to="/dashboard">研究总览</Link><Link to="/login">登录</Link><Link to="/cases" className="nav-primary">开始使用 <ArrowRight size={15} /></Link></nav>
    </header>
    <section className="product-hero">
      <div className="product-hero-paper" aria-hidden="true" /><div className="product-hero-watermark" aria-hidden="true"><span>远</span><span>志</span></div>
      <div className="product-hero-content"><p className="hero-kicker">Traditional medicine, computational evidence</p><h1>远志 AI Scientist</h1>
        <p className="hero-lead">平台从知识目录、来源追溯和研究者工作区开始建设；文件上传与蛋白组学首版已接通，其余分析能力逐步迁入。</p>
        <div className="hero-actions"><Link to="/cases" className="hero-primary">进入研究工作台 <ArrowRight size={18} /></Link><a href="/api/docs/" className="hero-secondary"><FileSearch size={17} /> 查看平台接口</a></div>
      </div>
      <HeroScroll /><div className="hero-metrics" aria-label="知识库规模">{metrics.map((item) => <HomeMetric key={item.label} {...item} />)}</div>
    </section>
    <section id="workflow" className="home-band home-workflow"><div className="home-section-heading"><p>Evidence workflow</p><h2>从研究问题到可复核证据</h2><span>目前已完成身份、数据结构和 API 的基础搭建；研究分析流程仍在迁移中。</span></div><div className="workflow-grid">{workflow.map((item) => <article key={item.index}><span>{item.index}</span><h3>{item.title}</h3><p>{item.text}</p></article>)}</div></section>
    <section id="capabilities" className="home-band home-capabilities"><div className="capability-intro"><p>Research infrastructure</p><h2>围绕真实科研任务设计</h2><span>先把模块边界与数据归属搭稳，再按来源代码补齐科研工作流。</span></div>
      <div className="capability-list"><article><Database size={22} /><div><h3>统一数据底座</h3><p>已建立带来源及版本字段的结构化数据模型；Reactome 目录支持管理员预览和确认同步。</p></div></article><article><Network size={22} /><div><h3>查询驱动图谱</h3><p>研究者可按名称检索已导入实体并查看关系来源版本；网络药理结果已有可筛选、缩放并查看来源的交互图，R 交互图仍待接入。</p></div></article><article><BookOpenCheck size={22} /><div><h3>证据约束的科研助手</h3><p>研究者可选本地实体证据，默认只做目录检索；明确同意后才将问题和证据发送到配置的本机/内网模型。</p></div></article><article><Download size={22} /><div><h3>研究材料导出</h3><p>数据集和蛋白组学结果可导出；可视化报告会在对应业务模块实现后补齐。</p></div></article></div>
    </section>
    <section className="home-cta"><div><p>Ready for research</p><h2>用真实数据开始下一次分析</h2></div><Link to="/register">创建研究账号 <ArrowRight size={17} /></Link></section>
    <footer className="site-footer"><span>远志 AI Scientist</span><span>中医药理知识图谱与网络药理学分析平台</span></footer>
  </main>;
}
