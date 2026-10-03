import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useOutletContext } from "react-router-dom";
import { Database, LogOut, ShieldCheck, Users } from "lucide-react";
import { logout, type Session } from "../api/auth";
import { getAdminOverview, type AdminOverview, type AdminOverviewTask } from "../api/admin";
import { ApiError } from "../api/client";

const taskStatusLabels: Record<AdminOverviewTask["status"], string> = {
  queued: "排队中", running: "运行中", succeeded: "已完成", failed: "失败", cancelled: "已取消",
};

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "请求未完成，请稍后重试。";
}

function dateTime(value: string | null) {
  return value ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "尚无记录";
}

function AdminSummary({ title, kind, items, loading }: {
  title: string;
  kind: "datasets" | "tasks";
  items: AdminOverview["datasets"] | AdminOverview["tasks"];
  loading: boolean;
}) {
  return <section className="panel dashboard-panel">
    <div className="dashboard-section-heading"><h2 className="section-title-sm">最近{title}</h2><span className="section-help">最近 10 项</span></div>
    {loading ? <p className="empty-state dashboard-empty" role="status">正在读取…</p> : items.length ? <div className="dashboard-latest-list">
      {kind === "datasets" ? (items as AdminOverview["datasets"]).map((item) => <article className="saved-analysis" key={item.id}>
        <div className="dashboard-task-heading"><div><p>{item.name}</p><small>{item.owner_name} · {item.row_count.toLocaleString("zh-CN")} 行</small></div><time>{dateTime(item.created_at)}</time></div>
      </article>) : (items as AdminOverview["tasks"]).map((item) => <article className="saved-analysis" key={item.id}>
        <div className="dashboard-task-heading"><div><p>{item.name}</p><small>{item.owner_name} · {item.task_type}</small></div><span className={`status-badge ${item.status === "failed" ? "status-error" : item.status === "succeeded" ? "status-success" : "status-pending"}`}>{taskStatusLabels[item.status]}</span></div>
        <time>{dateTime(item.created_at)}</time>
      </article>)}
    </div> : <p className="empty-state dashboard-empty">暂无记录</p>}
  </section>;
}

export function AdminOverviewPage() {
  const user = useOutletContext<NonNullable<Session["user"]>>();
  const navigate = useNavigate();
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getAdminOverview().then((data) => { if (active) setOverview(data); })
      .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  async function signOut() {
    try { await logout(); navigate("/login", { replace: true }); }
    catch (cause) { setError(errorMessage(cause)); }
  }

  if (!user.isSuperuser) return <Navigate to="/dashboard" replace />;

  const users = overview?.users ?? [];
  const adminCount = users.filter((item) => item.role === "ADMIN").length;
  const metrics = [
    { label: "总用户", value: users.length, icon: Users },
    { label: "平台管理员", value: adminCount, icon: ShieldCheck },
    { label: "研究者", value: users.length - adminCount, icon: Database },
  ];

  return <main className="workspace-page">
    <header className="workspace-nav">
      <Link to="/" className="site-brand" aria-label="远志 AI Scientist 首页"><img src="/images/yuanzhi-mark.png" alt="" width={42} height={42} className="brand-mark" /><span><strong>远志 AI Scientist</strong><small>平台管理</small></span></Link>
      <nav className="workspace-module-nav" aria-label="平台管理"><Link to="/admin" aria-current="page">系统总览</Link><Link to="/admin/sources">数据源同步</Link><Link to="/admin/integrations">API 接入监测</Link></nav>
      <div className="workspace-nav-actions"><span className="workspace-user">{user.username} · 平台管理员</span><button className="btn btn-secondary" type="button" onClick={() => void signOut()}><LogOut size={16} />退出</button></div>
    </header>
    <div className="app-main workspace-main"><div className="app-main-inner">
      <div className="page-heading"><div className="page-heading-copy"><p className="page-kicker">Platform administration</p><h1 className="page-title">系统总览</h1><p className="page-description">查看平台账号及近期研究数据集、分析任务。此页面仅平台超级管理员可访问。</p></div><span className="status-badge status-success">管理员</span></div>
      {error && <div className="notice-error workspace-notice" role="alert">{error}</div>}
      <div className="dashboard-stat-grid" aria-label="平台用户统计">
        {metrics.map((item) => <article className="stat-card" key={item.label}><span className="stat-card-icon"><item.icon size={20} /></span><div><p>{item.label}</p><strong>{loading ? "…" : item.value.toLocaleString("zh-CN")}</strong></div></article>)}
      </div>
      <section className="panel dashboard-panel" aria-labelledby="admin-users-title">
        <div className="dashboard-section-heading"><div><h2 id="admin-users-title" className="section-title-sm">用户管理</h2><p className="section-help">账号状态、研究资产数量、注册时间和最近登录</p></div></div>
        {loading ? <p className="empty-state dashboard-empty" role="status">正在读取平台数据…</p> : users.length ? <div className="overflow-x-auto">
          <table className="data-table min-w-[980px]"><thead><tr><th>用户</th><th>角色</th><th>账号状态</th><th>数据集</th><th>医案</th><th>分析任务</th><th>注册时间</th><th>最近登录</th></tr></thead>
            <tbody>{users.map((item) => <tr key={item.id}><td><strong>{item.name}</strong><small className="block text-ink/55">{item.email || "未填写邮箱"}</small></td>
              <td><span className={`status-badge ${item.role === "ADMIN" ? "bg-cinnabar/10 text-cinnabar" : "status-success"}`}>{item.role === "ADMIN" ? "管理员" : "研究者"}</span></td>
              <td><span className={`status-badge ${item.is_active ? "status-success" : "status-pending"}`}>{item.is_active ? "正常" : "未启用"}</span></td>
              <td>{item.dataset_count}</td><td>{item.case_count}</td><td>{item.task_count}</td><td>{dateTime(item.date_joined)}</td><td>{dateTime(item.last_login)}</td></tr>)}</tbody>
          </table>
        </div> : <div className="empty-state"><strong>暂无用户</strong><p>注册账号将在这里显示。</p></div>}
      </section>
      <div className="dashboard-detail-grid"><AdminSummary title="数据集" kind="datasets" items={overview?.datasets ?? []} loading={loading} /><AdminSummary title="分析任务" kind="tasks" items={overview?.tasks ?? []} loading={loading} /></div>
    </div></div>
  </main>;
}
