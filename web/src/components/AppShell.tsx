// Main's sidebar/header/mobile navigation layout; Django owns identity and session.
import { useEffect, useState, type ReactNode } from "react";
import { Link, Outlet, useNavigate, useOutletContext } from "react-router-dom";
import { LogOut, Search, Server } from "lucide-react";
import { logout, type Session } from "../api/auth";
import { apiRequest, ApiError } from "../api/client";
import { DesktopNavigation, MobileNavigation } from "./AppNavigation";
import { AssistantWidget } from "./AssistantWidget";
import { ModuleDemoNotice } from "./ModuleDemoNotice";

type ShellUser = NonNullable<Session["user"]>;
export function AppShell({ user, children }: { user: ShellUser; children: ReactNode }) {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [exiting, setExiting] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const name = user.name || user.username;
  useEffect(() => {
    let active = true;
    void apiRequest<{ status: string; database: string }>("/api/v1/health/")
      .then((health) => { if (active) setOnline(health.status === "ok" && health.database === "ok"); })
      .catch(() => { if (active) setOnline(false); });
    return () => { active = false; };
  }, []);
  async function signOut() {
    setExiting(true); setError(null);
    try { await logout(); navigate("/login", { replace: true }); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : "退出未完成，请稍后重试。"); }
    finally { setExiting(false); }
  }
  const serviceText = online === null ? "正在检查服务…" : online ? "服务运行正常" : "暂时无法连接";
  return <div className="app-frame">
    <a className="skip-link" href="#main-content">跳到主要内容</a>
    <aside className="app-sidebar">
      <Link to="/dashboard" className="brand-lockup" aria-label="远志 AI Scientist 研究工作台"><img src="/images/yuanzhi-mark.png" alt="" width={48} height={48} className="brand-mark" /><span><strong>远志 AI Scientist</strong><small>中医药理研究平台</small></span></Link>
      <DesktopNavigation isAdmin={user.isSuperuser} />
      <div className="sidebar-footer">
        <div className="sidebar-service"><Server size={14} aria-hidden="true" /><span><strong>本地知识库</strong><small>{serviceText}</small></span><i aria-label={serviceText} style={online ? undefined : { background: "var(--color-ink-faint)", boxShadow: "none" }} /></div>
        <div className="sidebar-user"><span className="avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span><span className="min-w-0"><strong>{name}</strong><small>{user.isSuperuser ? "平台管理员" : "研究员"}</small></span></div>
      </div>
    </aside>
    <div className="app-content">
      <header className="app-header">
        <Link to="/dashboard" className="mobile-brand" aria-label="返回研究总览"><img src="/images/yuanzhi-mark.png" alt="" width={32} height={32} className="brand-mark" /><strong>远志</strong></Link>
        <div className="app-header-copy"><p>Research workspace</p><h1>中医药理智能分析平台</h1></div>
        <div className="app-header-actions">
          <Link to="/research" className="header-search" aria-label="打开药理检索"><Search size={16} /><span>检索疾病、中药或靶点</span></Link>
          <div className="header-user"><strong>{name}</strong><small>{user.email || ""}</small></div>
          <button className="icon-button" onClick={() => void signOut()} title="退出登录" aria-label="退出登录" disabled={exiting}><LogOut size={16} /></button>
        </div>
      </header>
      <main id="main-content" className="app-main"><div className="app-main-inner">{error && <p className="notice-error workspace-notice" role="alert">{error}</p>}{children}</div></main>
    </div>
    <MobileNavigation />
    <AssistantWidget />
  </div>;
}

export function WorkspaceLayout() {
  const user = useOutletContext<ShellUser>();
  return <AppShell user={user}><ModuleDemoNotice /><Outlet context={user} /></AppShell>;
}
