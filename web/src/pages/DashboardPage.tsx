import { useEffect, useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { Activity, ArrowRight, BookOpenCheck, Database, FileSearch, FileText, FlaskConical, Leaf, LogOut, Network, Pill, Route, Upload } from "lucide-react";
import { logout, type Session } from "../api/auth";
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
  const navigate = useNavigate();
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

  async function signOut() {
    try {
      await logout();
      navigate("/login", { replace: true });
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

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
    { label: "作用靶点", value: stats?.targets, icon: Activity },
    { label: "生物通路", value: stats?.pathways, icon: Route },
  ];
  const actions = [
    { href: "/research", title: "开始药理检索", description: "查询中药、成分、靶点与证据来源", icon: FileSearch },
    { href: "/datasets", title: "导入研究数据", description: "上传文件并保留数据来源记录", icon: Upload },
    { href: "/cases", title: "管理医案记录", description: "录入脱敏医案并查看候选证据", icon: BookOpenCheck },
  ];

  return <main className="workspace-page">
    <header className="workspace-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页">
        <img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} className="brand-mark" />
        <span><strong>远志 AI Scientist</strong><small>研究者工作区</small></span>
      </Link>
      <nav className="workspace-module-nav" aria-label="研究模块">
        <Link to="/dashboard" aria-current="page">研究总览</Link><Link to="/cases">医案管理</Link><Link to="/datasets">研究数据集</Link><Link to="/proteomics">蛋白组学</Link><Link to="/network-pharmacology">网络药理</Link><Link to="/research">知识检索</Link><Link to="/assistant">科研助手</Link>{user.isSuperuser && <Link to="/admin/sources">数据源同步</Link>}
      </nav>
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username}{user.isSuperuser ? " · 平台管理员" : " · 研究者"}</span>
        <button className="btn btn-secondary" type="button" onClick={() => void signOut()}><LogOut size={16} />退出</button></div>
    </header>

    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Workspace overview</p><h1 className="page-title">{user.username}，欢迎回来</h1>
        <p className="page-description">查看研究资产、知识库规模与近期任务，然后继续研究工作。</p></div><span className="status-badge status-success">本地知识目录</span>
      </div>

      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      <div className="dashboard-stat-grid" aria-label="研究数据统计">
        {metricCards.map((item) => <article className="stat-card" key={item.label}><span className="stat-card-icon"><item.icon size={20} /></span><div><p>{item.label}</p><strong>{formatCount(item.value, loading)}</strong></div></article>)}
      </div>

      <section className="panel dashboard-panel" aria-labelledby="dashboard-actions-title">
        <div className="dashboard-section-heading"><div><h2 id="dashboard-actions-title" className="section-title-sm">常用操作</h2><p className="section-help">从高频研究工作开始</p></div></div>
        <div className="dashboard-actions-grid">{actions.map((action) => <Link key={action.href} to={action.href} className="dashboard-action"><span className="dashboard-action-icon"><action.icon size={19} /></span><span><strong>{action.title}</strong><small>{action.description}</small></span><ArrowRight size={17} /></Link>)}</div>
      </section>

      <div className="dashboard-detail-grid">
        <section className="panel dashboard-panel" aria-labelledby="dashboard-latest-title">
          <div className="dashboard-section-heading"><div><h2 id="dashboard-latest-title" className="section-title-sm">最近分析</h2><p className="section-help">最近保存的五项任务</p></div><Link to="/proteomics" className="dashboard-text-link">查看分析模块</Link></div>
          {loading ? <div className="empty-state dashboard-empty" role="status">正在读取研究数据…</div>
            : dashboard?.latest_tasks.length ? <div className="dashboard-latest-list">{dashboard.latest_tasks.map((task) => <Link className="saved-analysis" to={taskRoutes[task.task_type]} key={task.id}>
              <div className="dashboard-task-heading"><div><p>{task.title}</p><time dateTime={task.created_at}>{new Date(task.created_at).toLocaleDateString("zh-CN")}</time></div><span className={`status-badge ${taskStatusClass(task.status)}`}>{statusLabels[task.status]}</span></div>
              <p className="dashboard-task-summary">{task.summary}</p>
            </Link>)}</div>
            : <div className="empty-state dashboard-empty"><FlaskConical size={25} /><strong>暂无分析任务</strong><p>创建任务后，最近的研究摘要会显示在这里。</p><Link className="btn btn-secondary" to="/proteomics">打开蛋白组学</Link></div>}
        </section>

        <section className="panel dashboard-panel" aria-labelledby="dashboard-knowledge-title">
          <div className="dashboard-section-heading"><div><h2 id="dashboard-knowledge-title" className="section-title-sm">知识库概览</h2><p className="section-help">已纳入研究检索的结构化实体</p></div></div>
          {knowledge.map((item) => <dl className="knowledge-stat" key={item.label}><span><item.icon size={16} /></span><dt>{item.label}</dt><dd>{formatCount(item.value, loading)}</dd></dl>)}
        </section>
      </div>
    </div></div>
  </main>;
}
