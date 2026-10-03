import { Link, useLocation } from "react-router-dom";

// The main AppNavigation's modules, mapped to the current Django/Vite routes.
const primary = [
  ["/dashboard", "研究总览"], ["/cases", "医案管理"], ["/datasets", "研究数据集"],
  ["/analysis", "证候分析"], ["/proteomics", "蛋白组学"], ["/network-pharmacology", "网络药理"],
  ["/research", "知识检索"], ["/assistant", "科研助手"],
];
const administration = [["/admin", "系统总览"], ["/admin/sources", "数据源同步"], ["/admin/integrations", "API 接入监测"]];

export function WorkspaceModuleNav({ isSuperuser }: { isSuperuser: boolean }) {
  const { pathname } = useLocation();
  return <nav className="workspace-module-nav" aria-label="研究模块">
    {[...primary, ...(isSuperuser ? administration : [])].map(([href, label]) =>
      <Link key={href} to={href} aria-current={pathname === href ? "page" : undefined}>{label}</Link>)}
  </nav>;
}
