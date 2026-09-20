import Link from "next/link";
import Image from "next/image";
import { Search, Server } from "lucide-react";
import { DesktopNavigation, MobileNavigation } from "@/components/AppNavigation";
import { LogoutButton } from "@/components/LogoutButton";
import { AssistantWidget } from "@/components/AssistantWidget";

type User = { name: string; email: string; role: string };

export function AppShell({ user, children }: { user: User; children: React.ReactNode }) {
  const roleLabel = user.role === "ADMIN" ? "平台管理员" : "研究员";

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="app-sidebar">
        <Link href="/dashboard" className="brand-lockup" aria-label="远志 AI Scientist 研究工作台">
          <Image src="/images/yuanzhi-mark.png" alt="" width={48} height={48} className="brand-mark" priority />
          <span><strong>远志 AI Scientist</strong><small>中医药理研究平台</small></span>
        </Link>
        <DesktopNavigation isAdmin={user.role === "ADMIN"} />
        <div className="sidebar-footer">
          <div className="sidebar-service">
            <Server size={14} aria-hidden="true" />
            <span><strong>本地知识库</strong><small>服务运行正常</small></span>
            <i aria-label="在线" />
          </div>
          <div className="sidebar-user">
            <span className="avatar" aria-hidden="true">{user.name.slice(0, 1).toUpperCase()}</span>
            <span className="min-w-0"><strong>{user.name}</strong><small>{roleLabel}</small></span>
          </div>
        </div>
      </aside>

      <div className="app-content">
        <header className="app-header">
          <Link href="/dashboard" className="mobile-brand lg:hidden" aria-label="返回研究总览"><Image src="/images/yuanzhi-mark.png" alt="" width={32} height={32} className="brand-mark" /><strong>远志</strong></Link>
          <div className="app-header-copy">
            <p>Research workspace</p>
            <h1>中医药理智能分析平台</h1>
          </div>
          <div className="app-header-actions">
            <Link href="/research" className="header-search" aria-label="打开药理检索"><Search size={16} /><span>检索疾病、中药或靶点</span></Link>
            <div className="header-user"><strong>{user.name}</strong><small>{user.email}</small></div>
            <LogoutButton />
          </div>
        </header>
        <main id="main-content" className="app-main"><div className="app-main-inner">{children}</div></main>
      </div>
      <MobileNavigation />
      <AssistantWidget />
    </div>
  );
}
