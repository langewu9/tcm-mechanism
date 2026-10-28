import { useEffect, useRef, useState, type ReactNode } from "react";
import { SubviewTabs, useSubviewVisible } from "./SubviewTabs";
import { loadRWidgetDocument } from "./rWidgetDocument";

export function hasInteractiveRenderer(version: unknown) {
  return typeof version === "string" && /^r-viz-0\.(?:[4-9]|[1-9]\d+)\./.test(version);
}

/** Scripts run in an opaque, network-disabled iframe, never in the application origin. */
export function RChartViewer({ title, svgUrl, htmlUrl, interactive = false, defaultExpanded = false, onClose, footer }: {
  title: string; svgUrl?: string; htmlUrl?: string; interactive?: boolean; defaultExpanded?: boolean; onClose?: () => void; footer?: ReactNode;
}) {
  const [mode, setMode] = useState(interactive && htmlUrl ? "interactive" : "static");
  const [imageError, setImageError] = useState(false);
  const [expanded, setExpanded] = useState(defaultExpanded);
  const dialog = useRef<HTMLDivElement>(null);
  const visible = useSubviewVisible();
  const [widget, setWidget] = useState({ url: "", html: "", error: "" });
  const [loadAttempt, setLoadAttempt] = useState(0);
  useEffect(() => {
    if (!visible || mode !== "interactive" || !interactive || !htmlUrl) return;
    const controller = new AbortController();
    let active = true;
    setWidget({ url: htmlUrl, html: "", error: "" });
    void loadRWidgetDocument(htmlUrl, controller.signal).then(
      html => { if (active) setWidget({ url: htmlUrl, html, error: "" }); },
      () => { if (active) setWidget({ url: htmlUrl, html: "", error: "交互图表加载失败，请切换静态预览或重新生成图表。" }); },
    );
    return () => { active = false; controller.abort(); };
  }, [visible, mode, interactive, htmlUrl, loadAttempt]);
  useEffect(() => {
    if (!expanded || !visible) return;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [expanded, visible]);
  function close() { setExpanded(false); onClose?.(); }
  // Keep form/polling state, but do not execute heavy widgets in hidden result pages.
  if (!visible) return null;
  const staticView = imageError ? <p className="notice-error" role="alert">静态图片暂不可用，请尝试下载或重新准备图表资源。</p>
    : svgUrl ? <img className="visualization-preview" src={svgUrl} alt={title} onError={() => setImageError(true)} />
      : <p className="section-help">暂无静态图片。</p>;
  const views = [
    ...(interactive && htmlUrl ? [{ key: "interactive", label: "交互图表", content: <>
      {widget.url === htmlUrl && widget.error ? <div className="notice-error" role="alert"><p>{widget.error}</p><button className="btn btn-secondary" type="button" onClick={() => setLoadAttempt(value => value + 1)}>重新加载图表</button></div> : <>
        {!(widget.url === htmlUrl && widget.html) && <p className="section-help" role="status">正在加载交互图表…</p>}
        <iframe className="r-interactive-frame" title={`${title} · R 交互图表`} srcDoc={widget.url === htmlUrl ? widget.html : ""} sandbox="allow-scripts allow-downloads" referrerPolicy="no-referrer" />
      </>}
    </> }] : []),
    { key: "static", label: "静态预览", content: staticView },
  ];
  return <div ref={dialog} tabIndex={expanded ? -1 : undefined} className={expanded ? "r-chart-viewer r-chart-expanded" : "r-chart-viewer"}
    role={expanded ? "dialog" : undefined} aria-modal={expanded || undefined} aria-label={expanded ? `${title} · 大图` : undefined}
    onKeyDown={event => {
      if (event.key === "Escape") { event.preventDefault(); close(); }
      if (expanded && event.key === "Tab") {
        const controls = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), iframe, [tabindex="0"]') ?? []).filter(control => control.getClientRects().length > 0);
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }}>
    <div className="r-chart-viewer-toolbar">{expanded && <strong>{title}</strong>}<button className="btn btn-secondary" type="button" onClick={() => expanded ? close() : setExpanded(true)} aria-expanded={expanded}>
      {expanded ? onClose ? "关闭图窗" : "退出大图" : "展开大图"}
    </button></div>
    <SubviewTabs label="图表显示方式" value={mode} onChange={setMode} views={views} />
    {footer}
  </div>;
}
