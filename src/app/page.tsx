import Image from "next/image";
import Link from "next/link";
import {
  ArrowRight,
  BookOpenCheck,
  Database,
  Download,
  FileSearch,
  Network,
} from "lucide-react";
import { prisma } from "@/lib/prisma";
import { HeroScroll } from "@/components/HeroScroll";
import { HomeMetric } from "@/components/HomeMetric";

export const runtime = "nodejs";

export default async function HomePage() {
  const [herbs, compounds, targets, pathways] = await Promise.all([
    prisma.herb.count().catch(() => 0),
    prisma.compound.count().catch(() => 0),
    prisma.target.count().catch(() => 0),
    prisma.pathway.count().catch(() => 0)
  ]);

  const metrics = [
    { label: "中药实体", value: herbs, kind: "herb" as const },
    { label: "活性成分", value: compounds, kind: "compound" as const },
    { label: "作用靶点", value: targets, kind: "target" as const },
    { label: "生物通路", value: pathways, kind: "pathway" as const }
  ];

  const workflow = [
    { index: "01", title: "输入研究问题", text: "从疾病、中药、方剂或医案开始。" },
    { index: "02", title: "检索真实证据", text: "联合本地中医药数据库与 ChEMBL。" },
    { index: "03", title: "构建作用链路", text: "组织成分、靶点与通路关联。" },
    { index: "04", title: "生成研究假设", text: "由 BianCang/Qwen 辅助解释证据。" },
    { index: "05", title: "导出研究材料", text: "下载表格、图表和分析报告。" }
  ];

  return (
    <main className="site-home">
      <header className="site-nav">
        <Link href="/" className="site-brand" aria-label="远志 AI Scientist 首页">
          <Image src="/images/yuanzhi-mark.png" alt="" width={48} height={48} className="brand-mark" priority />
          <span><strong>远志 AI Scientist</strong><small>中医药理研究平台</small></span>
        </Link>
        <nav aria-label="首页导航">
          <a href="#workflow">研究流程</a>
          <a href="#capabilities">核心能力</a>
          <Link href="/login">登录</Link>
          <Link href="/register" className="nav-primary">开始使用 <ArrowRight size={15} /></Link>
        </nav>
      </header>

      <section className="product-hero">
        <div className="product-hero-paper" aria-hidden="true" />
        <div className="product-hero-watermark" aria-hidden="true">
          <span>远</span>
          <span>志</span>
        </div>
        <div className="product-hero-content">
          <p className="hero-kicker">Traditional medicine, computational evidence</p>
          <h1>远志 AI Scientist</h1>
          <p className="hero-lead">把医案、方药、成分、靶点与通路组织成可查询、可验证、可导出的网络药理学证据链。</p>
          <div className="hero-actions">
            <Link href="/login" className="hero-primary">进入研究工作台 <ArrowRight size={18} /></Link>
            <Link href="/research" className="hero-secondary"><FileSearch size={17} /> 查看药理检索</Link>
          </div>
        </div>
        <HeroScroll />
        <div className="hero-metrics" aria-label="知识库规模">
          {metrics.map((item) => <HomeMetric key={item.label} {...item} />)}
        </div>
      </section>

      <section id="workflow" className="home-band home-workflow">
        <div className="home-section-heading">
          <p>Evidence workflow</p>
          <h2>从研究问题到可复核证据</h2>
          <span>每一步都保留数据来源与下载出口，适合网络药理学前期准备和研究方案讨论。</span>
        </div>
        <div className="workflow-grid">
          {workflow.map((item) => (
            <article key={item.index}>
              <span>{item.index}</span>
              <h3>{item.title}</h3>
              <p>{item.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="capabilities" className="home-band home-capabilities">
        <div className="capability-intro">
          <p>Research infrastructure</p>
          <h2>围绕真实科研任务设计</h2>
          <span>界面服务于反复检索、比较、下载与复核，不把复杂业务藏进展示性页面。</span>
        </div>
        <div className="capability-list">
          <article><Database size={22} /><div><h3>统一数据底座</h3><p>动态接入本地药理库、业务库与 ChEMBL，记录同步状态和断点游标。</p></div></article>
          <article><Network size={22} /><div><h3>查询驱动图谱</h3><p>所有统计、图表和证据链都围绕当前中药与疾病查询重新计算。</p></div></article>
          <article><BookOpenCheck size={22} /><div><h3>本地模型辅助</h3><p>简单问题由知识库快速回答，复杂医案与机制问题交给本地 BianCang/Qwen。</p></div></article>
          <article><Download size={22} /><div><h3>研究材料导出</h3><p>支持原始比对表、候选靶点、完整 JSON、CSV 与分析报告导出。</p></div></article>
        </div>
      </section>

      <section className="home-cta">
        <div><p>Ready for research</p><h2>用真实数据开始下一次分析</h2></div>
        <Link href="/register">创建研究账号 <ArrowRight size={17} /></Link>
      </section>

      <footer className="site-footer"><span>远志 AI Scientist</span><span>中医药理知识图谱与网络药理学分析平台</span></footer>
    </main>
  );
}
