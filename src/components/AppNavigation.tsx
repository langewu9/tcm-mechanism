"use client";

import Link from "next/link";
import {
  BarChart3,
  Bot,
  Database,
  FileSearch,
  FileText,
  FlaskConical,
  LayoutDashboard,
  PlugZap,
  ShieldCheck
} from "lucide-react";
import { usePathname } from "next/navigation";

const primary = [
  { href: "/dashboard", label: "研究总览", shortLabel: "总览", icon: LayoutDashboard },
  { href: "/research", label: "药理检索", shortLabel: "检索", icon: FileSearch },
  { href: "/datasets", label: "数据资产", shortLabel: "数据", icon: Database },
  { href: "/cases", label: "医案库", shortLabel: "医案", icon: FileText },
  { href: "/analysis", label: "智能分析", shortLabel: "分析", icon: FlaskConical },
  { href: "/visualization", label: "网络图谱", shortLabel: "图谱", icon: BarChart3 },
  { href: "/assistant", label: "远志助手", shortLabel: "助手", icon: Bot }
];

const admin = [
  { href: "/api-integration", label: "接入监测", shortLabel: "接入", icon: PlugZap },
  { href: "/admin", label: "系统管理", shortLabel: "管理", icon: ShieldCheck }
];

type NavigationItem = (typeof primary)[number];

function NavLink({ item, compact = false }: { item: NavigationItem; compact?: boolean }) {
  const pathname = usePathname();
  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={compact ? `mobile-nav-item ${active ? "is-active" : ""}` : `side-nav-item ${active ? "is-active" : ""}`}
      title={compact ? item.label : undefined}
    >
      <Icon size={compact ? 19 : 17} strokeWidth={1.8} />
      <span>{compact ? item.shortLabel : item.label}</span>
    </Link>
  );
}

export function DesktopNavigation({ isAdmin }: { isAdmin: boolean }) {
  return (
    <nav className="side-navigation" aria-label="主导航">
      <p className="side-nav-label">研究工作区</p>
      {primary.map((item) => <NavLink key={item.href} item={item} />)}
      {isAdmin ? (
        <>
          <p className="side-nav-label">平台运维</p>
          {admin.map((item) => <NavLink key={item.href} item={item} />)}
        </>
      ) : null}
    </nav>
  );
}

export function MobileNavigation() {
  const items = [primary[0], primary[1], primary[4], primary[5], primary[6]];
  return <nav className="mobile-nav lg:hidden" aria-label="移动端导航">{items.map((item) => <NavLink key={item.href} item={item} compact />)}</nav>;
}
