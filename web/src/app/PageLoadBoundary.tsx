import { Component, type ReactNode } from "react";

export function PageLoading() {
  return <main className="site-home"><section className="panel empty-state" role="status" aria-live="polite">
    <strong>正在加载工作区…</strong><p>首次访问此模块需要加载页面资源。</p>
  </section></main>;
}

export class PageLoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <main className="site-home"><section className="panel empty-state" role="alert">
      <strong>页面暂时无法加载</strong><p>请确认网络连接后刷新。如果刚完成版本更新，刷新可获取最新页面资源。</p>
      <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>刷新页面</button>
      <a className="btn btn-secondary" href="/">返回首页</a>
    </section></main>;
    return this.props.children;
  }
}
