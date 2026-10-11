import { useEffect, useId, useState } from "react";
import { R_CHARTS } from "../demo/catalog";

type DemoChart = { key: string; label: string; rendererVersion: string; inputSha256: string };
type Manifest = { synthetic: boolean; disclaimer: string; charts: DemoChart[] };
export function readDemoManifest(value: unknown): Manifest {
  const data = value as Manifest | null;
  if (!data || data.synthetic !== true || typeof data.disclaimer !== "string" || !Array.isArray(data.charts)
    || data.charts.length !== R_CHARTS.length || new Set(data.charts.map(chart => chart?.key)).size !== R_CHARTS.length
    || data.charts.some(chart => !chart || !R_CHARTS.some(([key]) => key === chart.key) || typeof chart.label !== "string"
      || !/^[a-f0-9]{64}$/.test(chart.inputSha256) || typeof chart.rendererVersion !== "string")) throw new Error("Invalid demo manifest");
  return data;
}
export function RDemoGallery({ chartKey, defaultOpen = false }: { chartKey?: string; defaultOpen?: boolean }) {
  const [opened, setOpened] = useState(defaultOpen);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [imageError, setImageError] = useState(false);
  const selectionId = useId();
  useEffect(() => {
    if (!opened) return;
    let active = true;
    setError("");
    fetch("/r-demo/manifest.json").then(async response => {
      if (!response.ok) throw new Error();
      const value = readDemoManifest(await response.json());
      if (active) { setManifest(value); setError(""); }
    }).catch(() => { if (active) setError("演示图片尚未准备好，请运行 r_viz/prepare_demo_gallery.py 后重试。"); });
    return () => { active = false; };
  }, [opened, retry]);
  const chart = chartKey ? manifest?.charts.find(item => item.key === chartKey) : manifest?.charts[selected];
  useEffect(() => { setImageError(false); }, [chart?.key, retry]);
  return <section className="panel source-record" aria-label={chartKey ? `${chartKey} 合成演示` : "合成演示图库"} style={{ marginBottom: "1.5rem", marginTop: chartKey ? "1rem" : undefined }}>
    <p className="page-kicker">SYNTHETIC DEMO · NOT EXPERIMENTAL EVIDENCE</p>
    <h3 className="section-title-sm">{chartKey ? `${R_CHARTS.find(([key]) => key === chartKey)?.[1] ?? chartKey} · 演示` : "R 图表演示图库"}</h3>
    <p className="section-help">14 种图表配套独立 key 数据。全部为合成演示，不代表真实实验、数据库互作或富集结论，不写入正式分析任务。</p>
    <button type="button" className="btn btn-secondary" aria-expanded={opened} onClick={() => setOpened(!opened)}>{opened ? "收起演示图库" : chartKey ? "查看本图演示与 key 数据" : "查看全部图表与 key 数据"}</button>
    {opened && <>
      {error && <p className="notice-error" role="alert">{error} <button type="button" className="btn btn-secondary" onClick={() => setRetry(retry+1)}>重试演示加载</button></p>}
      {!manifest && !error && <p role="status">正在读取演示图片…</p>}
      {manifest && chart && <>
        <p className="notice-warning">{manifest.disclaimer}</p>
        {!chartKey && <><label className="field-label" htmlFor={selectionId}>选择演示图表（共 {manifest.charts.length} 种）</label>
        <select id={selectionId} className="field" value={selected} onChange={event => setSelected(Number(event.target.value))}>
          {manifest.charts.map((item, index) => <option key={item.key} value={index}>{item.label}</option>)}
        </select></>}
        <p className="section-help">图表 key：{chart.key} · {chart.rendererVersion} · 合成演示专用</p>
        {imageError ? <p className="notice-error" role="alert">演示图片缺失，请重新准备交付资源。</p> : <img key={`${chart.key}-${retry}`} loading="lazy" className="visualization-preview" src={`/r-demo/${chart.key}.svg`} alt={`合成演示（非真实实验）：${chart.label}`} onError={() => setImageError(true)} />}
        <div className="source-record-actions">{["json", "svg", "png", "pdf", "html"].map(format => <a className="btn btn-secondary" key={format} download href={`/r-demo/${chart.key}.${format}`}>{format === "json" ? "下载 key 数据 JSON" : `下载 ${format.toUpperCase()}`}</a>)}</div>
      </>}
    </>}
  </section>;
}
