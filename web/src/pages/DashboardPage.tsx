import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, Database, FileSearch, FileText, FlaskConical, Leaf, Network, Pill, Route, Upload } from "lucide-react";
import { type Session } from "../api/auth";
import { ApiError } from "../api/client";
import { getResearchDashboard, type DashboardTask, type ResearchDashboard } from "../api/catalog";

const statusLabels: Record<DashboardTask["status"], string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const taskRoutes: Record<DashboardTask["task_type"], string> = {
  proteomics: "/proteomics",
  case_link: "/cases",
  network: "/network-pharmacology",
  visualization: "/proteomics",
  research_assistant: "/assistant",
  text_analysis: "/analysis",
};

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function formatCount(value: number | undefined, loading: boolean) {
  return loading ? "…" : value?.toLocaleString("zh-CN") ?? "—";
}

function taskStatusClass(status: DashboardTask["status"]) {
  if (status === "succeeded") return "status-success";
  if (status === "failed" || status === "cancelled") return "status-error";
  return "status-pending";
}

export function DashboardPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const [dashboard, setDashboard] = useState<ResearchDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getResearchDashboard().then((data) => {
      if (active) setDashboard(data);
    }).catch((cause: unknown) => {
      if (active) setError(errorMessage(cause));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  const stats = dashboard?.stats;
  const metricCards = [
    { label: "研究数据集", value: stats?.datasets, icon: Database },
    { label: "医案记录", value: stats?.cases, icon: FileText },
    { label: "分析任务", value: stats?.tasks, icon: FlaskConical },
    { label: "知识节点", value: stats ? stats.herbs + stats.compounds + stats.targets + stats.pathways : undefined, icon: Network },
  ];
  const knowledge = [
    { label: "中药", value: stats?.herbs, icon: Leaf },
    { label: "活性成分", value: stats?.compounds, icon: Pill },
    { label: "作用靶点", value: stats?.targets, icon: Network },
    { label: "生物通路", value: stats?.pathways, icon: Route },
  ];
  const actions = [
    { href: "/research", title: "开始药理检索", description: "查询疾病、中药、成分、靶点与 ChEMBL", icon: FileSearch },
    { href: "/datasets", title: "导入研究数据", description: "上传 CSV 或 Excel 并纳入数据管理", icon: Upload },
    { href: "/analysis", title: "创建分析任务", description: "从医案生成证候到通路的分析链路", icon: FlaskConical },
  ];

  return <div className="space-y-6">
    <div className="page-heading">
      <div className="page-heading-copy">
        <p className="page-kicker">Workspace overview</p>
        <h1 className="page-title">{user.name || user.username}，欢迎回来</h1>
        <p className="page-description">查看研究资产、知识库规模与近期任务，然后继续上一次研究工作。</p>
      </div>
      <div className="page-heading-action"><span className="status-badge status-success">本地知识库</span></div>
    </div>

    {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}

    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="研究数据统计">
      {metricCards.map((item) => <article className="stat-card" key={item.label}>
        <span className="stat-card-icon"><item.icon size={20} /></span>
        <div><p>{item.label}</p><strong>{formatCount(item.value, loading)}</strong></div>
      </article>)}
    </div>

    <section className="panel overflow-hidden" aria-labelledby="dashboard-actions-title">
      <div className="panel-header"><div><h2 id="dashboard-actions-title" className="section-title-sm">常用操作</h2><p className="section-help">从高频任务开始工作</p></div></div>
      <div className="grid md:grid-cols-3">
        {actions.map((action, index) => <Link key={action.href} to={action.href} className={`dashboard-action group flex items-start gap-3 p-5 ${index ? "border-t border-cinnabar/10 md:border-l md:border-t-0" : ""}`}>
          <span className="dashboard-action-icon"><action.icon size={19} /></span>
          <span className="min-w-0 flex-1"><strong className="block text-sm">{action.title}</strong><small className="mt-1 block leading-5 text-ink/55">{action.description}</small></span>
          <ArrowRight className="mt-1 text-ink/30 group-hover:text-cinnabar" size={17} />
        </Link>)}
      </div>
    </section>

    <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
      <section className="panel overflow-hidden" aria-labelledby="dashboard-latest-title">
        <div className="panel-header"><div><h2 id="dashboard-latest-title" className="section-title-sm">最近分析</h2><p className="section-help">最近保存的五项任务</p></div><Link to="/analysis" className="text-xs font-bold text-cinnabar">文本分析</Link></div>
        {loading ? <div className="empty-state min-h-56" role="status">正在读取研究数据…</div>
          : error ? <div className="empty-state min-h-56" role="status"><strong>未能读取最近任务</strong><p>请稍后刷新页面重试。</p></div>
          : dashboard?.latest_tasks.length ? <div className="divide-y divide-cinnabar/10">{dashboard.latest_tasks.map((task) => <Link to={task.task_type === "network" ? task.analysis_kind === "catalog_evidence" ? `/research?catalogTask=${task.id}` : `/network-pharmacology?networkTask=${task.id}` : taskRoutes[task.task_type]} key={task.id} className="block px-5 py-4 hover:bg-cinnabar/5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <p className="truncate text-sm font-bold">{task.title}</p>
                {task.status !== "succeeded" && <span className={`status-badge shrink-0 ${taskStatusClass(task.status)}`}>{statusLabels[task.status]}</span>}
              </div>
              <time className="shrink-0 text-xs text-ink/45" dateTime={task.created_at}>{new Date(task.created_at).toLocaleDateString("zh-CN")}</time>
            </div>
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-ink/55">{task.summary}</p>
          </Link>)}</div>
          : <div className="empty-state min-h-56"><FlaskConical size={25} /><strong>暂无分析任务</strong><p>创建第一个任务后，分析摘要会出现在这里。</p></div>}
      </section>

      <section className="panel p-5" aria-labelledby="dashboard-knowledge-title">
        <h2 id="dashboard-knowledge-title" className="section-title-sm">知识库概览</h2>
        <p className="section-help">已纳入分析链路的结构化实体</p>
        <dl className="mt-5 space-y-4">
          {knowledge.map((item) => <div className="knowledge-stat" key={item.label}><span><item.icon size={16} /></span><dt>{item.label}</dt><dd>{formatCount(item.value, loading)}</dd></div>)}
        </dl>
      </section>
    </div>
  </div>;
}
