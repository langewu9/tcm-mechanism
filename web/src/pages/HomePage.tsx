import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpenCheck, ChartNoAxesCombined, Database, FileSearch, FlaskConical, Menu, Network, X } from "lucide-react";
import { getHomeStats } from "../api/catalog";
import { HomeMetric } from "../components/HomeMetric";
import { HeroScroll } from "../components/HeroScroll";
import { getSession } from "../api/auth";
import "../styles/homepage.css";
import "../styles/homepage-calligraphy.css";

type Metric = { label: string; value: number | null; kind: "herb" | "compound" | "target" | "pathway" };
const heroTitle = "让中医药研究有据可循。";
const modules = [
  { number: "01", icon: FileSearch, title: "中药与靶点检索", text: "检索中药成分、疾病靶点及其来源记录。", to: "/research", label: "开始检索" },
  { number: "02", icon: FlaskConical, title: "差异蛋白组学", text: "上传蛋白组学数据，进行差异筛选、富集分析和绘图。", to: "/proteomics", label: "进入分析" },
  { number: "03", icon: BookOpenCheck, title: "医案与研究记录", text: "检索参考医案，查阅症状、证型与方药，管理个人研究记录。", to: "/cases", label: "进入医案库" },
];
const workflow = [
  { title: "整理研究输入", text: "选择知识目录、上传数据集，或建立医案记录。" },
  { title: "连接来源证据", text: "核对实体映射和来源版本，保留缺失与歧义。" },
  { title: "分析与可视化", text: "查看网络、差异与富集结果，按图表子页探索。" },
  { title: "复核并导出", text: "导出图表与证据表，区分关联线索与研究结论。" },
];

export function HomePage() {
  const [authenticated, setAuthenticated] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [statsState, setStatsState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [metrics, setMetrics] = useState<Metric[]>([
    { label: "中药实体", value: null, kind: "herb" }, { label: "成分实体", value: null, kind: "compound" },
    { label: "靶点实体", value: null, kind: "target" }, { label: "生物通路", value: null, kind: "pathway" },
  ]);
  useEffect(() => {
    let active = true;
    getSession().then(session => { if (active) setAuthenticated(session.authenticated); }).catch(() => {});
    getHomeStats().then(({ counts }) => {
      if (!active) return;
      setMetrics([
        { label: "中药实体", value: counts.herbs, kind: "herb" }, { label: "成分实体", value: counts.compounds, kind: "compound" },
        { label: "靶点实体", value: counts.targets, kind: "target" }, { label: "生物通路", value: counts.pathways, kind: "pathway" },
      ]);
      setStatsState("ready");
    }).catch(() => { if (active) setStatsState("unavailable"); });
    return () => { active = false; };
  }, []);
  return <main className="site-home yz-home">
    <a className="yz-skip" href="#home-content">跳到主页内容</a>
    <div className="yz-first-screen">
    <header className="yz-header">
      <div className="yz-container yz-header-inner">
        <Link to="/" className="yz-brand" aria-label="远志 AI Scientist 首页">
          <img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} />
          <span><strong>远志 <span>AI Scientist</span></strong><small>中医药理研究平台</small></span>
        </Link>
        <button type="button" className="yz-menu" aria-label={menuOpen ? "收起导航" : "展开导航"} aria-expanded={menuOpen} aria-controls="home-navigation" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={22} /> : <Menu size={22} />}</button>
        <nav id="home-navigation" className={menuOpen ? "yz-nav is-open" : "yz-nav"} aria-label="首页导航" onClick={() => setMenuOpen(false)}>
          <a href="#capabilities">研究工具</a><a href="#workflow">使用流程</a><Link to="/demo">演示图库</Link>
          <Link to={authenticated ? "/dashboard" : "/login"} className="yz-login">{authenticated ? "研究工作区" : "登录"}</Link>
          <Link to={authenticated ? "/research" : "/register"} className="yz-button yz-button-dark">{authenticated ? "开始研究" : "创建账号"}<ArrowUpRight size={16} /></Link>
        </nav>
      </div>
    </header>
    <section id="home-content" className="yz-container yz-hero" aria-labelledby="home-title">
      <div className="yz-hero-copy">

        <h1 id="home-title" aria-label={heroTitle}><span aria-hidden="true">{Array.from(heroTitle).map((character, index) => <span key={index} className={`yz-title-char${character === "。" ? " yz-title-dot" : ""}`} style={{ animationDelay: `${160 + index * 85}ms` }}>{character}</span>)}</span></h1>
        <p className="yz-lead">中药、成分与靶点检索，蛋白组学分析及医案管理。</p>
        <div className="yz-actions"><Link to="/research" className="yz-button yz-button-red">探索中药与靶点 <ArrowRight size={18} /></Link><Link to="/demo" className="yz-text-link">先看图表演示 <ArrowUpRight size={17} /></Link></div>
        <a href="#capabilities" className="yz-explore">探索研究工具 <ArrowDown size={15} /></a>
      </div>
      <div className="yz-hero-visual">
        <div className="yz-visual-panel">
        <div className="yz-scroll-view">
          <HeroScroll />
        </div>
        </div>
      </div>
    </section>
    <section className="yz-container yz-data" aria-labelledby="knowledge-title">
      <div className="yz-data-label"><Database size={20} /><div><h2 id="knowledge-title">知识目录</h2><p role="status">{statsState === "ready" ? "已启用的数据目录" : statsState === "loading" ? "正在读取目录统计…" : "统计暂不可用，稍后刷新重试"}</p></div></div>
      <div className="yz-metrics" aria-label="知识库规模">{metrics.map(item => <HomeMetric key={item.kind} {...item} />)}</div>
    </section>
    <section id="capabilities" className="yz-container yz-tools" aria-labelledby="tools-title">
      <div className="yz-section-heading"><div><h2 id="tools-title">研究工具</h2></div></div>
      <div className="yz-tool-grid">{modules.map(item => <Link to={item.to} key={item.number} className="yz-tool"><div className="yz-tool-top"><item.icon size={25} strokeWidth={1.5} /><span>{item.number}</span></div><h3>{item.title}</h3><p className="yz-tool-description">{item.text}</p><div className="yz-tool-link">{item.label}<ArrowUpRight size={18} /></div></Link>)}</div>
      <div className="yz-quicklinks"><span>继续探索</span><Link to="/datasets"><Database size={16} />数据库<ArrowUpRight size={13} /></Link><Link to="/network-pharmacology"><Network size={16} />网络药理分析<ArrowUpRight size={13} /></Link><Link to="/assistant"><FileSearch size={16} />证据检索助手<ArrowUpRight size={13} /></Link><Link to="/dashboard"><ChartNoAxesCombined size={16} />研究总览<ArrowUpRight size={13} /></Link></div>
    </section>
    </div>
    <section id="workflow" className="yz-workflow" aria-labelledby="workflow-title"><div className="yz-container">
      <div className="yz-section-heading"><div><h2 id="workflow-title">使用流程</h2></div><Link to="/demo" className="yz-text-link">查看演示图库 <ArrowUpRight size={17} /></Link></div>
      <ol className="yz-steps">{workflow.map((item, index) => <li key={item.title}><span>0{index + 1}</span><h3>{item.title}</h3><p>{item.text}</p></li>)}</ol>
    </div></section>
    <footer className="yz-container yz-footer"><div><strong>远志 AI Scientist</strong></div><div><Link to="/demo">演示图库</Link><a href="/api/docs/">平台 API <ArrowUpRight size={13} /></a><Link to={authenticated ? "/dashboard" : "/login"}>进入工作区 <ArrowRight size={14} /></Link></div></footer>
  </main>;
}
