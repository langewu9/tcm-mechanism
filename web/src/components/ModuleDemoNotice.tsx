import { Link, useLocation } from "react-router-dom";
import { moduleForPath } from "../demo/catalog";
export function ModuleDemoNotice() {
  const { pathname } = useLocation();
  const module = moduleForPath(pathname);
  if (!module) return null;
  return <aside className="notice-info demo-module-notice" aria-label={`${module.label} 演示入口`}>
    <div><strong>{module.label} · 交付演示</strong><p>独立合成 key 数据与操作步骤，不改变下方真实工作区。</p></div>
    <Link className="btn btn-secondary" to={`/demo?module=${module.key}`}>打开本模块演示</Link>
  </aside>;
}
